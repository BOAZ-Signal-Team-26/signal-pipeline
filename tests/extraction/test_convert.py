import json

import pytest

from signal_pipeline.extraction.convert import (
    convert,
    dedupe_document,
    result_status,
    selected_evidence,
    validate_envelope,
)
from signal_pipeline.extraction.inputs import FieldInput, SectionText

LOSS = "투자원금의 손실이 발생할 수 있습니다."
RISK1 = "주가 변동에 따라 손실이 날 수 있습니다."
RISK2 = "환율 변동에 따라 손실이 날 수 있습니다."
FEE = {
    "classes": [
        {
            "class_name": "A",
            "front_load": {
                "rate": {"amount": 1.0, "unit": "%"},
                "basis": "납입금액",
                "condition": None,
                "text": "납입금액의 1.00% 이내",
            },
            "back_load": {
                "rate": {"amount": 0, "unit": "%"},
                "basis": None,
                "condition": None,
                "text": "없음",
            },
            "total_fee": {"amount": 0.845, "unit": "%"},
            "peer_total_fee": None,
        }
    ]
}


def field_input(field, sections, missing=()):
    secs = tuple(
        SectionText(label=f"절{i}", section_id=sid, char_start=cs, text=t)
        for i, (sid, cs, t) in enumerate(sections)
    )
    text = "\n\n".join(s.text for s in secs)
    return FieldInput(1, 2, field, secs, tuple(missing), text, "0" * 64, ())


def resp(status="FOUND", value=None, quotes=(), reason_code=None, notes=None):
    return json.dumps(
        {
            "status": status,
            "value": value,
            "evidence": [{"quote": q} for q in quotes],
            "reason_code": reason_code,
            "notes": notes,
        },
        ensure_ascii=False,
    )


PLN = field_input(
    "principal_loss_notice", [(10, 100, "표지 문장. " + LOSS), (11, 5000, "10절 본문")]
)
KRP = field_input("key_risk_phrases", [(11, 5000, f"{LOSS} {RISK1} {RISK2}")])


def test_found_principal_loss_offsets_and_raw_text() -> None:
    env = convert(PLN, resp(value=LOSS, quotes=[LOSS]))
    assert env == {
        "contract_version": 1,
        "field_name": "principal_loss_notice",
        "status": "FOUND",
        "value": LOSS,
        "raw_text": LOSS,
        "reason_code": None,
        "evidence": [
            {
                "section_id": 10,
                "char_start": 107,
                "char_end": 107 + len(LOSS),
                "quote": LOSS,
            }
        ],
        "checked_section_ids": [],
        "notes": None,
    }
    assert validate_envelope(env) == []
    assert result_status(env) == "OK"
    assert selected_evidence(env) == (10, 107, 107 + len(LOSS))


def test_step1_call_failed_wins_over_everything() -> None:
    env = convert(PLN, None, call_error="timeout")
    assert (env["status"], env["reason_code"]) == ("FAILED", "CALL_FAILED")
    assert env["notes"] == "timeout"
    assert result_status(env) == "FAILED"
    assert selected_evidence(env) == (None, None, None)
    assert validate_envelope(env) == []


@pytest.mark.parametrize("text", [None, "", "not json", "[1, 2]", '"str"'])
def test_step2_parse_failed(text) -> None:
    env = convert(PLN, text)
    assert (env["status"], env["reason_code"]) == ("FAILED", "PARSE_FAILED")
    assert validate_envelope(env) == []


def test_fenced_json_is_parsed() -> None:
    text = "```json\n" + resp(value=LOSS, quotes=[LOSS]) + "\n```"
    assert convert(PLN, text)["status"] == "FOUND"


