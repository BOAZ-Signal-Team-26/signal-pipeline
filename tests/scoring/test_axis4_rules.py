"""축 4 판정 규칙 단위 테스트. DB 없이 합성 절로 항목별 경계 사례를 확인한다. 키워드는 테스트 안에서 작게 만든다."""

import json
from importlib import resources

import pytest

from signal_pipeline.scoring.axis4_rules import (
    ITEMS,
    DocInput,
    Judgment,
    LlmRow,
    SectionRow,
    judge_document,
    validate_keywords,
)

KW = {
    "items": {
        "3.1": {
            "any": [{"id": "vol", "re": r"수익률\s*변동성"}, {"id": "var", "re": "VaR"}]
        },
        "3.2": {"any": [{"id": "result", "re": r"\d+(?:\.\d+)?%\s*로\s*\d\s*등급"}]},
        "3.3": {
            "meaning": [{"id": "scale", "re": r"1\s*등급\s*매우\s*높은\s*위험"}],
            "caution": [{"id": "change", "re": r"등급은\s*변경될\s*수\s*있"}],
        },
        "3.4": {"any": [{"id": "grade", "re": r"위험등급\s*:?\s*\d\s*등급"}]},
        "11.2": {"any": [{"id": "deposit", "re": r"예금자\s*보호"}]},
        "body": {
            "pointer": [{"id": "ref", "re": "참고|참조"}],
            "pointer_same_doc": [{"id": "attach", "re": "붙임|부록|별첨"}],
            "pointer_other_doc": [
                {
                    "id": "other",
                    "re": r"집합투자규약|신탁계약서|간이투자설명서|홈페이지|https?://",
                }
            ],
        },
        "toc": {
            "any": [
                {"id": "toc", "re": r"목\s*차"},
                {"id": "parts", "re": r"(?:제\s*\d\s*부[^\n]*\n){3,}"},
            ]
        },
    }
}


def sec(
    sid, seq, kind="body", part=None, no=None, text="", title=None, status="EXTRACT_OK"
):
    start = sid * 1000
    return SectionRow(
        sid, seq, part, no, kind, title, start, start + len(text), status, text
    )


def part2(no, text, sid=None, title=None):
    n = int(no)
    return sec(sid or 10 + n, 10 + n, "body", 2, no, text, title)


def judge(sections, llm=None, etf=False):
    doc = DocInput(1, tuple(sections), llm or {}, etf)
    result = judge_document(doc, KW)
    assert [j.item for j in result] == list(ITEMS)
    return {j.item: j for j in result}


def llm(status, value=None, evidence=(), reason=None, checked=(), eid=1, result=None):
    env = {
        "status": status,
        "value": value,
        "evidence": [
            dict(zip(("section_id", "char_start", "char_end", "quote"), e))
            for e in evidence
        ],
        "reason_code": reason,
        "checked_section_ids": list(checked),
    }
    default = {
        "FOUND": "OK",
        "NOT_FOUND": "OK",
        "NOT_APPLICABLE": "NOT_APPLICABLE",
        "UNDETERMINED": "UNDETERMINED",
    }
    return LlmRow(eid, result or default.get(status, "FAILED"), env)


BODY = sec(1, 1, "body")  # 표지가 있으려면 body가 필요하다


def cover(text, seq=1, sid=1, title=None):
    return sec(sid, seq, "other", None, None, text, title)


FIRST_BODY = sec(50, 50, "body", 1, "1", "본문")


# ---- 키워드 항목: 3.1 / 3.2 / 3.3 ----


def test_evidence_offset_is_section_start_plus_match_position() -> None:
    s = part2("10", "앞 문장입니다. 수익률 변동성을 기준으로 합니다.")
    j = judge([s])["3.1"]
    pos = s.section_text.index("수익률")
    assert j.status == "MET" and j.reason_code is None
    assert j.evidence == (
        {
            "section_id": s.section_id,
            "char_start": s.char_start + pos,
            "char_end": s.char_start + pos + len("수익률 변동성"),
        },
    )
    assert j.matched == ("vol",) and j.checked_section_ids == (s.section_id,)


