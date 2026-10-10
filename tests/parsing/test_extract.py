import json
import time
from pathlib import Path

import pytest
from synthetic import body_block, make, toc_block

from signal_pipeline.common.storage import RawStore
from signal_pipeline.parsing import extract, parallel
from signal_pipeline.parsing.pdf_layout import PdfLayout, PdfTextError

KEY = "20261002000026"
TEXT = make(toc_block(), body_block()) + "\n" + "충분히 긴 본문 " * 20


def layout(text: str = TEXT, **kwargs: object) -> PdfLayout:
    return PdfLayout(text, [0], kwargs.pop("tables", []), **kwargs)


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    RawStore(tmp_path).save("dart", KEY, "body_pdf", "pdf", b"%PDF-1.4 fake", {})
    monkeypatch.setattr(extract, "parser_version", lambda: "pdfplumber-0.11_prep-4")
    monkeypatch.setattr(extract, "read_pdf", lambda path: layout())
    # 자식 프로세스가 위 대체를 물려받도록 fork를 쓴다(운영은 spawn)
    monkeypatch.setattr(parallel, "START_METHOD", "fork")
    return tmp_path


def lines(root: Path, run_id: str) -> list[dict]:
    path = root / "runs" / run_id / "extraction_attempts.jsonl"
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def run_id_of(root: Path) -> str:
    return max((root / "runs").iterdir(), key=lambda p: p.stat().st_mtime_ns).name


def test_extract_then_skip(root: Path) -> None:
    summary = extract.run(root)
    assert summary["extract_ok"] == 1
    rec = lines(root, run_id_of(root))[0]
    assert rec["action"] == "EXTRACTED" and rec["structure_status"] == "AVAILABLE"
    structure = json.loads((root / rec["structure_path"]).read_text(encoding="utf-8"))
    assert structure["text_length"] == len(TEXT)
    assert rec["raw_storage_path"] == f"raw/dart/{KEY}/body_pdf__v1.pdf"

    again = extract.run(root)  # 같은 파서 버전이면 건너뜀(성공으로 셈)
    assert again["skipped_existing"] == 1 and again["extract_ok"] == 1


def test_hash_mismatch_reprocesses(root: Path) -> None:
    extract.run(root)
    rec = lines(root, run_id_of(root))[0]
    (root / rec["text_path"]).write_text("변조", encoding="utf-8")
    extract.run(root)
    assert lines(root, run_id_of(root))[0]["action"] == "EXTRACTED"


