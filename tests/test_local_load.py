import hashlib
import json
from pathlib import Path

import pytest

from signal_pipeline.loading.local_load import build_rows, pick_run
from signal_pipeline.parsing.extract import parser_version

PARSER = parser_version()
REPORT = "[기재정정]투자설명서(집합투자증권)(가나다증권투자신탁)"
RCEPT = "20260901000001"
PDF = b"%PDF-1 tiny"
TEXT = "가나다라마바사"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _fixture(root: Path) -> None:
    folder = root / "raw/dart" / RCEPT
    meta = {
        "source": "dart", "source_key": RCEPT, "file_role": "body_pdf", "version_seq": 1,
        "sha256": _sha(PDF), "size": len(PDF), "collected_at": "2026-10-09T15:00:00+00:00",
        "source_fields": {"rcept_no": RCEPT}, "endpoint": "https://x", "file_name": "a%20b.pdf",
    }  # fmt: skip
    _write(folder / "body_pdf__v1.pdf", PDF)
    _write(folder / "body_pdf__v1.pdf.meta.json", json.dumps(meta).encode())
    viewer = {**meta, "file_role": "viewer_tree"}  # 적재 대상 아님
    _write(folder / "viewer_tree__v1.html.meta.json", json.dumps(viewer).encode())
    listing = {"status": "000", "list": [{"rcept_no": RCEPT, "report_nm": REPORT}]}
    _write(
        root / "raw/dart/_list/2026-09-01/page-0001__v1.json",
        json.dumps(listing).encode(),
    )

    base = root / "derived" / _sha(PDF) / PARSER
    text_b = TEXT.encode()
    base.mkdir(parents=True)
    (base / "text.txt").write_bytes(text_b)
    sec = {"part_seq": None, "source_section_no": None, "title": None,
           "canonical_section_code": None, "quality_flags": []}  # fmt: skip
    structure = {
        "raw_sha256": _sha(PDF), "parser_version": PARSER,
        "sections": [
            {**sec, "section_seq": 1, "section_kind": "body", "char_start": 2, "char_end": 5,
             "extract_status": "EXTRACT_OK"},
            {**sec, "section_seq": 2, "section_kind": "body", "char_start": None, "char_end": None,
             "extract_status": "SECTION_BOUNDARY_NOT_FOUND"},
        ],
    }  # fmt: skip
    struct_b = json.dumps(structure).encode()
    (base / "structure.json").write_bytes(struct_b)

    run = "extract-20261013T000000Z-aaaa"
    attempt = {
        "raw_sha256": _sha(PDF), "source_key": RCEPT, "parser_version": PARSER,
        "extract_status": "EXTRACT_OK", "structure_status": "AVAILABLE", "error_reason": None,
        "canonical_text_path": f"derived/{_sha(PDF)}/{PARSER}/text.txt",
        "canonical_text_sha256": _sha(text_b), "text_length": len(TEXT),
        "structure_manifest_path": f"derived/{_sha(PDF)}/{PARSER}/structure.json",
        "structure_manifest_sha256": _sha(struct_b), "finished_at": "2026-10-13T00:00:01+00:00",
    }  # fmt: skip
    run_json = {
        "run_id": run, "run_kind": "EXTRACT", "is_official": False, "baseline_date": "2026-10-13",
        "status": "SUCCEEDED", "config_sha256": "0" * 64, "started_at": "2026-10-13T00:00:00+00:00",
        "completed_at": "2026-10-13T00:00:02+00:00",
        "config_manifest": json.dumps({"limit": None, "parser_version": PARSER}),
    }  # fmt: skip
    _write(root / "runs" / run / "run.json", json.dumps(run_json).encode())
    _write(
        root / "runs" / run / "extraction_attempts.jsonl",
        (json.dumps(attempt) + "\n").encode(),
    )


def test_build_rows_from_tiny_fixture(tmp_path: Path) -> None:
    _fixture(tmp_path)
    rows = build_rows(tmp_path)
    assert [d["source_doc_key"] for d in rows.documents] == [RCEPT]
    doc = rows.documents[0]
    assert doc["received_date"].isoformat() == "2026-09-01"
    # 문서 종류·정정 여부는 목록 report_nm에서(본문 파일명이 아님)
    assert doc["report_name"] == REPORT and doc["is_correction"] is True
    assert doc["document_type"] == "투자설명서"
    assert doc["source_record_payload"] == {"rcept_no": RCEPT, "report_nm": REPORT}
    assert [r["file_role"] for r in rows.raw_objects] == [
        "body_pdf"
    ]  # viewer_tree 제외
    assert rows.raw_objects[0]["file_name"] == "a b.pdf"
    assert rows.extractions[0]["extract_status"] == "EXTRACT_OK"
    found, missing = rows.sections
    assert found["section_text"] == TEXT[2:5]
    assert missing["char_start"] is None and missing["section_text"] is None
    assert build_rows(tmp_path) == rows  # 같은 입력이면 같은 행


def test_failed_extraction_has_no_sections(tmp_path: Path) -> None:
    _fixture(tmp_path)
    log = next(tmp_path.glob("runs/*/extraction_attempts.jsonl"))
    attempt = json.loads(log.read_text())
    attempt.update(
        extract_status="EXTRACT_FAILED", structure_status="UNAVAILABLE", error_reason="TIMEOUT",
        canonical_text_path=None, canonical_text_sha256=None, text_length=None,
        structure_manifest_path=None, structure_manifest_sha256=None,
    )  # fmt: skip
    log.write_text(json.dumps(attempt) + "\n")
    rows = build_rows(tmp_path)
    assert rows.extractions[0]["extract_status"] == "EXTRACT_FAILED"
    assert rows.sections == []


def test_document_missing_from_list_is_error(tmp_path: Path) -> None:
    _fixture(tmp_path)
    page = tmp_path / "raw/dart/_list/2026-09-01/page-0001__v1.json"
    page.write_text(json.dumps({"status": "000", "list": []}))
    with pytest.raises(ValueError, match="목록"):
        build_rows(tmp_path)


def test_pick_run_skips_interrupted_run(tmp_path: Path) -> None:
    _fixture(tmp_path)
    done = next(tmp_path.glob("runs/extract-*"))
    stopped = tmp_path / "runs" / "extract-20261014T000000Z-bbbb"
    stopped.mkdir()
    run = json.loads((done / "run.json").read_text())
    run.update(run_id=stopped.name, status="RUNNING", completed_at=None)
    (stopped / "run.json").write_text(json.dumps(run))
    (stopped / "extraction_attempts.jsonl").write_text("")
    assert pick_run(tmp_path, PARSER, None) == done.name