def test_whitespace_split_text_matches_without_normalization() -> None:
    s = part2("10", "최근\n수익률 \n  변동성 기준")
    j = judge([s])["3.1"]
    assert j.status == "MET"
    e = j.evidence[0]
    assert (
        s.section_text[e["char_start"] - s.char_start : e["char_end"] - s.char_start]
        == "수익률 \n  변동성"
    )


def test_31_and_32_share_one_sentence() -> None:
    s = part2("10", "서문. 최근 3년 수익률 변동성이 12.3%로 2등급입니다. 끝.")
    got = judge([s])
    assert got["3.1"].status == got["3.2"].status == "MET"
    sentence = s.section_text.index("최근")
    end = s.section_text.index("입니다.")
    for item in ("3.1", "3.2"):
        e = got[item].evidence[0]
        assert (
            sentence
            <= e["char_start"] - s.char_start
            < e["char_end"] - s.char_start
            <= end
        )


def test_31_unmet_when_no_keyword_and_checked_is_section10() -> None:
    s = part2("10", "위험 설명만 있음")
    j = judge([s])["3.1"]
    assert (j.status, j.checked_section_ids, j.evidence) == (
        "UNMET",
        (s.section_id,),
        (),
    )


@pytest.mark.parametrize("item", ["3.1", "3.2", "3.3"])
def test_risk_items_need_section10(item) -> None:
    j = judge([part2("9", "x")])[item]
    assert (j.status, j.reason_code) == ("UNDETERMINED", "SOURCE_SECTION_MISSING")


def test_risk_item_section10_unusable() -> None:
    j = judge([sec(5, 5, "body", 2, "10", "수익률 변동성", status="EXTRACT_FAILED")])[
        "3.1"
    ]
    assert j.reason_code == "SOURCE_SECTION_MISSING"


MEANING = "1등급 매우 높은 위험 ... 6등급 매우 낮은 위험."
CAUTION = "등급은 변경될 수 있습니다."


def test_33_needs_both_meaning_and_caution() -> None:
    both = judge([part2("10", f"{MEANING} {CAUTION}")])["3.3"]
    assert both.status == "MET" and both.matched == ("meaning:scale", "caution:change")
    assert len(both.evidence) == 2
    only_meaning = judge([part2("10", MEANING)])["3.3"]
    only_caution = judge([part2("10", CAUTION)])["3.3"]
    assert (only_meaning.status, only_caution.status) == ("UNMET", "UNMET")
    assert "주의 문구" in only_meaning.notes and "등급 체계의 뜻" in only_caution.notes
    assert only_meaning.checked_section_ids


# ---- 표지 항목: 3.4 / 11.2 ----


def test_cover_items_found_in_cover_with_offsets() -> None:
    c = cover(
        "투자결정시 유의사항\n이 펀드는 예금자 보호법에 따라 보호되지 않음\n위험등급: 2등급",
        sid=1,
    )
    got = judge([c, FIRST_BODY])
    assert got["11.2"].status == got["3.4"].status == "MET"
    pos = c.section_text.index("예금자")
    assert got["11.2"].evidence[0]["char_start"] == c.char_start + pos


def test_toc_section_is_excluded_from_cover_by_keyword_and_by_part_titles() -> None:
    toc = cover("목 차\n예금자보호 안내 ... 3\n", seq=1, sid=1)
    real = cover("표지 본문 예금자 보호 대상이 아닙니다", seq=2, sid=2)
    got = judge([toc, real, FIRST_BODY])["11.2"]
    assert got.status == "MET" and got.evidence[0]["section_id"] == 2
    assert got.checked_section_ids == (2,)
    # 제목이 아니라 부 제목이 줄지어 나오는 절도 목차
    parts = cover("제1부 모집\n제2부 운용\n제3부 재무\n예금자보호", seq=1, sid=1)
    only_toc = judge([parts, FIRST_BODY])["11.2"]
    assert (only_toc.status, only_toc.reason_code) == (
        "UNDETERMINED",
        "SOURCE_SECTION_MISSING",
    )
    # 목차를 빼고 남은 표지에 항목이 없으면 없음
    none_left = judge([toc, cover("아무 내용", seq=2, sid=2), FIRST_BODY])["11.2"]
    assert (none_left.status, none_left.checked_section_ids) == ("UNMET", (2,))