@pytest.mark.parametrize(
    "body",
    [
        resp(status="DONE"),
        resp(status="FAILED", reason_code="CALL_FAILED"),
        resp(status="FOUND", value=LOSS, quotes=[]),
        resp(status="FOUND", value=None, quotes=[LOSS]),
        resp(status="FOUND", value=LOSS, quotes=[LOSS], reason_code="AMBIGUOUS"),
        resp(status="FOUND", value=LOSS, quotes=[LOSS, LOSS]),
        resp(status="FOUND", value=["x"], quotes=[LOSS]),
        resp(status="FOUND", value=LOSS, quotes=["  "]),
        resp(status="NOT_FOUND", value="x", reason_code="NOT_IN_DOCUMENT"),
        resp(status="NOT_FOUND", reason_code="AMBIGUOUS"),
        json.dumps({"status": "FOUND", "value": LOSS, "evidence": [LOSS]}),
    ],
)
def test_step3_schema_invalid(body) -> None:
    env = convert(PLN, body)
    assert (env["status"], env["reason_code"]) == ("FAILED", "SCHEMA_INVALID")
    assert validate_envelope(env) == []


def test_key_risk_length_mismatch_is_schema_invalid() -> None:
    env = convert(KRP, resp(value=[RISK1, RISK2], quotes=[RISK1]))
    assert env["reason_code"] == "SCHEMA_INVALID"


def test_key_risk_more_than_five_is_schema_invalid() -> None:
    env = convert(KRP, resp(value=[RISK1] * 6, quotes=[RISK1] * 6))
    assert env["reason_code"] == "SCHEMA_INVALID"


def test_fee_structure_found_and_bad_amount() -> None:
    fi = field_input("fee_structure", [(20, 0, "A 납입금액의 1.00% 이내 없음 0.845")])
    ok = convert(fi, resp(value=FEE, quotes=["A 납입금액의 1.00% 이내"]))
    assert ok["status"] == "FOUND" and ok["raw_text"] == "A 납입금액의 1.00% 이내"
    bad = json.loads(json.dumps(FEE))
    bad["classes"][0]["total_fee"] = 0.845
    assert convert(fi, resp(value=bad, quotes=["A"]))["reason_code"] == "SCHEMA_INVALID"
    assert (
        convert(fi, resp(value={"classes": []}, quotes=["A"]))["reason_code"]
        == "SCHEMA_INVALID"
    )


def test_redemption_no_fee_found_with_empty_tiers() -> None:
    fi = field_input(
        "redemption_terms", [(30, 900, "이 투자신탁은 환매수수료를 부과하지 않습니다.")]
    )
    env = convert(
        fi, resp(value={"tiers": []}, quotes=["환매수수료를 부과하지 않습니다."])
    )
    assert env["status"] == "FOUND" and env["value"] == {"tiers": []}
    assert env["evidence"][0]["char_start"] == 900 + len("이 투자신탁은 ")
    assert validate_envelope(env) == []


def test_redemption_tier_shape() -> None:
    fi = field_input("redemption_terms", [(30, 0, "90일 미만 환매시 이익금의 70%")])
    tier = {
        "period": "90일 미만",
        "basis": "이익금",
        "rate": {"amount": 70, "unit": "%"},
        "applies_to": None,
    }
    assert (
        convert(fi, resp(value={"tiers": [tier]}, quotes=["90일 미만"]))["status"]
        == "FOUND"
    )
    del tier["applies_to"]
    assert (
        convert(fi, resp(value={"tiers": [tier]}, quotes=["90일 미만"]))["reason_code"]
        == "SCHEMA_INVALID"
    )


def test_step4_whitespace_collapse_maps_back_to_original() -> None:
    fi = field_input(
        "principal_loss_notice",
        [(10, 50, "앞\n투자원금의  손실이\n\t발생할 수 있습니다.")],
    )
    env = convert(
        fi, resp(value=LOSS, quotes=[" 투자원금의 손실이 발생할\n수 있습니다. "])
    )
    ev = env["evidence"][0]
    assert ev["quote"] == "투자원금의  손실이\n\t발생할 수 있습니다."
    assert (ev["char_start"], ev["char_end"]) == (52, 52 + len(ev["quote"]))
    assert env["raw_text"] == LOSS  # principal_loss_notice는 value와 같음


def test_step4_quote_not_found() -> None:
    env = convert(PLN, resp(value=LOSS, quotes=["없는 문장"]))
    assert (env["status"], env["reason_code"]) == ("FAILED", "EVIDENCE_NOT_LOCATED")


def test_step4_cross_section_quote_not_found() -> None:
    fi = field_input(
        "principal_loss_notice",
        [(10, 0, "투자원금의"), (11, 100, "손실이 발생할 수 있습니다.")],
    )
    env = convert(fi, resp(value=LOSS, quotes=[LOSS]))
    assert env["reason_code"] == "EVIDENCE_NOT_LOCATED"


