from synthetic import body_block, make, toc_block

from signal_pipeline.parsing.dart_sections import split_sections
from signal_pipeline.parsing.regions import (
    bookmark_check,
    emphasis_blocks,
    page_furniture_blocks,
    subheading_blocks,
    summary_label_blocks,
    table_blocks,
)


def page(first: str, body: str, last: str) -> str:
    return f"{first}\n\n{body}\n\n{last}"


def test_furniture_repeated_first_last_and_page_numbers() -> None:
    pages = [page("펀드명 투자설명서", f"본문 {i}", f"- {i} -") for i in range(1, 7)]
    text = "\f".join(pages)
    got = [text[r["char_start"] : r["char_end"]] for r in page_furniture_blocks(text)]
    assert got.count("펀드명 투자설명서") == 6
    assert got.count("- 3 -") == 1 and len(got) == 12
    assert "본문 2" not in got


def test_furniture_page_number_only_last_line_in_short_doc() -> None:
    # 쪽 수가 적어 반복 규칙에 안 걸려도 쪽 번호만 있는 끝 줄은 표시
    text = "첫 쪽 내용\n1\f둘째 쪽 내용\n2"
    got = [text[r["char_start"] : r["char_end"]] for r in page_furniture_blocks(text)]
    assert got == ["1", "2"]


def test_table_regions_has_sentences() -> None:
    text = "앞 구분 | 이 투자신탁은 위험합니다. 뒤 숫자 1,000 뒤"
    out = table_blocks(text, [(0, 22), (23, len(text))])
    assert [t["has_sentences"] for t in out] == [True, False]
    assert out[0] == {
        "kind": "table", "char_start": 0, "char_end": 22, "has_sentences": True,
    }  # fmt: skip


def test_bookmark_check_counts() -> None:
    text = make(toc_block(), ["* 용어정리"], body_block())
    split = split_sections(text)
    marks = [
        (0, "제1부 모집 또는 매출에 관한 사항"),
        (1, "1. 투자대상"),
        (1, "3. 없는 절"),
        (0, "제2부 발행인에 관한 사항"),
        (1, "1. 회사의 개요"),
        (1, "표지"),
    ]
    got = bookmark_check(marks, split)
    assert got["bookmark_parts"] == 2 and got["matched_parts"] == 2
    assert got["bookmark_sections"] == 3 and got["matched_sections"] == 2
    assert got["rule_parts"] == 3 and got["rule_sections"] == 5
    # 책갈피가 없으면 「하나도 안 맞음」(0)이 아니라 null
    assert bookmark_check([], split) is None
    assert bookmark_check(marks, None)["rule_parts"] == 0


def test_subheading_levels_ranges_and_table_lines_skipped() -> None:
    sub = [
        "가. 투자목적",
        "본문",
        "(1) 세부",
        "본문",
        "(2) 세부2",
        "나. 투자전략",
        "끝",
    ]
    body = body_block()
    at = body.index("1. 투자대상") + 1
    text = make(toc_block(), body[:at] + sub + body[at + 1 :])
    split = split_sections(text)
    table_line = text.index("(2) 세부2")
    got = subheading_blocks(text, split, [(table_line, table_line + 6)])
    titles = [(b["title"], b["level"]) for b in got]
    assert titles == [("가. 투자목적", 1), ("(1) 세부", 2), ("나. 투자전략", 1)]
    first, second, third = got
    assert first["char_end"] == third["char_start"]  # 같은 수준 다음 제목 직전까지
    assert second["char_end"] == third["char_start"]  # 상위 제목에서 끝남
    sec = next(s for s in split.sections if s.section_seq == first["section_seq"])
    assert sec.title == "1. 투자대상" and third["char_end"] == sec.char_end
    assert text[first["title_char_start"] : first["title_char_end"]] == "가. 투자목적"
    assert subheading_blocks(text, None, []) == []


def test_summary_labels_only_inside_summary_section() -> None:
    text = "[요약정보]\n투자목적 국내 주식\n" + make(toc_block(), body_block())
    split = split_sections(text)
    inside = (text.index("투자목적"), text.index("투자목적") + 4, "투자목적")
    outside = (text.index("본문 내용"), text.index("본문 내용") + 5, "본문 내용")
    got = summary_label_blocks([inside, outside], split)
    assert got == [
        {"kind": "summary_label", "char_start": inside[0], "char_end": inside[1],
         "text": "투자목적"},
    ]  # fmt: skip


def test_emphasis_blocks_fields() -> None:
    got = emphasis_blocks([(0, 3, "stroke", None), (5, 8, None, "#FF0000")])
    assert got[0]["bold"] and got[0]["bold_method"] == "stroke"
    assert not got[1]["bold"] and got[1]["color"] == "#FF0000"
    assert {b["kind"] for b in got} == {"emphasis"}