def test_toc_found_by_section_title() -> None:
    toc = cover("예금자보호", seq=1, sid=1, title="목차")
    assert judge([toc, FIRST_BODY])["11.2"].status == "UNDETERMINED"


def test_cover_is_other_sections_before_first_body_only() -> None:
    late_other = sec(
        60, 60, "other", None, None, "예금자 보호", None
    )  # 첫 body 뒤의 other는 표지가 아님
    c = cover("표지 내용", seq=1, sid=1)
    j = judge([c, FIRST_BODY, late_other])["11.2"]
    assert (j.status, j.checked_section_ids) == ("UNMET", (1,))


def test_cover_missing_cases() -> None:
    assert (
        judge([FIRST_BODY])["3.4"].reason_code == "SOURCE_SECTION_MISSING"
    )  # 표지 없음
    assert (
        judge([cover("위험등급 2등급")])["3.4"].status == "MET"
    )  # body 없으면 other 절 전체가 표지
    bad = sec(1, 1, "other", None, None, "x", status="EXTRACT_FAILED")
    assert judge([bad, FIRST_BODY])["3.4"].status == "UNDETERMINED"
    ok = cover("위험등급 2등급", seq=2, sid=2)
    assert (
        judge([bad, ok, FIRST_BODY])["3.4"].status == "MET"
    )  # 읽을 수 있는 절에서 찾으면 있음
    assert (
        judge([bad, cover("없음", seq=2, sid=2), FIRST_BODY])["3.4"].status
        == "UNDETERMINED"
    )


def test_document_without_sections() -> None:
    got = judge([])
    assert {(j.status, j.reason_code) for j in got.values()} == {
        ("UNDETERMINED", "DOCUMENT_NOT_EXTRACTED")
    }


# ---- 본문 규칙: 나1 / 4.3 ----


def body(no, text, part=2, title="투자목적"):
    return sec(
        part * 100 + int(no), part * 100 + int(no), "body", part, no, text, title
    )


def part5(text, title="신탁의 해지"):
    return body("2", text, part=5, title=title)


def na1(a, b, c):
    return judge([a, b, c] + [cover("표지", sid=900)])["나1"]


GOOD7 = body("7", "투자목적\n본 투자신탁은 국내 주식에 투자합니다.", title="투자목적")
GOOD8 = body("8", "투자대상\n주식 60% 이하", title="투자대상")
GOOD9 = body("9", "투자전략\n성장주 중심 운용", title="투자전략")


def test_na1_all_three_have_body() -> None:
    j = na1(GOOD7, GOOD8, GOOD9)
    assert (j.status, j.reason_code) == ("MET", None)
    assert [e["section_id"] for e in j.evidence] == [
        GOOD7.section_id,
        GOOD8.section_id,
        GOOD9.section_id,
    ]
    e = j.evidence[0]
    assert (
        GOOD7.section_text[
            e["char_start"] - GOOD7.char_start : e["char_end"] - GOOD7.char_start
        ]
        == "본 투자신탁은 국내 주식에 투자합니다."
    )


def test_title_only_is_unmet_and_beats_missing_section() -> None:
    title_only = body("7", "투자목적\n", title="투자목적")
    j = judge([title_only, GOOD8])["나1"]  # 9절 없음. 확정 없음이 판정 불가보다 앞선다
    assert j.status == "UNMET" and "제2부 7절" in j.notes
    assert set(j.checked_section_ids) == {title_only.section_id, GOOD8.section_id}


def test_title_only_with_whitespace_inside_title() -> None:
    s = body("7", "투 자 목 적  \n  ", title="투자목적")
    assert judge([s, GOOD8, GOOD9])["나1"].status == "UNMET"


def test_na1_missing_section_is_undetermined() -> None:
    j = judge([GOOD7, GOOD8])["나1"]
    assert (j.status, j.reason_code) == ("UNDETERMINED", "SOURCE_SECTION_MISSING")
    broken = sec(9, 9, "body", 2, "9", "x", "투자전략", status="EXTRACT_FAILED")
    assert judge([GOOD7, GOOD8, broken])["나1"].reason_code == "SOURCE_SECTION_MISSING"


