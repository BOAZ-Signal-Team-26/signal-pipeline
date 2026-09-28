#!/usr/bin/env python3
"""검증 2 — ETF 「상장지수」 문자열 규칙의 오분류율.

KRX ETF 전종목을 정답지로 놓고, 공공데이터포털 펀드상품기본정보 전건과 대조해
누락(ETF인데 규칙이 못 잡음)과 오탐(규칙은 잡았는데 ETF가 아님)을 센다.
판정 기준은 각 1% 미만이면 규칙 유지, 오탐이 유의미하면 KRX 대조를 1차 판정으로
승격이다. 근거와 결과 해석은 gate-a/13.

용례:
    cp .env.example .env   # DATA_GO_KR_API_KEY, KRX_API_KEY 를 채운다
    python3 scripts/verify_etf_rule.py --base-date 20260904 --cache /tmp/funds.json

대조를 이름으로 하는 이유: 공공데이터포털은 펀드 단축코드(`srtnCd`)를, KRX는
종목코드(`ISU_CD`)를 주는데 둘을 잇는 소스가 없다(01 미확인 2).

**완전일치는 쓰지 않는다.** KRX `ISU_NM`은 상장 약명(「1Q 200액티브」)이고
공공데이터포털 `fndNm`은 정식 펀드명(「하나1Q200액티브증권상장지수투자신탁[주식]」)
이라 완전일치율이 0.0%다. 그대로 재면 누락률이 거짓으로 100%가 된다(gate-a/13 4절).
그래서 KRX 약명이 펀드명에 포함되는지로 붙인다. 이 방식의 천장은 80.4%이며,
붙지 않는 건은 오답이 아니라 **판정 불가**로 따로 센다.
"""
from __future__ import annotations

import argparse
import collections
import csv
import io
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from typing import Any

DATA_GO_KR = ("https://apis.data.go.kr/1160100/service/"
              "GetFundProductInfoService/getStandardCodeInfo")
KRX_ETF = "https://data-dbg.krx.co.kr/svc/apis/etp/etf_bydd_trd"

ETF_MARKER = "상장지수"
PAGE_SIZE = 1000            # 공공데이터포털 한 페이지 최대치
THRESHOLD = 0.01            # 누락·오탐 각 1% 미만이면 규칙 유지
BUCKET_PREFIX = 3           # 비교 횟수를 줄이려고 앞 3자로 버킷을 나눈다


def load_env(path: str = ".env") -> None:
    """.env 를 읽어 환경변수에 얹는다. 이미 설정된 값은 덮어쓰지 않는다."""
    if not os.path.exists(path):
        return
    for line in io.open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        os.environ.setdefault(name.strip(), value.strip())


def normalize(name: str | None) -> str:
    """NFKC → 공백 제거 → 기호 전부 제거 → 대문자화.

    05 1절의 상품명 정규화보다 공격적이다. 호수·클래스를 분리하지 않는 대신
    괄호와 기호를 전부 없앤다. 두 소스가 `(합성)`·`(합성 H)`·`[주식]` 같은
    표기를 제각각 쓰기 때문이며, ETF 여부만 가르면 되므로 상품 동일성 판정보다
    거칠어도 된다.
    """
    text = unicodedata.normalize("NFKC", name or "")
    text = "".join(text.split())
    return re.sub(r"[^0-9A-Za-z가-힣]", "", text).upper()


def fetch_json(url: str, headers: dict[str, str] | None = None,
               timeout: int = 90, attempts: int = 3) -> Any:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0", **(headers or {})})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8", "replace"))
        except Exception as error:          # 네트워크·JSON 오류를 함께 받는다
            last = error
            if attempt < attempts - 1:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError("요청 실패: %s (%s)" % (url.split("?")[0], last))


