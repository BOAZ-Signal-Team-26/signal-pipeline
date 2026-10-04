import json
import re
from datetime import date
from pathlib import Path

from signal_pipeline.common.http import FetchResult, Outcome, Try
from signal_pipeline.common.runlog import RunLog, new_run_id
from signal_pipeline.common.state import Watermark
from signal_pipeline.common.storage import StoredObject


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_run_id_format() -> None:
    assert re.fullmatch(r"extract-\d{8}T\d{6}Z-[0-9a-f]{4}", new_run_id())


def test_each_try_becomes_one_line_and_last_line_gets_final_judgement(
    tmp_path: Path,
) -> None:
    log = RunLog(tmp_path, baseline_date="2026-10-05", config={"lookback_days": 3})
    result = FetchResult(
        endpoint="https://opendart.fss.or.kr/api/document.xml",
        request_params={"rcept_no": "20260929000462"},
        outcome=Outcome.SUCCESS,
        http_status=200,
        tries=[
            Try(1, "t1", 503, Outcome.RETRYABLE_FAILED, "HTTP 503"),
            Try(2, "t2", 200, Outcome.SUCCESS, None),
        ],
    )
    # HTTP 200이지만 내용이 status 014(파일 없음)인 경우를 크롤러가 판정해 덮어씀
    outcome = log.log_fetch(
        result,
        source="dart",
        request_key="document.xml:20260929000462",
        document_key="20260929000462",
        source_result_code="014",
        final_outcome=Outcome.PERMANENT_FAILED,
        final_error="status 014",
    )
    rows = read_jsonl(log.dir / "attempts.jsonl")
    assert outcome is Outcome.PERMANENT_FAILED
    assert [r["attempt_no"] for r in rows] == [1, 2]
    assert [r["attempt_id"] for r in rows] == [1, 2]
    assert (
        rows[0]["outcome"] == "RETRYABLE_FAILED"
        and rows[0]["source_result_code"] is None
    )
    assert (
        rows[1]["outcome"] == "PERMANENT_FAILED"
        and rows[1]["source_result_code"] == "014"
    )


def test_finish_fixes_manifest_and_status(tmp_path: Path) -> None:
    log = RunLog(tmp_path, baseline_date="2026-10-05", config={})
    log.log_object(
        StoredObject("raw/dart/x/body_pdf__v1.pdf", "ab" * 32, 1, 10, reused=False),
        source="dart",
        file_role="body_pdf",
        document_key="20261002000026",
    )
    log.finish("SUCCEEDED", {"body_pdf_new": 1})
    run = json.loads((log.dir / "run.json").read_text())
    assert run["status"] == "SUCCEEDED" and run["completed_at"]
    assert run["input_manifest_path"] == f"runs/{log.run_id}/raw_objects.jsonl"
    assert len(run["input_manifest_sha256"]) == 64
    assert run["run_kind"] == "EXTRACT" and run["is_official"] is False


def test_watermark_first_run_has_no_start(tmp_path: Path) -> None:
    assert Watermark(tmp_path, "dart").start_date(lookback_days=3) is None


def test_watermark_lookback_and_no_regression(tmp_path: Path) -> None:
    mark = Watermark(tmp_path, "dart")
    assert mark.advance(date(2026, 10, 2), "run-a", first_day=date(2026, 9, 1))
    assert mark.start_date(lookback_days=3) == date(2026, 9, 29)
    assert not mark.advance(date(2026, 10, 1), "run-b")  # 앞선 날로 되돌리지 않음
    assert mark.load() == date(2026, 10, 2)
    assert mark.advance(date(2026, 10, 3), "run-b")
    assert mark.load() == date(2026, 10, 3)


def test_lookback_does_not_go_before_first_start(tmp_path: Path) -> None:
    mark = Watermark(tmp_path, "dart")
    # 첫 실행이 10월 2일부터 시작해 그날을 마침 → 룩백해도 9월 29일이 아니라 10월 2일부터
    assert mark.advance(date(2026, 10, 2), "run-a", first_day=date(2026, 10, 2))
    assert mark.start_date(lookback_days=3) == date(2026, 10, 2)
    assert mark.advance(date(2026, 10, 10), "run-b", first_day=date(2026, 10, 9))
    assert mark.start_date(lookback_days=3) == date(2026, 10, 7)


def test_first_start_is_kept_after_later_runs(tmp_path: Path) -> None:
    mark = Watermark(tmp_path, "dart")
    mark.advance(date(2026, 9, 1), "run-a", first_day=date(2026, 8, 25))
    mark.advance(date(2026, 9, 2), "run-b", first_day=date(2026, 8, 29))
    data = json.loads(mark.path.read_text())
    assert data["first_rcept_dt"] == "2026-08-25" and data["rcept_dt"] == "2026-09-02"
