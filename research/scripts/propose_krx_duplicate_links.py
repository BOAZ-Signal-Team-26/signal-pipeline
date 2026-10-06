#!/usr/bin/env python3
"""기존 KRX↔포털 중복 연결의 별도 후보를 찾는다. 확정 대응표를 만들지 않는다.

Usage: python3 research/scripts/propose_krx_duplicate_links.py FUNDS_JSON OUT_CSV
"""

import argparse
import collections
import csv
import json
import re
from pathlib import Path

from verify_etf_rule import normalize


AUDIT = Path(__file__).resolve().parents[1] / "samples/krx_match_audit.csv"
TAILS = ("증권", "특별자산", "부동산", "상장지수")
# KRX 약칭과 포털 정식명칭이 달라 자동 이름 규칙에서는 누락되는 두 건.
# 두 코드는 운용사의 상품 자료에서 종목코드와 정식 펀드명을 함께 확인했다.
ISSUER_OVERRIDES = {
    "102780": ("KR5105834570", "https://m.samsungfund.com/sheet/20120718/SHEET51459Kodex%EC%82%BC%EC%84%B1%EA%B7%B8%EB%A3%B9%EC%A3%BC.pdf"),
    "329200": ("K55301CS7395", "https://www.tigeretf.com/upload/etf/20250408022707005958.pdf"),
}
ISSUER_EVIDENCE = {
    "0139P0": "https://www.aceetf.co.kr/fund/K55101EQ7660",
    "0085P0": "https://www.aceetf.co.kr/fund/K55101EL9166",
    "476760": "https://www.aceetf.co.kr/fund/K55101E91865",
    "360200": "https://www.aceetf.co.kr/fund/K55101D78195",
    "465580": "https://www.aceetf.co.kr/fund/K55101E52479",
    "253240": "https://www.kiwoometf.com/service/etf/KO02010200M?gcode=253240",
    "449770": "https://www.kiwoometf.com/service/etf/KO02010200M?gcode=449770",
    "138230": "https://www.kiwoometf.com/service/etf/KO02010200M?gcode=138230",
    "139660": "https://www.kiwoometf.com/service/etf/KO02010200M?gcode=139660",
    "316670": "https://www.kiwoometf.com/service/etf/KO02010200M?gcode=316670",
    "453810": "https://www.samsungfund.com/etf/search.do?searchText=kodex+%EC%9D%B8%EB%8F%84nifty50",
    "461900": "https://www.plusetf.co.kr/customer/notice/detail?n=28085",
    "433330": "https://www.soletf.com/ko/strategy/pension?tabIndex=2",
    "192090": "https://www.tigeretf.com/upload/etf/20250611092529009329.pdf",
}


def candidates(row, funds):
    name = row["KRX종목명"]
    core = normalize(re.sub(r"\([^)]*\)", "", name))
    hedged = "H)" in name
    inverse = "인버스" in name
    leveraged = "레버리지" in name
    out = []
    for fund in funds:
        portal_name = fund["fndNm"]
        normalized = normalize(portal_name)
        start = normalized.find(core)
        if start < 0:
            continue
        tail = normalized[start + len(core):]
        if tail and not tail.startswith(TAILS):
            continue
        portal_hedged = "(H)" in portal_name or "(합성H)" in portal_name.replace(" ", "")
        if hedged != portal_hedged:
            continue
        if inverse != ("인버스" in portal_name):
            continue
        if leveraged != ("레버리지" in portal_name):
            continue
        out.append(fund)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("funds_json", type=Path)
    parser.add_argument("out_csv", type=Path)
    args = parser.parse_args()

    # 사람이 검토한 근거의 정본. URL이 있다는 사실 자체를 검증으로 추론하지 않는다.
    review_path = AUDIT.parent / "krx_issuer_review.csv"
    evidence_by_code = dict(ISSUER_EVIDENCE)
    if review_path.exists():
        with review_path.open(encoding="utf-8", newline="") as stream:
            evidence_by_code.update({row["ISU_CD"]: row["source_url"] for row in csv.DictReader(stream)})

    funds = [fund for fund in json.loads(args.funds_json.read_text(encoding="utf-8"))
             if "상장지수" in fund["fndNm"] or "ETF" in fund["fndNm"].upper()]
    audit = list(csv.DictReader(AUDIT.open(encoding="utf-8")))
    by_portal = collections.defaultdict(list)
    for row in audit:
        if row["asoStdCd"]:
            by_portal[row["asoStdCd"]].append(row)
    shared = [row for group in by_portal.values()
              if len({row["ISU_CD"] for row in group}) > 1 for row in group]
    by_code = collections.defaultdict(list)
    for fund in funds:
        by_code[fund["asoStdCd"]].append(fund)

    proposals = []
    for row in shared:
        code = row["ISU_CD"]
        override = ISSUER_OVERRIDES.get(code)
        found = by_code[override[0]] if override else candidates(row, funds)
        proposal = found[0] if len(found) == 1 else None
        evidence_url = override[1] if override else evidence_by_code.get(code, "")
        proposals.append({
            "ISU_CD": code,
            "KRX종목명": row["KRX종목명"],
            "기존_asoStdCd": row["asoStdCd"],
            "후보_asoStdCd": proposal["asoStdCd"] if proposal else "",
            "후보_포털펀드명": proposal["fndNm"] if proposal else "",
            "후보수": len(found),
            "근거수준": "운용사_종목코드_상품명" if evidence_url else "포털_이름규칙",
            "운용사_근거_URL": evidence_url,
            "판정": ("변경후보_운용사확인" if evidence_url else "변경후보_추가검증")
                    if proposal and proposal["asoStdCd"] != row["asoStdCd"]
                    else (("기존유지후보_운용사확인" if evidence_url else "기존유지후보_추가검증") if proposal else "후보미확정"),
        })

    suggested = [row["후보_asoStdCd"] for row in proposals if row["후보_asoStdCd"]]
    if len(suggested) != len(set(suggested)):
        raise RuntimeError("후보 포털 상품이 둘 이상의 KRX 종목에 다시 연결됨")
    outside = {row["asoStdCd"] for row in audit if row not in shared and row["asoStdCd"]}
    if any(code in outside for code in suggested):
        raise RuntimeError("후보가 중복 그룹 밖의 기존 연결과 충돌함")

    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.out_csv.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(proposals[0]))
        writer.writeheader()
        writer.writerows(proposals)
    print("중복 행 %d, 고유 후보 %d, 변경 후보 %d" %
          (len(proposals), len(suggested), sum(row["판정"].startswith("변경") for row in proposals)))


if __name__ == "__main__":
    main()
