#!/usr/bin/env python3
"""금감원 검사결과제재 · 경영유의사항 등 공시 OPEN API 수집 (J11·J12).

설계 근거는 gate-a/14 6절. **2026-09-21 실호출로 검증 완료 (키 발급 09-21).**
금감원 스펙 페이지(OPEN API > 상세 및 테스트 > 검사결과제재 API)의 공개 샘플에
맞춰 짰고, 아래 「실호출로 확인한 것」 절이 그 검증 결과다.

**두 API는 같은 표의 두 뷰다** (14 6절). 필드 13개가 이름까지 동일하고 예시의
`examMgmtNo`(검사관리번호)가 같다. 검사 1건에서 나온 조치가 `emOpenSeq` 1·2로
갈리며 `transCode` 0/1, `actGbn` 10/20으로 구분된다. 그래서 파서는 하나면 되고
`--kind`로 엔드포인트만 바꾼다.

용례:
    python3 scripts/fetch_fss_sanctions.py --probe                 # 날짜 필터 대상 확인
    python3 scripts/fetch_fss_sanctions.py --from 2026-09-01 --to 2026-09-30 > s.csv
    python3 scripts/fetch_fss_sanctions.py --kind impr --from 2026-09-01 --to 2026-09-30 > i.csv

주의 넷 (전부 gate-a/14 6절)
- **JSON 루트 키는 `reponse`다.** `response`가 아니라 금감원 스펙의 오타 그대로다.
  `response`로 읽으면 전건 0으로 조용히 실패한다.
- **페이징이 없다.** 요청 변수는 넷뿐이라 전량 백필은 기간 분할로만 한다.
- **`emOpenSeq`는 워터마크가 아니다.** 검사 1건 안의 순번이며 요청 변수에도 없다.
  증분은 날짜로 잡는다.
- 응답에 **상품을 가리키는 칸이 없다.** 본문도 `㉮펀드`로 마스킹이라
  `문서.product_id`는 영구 NULL이고, 붙는 축은 `finInstName`(판매사)뿐이다.

다음에 고칠 것 (2026-09-22 코드 리뷰, 아직 안 고침)
- **모르는 resultCode가 재시도로 한도를 태운다.** `1`·`900`·`030`·`033` 넷 중 어느 것도
  아닌 코드는 `RuntimeError`로 던져지는데, 같은 try 블록의 `except Exception`이 잡아
  최대 3회까지 재시도한다. 재시도 1회가 실제 호출 1회이므로 한 구간에서 하루 한도의
  10%를 쓸 수 있다. `030`·`033`처럼 즉시 중단으로 분류하는 편이 안전하다.
- **재개 지점을 남기지 않는다.** 일일 한도로 중간에 끊기면 다음날 어디까지 했는지
  사람이 로그를 보고 `--from`을 다시 계산해야 한다. 여러 날에 걸친 백필에는 부족하다.
- **`--probe`는 지금 상태로 못 쓴다.** 조회 날짜 `2026-04-24`가 코드에 박혀 있고
  CLI로 바꿀 수 없다. 그 날짜는 자료가 없는 구간이라 결과도 안 나온다.
- 부수: euc-kr 디코딩에 `errors="replace"`를 써서 진짜 인코딩 문제가 생겨도
  예외 없이 치환문자로 넘어간다.

실호출로 확인한 것 (2026-09-21, 개인용 인증키)
- **응답 인코딩은 `euc-kr`이다, `utf-8`이 아니다.** `Content-Type: text/html;charset=euc-kr`.
  이전 버전은 `utf-8`로 강제 디코드해 한글 필드(`resultMsg`·`finInstName`·`actObjContent`)가
  전부 깨졌다(치환문자로 뭉갬). 지금 버전은 `euc-kr`로 고쳤다.
- **`resultCode`는 성공/실패가 아니라 네 갈래다.** `1`=정상(결과 0건 포함 가능) /
  `900`=그 구간에 자료 없음(정상, 에러 아님) / `030`=조회기간이 키 등급의 상한을 넘음 /
  `033`=**일일 조회 건수 초과**. 이전 버전은 `1`이 아니면 전부 예외로 던져 `900`(빈 결과)도
  실패로 잘못 처리했다. 지금은 `900`을 빈 리스트로 반환한다.
- **개인용 키는 한 번 호출에 최대 1개월치만 조회된다.** `030` 메시지 원문:
  「최대 조회기간 초과(개인 : 1개월)」. 이전 `CHUNK_DAYS = 90`은 개인 키에서 전부 `030`으로 실패한다.
  법인 키의 상한은 미확인 — 법인 키를 받으면 재확인할 것.
- **일일 조회 건수 한도는 30회다.** `sanction`·`impr` 두 엔드포인트가 **같은 키의 같은 한도를
  공유한다**(양쪽에서 각각 확인). 초과하면 `033`이 오고 다음 초기화 시점은 확인하지 못했다
  (달력일 자정 추정, 미확인). **하루 계획 호출 수를 30 밑으로 반드시 잡을 것.**
- 2026-09-01~09-30 구간에서 `resultCnt=8`을 확인했다(`resultCode=1`). 단, 이 구간의 실제
  행 내용은 **그 직후 일일 한도 초과로 받지 못했다** — 다음 조회일에 재수집해야 한다.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request

# 두 엔드포인트는 요청 변수도 결과 필드도 같다. 다른 것은 경로뿐이다.
URLS = {
    "sanction": "https://www.fss.or.kr/fss/kr/openApi/api/openInfo.jsp",      # 검사결과제재
    "impr": "https://www.fss.or.kr/fss/kr/openApi/api/openInfoImpr.jsp",      # 경영유의사항 등
}

# 결과변수 표 그대로. 순서를 CSV 열 순서로 쓴다.
FIELDS = ["emOpenNo", "examMgmtNo", "transCode", "emOpenSeq", "actGbn",
          "finInstName", "actReqDate", "actOrganCon", "actOfficerCon",
          "actEmpCon", "actObjContent", "inputDate", "inputMan"]

# 값의 근거는 gate-a/15 9절 + 09-21 실호출.
CALL_INTERVAL = 1.0     # 방어적 수집 원칙(조사 상세 2-1)
CHUNK_DAYS = 28         # 개인 키 실측: 한 호출 최대 1개월(030). 28일로 여유를 둔다.
DAILY_CALL_LIMIT = 30   # 실측(033): sanction·impr 공유. 초과분은 이 스크립트가 막지 않는다 — 호출 전 직접 셀 것.


def load_env(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                name, _, value = line.partition("=")
                os.environ.setdefault(name.strip(), value.strip())


# resultCode 실측 (2026-09-21). 「모름」이던 것을 실호출로 확정했다.
RESULT_NO_DATA = "900"     # 정상 — 그 구간에 자료가 없다. 예외로 던지면 안 된다.
RESULT_OK = "1"
# 재시도해도 풀리지 않는 코드. 여기서 즉시 멈춰야 한다 —
# 033을 백오프하며 3번 두드리면 이미 바닥난 일일 한도를 스크립트 자신이 더 깎아 먹는다
# (실측: 033도 정상 호출과 똑같이 한도를 소비한다).
RESULT_NO_RETRY = {"033": "일일 조회 건수(30회) 초과", "030": "조회기간이 키 등급 상한 초과(개인:1개월)"}


class FssQuotaError(RuntimeError):
    """재시도로 해결되지 않는 금감원 응답 (일일 한도·기간 상한 등)."""


def call(key: str, start: str, end: str, kind: str = "sanction",
         timeout: int = 60, attempts: int = 3) -> list[dict[str, str]]:
    query = urllib.parse.urlencode({"apiType": "json", "startDate": start,
                                    "endDate": end, "authKey": key})
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(
                "%s?%s" % (URLS[kind], query),
                headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                # 응답은 euc-kr이다 (Content-Type: text/html;charset=euc-kr, 09-21 실측).
                # utf-8로 읽으면 한글 필드가 전부 깨진다.
                payload = json.loads(response.read().decode("euc-kr", "replace"))
            # 스펙의 오타를 그대로 따르되, 금감원이 고칠 경우에 대비해 둘 다 본다.
            body = payload.get("reponse") or payload.get("response") or {}
            code = str(body.get("resultCode", ""))
            if code == RESULT_NO_DATA:
                return []  # 정상적인 빈 결과. 실패가 아니다.
            if code in RESULT_NO_RETRY:
                raise FssQuotaError("금감원 오류 [%s] %s: %s"
                                     % (code, RESULT_NO_RETRY[code], body.get("resultMsg", "")))
            if code != RESULT_OK:
                raise RuntimeError("금감원 오류 [%s]: %s" % (code, body.get("resultMsg", payload)))
            rows = body.get("result") or []
            return [rows] if isinstance(rows, dict) else rows
        except FssQuotaError:
            raise  # 즉시 중단. 백오프하지 않는다.
        except Exception as error:
            last = error
            if attempt < attempts - 1:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError("%s 조회 실패 (%s~%s): %s" % (kind, start, end, last))


def spans(start: str, end: str) -> list[tuple[str, str]]:
    first = dt.date.fromisoformat(start)
    last = dt.date.fromisoformat(end)
    out = []
    while first <= last:
        stop = min(first + dt.timedelta(days=CHUNK_DAYS - 1), last)
        out.append((first.isoformat(), stop.isoformat()))
        first = stop + dt.timedelta(days=1)
    return out


def probe(key: str, kind: str = "sanction") -> None:
    """날짜 필터가 actReqDate에 걸리는지 inputDate에 걸리는지 가른다 (14 6절 미확인).

    두 날짜가 어긋나는 행이 있으면 조회 구간 밖의 값을 가진 쪽이 필터 대상이 아니다.
    """
    start, end = "2026-04-24", "2026-04-24"
    rows = call(key, start, end, kind)
    print("%s %s~%s: %d행" % (kind, start, end, len(rows)))
    for row in rows[:20]:
        act = (row.get("actReqDate") or "").replace(".", "-")
        inp = (row.get("inputDate") or "")[:10]
        mark = "" if act == inp else "  ← 두 날짜가 다르다"
        print("  actReqDate=%s  inputDate=%s  %s%s"
              % (act, inp, row.get("finInstName", ""), mark))
    print("\n조회 구간과 일치하는 쪽이 필터 대상이다. 다른 쪽이 앞서면 그 차이가 룩백 하한이다.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="start", default="2026-01-01", help="YYYY-MM-DD")
    parser.add_argument("--to", dest="end",
                        default=dt.date.today().isoformat(), help="YYYY-MM-DD")
    parser.add_argument("--kind", choices=sorted(URLS), default="sanction",
                        help="sanction=검사결과제재, impr=경영유의사항 등 공시")
    parser.add_argument("--probe", action="store_true",
                        help="날짜 필터 대상 필드만 확인하고 끝낸다")
    args = parser.parse_args()

    load_env()
    key = os.environ.get("FSS_API_KEY", "").strip()
    if not key:
        sys.exit(".env 에 FSS_API_KEY 가 비어 있다. "
                 "www.fss.or.kr > OPEN API > 인증키 신청 (32자리). "
                 "법인 신청은 요청 IP 등록이 따른다 — gate-a/14 6절.")

    if args.probe:
        probe(key, args.kind)
        return

    writer = csv.DictWriter(sys.stdout, fieldnames=FIELDS, extrasaction="ignore")
    writer.writeheader()
    total = 0
    windows = spans(args.start, args.end)
    for index, (start, end) in enumerate(windows, 1):
        if index > 1:
            time.sleep(CALL_INTERVAL)
        rows = call(key, start, end, args.kind)
        writer.writerows(rows)
        total += len(rows)
        print("  [%d/%d] %s~%s %5d건 (누적 %d)"
              % (index, len(windows), start, end, len(rows), total), file=sys.stderr)
    print("합계 %d행" % total, file=sys.stderr)


if __name__ == "__main__":
    main()
