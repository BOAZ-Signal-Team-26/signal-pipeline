#!/usr/bin/env python3
"""과거 측정은 보존하고, KRX 연결의 검토 상태와 수정안을 새 버전으로 합친다.

python3 research/scripts/build_krx_review_table.py FUNDS_JSON OUT_CSV
resolved_asoStdCd만 확인된 연결이다. candidate_asoStdCd는 미확정 후보를 포함한다.
"""

import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path


SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def unique_index(rows, label):
    index = {}
    for row in rows:
        code = row["ISU_CD"]
        if code in index:
            raise ValueError(f"{label}: duplicate KRX code {code}")
        index[code] = row
    return index


def build_rows(audit, duplicate_proposals, other_proposals, issuer_review, funds):
    original = unique_index(audit, "audit")
    duplicates = unique_index(duplicate_proposals, "duplicate proposals")
    others = unique_index(other_proposals, "other proposals")
    decisions = unique_index(issuer_review, "issuer review")
    if set(duplicates) & set(others):
        raise ValueError("review cohorts overlap")
    if not (set(duplicates) | set(others) | set(decisions)) <= set(original):
        raise ValueError("review contains a KRX code outside the snapshot")
    names = collections.defaultdict(set)
    for fund in funds:
        names[fund["asoStdCd"]].add(fund["fndNm"])

    output = []
    for code, row in original.items():
        proposal = duplicates.get(code) or others.get(code)
        candidate = proposal["후보_asoStdCd"] if proposal else row["asoStdCd"]
        candidate_name = proposal["후보_포털펀드명"] if proposal else row["포털펀드명"]
        resolved = evidence_type = evidence_url = ""
        note = ""
        decision = decisions.get(code)
        if decision:
            candidate = decision["asoStdCd"]
            candidate_name = decision["포털펀드명"]
            if not decision["source_url"].startswith("https://"):
                raise ValueError(f"issuer review needs an evidence URL: {code}")
            if candidate_name not in names[candidate]:
                raise ValueError(f"issuer review selects a missing portal product: {code}")
            resolved = candidate
            status = "ISSUER_REVIEWED"
            evidence_type = decision["evidence_type"]
            evidence_url = decision["source_url"]
            note = decision["note"]
        elif row["result"] == "확정(사람 확인)" and not row["review_reasons"]:
            resolved = candidate
            status = "PREVIOUS_MANUAL"
            evidence_type = "PREVIOUS_REVIEW_MEMO"
            note = "기존 사람 확인 판정 유지. 운용사 근거 검토와 별도"
        elif not row["review_reasons"]:
            status = "STRUCTURAL_PASS_ONLY"
            note = "후보 수·중복 검사 통과. 상품 동일성 확인 전"
        else:
            status = "PENDING"
            note = "운용사 근거와 상품 동일성 추가 확인 필요"
            if code == "285690":
                candidate = "K55104C03165"
                candidate_name = "브이아이 FOCUS ESG Leaders 150 증권 상장지수 투자신탁[주식]"
                note = "영문 정식명칭 후보 발견. 공식 상품 목록과 KRX 코드의 직접 대응 미확인"
            elif code == "0133E0":
                note = "포털 상품 두 개: K55301EP6877(2026-01-30), KR5225874118(2009-10-20). 설정일만으로 확정하지 않음"
            elif code == "0191S0":
                note = "유일 포털 후보를 찾았으나 IBK자산운용 공식 자료에서 종목코드·상품명 대응을 확인하지 못함"
            elif code in {"102110", "091230", "277630"}:
                note = "유일 변경 후보. 공식 상품 페이지 접근 제한과 검색 미확인으로 보류"
            elif not candidate:
                note = "포털 원본에서 적합 후보 없음. 비슷한 이름의 다른 상품으로 대체하지 않음"
        if candidate and candidate_name not in names[candidate]:
            raise ValueError(f"candidate is absent from the portal snapshot: {code}")
        output.append({
            "ISU_CD": code,
            "KRX종목명": row["KRX종목명"],
            "original_asoStdCd": row["asoStdCd"],
            "candidate_asoStdCd": candidate,
            "candidate_portal_name": candidate_name,
            "resolved_asoStdCd": resolved,
            "review_status": status,
            "evidence_type": evidence_type,
            "evidence_url": evidence_url,
            "original_review_reasons": row["review_reasons"],
            "review_note": note,
        })
    # 후보와 확정 연결을 각각 검사한다. 후보가 유일해도 자동 확정하지 않는다.
    for field in ("candidate_asoStdCd", "resolved_asoStdCd"):
        claimed = collections.defaultdict(set)
        for row in output:
            if row[field]:
                claimed[row[field]].add(row["ISU_CD"])
        conflicts = {key: sorted(value) for key, value in claimed.items() if len(value) > 1}
        if conflicts:
            raise ValueError(f"{field} collision: {conflicts}")
    return output


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("funds_json", type=Path)
    parser.add_argument("out_csv", type=Path)
    args = parser.parse_args()
    paths = {
        "audit": SAMPLES / "krx_match_audit.csv",
        "duplicate_proposals": SAMPLES / "krx_duplicate_link_proposals.csv",
        "other_proposals": SAMPLES / "krx_other_review_proposals.csv",
        "issuer_review": SAMPLES / "krx_issuer_review.csv",
    }
    rows = build_rows(**{key: read_csv(path) for key, path in paths.items()},
                      funds=json.loads(args.funds_json.read_text(encoding="utf-8")))
    summary = {
        "scope": "KRX 2026-09-04 snapshot; issuer review 2026-10-04. Identity confirmation does not establish current listing or CDI eligibility.",
        "row_count": len(rows),
        "statuses": dict(collections.Counter(row["review_status"] for row in rows)),
        "issuer_confirmed_corrections": sum(row["review_status"] == "ISSUER_REVIEWED" and bool(row["original_asoStdCd"]) and row["resolved_asoStdCd"] != row["original_asoStdCd"] for row in rows),
        "issuer_confirmed_new_links": sum(row["review_status"] == "ISSUER_REVIEWED" and not row["original_asoStdCd"] for row in rows),
        "candidate_changes": sum(bool(row["original_asoStdCd"]) and bool(row["candidate_asoStdCd"]) and row["candidate_asoStdCd"] != row["original_asoStdCd"] for row in rows),
        "candidate_missing": sum(not row["candidate_asoStdCd"] for row in rows),
        "candidate_portal_collision_groups": 0,
        "resolved_portal_collision_groups": 0,
        "inputs_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (*paths.values(), args.funds_json)},
    }
    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.out_csv.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    args.out_csv.with_suffix(".summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