def test_step4_multi_match_uses_first_and_notes() -> None:
    fi = field_input(
        "principal_loss_notice", [(10, 0, f"x {LOSS}"), (11, 100, f"{LOSS} {LOSS}")]
    )
    env = convert(fi, resp(value=LOSS, quotes=[LOSS], notes="모델 설명"))
    assert (
        env["evidence"][0]["section_id"] == 10 and env["evidence"][0]["char_start"] == 2
    )
    assert env["notes"] == "모델 설명; 다중 일치 3회"


def test_step5_not_found_with_complete_sources() -> None:
    env = convert(PLN, resp(status="NOT_FOUND", reason_code="NOT_IN_DOCUMENT"))
    assert env["status"] == "NOT_FOUND" and env["checked_section_ids"] == [10, 11]
    assert result_status(env) == "OK" and validate_envelope(env) == []


def test_step5_not_found_with_missing_source_becomes_undetermined() -> None:
    fi = field_input("principal_loss_notice", [(11, 0, "본문")], missing=["표지"])
    env = convert(fi, resp(status="NOT_FOUND", reason_code="NOT_IN_DOCUMENT"))
    assert (env["status"], env["reason_code"]) == (
        "UNDETERMINED",
        "SOURCE_SECTION_MISSING",
    )
    assert env["checked_section_ids"] == [] and result_status(env) == "UNDETERMINED"
    assert validate_envelope(env) == []


def test_step5_no_sources_at_all_is_source_missing() -> None:
    fi = field_input("principal_loss_notice", [], missing=["표지", "제2부 10절"])
    env = convert(fi, resp(status="NOT_FOUND", reason_code="NOT_IN_DOCUMENT"))
    assert env["reason_code"] == "SOURCE_SECTION_MISSING"


def test_found_with_missing_source_keeps_found_and_notes() -> None:
    fi = field_input("principal_loss_notice", [(11, 0, LOSS)], missing=["표지"])
    env = convert(fi, resp(value=LOSS, quotes=[LOSS]))
    assert env["status"] == "FOUND" and env["notes"] == "출처 절 누락: 표지"


def test_ambiguous_and_not_applicable_kept() -> None:
    fi = field_input("redemption_terms", [], missing=["제2부 11절"])
    amb = convert(
        fi, resp(status="UNDETERMINED", reason_code="AMBIGUOUS", notes="후보 2개")
    )
    assert (amb["status"], amb["reason_code"], amb["notes"]) == (
        "UNDETERMINED",
        "AMBIGUOUS",
        "후보 2개",
    )
    na = convert(fi, resp(status="NOT_APPLICABLE", reason_code="OUT_OF_SCOPE"))
    assert result_status(na) == "NOT_APPLICABLE" and validate_envelope(na) == []


def found_pair():
    fi = field_input("principal_loss_notice", [(11, 5000, KRP.sections[0].text)])
    return convert(fi, resp(value=LOSS, quotes=[LOSS]))


def test_step6_partial_dedupe() -> None:
    krp = convert(
        KRP, resp(value=[LOSS, RISK1, RISK2], quotes=[LOSS[3:], RISK1, RISK2])
    )
    before = json.dumps(krp, ensure_ascii=False)
    out = dedupe_document(
        {"principal_loss_notice": found_pair(), "key_risk_phrases": krp}, KRP
    )
    new = out["key_risk_phrases"]
    assert new["status"] == "FOUND" and new["value"] == [RISK1, RISK2]
    assert [e["quote"] for e in new["evidence"]] == [RISK1, RISK2]
    assert new["raw_text"] == f"{RISK1}\n{RISK2}"
    assert new["notes"] == "중복 제거로 1개 삭제"
    assert selected_evidence(new)[1] == 5000 + len(LOSS) + 1
    assert json.dumps(krp, ensure_ascii=False) == before  # 입력을 고치지 않음
    assert validate_envelope(new) == []