def test_title_not_located() -> None:
    odd = body("7", "전혀 다른 문구의 본문입니다", title="투자목적")
    j = judge([odd, GOOD8, GOOD9])["나1"]
    assert (j.status, j.reason_code) == ("UNDETERMINED", "TITLE_NOT_LOCATED")
    no_title = body("7", "본문", title=None)
    assert judge([no_title, GOOD8, GOOD9])["나1"].reason_code == "TITLE_NOT_LOCATED"
    # 위치를 못 찾은 절이 있어도 다른 절이 확정 없음이면 없음
    title_only = body("8", "투자대상", title="투자대상")
    assert judge([odd, title_only, GOOD9])["나1"].status == "UNMET"


def test_43_body_rule_branches() -> None:
    def item43(text, title="신탁의 해지"):
        return judge([part5(text, title), cover("표지", sid=900)])["4.3"]

    assert item43("신탁의 해지\n의무해지: 수익자 전원이 동의한 경우").status == "MET"
    only_title = item43("신탁의 해지")
    assert only_title.status == "UNMET" and "제목만" in only_title.notes
    same = item43("신탁의 해지\n자세한 내용은 붙임 1을 참고하시기 바랍니다.")
    assert same.status == "MET" and same.matched == ("pointer_same_doc:attach",)
    other = item43("신탁의 해지\n해지 사유는 집합투자규약을 참조하시기 바랍니다.")
    assert other.status == "UNMET" and other.matched == ("pointer_other_doc:other",)
    assert "다른 문서" in other.notes and other.checked_section_ids
    # 참조 문장과 실질 문장이 섞이면 본문이 있는 것
    mixed = item43(
        "신탁의 해지\n수익자 전원 동의 시 해지합니다. 자세한 내용은 홈페이지를 참조."
    )
    assert mixed.status == "MET" and mixed.matched == ()
    # 같은 문서와 다른 문서를 함께 가리키면 있음
    both = item43("신탁의 해지\n붙임 2 및 홈페이지를 참조")
    assert both.status == "MET"
    # 어디를 가리키는지 알 수 없는 참조는 있음
    vague = item43("신탁의 해지\n아래 내용을 참고하세요")
    assert vague.status == "MET"
    assert item43("전혀 다름").reason_code == "TITLE_NOT_LOCATED"
    assert (
        judge([cover("표지", sid=900)])["4.3"].reason_code == "SOURCE_SECTION_MISSING"
    )


# ---- LLM 항목 ----

Q = ("quote",)
PLN_OK = llm("FOUND", "원금 손실 가능", [(11, 11100, 11110, "q")], eid=1)
KRP_OK = llm("FOUND", ["a", "b"], [(11, 11120, 11130, "q")], eid=2)
SEC10 = part2("10", "위험 본문", sid=11)


def na2(pln=PLN_OK, krp=KRP_OK, sections=(SEC10,)):
    rows = {
        k: v
        for k, v in (("principal_loss_notice", pln), ("key_risk_phrases", krp))
        if v
    }
    return judge(list(sections), rows)["나2"]


def test_na2_met_uses_evidence_without_quote() -> None:
    j = na2()
    assert j.status == "MET" and j.llm_extraction_ids == (1, 2)
    assert j.evidence == (
        {"section_id": 11, "char_start": 11100, "char_end": 11110},
        {"section_id": 11, "char_start": 11120, "char_end": 11130},
    )


def test_na2_unmet_cases() -> None:
    nf = llm("NOT_FOUND", reason="NOT_IN_DOCUMENT", checked=[11], eid=3)
    assert na2(pln=nf).status == "UNMET" and na2(pln=nf).checked_section_ids == (11,)
    assert na2(krp=nf).status == "UNMET"
    assert (
        na2(krp=llm("FOUND", [], [(11, 11100, 11110, "q")])).status == "UNMET"
    )  # 빈 목록
    und = llm("UNDETERMINED", reason="AMBIGUOUS")
    assert na2(pln=nf, krp=und).status == "UNMET"  # 없음이 판정 불가보다 앞선다
    assert na2(
        pln=llm("NOT_FOUND", reason="NOT_IN_DOCUMENT", checked=[]), krp=PLN_OK
    ).checked_section_ids == (11,)  # checked가 비면 10절로 대신함


