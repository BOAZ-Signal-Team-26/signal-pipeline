#!/usr/bin/env python3
"""보존된 포털·KRX 스냅숏으로 ETF 연결의 구조적 충돌을 찾는다.

사용법: python3 research/scripts/audit_krx_matches.py FUNDS_JSON KRX_JSON OUT_CSV
이름 후보가 하나여도 상품 동일성의 최종 증명은 아니므로 검토 대상만 구분한다.
"""

import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path

from verify_etf_rule import BUCKET_PREFIX, build_buckets, normalize


ROOT = Path(__file__).resolve().parents[2]
BASE_CSV = ROOT / "research/samples/etf_rule_check.csv"
REMATCH_CSV = ROOT / "research/samples/krx_unmatched_rematch.csv"


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("funds_json", type=Path)
    parser.add_argument("krx_json", type=Path)
    parser.add_argument("out_csv", type=Path)
    args = parser.parse_args()

    funds = json.loads(args.funds_json.read_text(encoding="utf-8"))
    krx = json.loads(args.krx_json.read_text(encoding="utf-8"))
    base = list(csv.DictReader(BASE_CSV.open(encoding="utf-8")))
    rematch = list(csv.DictReader(REMATCH_CSV.open(encoding="utf-8")))
    krx_by_code = {row["ISU_CD"]: row for row in krx}
    fund_by_code = collections.defaultdict(list)
    normalized_funds = []
    for row in funds:
        fund_by_code[row["asoStdCd"]].append(row)
        normalized_funds.append({
            "name": row["fndNm"], "norm": normalize(row["fndNm"]),
            "asoStdCd": row["asoStdCd"], "srtnCd": row["srtnCd"],
        })
    prefixes = {normalize(row["ISU_NM"])[:BUCKET_PREFIX] for row in krx}
    buckets = build_buckets(normalized_funds, prefixes)

    links = []
    for row in base:
        if row["구분"] in ("일치", "누락"):
            links.append(("9월 이름 규칙", row["ISU_CD"], row["asoStdCd"], row["펀드명"], row["구분"]))
    for row in rematch:
        links.append(("10월 재대조", row["ISU_CD"], row["asoStdCd"], row["포털펀드명"], row["결과"]))

    proposals = collections.defaultdict(set)
    for _, code, portal_code, _, _ in links:
        if portal_code:
            proposals[portal_code].add(code)

    audit = []
    for cohort, code, portal_code, portal_name, result in links:
        entry = krx_by_code.get(code)
        reasons = []
        candidate_count = ""
        if entry is None:
            reasons.append("KRX_CODE_MISSING")
        if cohort == "9월 이름 규칙" and entry is not None:
            name = normalize(entry["ISU_NM"])
            candidates = [f for f in buckets.get(name[:BUCKET_PREFIX], []) if name in f["norm"]]
            candidate_count = len(candidates)
            if candidate_count != 1:
                reasons.append("MULTIPLE_NAME_CANDIDATES" if candidate_count > 1 else "NO_NAME_CANDIDATE")
            if not any(f["asoStdCd"] == portal_code and f["name"] == portal_name for f in candidates):
                reasons.append("SELECTED_OUTSIDE_CANDIDATES")
        if portal_code:
            if not any(f["fndNm"] == portal_name for f in fund_by_code[portal_code]):
                reasons.append("PORTAL_PRODUCT_MISSING")
            if len(proposals[portal_code]) > 1:
                reasons.append("SHARED_PORTAL_PRODUCT")
        if result == "보류":
            reasons.append("PENDING")
        audit.append({
            "cohort": cohort, "ISU_CD": code,
            "KRX종목명": entry["ISU_NM"] if entry else "",
            "result": result, "asoStdCd": portal_code,
            "포털펀드명": portal_name, "name_candidate_count": candidate_count,
            "linked_krx_count": len(proposals[portal_code]) if portal_code else 0,
            "review_reasons": ";".join(reasons),
        })

    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.out_csv.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(audit[0]))
        writer.writeheader()
        writer.writerows(audit)
    summary = {
        "scope": "KRX 2026-09-04 snapshot; structural link checks, not product identity certification",
        "inputs_sha256": {str(path.name): digest(path) for path in
                          (args.funds_json, args.krx_json, BASE_CSV, REMATCH_CSV)},
        "counts": dict(collections.Counter(row["result"] for row in audit)),
        "cohorts": dict(collections.Counter(row["cohort"] for row in audit)),
        "review_rows": sum(bool(row["review_reasons"]) for row in audit),
        "reason_counts": dict(collections.Counter(reason for row in audit
                                                   for reason in row["review_reasons"].split(";") if reason)),
    }
    summary_path = args.out_csv.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
