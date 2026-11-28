"""대시보드 내보내기 계약·공개 식별자·전수 대조 로직 단위 테스트."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

DASHBOARD_DIR = Path(__file__).resolve().parents[2] / "dashboard"
if str(DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_DIR))

from build_exports import (
    build_exports,
    infer_baseline_date,
    load_residual_rows,
    sanitize_residual_summary,
    verify_residual_matches_judgments,
)
from constants import (
    AXIS4_ITEM_ORDER,
    FORBIDDEN_EXPORT_COLUMNS,
    assert_public_columns,
)


def _ten_item_judgments(
    rcept_no: str, *, unmet_items: set[str] | None = None
) -> list[dict[str, str]]:
    unmet = unmet_items or set()
    return [
        {
            "rcept_no": rcept_no,
            "item": item,
            "status": "없음" if item in unmet else "있음",
        }
        for item in AXIS4_ITEM_ORDER
    ]


def test_axis4_item_order_has_10_items() -> None:
    assert len(AXIS4_ITEM_ORDER) == 10
    assert set(AXIS4_ITEM_ORDER) == {
        "나1",
        "나2",
        "3.1",
        "3.2",
        "3.3",
        "3.4",
        "4.1",
        "4.2",
        "4.3",
        "11.2",
    }


def test_assert_public_columns_rejects_forbidden() -> None:
    assert_public_columns(["fund_key", "rcept_no", "axis4_residual_b"], "docs")
    for col in FORBIDDEN_EXPORT_COLUMNS:
        with pytest.raises(ValueError, match="공개 금지 칼럼"):
            assert_public_columns(["fund_key", col], "docs")


def test_sanitize_residual_summary_removes_local_paths() -> None:
    raw = {
        "groups": 2,
        "inputs": {
            "judgments_csv": {
                "path": "../signal-data/exports/runs/score-1/axis4_judgments.csv",
                "sha256": "abc",
            }
        },
    }
    cleaned = sanitize_residual_summary(raw)
    meta = cleaned["inputs"]["judgments_csv"]
    assert "path" not in meta
    assert meta["file_name"] == "axis4_judgments.csv"
    assert meta["sha256"] == "abc"


def test_load_residual_rows_rejects_duplicate_fund_group(tmp_path: Path) -> None:
    dup_csv = tmp_path / "dup.csv"
    header = (
        "운용사코드,운용사,묶음키,대표접수번호,위험등급,ETF,운용사_묶음수,"
        "있음,없음,판정불가,적용대상아님,없음비율,적합값_A,잔차_A,적합값_B,잔차_B,제외사유\n"
    )
    row = "00000001,테스트운용,같은펀드,20260929000001,2,0,2,9,1,0,0,0.1,0.1,0.0,0.1,0.0,\n"
    dup_csv.write_text(header + row + row, encoding="utf-8-sig")
    with pytest.raises(ValueError, match="중복 펀드 묶음"):
        load_residual_rows(dup_csv)


def test_verify_residual_matches_judgments_detects_mismatch_and_duplicates() -> None:
    docs = [
        {
            "rcept_no": "20260901000001",
            "axis4_met_count": 9,
            "axis4_unmet_count": 1,
            "axis4_undetermined_count": 0,
            "axis4_na_count": 0,
        }
    ]
    good = _ten_item_judgments("20260901000001", unmet_items={"3.3"})
    verify_residual_matches_judgments(docs, good)

    # 중복 항목(3.3이 2번, 3.2 누락)은 상태 합계가 같아도 거부해야 함
    dup = [row for row in good if row["item"] != "3.2"] + [
        {"rcept_no": "20260901000001", "item": "3.3", "status": "있음"}
    ]
    with pytest.raises(ValueError, match="중복"):
        verify_residual_matches_judgments(docs, dup)

    # 10항목 중 일부 누락 거부
    missing_item = [row for row in good if row["item"] != "3.1"]
    with pytest.raises(ValueError, match="항목 불일치"):
        verify_residual_matches_judgments(docs, missing_item)

    # 상태 건수 불일치 거부
    bad_status = _ten_item_judgments("20260901000001", unmet_items=set())
    with pytest.raises(ValueError, match="불일치"):
        verify_residual_matches_judgments(docs, bad_status)


def test_infer_baseline_date_uses_latest_rcept_no() -> None:
    docs = [
        {"rcept_no": "20260901000008"},
        {"rcept_no": None},
        {"rcept_no": "20260929000123"},
    ]
    assert infer_baseline_date(docs) == "2026-09-29"


def test_build_exports_roundtrip_parquet_and_path_traversal_guard(
    tmp_path: Path,
) -> None:
    pytest.importorskip("pyarrow")
    pytest.importorskip("pandas")
    from data_loader import _read_bytes, load_bundle

    residual_csv = tmp_path / "residual.csv"
    residual_csv.write_text(
        "운용사코드,운용사,묶음키,대표접수번호,위험등급,ETF,운용사_묶음수,"
        "있음,없음,판정불가,적용대상아님,없음비율,적합값_A,잔차_A,적합값_B,잔차_B,제외사유\n"
        "00000001,테스트운용,테스트펀드1호,20260929000001,2,0,1,9,1,0,0,0.1,0.1,0.0,0.2,-0.1,\n",
        encoding="utf-8-sig",
    )
    judg_lines = ["번호,접수번호,항목,판정값,근거절,인용문장_또는_사유"]
    for idx, item in enumerate(AXIS4_ITEM_ORDER, 1):
        status = "없음" if item == "3.3" else "있음"
        judg_lines.append(f"{idx},20260929000001,{item},{status},제2부 10절,근거 문장")
    judgments_csv = tmp_path / "axis4_judgments.csv"
    judgments_csv.write_text("\n".join(judg_lines) + "\n", encoding="utf-8-sig")

    residual_json = tmp_path / "residual.json"
    residual_json.write_text(
        json.dumps(
            {"groups": 1, "used": 1, "model_a": {"r2": 0.1}, "model_b": {"r2": 0.4}}
        ),
        encoding="utf-8",
    )
    sanction_csv = tmp_path / "sanction.csv"
    sanction_csv.write_text(
        "운용사,집단,문서수,없음비율_3.2,없음비율_3.3,없음비율_3.4,없음비율_4.1,"
        "없음비율_4.2,없음비율_판별 5항목,없음비율_전체 10항목\n"
        "테스트운용,대조군 후보,1,0.0,1.0,0.0,0.0,0.0,0.2,0.1\n",
        encoding="utf-8-sig",
    )

    out_root = tmp_path / "exports"
    official_path = build_exports(
        residual_csv=residual_csv,
        residual_json=residual_json,
        judgments_csv=judgments_csv,
        sanction_csv=sanction_csv,
        score_run_id="score-test-01",
        out_root=out_root,
    )
    assert official_path.exists()

    bundle = load_bundle(str(out_root))
    assert bundle.official["score_run_id"] == "score-test-01"
    assert bundle.official["baseline_date"] == "2026-09-29"
    assert len(bundle.documents) == 1
    assert len(bundle.axis4_judgments) == 10
    assert bundle.sanction_validation is not None
    assert len(bundle.sanction_validation) == 1

    with pytest.raises(ValueError, match="허용되지 않는 상대 경로"):
        _read_bytes(str(out_root), "../secret.txt")
