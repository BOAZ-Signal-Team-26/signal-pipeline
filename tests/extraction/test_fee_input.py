"""수수료 표 정리본 입력과 클래스별 근거 요구 테스트(이슈 #99). DB 없음."""

import json
from dataclasses import replace

import pytest

from signal_pipeline.extraction import fee_input
from signal_pipeline.extraction.convert import convert
from signal_pipeline.extraction.inputs import (
    FieldInput,
    SectionText,
    assemble_document,
    assemble_field_input,
)

SHA = "ab" * 32
TABLE = {
    "version": "fee-table-v1",
    "rcept_no": "20260101000001",
    "raw_sha256": SHA,
    "section_parser_version": "pdfplumber-0.11_prep-9",
    "status": "OK",
    "tables": [
        {
            "pages": [32],
            "orientation": "ROWS",
            "columns": ["집합투자업자보수", "총보수"],
            "rows": [
                {"label": "수수료선취-오프라인(A)", "cells": ["0.6000", "1.2970"]},
                {"label": "수수료미징구-오프라인(C)", "cells": ["0.6000", "1.9470"]},
            ],
        }
    ],
    "note": None,
}


def _row(sid, seq, text, kind="body", part=2, no=None):
    return {
        "section_id": sid,
        "raw_object_id": 1,
        "parser_version": "p1",
        "section_seq": seq,
        "part_seq": part,
        "source_section_no": no,
        "section_kind": kind,
        "char_start": sid * 100,
        "extract_status": "EXTRACT_OK",
        "section_text": text,
        "raw_sha256": SHA,
    }


S10 = _row(3, 5, "위험 원문", no="10")
ROWS = [
    _row(1, 1, "표지 원문", kind="other", part=None),
    _row(2, 2, "요약 원문", kind="summary", part=None),
    S10,
    _row(4, 6, "환매 원문", no="11"),
    _row(5, 7, "수수료 원문", no="13"),
]
DOC = {
    "document_id": 7,
    "source_doc_key": "k",
    "rcept_no": "r",
    "report_name": "가나펀드",
}


def _write(tmp_path, data):
    path = tmp_path / fee_input.table_path(SHA)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_render_rows_and_skip_unreadable() -> None:
    assert fee_input.render(TABLE).splitlines() == [
        fee_input.HEADER,
        "표 1 (32쪽)",
        "수수료선취-오프라인(A): 집합투자업자보수=0.6000; 총보수=1.2970",
        "수수료미징구-오프라인(C): 집합투자업자보수=0.6000; 총보수=1.9470",
    ]
    blank = {"label": "", "cells": ["", "0.5"]}
    assert fee_input._row_line(["집합투자업자보수", "총보수"], blank) == (
        "(클래스 이름 없음): 총보수=0.5"
    )
    assert fee_input.render({**TABLE, "status": "UNREADABLE"}) is None
    empty = {**TABLE, "tables": [{**TABLE["tables"][0], "rows": []}]}
    assert fee_input.render(empty) is None


def test_read_missing_file_and_mismatched_hash(tmp_path) -> None:
    assert fee_input.read(tmp_path, SHA) is None
    _write(tmp_path, {**TABLE, "raw_sha256": "cd" * 32})
    with pytest.raises(ValueError):
        fee_input.read(tmp_path, SHA)


def test_table_appended_only_to_fee_structure_with_section13(tmp_path) -> None:
    _write(tmp_path, TABLE)
    fis, _ = assemble_document(DOC, ROWS, tmp_path)
    by_field = {fi.field_name: fi for fi in fis}
    fee = by_field.pop("fee_structure")
    assert fee.fee_table is not None
    assert fee.input_text.endswith("\n\n" + fee_input.render(TABLE))
    assert all(fi.fee_table is None for fi in by_field.values())
    # 13절이 없으면 정리본을 붙이지 않음
    no13 = assemble_field_input(7, "fee_structure", [S10], fee.fee_table)
    assert no13.fee_table is None and fee_input.HEADER not in no13.input_text


def test_without_data_root_input_is_unchanged() -> None:
    fis, _ = assemble_document(DOC, ROWS)
    fee = next(fi for fi in fis if fi.field_name == "fee_structure")
    assert fee.fee_table is None and fee_input.HEADER not in fee.input_text


def _fee_value(*names):
    load = {"rate": None, "basis": None, "condition": None, "text": "-"}
    return {
        "classes": [
            {
                "class_name": n,
                "front_load": load,
                "back_load": None,
                "total_fee": None,
                "peer_total_fee": None,
            }
            for n in names
        ]
    }


def _resp(value, quotes):
    body = {
        "status": "FOUND",
        "value": value,
        "evidence": [{"quote": q} for q in quotes],
        "reason_code": None,
        "notes": None,
    }
    return json.dumps(body, ensure_ascii=False)


def test_per_class_evidence_required_only_with_table() -> None:
    text = "수수료선취- 오프라인(A) - 수수료미징구- 오프라인(C) -"
    sec = SectionText(label="제2부 13절", section_id=20, char_start=0, text=text)
    base = FieldInput(1, 2, "fee_structure", (sec,), (), text, "0" * 64, ())
    with_table = replace(base, fee_table=fee_input.FeeTable("표", "p", "0" * 64))
    value = _fee_value("수수료선취-오프라인(A)", "수수료미징구-오프라인(C)")
    one = _resp(value, ["수수료선취-"])
    two = _resp(value, ["수수료선취-", "수수료미징구-"])
    assert convert(base, one)["status"] == "FOUND"
    failed = convert(with_table, one)
    assert failed["reason_code"] == "SCHEMA_INVALID"
    assert "클래스별 근거 부족" in failed["notes"]
    assert convert(with_table, two)["status"] == "FOUND"