def test_step6_all_removed_becomes_not_found() -> None:
    krp = convert(KRP, resp(value=[LOSS], quotes=[LOSS]))
    out = dedupe_document(
        {"principal_loss_notice": found_pair(), "key_risk_phrases": krp}, KRP
    )
    new = out["key_risk_phrases"]
    assert new == {
        "contract_version": 1,
        "field_name": "key_risk_phrases",
        "status": "NOT_FOUND",
        "value": None,
        "raw_text": None,
        "reason_code": "NOT_IN_DOCUMENT",
        "evidence": [],
        "checked_section_ids": [11],
        "notes": "중복 제거로 1개 삭제",
    }


def test_step6_all_removed_with_missing_source_is_undetermined() -> None:
    fi = field_input(
        "key_risk_phrases", [(11, 5000, f"{LOSS} {RISK1}")], missing=["제2부 10절"]
    )
    krp = convert(fi, resp(value=[LOSS], quotes=[LOSS]))
    out = dedupe_document(
        {"principal_loss_notice": found_pair(), "key_risk_phrases": krp}, fi
    )
    assert (
        out["key_risk_phrases"]["status"],
        out["key_risk_phrases"]["reason_code"],
    ) == (
        "UNDETERMINED",
        "SOURCE_SECTION_MISSING",
    )


def test_step6_no_overlap_or_not_found_is_unchanged() -> None:
    krp = convert(KRP, resp(value=[RISK1], quotes=[RISK1]))
    envs = {"principal_loss_notice": found_pair(), "key_risk_phrases": krp}
    assert dedupe_document(envs, KRP) == envs
    nf = convert(PLN, resp(status="NOT_FOUND", reason_code="NOT_IN_DOCUMENT"))
    assert (
        dedupe_document({"principal_loss_notice": nf, "key_risk_phrases": krp}, KRP)[
            "key_risk_phrases"
        ]
        == krp
    )
    assert dedupe_document({"fee_structure": krp}, None) == {"fee_structure": krp}


def test_step6_other_section_same_offsets_do_not_overlap() -> None:
    pln = {
        **found_pair(),
        "evidence": [
            {"section_id": 99, "char_start": 5000, "char_end": 5010, "quote": "x"}
        ],
    }
    krp = convert(KRP, resp(value=[LOSS], quotes=[LOSS]))
    assert (
        dedupe_document({"principal_loss_notice": pln, "key_risk_phrases": krp}, KRP)[
            "key_risk_phrases"
        ]
        == krp
    )


def test_step7_validate_envelope_catches_inconsistency() -> None:
    env = convert(PLN, resp(value=LOSS, quotes=[LOSS]))
    assert validate_envelope({**env, "evidence": []})
    assert validate_envelope({**env, "reason_code": "AMBIGUOUS"})
    assert validate_envelope(
        {**env, "status": "NOT_FOUND", "value": None, "evidence": [], "raw_text": None}
    )
    assert validate_envelope({**env, "status": "WHAT"})
    nf = convert(PLN, resp(status="NOT_FOUND", reason_code="NOT_IN_DOCUMENT"))
    assert validate_envelope({**nf, "checked_section_ids": []})
    assert validate_envelope({**nf, "reason_code": "BOGUS"})
    assert validate_envelope({**nf, "contract_version": 2})


def test_step6_all_removed_without_input_raises() -> None:
    krp = convert(KRP, resp(value=[LOSS], quotes=[LOSS]))
    with pytest.raises(ValueError):
        dedupe_document(
            {"principal_loss_notice": found_pair(), "key_risk_phrases": krp}, None
        )


def _fee_with(**changes):
    cls = {**FEE["classes"][0], **changes}
    return {"classes": [cls]}


@pytest.mark.parametrize(
    "value",
    [
        [],
        {"classes": "x"},
        {"classes": [1]},
        _fee_with(class_name=1),
        _fee_with(front_load={"rate": None}),
        _fee_with(
            front_load={"rate": 1, "basis": None, "condition": None, "text": None}
        ),
        _fee_with(
            back_load={"rate": None, "basis": 1, "condition": None, "text": None}
        ),
        _fee_with(peer_total_fee={"amount": True, "unit": "%"}),
        _fee_with(total_fee={"amount": 1, "unit": ""}),
    ],
)
def test_fee_structure_schema_errors(value) -> None:
    fi = field_input("fee_structure", [(20, 0, "A 표")])
    assert (
        convert(fi, resp(value=value, quotes=["A"]))["reason_code"] == "SCHEMA_INVALID"
    )


