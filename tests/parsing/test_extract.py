import json
from pathlib import Path

import pytest
from synthetic import body_block, make, toc_block

from signal_pipeline.common.storage import RawStore
from signal_pipeline.parsing import extract

KEY = "20261002000026"
TEXT = make(toc_block(), body_block()) + "\n" + "충분히 긴 본문 " * 20


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    RawStore(tmp_path).save("dart", KEY, "body_pdf", "pdf", b"%PDF-1.4 fake", {})
    monkeypatch.setattr(extract, "parser_version", lambda: "pdftotext-24.02_prep-1")
    monkeypatch.setattr(extract, "pdf_to_text", lambda path: TEXT)
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
    def boom(path: Path) -> str:
        raise extract.PdfTextError("깨진 PDF")

    monkeypatch.setattr(extract, "pdf_to_text", boom)
    extract.run(root)
    rec = lines(root, run_id_of(root))[0]
    assert rec["extract_status"] == "EXTRACT_FAILED" and rec["error_reason"]
    assert rec["text_path"] is None and not (root / "derived").exists()


def test_empty_text_is_ocr_candidate_and_non_pdf_unsupported(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(extract, "pdf_to_text", lambda path: "  \n ")
    extract.run(root)
    assert lines(root, run_id_of(root))[0]["extract_status"] == "OCR_CANDIDATE"

    RawStore(root).save("dart", "20261002000027", "body_pdf", "pdf", b"<html>", {})
    extract.run(root)
    statuses = {
        r["source_key"]: r["extract_status"] for r in lines(root, run_id_of(root))
    }
    assert statuses["20261002000027"] == "EXTRACT_UNSUPPORTED_FORMAT"


def test_no_part_keeps_text_without_structure(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(extract, "pdf_to_text", lambda path: "내용 없는 구조 " * 30)
    summary = extract.run(root)
    rec = lines(root, run_id_of(root))[0]
    assert (
        rec["extract_status"] == "EXTRACT_OK"
        and rec["structure_status"] == "UNAVAILABLE"
    )
    assert rec["text_path"] and rec["structure_path"] is None
    assert summary["document_fail"]["source_keys"] == [KEY]
    assert extract.quality_flags("짧음") == ["SHORT_TEXT"]
    assert "BROKEN_CHARS" in extract.quality_flags("�" * 600)