def fetch_krx_etf(key: str, base_date: str) -> list[dict[str, Any]]:
    """KRX ETF 일별매매정보. AUTH_KEY 헤더로 인증한다.

    키가 틀리면 `Unauthorized Key`, 키는 맞으나 서비스 이용 승인이 없으면
    `Unauthorized API Call`이 온다. 두 메시지를 구분해야 원인을 안다.
    """
    payload = fetch_json("%s?basDd=%s" % (KRX_ETF, base_date), {"AUTH_KEY": key})
    if isinstance(payload, dict) and "respCode" in payload:
        raise RuntimeError("KRX 오류: %s" % payload)
    # 응답 루트 키는 `OutBlock_1` 하나다 (09-20 실측, gate-a/15 3절).
    # 과거 일자도 최소 10년까지 그대로 돌려준다.
    rows = payload.get("OutBlock_1")
    if rows is None:
        raise RuntimeError("KRX 응답에 OutBlock_1이 없다: %s" % str(payload)[:200])
    return rows


def fetch_funds(key: str, cache: str | None = None) -> list[dict[str, Any]]:
    """펀드상품기본정보 전건. 펀드 1개당 1행이며 클래스와 사모를 포함한다."""
    if cache and os.path.exists(cache):
        print("  캐시 사용: %s" % cache, file=sys.stderr)
        return json.load(io.open(cache, encoding="utf-8"))
    funds: list[dict[str, Any]] = []
    page = 1
    while True:
        query = urllib.parse.urlencode(
            {"serviceKey": key, "numOfRows": PAGE_SIZE,
             "pageNo": page, "resultType": "json"}, safe="")
        body = fetch_json("%s?%s" % (DATA_GO_KR, query))["response"]["body"]
        items = body.get("items", {}).get("item", [])
        if isinstance(items, dict):
            items = [items]
        funds.extend(items)
        total = int(body.get("totalCount", 0))
        print("  공공데이터포털 %d/%d" % (len(funds), total), end="\r", file=sys.stderr)
        if not items or len(funds) >= total:
            break
        page += 1
    print(file=sys.stderr)
    if cache:
        json.dump(funds, io.open(cache, "w", encoding="utf-8"), ensure_ascii=False)
    return funds


