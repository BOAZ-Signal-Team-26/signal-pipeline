"""축 4 잔차 초안 테스트(DB 없음)."""

from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from signal_pipeline.matching.fund_key import CoverGrade, Doc, build_groups
from signal_pipeline.scoring.residual import (
    FundRow,
    build_rows,
    check_coverage,
    fit_both,
    ols,
    save,
    summarize,
)


def test_ols_recovers_exact_line() -> None:
    x = [[1.0, float(i)] for i in range(5)]
    y = [2.0 + 3.0 * i for i in range(5)]
    fit = ols(["절편", "x"], x, y)
    assert fit.coef["절편"] == pytest.approx(2.0)
    assert fit.coef["x"] == pytest.approx(3.0)
    assert max(abs(e) for e in fit.residual) < 1e-9
    assert fit.r2 == pytest.approx(1.0)


def test_ols_drops_collinear_column() -> None:
    # 세 번째 열 = 두 번째 열 복사. 계수 None, 잔차 합은 0(절편 있음)
    x = [[1.0, float(i), float(i)] for i in range(4)]
    y = [1.0, 2.0, 2.5, 4.5]
    fit = ols(["절편", "a", "a2"], x, y)
    assert fit.coef["a2"] is None
    assert sum(fit.residual) == pytest.approx(0.0, abs=1e-9)


def test_dummy_regression_residual_is_deviation_from_group_mean() -> None:
    # 등급 더미만 있으면 잔차 = 같은 등급 평균과의 차이
    rows = [
        FundRow("c", "운용사", f"k{i}", f"r{i}", g, False, {"있음": 10 - n, "없음": n})
        for i, (g, n) in enumerate([(1, 0), (1, 2), (2, 1), (2, 3)])
    ]
    _, a, _ = fit_both(rows)
    assert a.coef["ETF"] is None  # ETF가 모두 0인 열이라 뺌
    assert [round(e, 6) for e in a.residual] == [-0.1, 0.1, -0.1, 0.1]


def _doc(i: int, name: str, corp: str = "001") -> Doc:
    title = f"투자설명서(집합투자증권)({name})"
    return Doc(i, f"2026090100{i:04d}", title, corp, "가나자산운용", date(2026, 9, i))


def test_build_rows_exclusions_and_representative() -> None:
    docs = [
        _doc(1, "가 펀드"),
        _doc(2, "가 펀드"),  # 같은 묶음, 더 늦게 접수 → 대표
        _doc(3, "나 펀드"),
        _doc(4, "다 상장지수"),
        _doc(5, "라 펀드"),
    ]
    groups, _ = build_groups(docs)
    grades = {
        1: CoverGrade(3, None),
        2: CoverGrade(3, None),
        3: CoverGrade(None, "NOT_FOUND"),
        4: CoverGrade(2, None),
        5: CoverGrade(4, None),
    }
    judgments = {
        docs[1].rcept_no: Counter({"있음": 9, "없음": 1}),
        docs[3].rcept_no: Counter({"있음": 8, "적용 대상 아님": 2}),
        docs[4].rcept_no: Counter({"판정 불가": 10}),
    }
    rows = {r.group_key: r for r in build_rows(groups, grades, judgments)}
    assert rows["가펀드"].rcept_no == docs[1].rcept_no
    assert rows["가펀드"].none_ratio == pytest.approx(0.1)
    assert rows["가펀드"].excluded is None
    assert rows["나펀드"].excluded == "등급 없음(MISSING)"
    assert rows["다상장지수"].is_etf and rows["다상장지수"].none_ratio == 0
    assert rows["라펀드"].excluded == "있음+없음 0"


def test_same_day_latest_documents_are_excluded() -> None:
    a = _doc(1, "마 펀드")
    b = Doc(2, "20260901000002", a.report_name, "001", "가나자산운용", a.received_date)
    groups, _ = build_groups([a, b])
    grades = {1: CoverGrade(2, None), 2: CoverGrade(2, None)}
    judgments = {d.rcept_no: Counter({"있음": 10}) for d in (a, b)}
    (row,) = build_rows(groups, grades, judgments)
    assert row.excluded == "대표 문서 동률(AMBIGUOUS_DOCUMENT)"


def test_check_coverage_rejects_missing_extra_and_short() -> None:
    docs = [_doc(1, "가 펀드"), _doc(2, "나 펀드")]
    full = Counter({"있음": 10})
    check_coverage(docs, {d.rcept_no: full for d in docs})
    with pytest.raises(ValueError, match="빠진"):
        check_coverage(docs, {docs[0].rcept_no: full})
    with pytest.raises(ValueError, match="DB에 없는"):
        check_coverage(docs, {**{d.rcept_no: full for d in docs}, "x": full})
    with pytest.raises(ValueError, match="항목 수"):
        check_coverage(
            docs, {docs[0].rcept_no: full, docs[1].rcept_no: Counter({"있음": 9})}
        )


def test_summary_records_actual_base_grade() -> None:
    rows = [
        FundRow("c", "운용사", f"k{i}", f"r{i}", g, False, {"있음": 9, "없음": n})
        for i, (g, n) in enumerate([(2, 0), (2, 1), (3, 1), (3, 2)])
    ]
    used, a, b = fit_both(rows)
    summary = summarize(rows, used, a, b)
    assert summary["base_grade"] == 2
    assert "등급2" not in summary["model_a"]["coef"]


def test_save_removes_new_csv_when_json_exists(tmp_path: Path) -> None:
    stem = tmp_path / "out"
    stem.with_suffix(".json").write_bytes(b"old")  # 실행 전부터 있던 파일
    with pytest.raises(FileExistsError):
        save(stem, b"csv", b"json")
    assert not stem.with_suffix(".csv").exists()
    assert stem.with_suffix(".json").read_bytes() == b"old"


def test_fit_both_requires_rows() -> None:
    with pytest.raises(ValueError):
        fit_both([FundRow("c", "n", "k", "r", None, False, {}, "판정값 없음")])


def test_save_removes_partial_json_written_this_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CodeRabbit(PR #101): JSON을 만든 뒤 쓰기에 실패하면 반쯤 쓴 JSON도 지워 재실행이 막히지 않게 함
    import signal_pipeline.scoring.residual as mod

    real = mod.write_new

    def failing(path: Path, data: bytes) -> None:
        if path.suffix == ".json":
            path.write_bytes(data[:3])  # 파일은 만들어졌고 쓰다가 실패
            raise OSError("disk full")
        real(path, data)

    monkeypatch.setattr(mod, "write_new", failing)
    stem = tmp_path / "out"
    with pytest.raises(OSError):
        save(stem, b"csv", b"json-body")
    assert not stem.with_suffix(".csv").exists()
    assert not stem.with_suffix(".json").exists()


def test_summary_explains_coefficients() -> None:
    rows = [
        FundRow("c", "운용사", f"k{i}", f"r{i}", g, False, {"있음": 9, "없음": n})
        for i, (g, n) in enumerate([(1, 0), (1, 1), (2, 1), (2, 2)])
    ]
    used, a, b = fit_both(rows)
    assert "base_grade" in summarize(rows, used, a, b)["coef_note"]
