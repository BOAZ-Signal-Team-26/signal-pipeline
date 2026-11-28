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


def test_per_class_evidence_is_partial_with_table() -> None:
    text = "수수료선취- 오프라인(A) - 수수료미징구- 오프라인(C) -"
    sec = SectionText(label="제2부 13절", section_id=20, char_start=0, text=text)
    base = FieldInput(1, 2, "fee_structure", (sec,), (), text, "0" * 64, ())
    with_table = replace(base, fee_table=fee_input.FeeTable("표", "p", "0" * 64))
    value = _fee_value("수수료선취-오프라인(A)", "수수료미징구-오프라인(C)")
    lost_one = _resp(value, ["수수료선취-", "원문에 없는 인용"])
    # 정리본이 없으면 근거 하나라도 못 찾으면 실패(현행)
    assert convert(base, lost_one)["reason_code"] == "EVIDENCE_NOT_LOCATED"
    # 정리본이 있으면 찾은 근거만 남기고 FOUND, 클래스별 근거 확인 수를 notes에
    env = convert(with_table, lost_one)
    assert env["status"] == "FOUND" and len(env["evidence"]) == 1
    assert len(env["value"]["classes"]) == 2
    assert (
        "클래스별 근거 확인 1/2(위치를 못 찾은 근거 1개, 남은 근거의 원래 순번 1)"
        in env["notes"]
    )
    both = convert(with_table, _resp(value, ["수수료선취-", "수수료미징구-"]))
    assert both["status"] == "FOUND" and "클래스별 근거 확인" not in (
        both["notes"] or ""
    )
    # 모두 못 찾으면 실패
    none = convert(with_table, _resp(value, ["없는 인용 1", "없는 인용 2"]))
    assert none["reason_code"] == "EVIDENCE_NOT_LOCATED"


def _cls(name, total, peer=None):
    pct = lambda v: None if v is None else {"amount": v, "unit": "%"}
    return {
        "class_name": name,
        "front_load": None,
        "back_load": None,
        "total_fee": pct(total),
        "peer_total_fee": pct(peer),
    }


def test_correct_replaces_wrong_column_values() -> None:
    data = {
        **TABLE,
        "tables": [
            {
                "pages": [3],
                "orientation": "ROWS",
                "columns": ["총보수", "총보수·비용", "동종유형 총보수"],
                "rows": [
                    {
                        "label": "수수료선취-오프라인(A)",
                        "cells": ["0.18", "0.3214", "-"],
                    },
                    {
                        "label": "수수료미징구-온라인(Ce)",
                        "cells": ["1.147", "1.15", "1.03"],
                    },
                ],
            }
        ],
    }
    table = fee_input.FeeTable("t", "p", "0" * 64, fee_input.fee_rows(data))
    value = {
        "classes": [
            _cls(
                "수수료선취-오프라인 (A)", 0.3214, 0.1446
            ),  # 총보수·비용·증권거래비용을 잘못 고름
            _cls("수수료미징구-온라인(Ce)", 1.147, 1.03),  # 이미 맞음
        ]
    }
    fixed, note = fee_input.correct(value, table)
    assert fixed["classes"][0]["total_fee"] == {"amount": 0.18, "unit": "%"}
    assert fixed["classes"][0]["peer_total_fee"] is None
    assert fixed["classes"][1] == value["classes"][1]
    assert (
        note == "표 정리본 값으로 보정: 총보수 1개, 동종유형 총보수 1개(fee-table-v1)"
    )
    assert value["classes"][0]["total_fee"]["amount"] == 0.3214  # 원본은 그대로


def test_correct_keeps_model_value_when_no_match_or_not_number() -> None:
    rows = (
        fee_input.FeeRow("A", "0.5", None),
        fee_input.FeeRow("B", "별도", None),
        fee_input.FeeRow("C", "0.7", None),
    )
    table = fee_input.FeeTable("t", "p", "0" * 64, rows)
    value = {
        "classes": [_cls("B", 0.9), _cls("Z", 0.8)]
    }  # B는 숫자가 아님, Z는 맞는 행 없음(행 수도 다름)
    fixed, note = fee_input.correct(value, table)
    assert fixed == value and note is None
    assert fee_input.correct(value, None) == (value, None)


def test_short_code_does_not_match_other_class() -> None:
    # 표에 A·AG만 있고 모델 클래스가 (Ae)이면 「A」가 글자로 들어 있어도 맞추지 않음
    rows = (
        fee_input.FeeRow("A", "0.5", None),
        fee_input.FeeRow("AG", "0.4", None),
    )
    table = fee_input.FeeTable("t", "p", "0" * 64, rows)
    value = {"classes": [_cls("수수료선취-온라인(Ae)", 0.9)]}
    assert fee_input.correct(value, table) == (value, None)
    # 괄호 코드·맨 앞 코드는 맞춤
    coded = {"classes": [_cls("수수료선취-오프라인(A)", 0.9), _cls("AG(무권유)", 0.9)]}
    fixed, _ = fee_input.correct(coded, table)
    assert [c["total_fee"]["amount"] for c in fixed["classes"]] == [0.5, 0.4]


def test_order_fallback_disabled_when_name_matches_disagree() -> None:
    rows = (
        fee_input.FeeRow("C", "1.0", None),
        fee_input.FeeRow("A", "0.5", None),
    )
    table = fee_input.FeeTable("t", "p", "0" * 64, rows)
    # A는 이름으로 2번째 행에 맞는데 모델 순서상 1번째 → 순서 매칭을 쓰지 않아 이름 없는 클래스는 그대로
    value = {"classes": [_cls("수수료선취(A)", 0.9), _cls(None, 0.8)]}
    fixed, _ = fee_input.correct(value, table)
    assert fixed["classes"][0]["total_fee"]["amount"] == 0.5
    assert fixed["classes"][1]["total_fee"]["amount"] == 0.8