def test_failures_are_recorded_with_reason(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(path: Path) -> PdfLayout:
        raise PdfTextError("깨진 PDF")

    monkeypatch.setattr(extract, "read_pdf", boom)
    extract.run(root)
    rec = lines(root, run_id_of(root))[0]
    assert rec["extract_status"] == "EXTRACT_FAILED" and rec["error_reason"]
    assert rec["text_path"] is None and not (root / "derived").exists()


def test_empty_text_is_ocr_candidate_and_non_pdf_unsupported(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(extract, "read_pdf", lambda path: layout("  \n "))
    extract.run(root)
    assert lines(root, run_id_of(root))[0]["extract_status"] == "OCR_CANDIDATE"

    RawStore(root).save("dart", "20261002000027", "body_pdf", "pdf", b"<html>", {})
    extract.run(root)
    statuses = {
        r["source_key"]: r["extract_status"] for r in lines(root, run_id_of(root))
    }
    assert statuses["20261002000027"] == "EXTRACT_UNSUPPORTED_FORMAT"


def test_no_part_writes_structure_without_parts_and_is_skipped_next_time(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = "내용 없는 구조 " * 30
    monkeypatch.setattr(extract, "read_pdf", lambda path: layout(text, tables=[(0, 7)]))
    summary = extract.run(root)
    rec = lines(root, run_id_of(root))[0]
    assert (
        rec["extract_status"] == "EXTRACT_OK"
        and rec["structure_status"] == "UNAVAILABLE"
    )
    assert rec["text_path"] and rec["structure_path"]
    structure = json.loads((root / rec["structure_path"]).read_text(encoding="utf-8"))
    assert structure["parts"] == [] and structure["sections"] == []
    assert structure["table_regions"] == [
        {"char_start": 0, "char_end": 7, "has_sentences": False}
    ]
    assert structure["headings_source"] == "RULE"
    assert summary["document_fail"]["source_keys"] == [KEY]
    assert extract.quality_flags("짧음") == ["SHORT_TEXT"]
    assert "BROKEN_CHARS" in extract.quality_flags("�" * 600)

    again = extract.run(root)  # 구조 없음도 EXTRACT_OK이면 다시 추출하지 않는다
    assert again["skipped_existing"] == 1
    assert lines(root, run_id_of(root))[0]["structure_status"] == "UNAVAILABLE"


def test_structure_has_regions_kinds_and_bookmark_source(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = "[요약정보]\n요약\n" + TEXT
    marks = [(0, "제1부 모집 또는 매출에 관한 사항"), (1, "1. 투자대상")]
    monkeypatch.setattr(
        extract, "read_pdf", lambda path: layout(text, bookmarks=marks, producer="x")
    )
    extract.run(root)
    rec = lines(root, run_id_of(root))[0]
    structure = json.loads((root / rec["structure_path"]).read_text(encoding="utf-8"))
    assert structure["headings_source"] == "BOOKMARK"
    assert structure["bookmark_check"]["matched_sections"] == 1
    # 요약정보가 텍스트 맨 앞이라 앞쪽 other는 없다
    assert structure["sections"][0]["section_kind"] == "summary"
    assert all("title" in s and "section_title" not in s for s in structure["sections"])
    assert "page_furniture_regions" in structure
    assert rec["section_count"] == 5  # 본문 절만 센다


def test_parser_version_format() -> None:
    assert extract.re.fullmatch(r"pdfplumber-\d+\.\d+_prep-4", extract.parser_version())


def slow(seconds: float) -> str:
    time.sleep(seconds)
    return "done"


def test_hung_job_is_killed_and_order_is_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(parallel, "START_METHOD", "fork")
    began = time.monotonic()
    got = parallel.run_isolated(slow, [(0.3,), (60,), (0.0,)], workers=2, timeout=1.5)
    assert [state for state, _ in got] == ["ok", "timeout", "ok"]
    assert time.monotonic() - began < 10  # 60초 작업을 기다리지 않고 끝냄


def crash(_: int) -> str:
    raise SystemExit(3)


def test_child_error_is_reported_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(parallel, "START_METHOD", "fork")
    got = parallel.run_isolated(crash, [(1,)], workers=1, timeout=5)
    assert got[0][0] == "error"


def test_run_records_timeout_as_failed_and_continues(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    RawStore(root).save("dart", "20261002000027", "body_pdf", "pdf", b"%PDF-1.4 b", {})
    real = layout()

    def maybe_hang(path: Path) -> PdfLayout:
        if path.parent.name == KEY:
            time.sleep(60)
        return real

    monkeypatch.setattr(extract, "read_pdf", maybe_hang)
    summary = extract.run(root, timeout=1.5)
    by_key = {r["source_key"]: r for r in lines(root, run_id_of(root))}
    assert by_key[KEY]["extract_status"] == "EXTRACT_FAILED"
    assert "시간 초과" in by_key[KEY]["error_reason"]
    assert by_key["20261002000027"]["extract_status"] == "EXTRACT_OK"
    assert summary["N_files"] == 2 and summary["extract_ok"] == 1
    # 기록 순서는 입력(접수번호) 순서
    assert [r["source_key"] for r in lines(root, run_id_of(root))] == [
        KEY,
        "20261002000027",
    ]


def test_unexpected_error_in_one_file_does_not_stop_run(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    RawStore(root).save("dart", "20261002000027", "body_pdf", "pdf", b"%PDF-1.4 b", {})
    real = extract.process_file

    def flaky(root: Path, pdf: Path, run_id: str, version: str):
        if pdf.parent.name == KEY:
            raise OSError("읽기 실패")
        return real(root, pdf, run_id, version)

    monkeypatch.setattr(extract, "process_file", flaky)
    summary = extract.run(root)
    assert summary["N_files"] == 2 and summary["extract_ok"] == 1
    failed = next(r for r in lines(root, run_id_of(root)) if r["source_key"] == KEY)
    assert failed["extract_status"] == "EXTRACT_FAILED"
    assert "OSError" in failed["error_reason"]
    run_json = json.loads((root / "runs" / run_id_of(root) / "run.json").read_text())
    assert run_json["status"] == "SUCCEEDED"
