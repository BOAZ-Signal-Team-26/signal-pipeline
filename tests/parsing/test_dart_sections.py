import pytest
from synthetic import body_block, make, toc_block

from signal_pipeline.parsing.dart_sections import (
    SectionSplitError,
    invariant_violations,
    split_sections,
)


def check(result, text) -> None:
    assert invariant_violations(result, len(text)) == []


def test_toc_and_body() -> None:
    text = make(toc_block(), ["* 용어정리", "1. 투자목적"], body_block())
    result = split_sections(text)
    check(result, text)
    assert [p.part_seq for p in result.parts] == [1, 2, 3]
    assert result.toc_section_count == 5 and result.toc_part_count == 3
    assert all(s.char_start is not None for s in result.sections)
    first = result.sections[0]
    assert text[first.char_start :].startswith("1. 투자대상")
    # 절 끝 = 다음 절 시작, 부의 마지막 절 끝 = 부 끝
    assert first.char_end == result.sections[1].char_start
    assert result.sections[1].char_end == result.parts[0].char_end
    assert result.parts[-1].char_end == len(text)


def test_without_toc_has_parts_but_no_sections() -> None:
    text = make(body_block())
    result = split_sections(text)
    check(result, text)
    assert (
        len(result.parts) == 3 and result.sections == [] and result.toc_part_count == 0
    )


def test_no_part_raises() -> None:
    with pytest.raises(SectionSplitError):
        split_sections("표지\n아무 내용\n1. 개요")


def test_toc_stops_when_section_number_goes_back() -> None:
    toc = toc_block() + [
        "1. 투자자 유의사항",
        "2. 기타 안내",
    ]  # 제3부 절 번호가 되돌아감
    text = make(toc, body_block())
    assert split_sections(text).toc_section_count == 5


def test_missing_section_has_none_and_seq_is_continuous() -> None:
    body = [line for line in body_block() if "투자전략" not in line]
    text = make(toc_block(), body)
    result = split_sections(text)
    check(result, text)
    missing = [s for s in result.sections if s.extract_status != "EXTRACT_OK"]
    assert len(missing) == 1
    assert missing[0].char_start is None and missing[0].char_end is None
    assert [s.section_seq for s in result.sections] == [1, 2, 3, 4, 5]
    # 못 찾은 절 앞 절은 부 끝까지
    assert result.sections[0].char_end == result.parts[0].char_end


def test_spaced_body_heading_and_dotted_toc() -> None:
    # 10월 10일 실측 형태: 목차 줄 끝에 점선·쪽 번호, 본문 표제는 「제 3 부」처럼 띄어 씀
    toc = [
        line + " " + "." * 40 + " 12" if line.startswith("제") else line
        for line in toc_block()
    ]
    body = [line.replace("제3부", "제 3 부") for line in body_block()]
    text = make(toc, ["* 용어정리"], body)
    result = split_sections(text)
    check(result, text)
    assert [p.part_seq for p in result.parts] == [1, 2, 3]
    assert result.toc_part_count == 3
    assert all(s.char_start is not None for s in result.sections)


def test_heading_without_title_on_same_line() -> None:
    body = []
    for line in body_block():
        if line.strip().startswith("제2부"):
            body += ["   제2부", "발행인에 관한 사항"]
        else:
            body.append(line)
    text = make(toc_block(), ["* 용어정리"], body)
    result = split_sections(text)
    check(result, text)
    assert [p.part_seq for p in result.parts] == [1, 2, 3]


def test_later_title_mentioned_before_earlier_section() -> None:
    # 제1부 본문 앞쪽에 「2. 투자전략」으로 시작하는 줄이 먼저 나와도 1절 뒤에서 찾는다
    body = []
    for line in body_block():
        body.append(line)
        if line.strip().startswith("제1부"):
            body.append("2. 투자전략 요약표")
    text = make(toc_block(), ["* 용어정리"], body)
    result = split_sections(text)
    check(result, text)
    second = result.sections[1]
    assert text[second.char_start :].startswith("2. 투자전략")