def test_na2_undetermined_cases() -> None:
    und = llm("UNDETERMINED", reason="AMBIGUOUS")
    assert (na2(krp=und).status, na2(krp=und).reason_code) == (
        "UNDETERMINED",
        "AMBIGUOUS",
    )
    assert na2(pln=None).reason_code == "LLM_NOT_RUN"
    failed = llm("FAILED", result="FAILED")
    assert na2(krp=failed).reason_code == "INPUT_FAILED"
    assert (
        na2(sections=[part2("9", "x")]).reason_code == "SOURCE_SECTION_MISSING"
    )  # 10절 없음
    assert (
        na2(
            sections=[sec(11, 11, "body", 2, "10", "x", status="EXTRACT_FAILED")]
        ).reason_code
        == "SOURCE_SECTION_MISSING"
    )


FEE = llm("FOUND", {"classes": []}, [(21, 21000, 21010, "q")], eid=5)


def test_41_cases() -> None:
    def item(row):
        return judge([part2("13", "수수료")], {"fee_structure": row} if row else {})[
            "4.1"
        ]

    assert item(FEE).status == "MET" and item(FEE).evidence == (
        {"section_id": 21, "char_start": 21000, "char_end": 21010},
    )
    nf = item(llm("NOT_FOUND", reason="NOT_IN_DOCUMENT", checked=[21]))
    assert (nf.status, nf.checked_section_ids) == ("UNMET", (21,))
    amb = item(llm("UNDETERMINED", reason="AMBIGUOUS"))
    assert (amb.status, amb.reason_code) == ("UNDETERMINED", "AMBIGUOUS")
    assert (
        item(llm("UNDETERMINED", reason="SOURCE_SECTION_MISSING")).reason_code
        == "SOURCE_SECTION_MISSING"
    )
    assert item(None).reason_code == "LLM_NOT_RUN"
    assert item(llm("FAILED", result="FAILED")).reason_code == "INPUT_FAILED"


def test_42_tiers_etf_and_out_of_scope() -> None:
    def item(row, etf=False):
        return judge(
            [part2("11", "환매")], {"redemption_terms": row} if row else {}, etf
        )["4.2"]

    empty_tiers = llm("FOUND", {"tiers": []}, [(31, 31000, 31010, "q")])
    assert item(empty_tiers).status == "MET"  # 빈 tiers도 있음
    assert (
        item(llm("NOT_FOUND", reason="NOT_IN_DOCUMENT", checked=[31])).status == "UNMET"
    )
    oos = item(llm("NOT_APPLICABLE", reason="OUT_OF_SCOPE", eid=9))
    assert (oos.status, oos.reason_code, oos.llm_extraction_ids) == (
        "NOT_APPLICABLE",
        "OUT_OF_SCOPE",
        (9,),
    )
    etf = item(None, etf=True)  # LLM 행을 보지 않는다
    assert (etf.status, etf.reason_code, etf.llm_extraction_ids) == (
        "NOT_APPLICABLE",
        "ETF_KRX_CONFIRMED",
        (),
    )
    assert item(empty_tiers, etf=True).reason_code == "ETF_KRX_CONFIRMED"
    assert item(None).reason_code == "LLM_NOT_RUN"
    assert item(llm("FAILED", result="FAILED")).reason_code == "INPUT_FAILED"


# ---- 불변식·키워드 자산 ----


def test_judgment_invariants() -> None:
    with pytest.raises(ValueError):
        Judgment("3.1", "UNMET")
    with pytest.raises(ValueError):
        Judgment("3.1", "UNDETERMINED")
    with pytest.raises(ValueError):
        Judgment("3.1", "MET", reason_code="X")


def test_validate_keywords_rejects_bad_shapes() -> None:
    assert validate_keywords(KW) is KW
    bad_re = json.loads(json.dumps(KW))
    bad_re["items"]["3.1"]["any"][0]["re"] = "("
    dup = json.loads(json.dumps(KW))
    dup["items"]["3.1"]["any"][1]["id"] = "vol"
    empty = json.loads(json.dumps(KW))
    empty["items"]["3.3"]["caution"] = []
    no_toc = json.loads(json.dumps(KW))
    del no_toc["items"]["toc"]
    for bad in (bad_re, dup, empty, no_toc, {}):
        with pytest.raises(ValueError):
            validate_keywords(bad)