def test_fee_structure_null_load_and_classless_ok() -> None:
    fi = field_input("fee_structure", [(20, 0, "A 표")])
    assert (
        convert(
            fi, resp(value=_fee_with(class_name=None, back_load=None), quotes=["A"])
        )["status"]
        == "FOUND"
    )


@pytest.mark.parametrize(
    "tiers",
    [
        "x",
        [1],
        [{"period": 1, "basis": None, "rate": None, "applies_to": None}],
        [{"period": "p", "basis": 1, "rate": None, "applies_to": None}],
        [{"period": "p", "basis": None, "rate": 70, "applies_to": None}],
        [{"period": "p", "basis": None, "rate": None, "applies_to": []}],
    ],
)
def test_redemption_schema_errors(tiers) -> None:
    fi = field_input("redemption_terms", [(30, 0, "환매 표")])
    assert (
        convert(fi, resp(value={"tiers": tiers}, quotes=["환매"]))["reason_code"]
        == "SCHEMA_INVALID"
    )


def test_unknown_field_and_bad_notes_are_schema_invalid() -> None:
    fi = field_input("risk_grade", [(1, 0, "x")])
    assert convert(fi, resp(status="NOT_FOUND"))["reason_code"] == "SCHEMA_INVALID"
    assert (
        convert(PLN, resp(status="NOT_FOUND", notes=["x"]))["reason_code"]
        == "SCHEMA_INVALID"
    )


def test_step7_more_inconsistencies() -> None:
    env = convert(PLN, resp(value=LOSS, quotes=[LOSS]))
    assert validate_envelope({**env, "raw_text": None})
    assert validate_envelope({**env, "value": None})
    assert validate_envelope({**env, "field_name": None})
    assert validate_envelope({**env, "notes": 1})
    assert validate_envelope({**env, "checked_section_ids": [1]})
    assert validate_envelope(
        {
            **env,
            "evidence": [
                {"section_id": 1, "char_start": 5, "char_end": 5, "quote": ""}
            ],
        }
    )
    nf = convert(PLN, resp(status="NOT_FOUND"))
    assert nf["reason_code"] == "NOT_IN_DOCUMENT"  # null이면 상태의 reason_code로 채움
    assert validate_envelope({**nf, "value": "x"})
    assert validate_envelope({**nf, "evidence": env["evidence"]})


def test_줄바꿈이_단어를_끊어도_공백_없이_다시_찾음():
    fi = field_input(
        "key_risk_phrases", [(7, 100, "가격 하락 위험에 노\n출됩니다. 끝")]
    )
    q = "가격 하락 위험에 노출됩니다."
    env = convert(fi, resp(value=[q], quotes=[q]))
    assert env["status"] == "FOUND"
    assert env["evidence"][0]["char_start"] == 100
    assert env["evidence"][0]["quote"] == "가격 하락 위험에 노\n출됩니다."


def test_조금_고쳐_쓴_인용은_근사_일치로_원문_구간을_씀():
    src = "앞 문장입니다. 이 투자신탁은 증권시장에 상장되어 거래되는 주식 등 가격변동으로 인한 손실위험에 노출됩니다. 뒤"
    fi = field_input("key_risk_phrases", [(7, 0, src)])
    q = "이 투자신탁은 증권시장에 상장되어 거래되는 주식 등에 주로 투자하기 때문에 동 주식의 가격변동으로 인한 손실위험에 노출됩니다."
    env = convert(fi, resp(value=[q], quotes=[q]))
    assert env["status"] == "FAILED"  # 유사도 0.9 미만은 그대로 실패
    q2 = "이 투자신탁은 증권시장에 상장되어 거래되는 주식 등의 가격변동으로 인한 손실위험에 노출됩니다."
    env = convert(fi, resp(value=[q2], quotes=[q2]))
    assert env["status"] == "FOUND"
    assert "근사 일치" in env["notes"]
    assert env["value"] == [env["evidence"][0]["quote"]]
    assert env["evidence"][0]["quote"].startswith("이 투자신탁은")
