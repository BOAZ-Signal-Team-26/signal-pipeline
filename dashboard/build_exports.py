"""로컬 내보내기 CSV·JSON을 대시보드 계약(official.json + Parquet)으로 변환하는 CLI.

실행 예:
    uv run --with-requirements dashboard/requirements.txt \
        python dashboard/build_exports.py \
        --residual-csv ../signal-data/exports/residual/axis4_residual__20261128.csv \
        --residual-json ../signal-data/exports/residual/axis4_residual__20261128.json \
        --judgments-csv ../signal-data/exports/runs/score-20261124T155900Z-7260/axis4_judgments.csv \
        --sanction-csv ../signal-data/exports/axis4_sanction/negative_control__20261125.csv \
        --out-root ../signal-data/exports/dashboard
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from constants import (
    AXIS4_ITEM_MAP,
    AXIS4_ITEM_ORDER,
    CONTRACT_VERSION,
    assert_public_columns,
)

KST = timezone(timedelta(hours=9))
EXPECTED_AXIS4_ITEMS = frozenset(AXIS4_ITEM_ORDER)


def sha256_file(path: Path) -> str:
    """파일의 SHA-256 16진수 해시를 계산한다."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_int(value: str | None) -> int | None:
    if value is None or value.strip() == "":
        return None
    return int(value.strip())