def build_buckets(funds: list[dict[str, Any]],
                  prefixes: set[str]) -> dict[str, list[dict[str, Any]]]:
    """앞 3자 토큰별로 펀드를 모아 둔다. 1,167 × 183,649 전수 비교를 피한다."""
    buckets: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for fund in funds:
        for prefix in prefixes:
            if prefix in fund["norm"]:
                buckets[prefix].append(fund)
    return buckets


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-date", default="20260904", help="KRX 조회 기준일 YYYYMMDD")
    parser.add_argument("--out", default="reference/etf_rule_check.csv")
    parser.add_argument("--cache", default=None,
                        help="공공데이터포털 응답 캐시 경로. 재실행을 빠르게 한다")
    args = parser.parse_args()

    load_env()
    data_key = os.environ.get("DATA_GO_KR_API_KEY", "").strip()
    krx_key = os.environ.get("KRX_API_KEY", "").strip()
    missing = [n for n, v in (("DATA_GO_KR_API_KEY", data_key),
                              ("KRX_API_KEY", krx_key)) if not v]
    if missing:
        sys.exit(".env 에 %s 가 비어 있다. .env.example 참고." % ", ".join(missing))

    print("KRX ETF 정답지 조회 (%s)" % args.base_date, file=sys.stderr)
    krx = [{"code": r["ISU_CD"], "name": r["ISU_NM"], "norm": normalize(r["ISU_NM"])}
           for r in fetch_krx_etf(krx_key, args.base_date)]
    print("  ETF %d건" % len(krx), file=sys.stderr)

    print("공공데이터포털 펀드상품기본정보 조회", file=sys.stderr)
    funds = [{"name": f.get("fndNm", ""), "norm": normalize(f.get("fndNm")),
              "srtnCd": f.get("srtnCd", ""), "asoStdCd": f.get("asoStdCd", ""),
              "setpDt": f.get("setpDt", "")}
             for f in fetch_funds(data_key, args.cache)]
    for fund in funds:
        fund["is_hit"] = ETF_MARKER in fund["norm"]
    hits = [f for f in funds if f["is_hit"]]
    print("  전체 %d건 중 「상장지수」 포함 %d건" % (len(funds), len(hits)), file=sys.stderr)

    prefixes = {k["norm"][:BUCKET_PREFIX] for k in krx if len(k["norm"]) >= BUCKET_PREFIX}
    buckets = build_buckets(funds, prefixes)

    rows: list[list[Any]] = []
    matched = missed = unmatched_krx = 0
    claimed: set[str] = set()
    for entry in krx:
        candidates = buckets.get(entry["norm"][:BUCKET_PREFIX], [])
        found = [f for f in candidates if entry["norm"] in f["norm"]]
        if not found:
            unmatched_krx += 1
            rows.append(["KRX매칭실패", entry["code"], entry["name"], "", "", "", "", 0])
            continue
        matched += 1
        marked = [f for f in found if f["is_hit"]]
        if marked:
            claimed.update(f["srtnCd"] for f in marked)
            best = marked[0]
            rows.append(["일치", entry["code"], entry["name"], best["name"],
                         best["srtnCd"], best["asoStdCd"], best["setpDt"], len(found)])
        else:
            # ETF인데 붙은 펀드명에 「상장지수」가 없다 = 규칙이 놓친 진짜 누락
            missed += 1
            rows.append(["누락", entry["code"], entry["name"], found[0]["name"],
                         found[0]["srtnCd"], found[0]["asoStdCd"], found[0]["setpDt"],
                         len(found)])

    leftover = [f for f in hits if f["srtnCd"] not in claimed]
    for fund in leftover:
        rows.append(["오탐후보", "", "", fund["name"], fund["srtnCd"],
                     fund["asoStdCd"], fund["setpDt"], 0])

    miss_rate = missed / matched if matched else 0.0
    false_high = len(leftover) / len(hits) if hits else 0.0
    # 매칭 실패한 KRX ETF는 오탐 후보 안에 섞여 있다. 전부 뺀 값이 하한이다.
    false_low_n = max(0, len(leftover) - unmatched_krx)
    false_low = false_low_n / len(hits) if hits else 0.0

    print("\n=== 대조 결과 (KRX 기준일 %s) ===" % args.base_date)
    print("  KRX ETF          %6d" % len(krx))
    print("  규칙 적중         %6d" % len(hits))
    print("  ├ 매칭됨         %6d  (%.1f%%)" % (matched, matched / len(krx) * 100))
    print("  └ 매칭 실패       %6d  ← 이름 공간 차이. 판정 불가" % unmatched_krx)
    print("\n  누락             %6d  (매칭분 대비 %.2f%%)" % (missed, miss_rate * 100))
    print("  오탐 상한         %6d  (규칙 적중 대비 %.1f%%)" % (len(leftover), false_high * 100))
    print("  오탐 하한         %6d  (매칭 실패분을 모두 제외 시 %.1f%%)"
          % (false_low_n, false_low * 100))

    if miss_rate < THRESHOLD and false_high < THRESHOLD:
        verdict = "문자열 규칙 유지 (누락·오탐 각 1% 미만)"
    elif miss_rate < THRESHOLD:
        verdict = ("오탐이 유의미 → KRX 대조를 1차 판정으로 승격, "
                   "문자열 규칙은 후보 선별로 강등 (재현율은 온전하다)")
    else:
        verdict = "누락이 유의미 → 규칙 자체를 재설계해야 한다"
    print("\n판정: %s" % verdict)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with io.open(args.out, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["구분", "ISU_CD", "KRX종목명", "펀드명",
                         "srtnCd", "asoStdCd", "설정일", "후보수"])
        writer.writerows(rows)
    print("상세: %s (%d행)" % (args.out, len(rows)))


if __name__ == "__main__":
    main()
