#!/usr/bin/env python3
"""금투협 전자공시에서 판매회사 마스터와 판매사별 펀드 목록을 받는다 (인증키 불필요).

`상품_판매사` 브릿지 표의 유일한 입력이다. 근거는 gate-a/14 4절.

용례:
    python3 scripts/fetch_kofia_sales.py --companies          # 판매회사 200건
    python3 scripts/fetch_kofia_sales.py --funds A02015       # 한 판매사의 펀드 목록
    python3 scripts/fetch_kofia_sales.py --all > bridge.csv   # 전체 브릿지 (오래 걸린다)

주의 셋
- 행 요소가 `<list>`가 아니라 **`<selectMeta>`**다. 금투협의 다른 서비스와 다르다.
- 「상장지수」는 0건이다. **ETF는 이 소스로 판매사를 붙일 수 없다.**
- 전체 순회는 판매사 200곳 × 평균 3,000건 ≈ 60만 행이다. 방어적 수집 원칙에 따라
  호출 간격을 둔다.
"""
from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
import time

URL = "https://dis.kofia.or.kr/proframeWeb/XMLSERVICES/"

COMPANY_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<message>
  <proframeHeader>
    <pfmAppName>FS-DIS2</pfmAppName>
    <pfmSvcName>DISMngCompInqSO</pfmSvcName>
    <pfmFnName>select</pfmFnName>
  </proframeHeader>
  <systemHeader></systemHeader>
  <DISMngCompInqListDTO>
    <option>S2</option>
    <standardDt>{month}</standardDt>
  </DISMngCompInqListDTO>
</message>"""

FUND_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<message>
  <proframeHeader>
    <pfmAppName>FS-DIS2</pfmAppName>
    <pfmSvcName>DISSalesCompFeeCmsSO</pfmSvcName>
    <pfmFnName>select</pfmFnName>
  </proframeHeader>
  <systemHeader></systemHeader>
  <DISCondFuncDTO>
    <tmpV11>{company}</tmpV11>
    <tmpV30>{date}</tmpV30>
    <tmpV12></tmpV12>
    <tmpV3></tmpV3>
    <tmpV5></tmpV5>
    <tmpV4></tmpV4>
  </DISCondFuncDTO>
</message>"""

# 방어적 수집 원칙(조사 상세 2-1): 호출 간격 1초 이상, 동시 요청 1개.
# 값의 근거는 gate-a/15 9절. 바꾸려면 거기부터 고친다.
CALL_INTERVAL = 1.0


def post(body: str, timeout: int = 150, attempts: int = 3) -> str:
    """curl로 보낸다. urllib은 이 서버의 큰 응답을 중간에서 끊어 받는다."""
    last = ""
    for attempt in range(attempts):
        result = subprocess.run(
            ["curl", "-sS", "--max-time", str(timeout), "-X", "POST", URL,
             "-H", "Content-Type: text/xml; charset=UTF-8",
             "-H", "Referer: https://dis.kofia.or.kr/websquare/index.jsp",
             "-A", "Mozilla/5.0", "--data-binary", "@-"],
            input=body.encode("utf-8"), capture_output=True,
        )
        text = result.stdout.decode("utf-8", "replace")
        if result.returncode == 0 and text.rstrip().endswith("</root>"):
            return text
        last = (result.stderr.decode("utf-8", "replace").strip()
                or "응답이 </root>로 끝나지 않음 (%d바이트)" % len(text))
        if attempt < attempts - 1:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("금투협 조회 실패: %s" % last)


def _tag(block: str, name: str) -> str:
    match = re.search(r"<%s>(.*?)</%s>" % (name, name), block, re.S)
    return match.group(1).strip() if match else ""


def companies(month: str) -> list[dict[str, str]]:
    xml = post(COMPANY_TEMPLATE.format(month=month))
    return [{"saleCompCd": _tag(b, "saleCompCd"), "koreanNm": _tag(b, "koreanNm")}
            for b in re.findall(r"<list>(.*?)</list>", xml, re.S)
            if _tag(b, "saleCompCd")]


def funds(company: str, date: str) -> list[dict[str, str]]:
    """행 요소는 <selectMeta>다. tmpV17=표준코드, tmpV18=운용사코드, tmpV2=펀드명."""
    xml = post(FUND_TEMPLATE.format(company=company, date=date))
    rows = []
    for block in re.findall(r"<selectMeta>(.*?)</selectMeta>", xml, re.S):
        code = _tag(block, "tmpV17")
        if code:
            rows.append({"saleCompCd": company, "asoStdCd": code,
                         "mgmtCompCd": _tag(block, "tmpV18"),
                         "fndNm": _tag(block, "tmpV2"),
                         "setpDt": _tag(block, "tmpV4"),
                         "standardDt": _tag(block, "tmpV16")})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--companies", action="store_true", help="판매회사 마스터만 출력")
    parser.add_argument("--funds", metavar="saleCompCd", help="한 판매사의 펀드 목록")
    parser.add_argument("--all", action="store_true", help="판매사 전체 순회 (오래 걸린다)")
    parser.add_argument("--date", default="20260831", help="기준일 YYYYMMDD")
    args = parser.parse_args()

    month = args.date[:6]
    if args.companies:
        rows = companies(month)
        writer = csv.DictWriter(sys.stdout, fieldnames=["saleCompCd", "koreanNm"])
        writer.writeheader()
        writer.writerows(rows)
        print("판매회사 %d건" % len(rows), file=sys.stderr)
        return

    fields = ["saleCompCd", "asoStdCd", "mgmtCompCd", "fndNm", "setpDt", "standardDt"]
    writer = csv.DictWriter(sys.stdout, fieldnames=fields)
    writer.writeheader()

    if args.funds:
        rows = funds(args.funds, args.date)
        writer.writerows(rows)
        print("%s: %d건" % (args.funds, len(rows)), file=sys.stderr)
        return

    if args.all:
        targets = companies(month)
        total = 0
        for index, company in enumerate(targets, 1):
            time.sleep(CALL_INTERVAL)
            try:
                rows = funds(company["saleCompCd"], args.date)
            except RuntimeError as error:
                print("  실패 %s %s: %s" % (company["saleCompCd"], company["koreanNm"], error),
                      file=sys.stderr)
                continue
            writer.writerows(rows)
            total += len(rows)
            print("  [%3d/%d] %-20s %6d건 (누적 %d)"
                  % (index, len(targets), company["koreanNm"], len(rows), total),
                  file=sys.stderr)
        print("합계 %d행" % total, file=sys.stderr)
        return

    parser.error("--companies / --funds / --all 중 하나를 지정하세요")


if __name__ == "__main__":
    main()