def _parse_float(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    return float(value.strip())


def _clean_str(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text if text != "" else None


def load_residual_rows(residual_csv: Path) -> list[dict[str, Any]]:
    """잔차 회귀 CSV를 대시보드 문서 계약 행 목록으로 변환하고 (corp_code, fund_key) 유일성을 검사한다."""
    rows: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    with residual_csv.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            corp_code = raw["운용사코드"].strip()
            fund_key = raw["묶음키"].strip()
            composite = (corp_code, fund_key)
            if composite in seen_keys:
                raise ValueError(
                    f"잔차 CSV에 중복 펀드 묶음이 있음: {corp_code} / {fund_key}"
                )
            seen_keys.add(composite)
            rows.append(
                {
                    "corp_code": corp_code,
                    "manager": raw["운용사"].strip(),
                    "fund_key": fund_key,
                    "rcept_no": _clean_str(raw.get("대표접수번호")),
                    "risk_grade": _parse_int(raw.get("위험등급")),
                    "is_etf": raw["ETF"].strip() == "1",
                    "manager_group_count": int(raw["운용사_묶음수"].strip()),
                    "axis4_met_count": _parse_int(raw.get("있음")),
                    "axis4_unmet_count": _parse_int(raw.get("없음")),
                    "axis4_undetermined_count": _parse_int(raw.get("판정불가")),
                    "axis4_na_count": _parse_int(raw.get("적용대상아님")),
                    "axis4_unmet_ratio": _parse_float(raw.get("없음비율")),
                    "axis4_fitted_a": _parse_float(raw.get("적합값_A")),
                    "axis4_residual_a": _parse_float(raw.get("잔차_A")),
                    "axis4_fitted_b": _parse_float(raw.get("적합값_B")),
                    "axis4_residual_b": _parse_float(raw.get("잔차_B")),
                    "exclude_reason": _clean_str(raw.get("제외사유")),
                    # 파트 B(축 1·2) 합류 전 슬롯: 파트 A와 절대 합산하지 않음
                    "part_b_status": "PENDING",
                    "axis1_raw": None,
                    "axis2_raw": None,
                    "part_b_score": None,
                    "part_b_percentile": None,
                    "part_b_grade_5": None,
                    "part_b_residual_b": None,
                }
            )
    if not rows:
        raise ValueError(f"잔차 CSV가 비어 있음: {residual_csv}")
    assert_public_columns(rows[0].keys(), "dashboard_documents")
    return rows


def load_judgment_rows(
    judgments_csv: Path,
    allowed_rcepts: set[str],
) -> list[dict[str, Any]]:
    """축 4 판정 CSV에서 대표 문서 집합의 10항목 행만 추출·보강한다."""
    rows: list[dict[str, Any]] = []
    with judgments_csv.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            rcept_no = raw["접수번호"].strip()
            if rcept_no not in allowed_rcepts:
                continue
            item_code = raw["항목"].strip()
            meta = AXIS4_ITEM_MAP.get(item_code)
            if meta is None:
                raise ValueError(f"알 수 없는 축 4 항목 코드: {item_code}")
            rows.append(
                {
                    "rcept_no": rcept_no,
                    "item": item_code,
                    "item_name": meta["item_name"],
                    "legal_basis": meta["legal_basis"],
                    "status": raw["판정값"].strip(),
                    "evidence_sections": _clean_str(raw.get("근거절")),
                    "quote_or_reason": _clean_str(raw.get("인용문장_또는_사유")),
                }
            )
    if not rows:
        raise ValueError(f"대표 문서에 해당하는 축 4 판정 행이 없음: {judgments_csv}")
    assert_public_columns(rows[0].keys(), "axis4_judgments")
    return rows


def verify_residual_matches_judgments(
    doc_rows: list[dict[str, Any]],
    judgment_rows: list[dict[str, Any]],
    *,
    require_all_10: bool = True,
) -> None:
    """문서당 고유 10항목 완전성과 잔차–판정 상태 건수 불일치 0건을 검증한다."""
    counts_by_rcept: dict[str, Counter[str]] = {}
    items_by_rcept: dict[str, set[str]] = {}
    duplicate_items: list[str] = []

    for row in judgment_rows:
        rcept = row["rcept_no"]
        item = row["item"]
        seen = items_by_rcept.setdefault(rcept, set())
        if item in seen:
            duplicate_items.append(f"{rcept}:{item}")
        seen.add(item)
        counts_by_rcept.setdefault(rcept, Counter())[row["status"]] += 1

    if duplicate_items:
        preview = ", ".join(duplicate_items[:5])
        raise ValueError(
            f"축 4 판정 CSV에 중복 (접수번호, 항목) {len(duplicate_items)}건: {preview}"
        )

    mismatches: list[str] = []
    for doc in doc_rows:
        rcept = doc["rcept_no"]
        if rcept is None:
            continue
        actual = counts_by_rcept.get(rcept)
        if actual is None:
            mismatches.append(f"{rcept}: 판정 행 누락")
            continue
        if require_all_10:
            doc_items = items_by_rcept.get(rcept, set())
            if doc_items != EXPECTED_AXIS4_ITEMS:
                missing = sorted(EXPECTED_AXIS4_ITEMS - doc_items)
                extra = sorted(doc_items - EXPECTED_AXIS4_ITEMS)
                mismatches.append(f"{rcept}: 항목 불일치(누락={missing}, 추가={extra})")
                continue
        expected = {
            "있음": doc["axis4_met_count"] or 0,
            "없음": doc["axis4_unmet_count"] or 0,
            "판정 불가": doc["axis4_undetermined_count"] or 0,
            "적용 대상 아님": doc["axis4_na_count"] or 0,
        }
        for status, exp_cnt in expected.items():
            act_cnt = actual.get(status, 0)
            if act_cnt != exp_cnt:
                mismatches.append(f"{rcept}({status}): 잔차={exp_cnt}, 판정={act_cnt}")
    if mismatches:
        preview = "; ".join(mismatches[:5])
        raise ValueError(
            f"잔차 CSV와 축 4 판정 CSV의 항목 건수 불일치 {len(mismatches)}건: {preview}"
        )


def load_sanction_rows(sanction_csv: Path) -> list[dict[str, Any]]:
    """법인 단위 축 4 제재 대조군 비교 CSV를 계약 행 목록으로 변환한다."""
    rows: list[dict[str, Any]] = []
    with sanction_csv.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            rows.append(
                {
                    "manager": raw["운용사"].strip(),
                    "group": raw["집단"].strip(),
                    "document_count": int(raw["문서수"].strip()),
                    "unmet_ratio_3_2": _parse_float(raw.get("없음비율_3.2")),
                    "unmet_ratio_3_3": _parse_float(raw.get("없음비율_3.3")),
                    "unmet_ratio_3_4": _parse_float(raw.get("없음비율_3.4")),
                    "unmet_ratio_4_1": _parse_float(raw.get("없음비율_4.1")),
                    "unmet_ratio_4_2": _parse_float(raw.get("없음비율_4.2")),
                    "unmet_ratio_discriminating_5": _parse_float(
                        raw.get("없음비율_판별 5항목")
                    ),
                    "unmet_ratio_all_10": _parse_float(raw.get("없음비율_전체 10항목")),
                }
            )
    if not rows:
        raise ValueError(f"제재 대조군 CSV가 비어 있음: {sanction_csv}")
    assert_public_columns(rows[0].keys(), "sanction_validation")
    return rows


def sanitize_residual_summary(raw_summary: dict[str, Any]) -> dict[str, Any]:
    """공개 금지 로컬 파일 경로를 제거하고 파일명·해시만 남긴다."""
    cleaned = json.loads(json.dumps(raw_summary))
    inputs = cleaned.get("inputs")
    if isinstance(inputs, dict):
        for meta in inputs.values():
            if isinstance(meta, dict) and "path" in meta:
                meta["file_name"] = Path(str(meta.pop("path"))).name
    return cleaned


def infer_baseline_date(doc_rows: list[dict[str, Any]]) -> str:
    """대표 접수번호(YYYYMMDDxxxxxx) 중 가장 늦은 접수일을 YYYY-MM-DD로 반환한다."""
    dates = [
        row["rcept_no"][:8]
        for row in doc_rows
        if row["rcept_no"]
        and len(row["rcept_no"]) >= 8
        and row["rcept_no"][:8].isdigit()
    ]
    if not dates:
        return datetime.now(KST).strftime("%Y-%m-%d")
    latest = max(dates)
    return f"{latest[:4]}-{latest[4:6]}-{latest[6:8]}"


def build_sanction_summary(sanction_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """법인 단위 비교 요약과 12월 2일 대조군 감사 정밀도 슬롯을 생성한다."""
    sanctioned = [r for r in sanction_rows if r["group"] == "제재 있음"]
    control = [r for r in sanction_rows if r["group"] == "대조군 후보"]

    def _mean(rows: list[dict[str, Any]], key: str) -> float | None:
        vals = [r[key] for r in rows if r[key] is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    return {
        "firm_level_note": (
            "문서를 제출한 운용사 16곳의 금감원 제재 21건 중 투자설명서 기재 관련 제재는 0건으로 "
            "확인되어 법인 단위 비교는 음성 결과로 보고함(11월 24일 PM 결정, 2인 독립 판정 검증 중)."
        ),
        "sanctioned_managers": len(sanctioned),
        "control_managers": len(control),
        "sanctioned_mean_unmet_all_10": _mean(sanctioned, "unmet_ratio_all_10"),
        "control_mean_unmet_all_10": _mean(control, "unmet_ratio_all_10"),
        "sanctioned_mean_unmet_5": _mean(sanctioned, "unmet_ratio_discriminating_5"),
        "control_mean_unmet_5": _mean(control, "unmet_ratio_discriminating_5"),
        "audit_precision_status": "PENDING",
        "audit_precision_note": (
            "대조군 감사 표본 2인 독립 판정(분석·리서치(민석)·데이터 사이언스(다빈)) 완료 후 "
            "전체·항목별 정밀도와 Wilson 95% 신뢰구간을 반영 예정(12월 2일 마감)."
        ),
        "audit_overall": None,
        "audit_by_item": [],
    }


def _write_parquet(rows: list[dict[str, Any]], dest: Path, schema: Any) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.Table.from_pylist(rows, schema=schema)
    pq.write_table(table, dest, compression="snappy")


def _write_json_atomic(dest: Path, payload: dict[str, Any]) -> None:
    tmp = dest.with_name(f".{dest.name}.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(dest)


def build_exports(
    *,
    residual_csv: Path,
    residual_json: Path,
    judgments_csv: Path,
    out_root: Path,
    score_run_id: str | None = None,
    sanction_csv: Path | None = None,
    allow_sha_mismatch: bool = False,
    require_all_10: bool = True,
) -> Path:
    """대시보드 계약 파일 묶음(official.json + runs/{score_run_id}/)을 원자적으로 생성한다."""
    import pyarrow as pa

    # 1단계: 파일 쓰기 전에 모든 입력 파싱·해시·전수 대조 완료
    raw_summary = json.loads(residual_json.read_text(encoding="utf-8"))
    expected_sha = raw_summary.get("inputs", {}).get("judgments_csv", {}).get("sha256")
    actual_sha = sha256_file(judgments_csv)
    if expected_sha and actual_sha != expected_sha and not allow_sha_mismatch:
        raise ValueError(
            "판정 CSV 해시가 잔차 요약 JSON의 입력 해시와 다릅니다. "
            "같은 실행의 판정 CSV를 지정하거나 --allow-sha-mismatch를 사용하세요."
        )

    resolved_run_id = score_run_id or judgments_csv.parent.name
    doc_rows = load_residual_rows(residual_csv)
    allowed_rcepts = {r["rcept_no"] for r in doc_rows if r["rcept_no"] is not None}
    judgment_rows = load_judgment_rows(judgments_csv, allowed_rcepts)
    verify_residual_matches_judgments(
        doc_rows, judgment_rows, require_all_10=require_all_10
    )
    cleaned_summary = sanitize_residual_summary(raw_summary)

    sanction_rows: list[dict[str, Any]] | None = None
    sanction_summary: dict[str, Any] | None = None
    if sanction_csv is not None:
        sanction_rows = load_sanction_rows(sanction_csv)
        sanction_summary = build_sanction_summary(sanction_rows)

    doc_schema = pa.schema(
        [
            ("corp_code", pa.string()),
            ("manager", pa.string()),
            ("fund_key", pa.string()),
            ("rcept_no", pa.string()),
            ("risk_grade", pa.int8()),
            ("is_etf", pa.bool_()),
            ("manager_group_count", pa.int32()),
            ("axis4_met_count", pa.int16()),
            ("axis4_unmet_count", pa.int16()),
            ("axis4_undetermined_count", pa.int16()),
            ("axis4_na_count", pa.int16()),
            ("axis4_unmet_ratio", pa.float64()),
            ("axis4_fitted_a", pa.float64()),
            ("axis4_residual_a", pa.float64()),
            ("axis4_fitted_b", pa.float64()),
            ("axis4_residual_b", pa.float64()),
            ("exclude_reason", pa.string()),
            ("part_b_status", pa.string()),
            ("axis1_raw", pa.float64()),
            ("axis2_raw", pa.float64()),
            ("part_b_score", pa.float64()),
            ("part_b_percentile", pa.float64()),
            ("part_b_grade_5", pa.int8()),
            ("part_b_residual_b", pa.float64()),
        ]
    )
    judg_schema = pa.schema(
        [
            ("rcept_no", pa.string()),
            ("item", pa.string()),
            ("item_name", pa.string()),
            ("legal_basis", pa.string()),
            ("status", pa.string()),
            ("evidence_sections", pa.string()),
            ("quote_or_reason", pa.string()),
        ]
    )
    sanction_schema = pa.schema(
        [
            ("manager", pa.string()),
            ("group", pa.string()),
            ("document_count", pa.int32()),
            ("unmet_ratio_3_2", pa.float64()),
            ("unmet_ratio_3_3", pa.float64()),
            ("unmet_ratio_3_4", pa.float64()),
            ("unmet_ratio_4_1", pa.float64()),
            ("unmet_ratio_4_2", pa.float64()),
            ("unmet_ratio_discriminating_5", pa.float64()),
            ("unmet_ratio_all_10", pa.float64()),
        ]
    )

    # 2단계: 쓰기 중 실패하면 이번에 새로 만든 파일만 정리
    run_dir = out_root / "runs" / resolved_run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    try:
        docs_path = run_dir / "dashboard_documents.parquet"
        if not docs_path.exists():
            created.append(docs_path)
        _write_parquet(doc_rows, docs_path, doc_schema)

        judg_path = run_dir / "axis4_judgments.parquet"
        if not judg_path.exists():
            created.append(judg_path)
        _write_parquet(judgment_rows, judg_path, judg_schema)

        res_sum_path = run_dir / "residual_summary.json"
        if not res_sum_path.exists():
            created.append(res_sum_path)
        _write_json_atomic(res_sum_path, cleaned_summary)

        files_map: dict[str, str | None] = {
            "documents": f"runs/{resolved_run_id}/dashboard_documents.parquet",
            "axis4_judgments": f"runs/{resolved_run_id}/axis4_judgments.parquet",
            "residual_summary": f"runs/{resolved_run_id}/residual_summary.json",
            "sanction_validation": None,
            "sanction_summary": None,
            "section_scores": None,
            "sensitivity_summary": None,
        }

        if sanction_rows is not None and sanction_summary is not None:
            s_parq = run_dir / "sanction_validation.parquet"
            if not s_parq.exists():
                created.append(s_parq)
            _write_parquet(sanction_rows, s_parq, sanction_schema)

            s_json = run_dir / "sanction_summary.json"
            if not s_json.exists():
                created.append(s_json)
            _write_json_atomic(s_json, sanction_summary)

            files_map["sanction_validation"] = (
                f"runs/{resolved_run_id}/sanction_validation.parquet"
            )
            files_map["sanction_summary"] = (
                f"runs/{resolved_run_id}/sanction_summary.json"
            )

        official = {
            "contract_version": CONTRACT_VERSION,
            "score_run_id": resolved_run_id,
            "baseline_date": infer_baseline_date(doc_rows),
            "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
            "residual_default_model": "model_b",
            "has_part_b": False,
            "has_rewrites": False,
            "has_sanction_audit": False,
            "files": files_map,
        }
        official_path = out_root / "official.json"
        _write_json_atomic(official_path, official)
    except Exception:
        for path in created:
            if path.exists():
                path.unlink()
        raise

    return official_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="대시보드용 Parquet·JSON 내보내기 생성"
    )
    parser.add_argument("--residual-csv", type=Path, required=True)
    parser.add_argument("--residual-json", type=Path, required=True)
    parser.add_argument("--judgments-csv", type=Path, required=True)
    parser.add_argument("--sanction-csv", type=Path, default=None)
    parser.add_argument("--score-run-id", type=str, default=None)
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--allow-sha-mismatch", action="store_true")
    args = parser.parse_args()

    official_path = build_exports(
        residual_csv=args.residual_csv,
        residual_json=args.residual_json,
        judgments_csv=args.judgments_csv,
        out_root=args.out_root,
        score_run_id=args.score_run_id,
        sanction_csv=args.sanction_csv,
        allow_sha_mismatch=args.allow_sha_mismatch,
    )
    print(f"내보내기 생성 완료: {official_path}")


if __name__ == "__main__":
    main()
