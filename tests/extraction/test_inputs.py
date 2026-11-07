"""LLM 입력 조립 테스트. 조립 함수는 행 dict만 받으므로 DB가 필요 없다. 마지막 테스트만 로컬 DB가 있을 때 돈다."""

import hashlib
import os

import psycopg
import pytest

from signal_pipeline.extraction.inputs import (
    FIELD_SOURCES,
    assemble_document,
    assemble_field_input,
    build_field_inputs,
    is_etf,
    is_feeder_like,
)


def _row(
    sid,
    seq,
    text,
    *,
    kind="body",
    part=2,
    no=None,
    status="EXTRACT_OK",
    raw=1,
    ver="p1",
):
    return {
        "section_id": sid,
        "raw_object_id": raw,
        "parser_version": ver,
        "section_seq": seq,
        "part_seq": part,
        "source_section_no": no,
        "section_kind": kind,
        "char_start": sid * 100 if status == "EXTRACT_OK" else None,
        "extract_status": status,
        "section_text": text if status == "EXTRACT_OK" else None,
        "raw_sha256": "ab" * 32,
    }


COVER = _row(1, 1, "표지 원문 ", kind="other", part=None)
SUMMARY = _row(2, 2, "요약 원문", kind="summary", part=None)
S10 = _row(3, 5, " 위험 원문\n", no="10")
S11 = _row(4, 6, "환매 원문", no="11")
S13 = _row(5, 7, "수수료 원문", no="13")
ROWS = [S13, S10, COVER, S11, SUMMARY]  # 입력 순서가 섞여도 결과는 같아야 한다
DOC = {
    "document_id": 7,
    "source_doc_key": "20260101000001",
    "rcept_no": "20260101000001",
}


def test_hash_rule_fixed_hex():
    # 표지 + 빈 줄 + 10절, strip·정규화 없음
    fi = assemble_field_input(7, "principal_loss_notice", ROWS)
    assert fi.input_text == "표지 원문 \n\n 위험 원문\n"
    assert fi.input_sha256 == hashlib.sha256(fi.input_text.encode()).hexdigest()
    assert (
        fi.input_sha256
        == "b1fd1f5e5da6b95aa155b5fcfc00fa14666b7a719cfbcdc02fae86a24284fe59"
    )


def test_order_follows_field_sources_and_inputs():
    fi = assemble_field_input(7, "fee_structure", ROWS)
    assert [s.label for s in fi.sections] == list(FIELD_SOURCES["fee_structure"])
    assert fi.inputs == (
        {
            "raw_object_id": 1,
            "raw_sha256": "ab" * 32,
            "parser_version": "p1",
            "section_ids": [2, 5],
        },
    )
    assert fi.raw_object_id == 1
    assert fi.sections[0].char_start == 200


def test_inputs_split_when_raw_object_differs():
    other = _row(5, 7, "수수료 원문", no="13", raw=9)
    fi = assemble_field_input(7, "fee_structure", [SUMMARY, other])
    assert [e["raw_object_id"] for e in fi.inputs] == [1, 9]
    assert [e["section_ids"] for e in fi.inputs] == [[2], [5]]


def test_missing_absent_and_boundary_failure():
    fi = assemble_field_input(7, "principal_loss_notice", [S10])
    assert fi.missing == ("표지",)
    bad = _row(4, 6, "", no="11", status="SECTION_BOUNDARY_NOT_FOUND")
    fi = assemble_field_input(7, "redemption_terms", [bad])
    assert fi.missing == ("제2부 11절",) and fi.sections == ()
    assert fi.input_text == "" and fi.inputs == () and fi.raw_object_id is None


def test_duplicate_label_picks_lowest_section_seq():
    dup = _row(9, 8, "뒤 10절", no="10")
    fi = assemble_field_input(7, "key_risk_phrases", [dup, S10])
    assert [s.section_id for s in fi.sections] == [3]


def test_other_after_cover_is_not_cover():
    extra = _row(8, 3, "기타", kind="other", part=None)
    fi = assemble_field_input(7, "principal_loss_notice", [extra, S10])
    assert fi.missing == ("표지",)


def test_etf_excludes_redemption_terms():
    etf = {**DOC, "report_name": "OO 상장지수투자신탁 투자설명서"}
    inputs, exc = assemble_document(etf, ROWS)
    assert "redemption_terms" not in {i.field_name for i in inputs} and len(inputs) == 3
    assert exc["document_id"] == 7 and exc["source_doc_key"] == "20260101000001"
    assert exc["feeder_like"] is False


def test_non_etf_gets_four_fields_no_exclusion():
    inputs, exc = assemble_document({**DOC, "report_name": "OO증권투자신탁"}, ROWS)
    assert [i.field_name for i in inputs][-1] == "redemption_terms" and len(inputs) == 4
    assert exc is None


def test_feeder_flag():
    assert is_feeder_like("OO 재간접형 상장지수")
    assert is_feeder_like("OO 자투자신탁")
    assert not is_feeder_like("OO 상장지수")
    _, exc = assemble_document({**DOC, "report_name": "OO 재간접 상장지수"}, ROWS)
    assert is_etf("OO 재간접 상장지수") and exc["feeder_like"] is True


def _local_url() -> str | None:
    return os.environ.get("SIGNAL_LOCAL_DATABASE_URL")


@pytest.mark.skipif(not _local_url(), reason="SIGNAL_LOCAL_DATABASE_URL 없음")
def test_db_smoke():
    with psycopg.connect(_local_url()) as conn:
        fis, excl = build_field_inputs(conn, [], "p1")
    assert fis == [] and excl == []
