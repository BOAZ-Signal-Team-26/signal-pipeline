from synthetic import body_block, make, toc_block

from signal_pipeline.parsing.dart_sections import split_sections
from signal_pipeline.parsing.regions import (
    bookmark_check,
    page_furniture_regions,
    table_regions,
)


def page(first: str, body: str, last: str) -> str:
    return f"{first}\n\n{body}\n\n{last}"


def test_furniture_repeated_first_last_and_page_numbers() -> None:
    pages = [page("펀드명 투자설명서", f"본문 {i}", f"- {i} -") for i in range(1, 7)]
    text = "\f".join(pages)
    got = [text[r["char_start"] : r["char_end"]] for r in page_furniture_regions(text)]
    assert got.count("펀드명 투자설명서") == 6
    assert got.count("- 3 -") == 1 and len(got) == 12
    assert "본문 2" not in got


def test_furniture_page_number_only_last_line_in_short_doc() -> None:
    # 쪽 수가 적어 반복 규칙에 안 걸려도 쪽 번호만 있는 끝 줄은 표시
    text = "첫 쪽 내용\n1\f둘째 쪽 내용\n2"
    got = [text[r["char_start"] : r["char_end"]] for r in page_furniture_regions(text)]
    assert got == ["1", "2"]


def test_table_regions_has_sentences() -> None:
    text = "앞 구분 | 이 투자신탁은 위험합니다. 뒤 숫자 1,000 뒤"
    out = table_regions(text, [(0, 22), (23, len(text))])
    assert [t["has_sentences"] for t in out] == [True, False]
    assert out[0]["char_start"] == 0 and out[0]["char_end"] == 22


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
    assert bookmark_check([], None)["rule_parts"] == 0