def test_real_keyword_asset_shape() -> None:
    path = resources.files("signal_pipeline.scoring") / "keywords" / "axis4_v0.json"
    validate_keywords(json.loads(path.read_text(encoding="utf-8")))


# ---- 실측 검토 반영 ----


def test_cover_without_body_uses_all_non_toc_other_sections() -> None:
    toc = cover("목 차\n예금자보호 ... 3", seq=1, sid=1)
    real = cover("표지 예금자 보호 대상이 아닙니다 위험등급: 2등급", seq=2, sid=2)
    got = judge([toc, real])
    assert got["11.2"].status == got["3.4"].status == "MET"
    assert got["11.2"].checked_section_ids == (2,)
    assert judge([cover("아무 내용")])["11.2"].status == "UNMET"


def test_41_needs_section13() -> None:
    fee = {"fee_structure": llm("FOUND", {}, [(21, 21000, 21010, "q")])}
    assert judge([part2("10", "x")], fee)["4.1"].reason_code == "SOURCE_SECTION_MISSING"
    broken = sec(7, 7, "body", 2, "13", "x", status="EXTRACT_FAILED")
    assert judge([broken], fee)["4.1"].reason_code == "SOURCE_SECTION_MISSING"


def test_unmet_with_empty_llm_checked_falls_back_to_source_section() -> None:
    nf = llm("NOT_FOUND", reason="NOT_IN_DOCUMENT", checked=[])
    s13, s11 = part2("13", "수수료", sid=13), part2("11", "환매", sid=11)
    got = judge([s13, s11], {"fee_structure": nf, "redemption_terms": nf})
    assert got["4.1"].checked_section_ids == (13,)
    assert got["4.2"].checked_section_ids == (11,)
    no11 = judge([s13], {"redemption_terms": nf})[
        "4.2"
    ]  # 11절 없음 -> 대신할 절이 없음
    assert (no11.status, no11.reason_code) == ("UNDETERMINED", "SOURCE_SECTION_MISSING")


def test_42_etf_by_report_name() -> None:
    doc = DocInput(1, (part2("11", "환매"),), {}, False, True)
    j = judge_document(doc, KW)[ITEMS.index("4.2")]
    assert (j.status, j.reason_code) == ("NOT_APPLICABLE", "ETF_REPORT_NAME")
    both = DocInput(1, (part2("11", "환매"),), {}, True, True)
    assert (
        judge_document(both, KW)[ITEMS.index("4.2")].reason_code == "ETF_KRX_CONFIRMED"
    )


def _item43(text):
    return judge([part5(text), cover("표지", sid=900)])["4.3"]


def test_body_rule_newline_inside_sentence() -> None:
    j = _item43("신탁의 해지\n해지 사유는 집합투자규약을\n참고하시기 바랍니다.")
    assert (j.status, j.matched) == ("UNMET", ("pointer_other_doc:other",))
    # 줄바꿈 위치만 다른 같은 문장
    for text in (
        "신탁의 해지\n해지 사유는\n집합투자규약을 참고하시기\n바랍니다.",
        "신탁의 해지\n해지 사유는 집합투자\n규약을 참고하시기 바랍니다.",
    ):
        assert _item43(text).status == "UNMET", text
    same = _item43("신탁의 해지\n자세한 내용은 붙임\n1을 참고하시기 바랍니다.")
    assert same.status == "MET" and same.matched == ("pointer_same_doc:attach",)
    plain = _item43(
        "신탁의 해지\n의무해지 사유는 다음과 같습니다.\n수익자 전원이 동의한 경우\n그 밖의 경우"
    )
    assert plain.status == "MET"
    # 문장 끝(다 뒤 줄바꿈)에서는 나뉘므로 실질 문장이 섞이면 있음
    assert (
        _item43(
            "신탁의 해지\n수익자 전원이 동의하면 해지한다\n집합투자규약을 참고"
        ).status
        == "MET"
    )
