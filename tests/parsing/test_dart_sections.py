import pytest
from synthetic import body_block, make, toc_block

from signal_pipeline.parsing.dart_sections import (
    SectionSplitError,
    invariant_violations,
    split_sections,
)


def bodies(result):
    return [s for s in result.sections if s.section_kind == "body"]


def check(result, text) -> None:
    assert invariant_violations(result, len(text)) == []


def test_toc_and_body() -> None:
    text = make(toc_block(), ["* 용어정리", "1. 투자목적"], body_block())
    result = split_sections(text)
    check(result, text)
    assert [p.part_seq for p in result.parts] == [1, 2, 3]
    assert result.toc_section_count == 5 and result.toc_part_count == 3
    assert all(s.char_start is not None for s in result.sections)
    first = bodies(result)[0]
    assert text[first.char_start :].startswith("1. 투자대상")
    # 절 끝 = 다음 절 시작, 부의 마지막 절 끝 = 부 끝
    assert first.char_end == bodies(result)[1].char_start
    assert bodies(result)[1].char_end == result.parts[0].char_end
    # 제목 줄 범위는 줄 시작부터 줄 끝까지, 절 범위는 제목 줄 시작부터
    assert first.char_start == first.title_char_start
    assert text[first.title_char_start : first.title_char_end] == "1. 투자대상"
    assert first.title == "1. 투자대상"
    assert result.parts[-1].char_end == len(text)


def test_without_toc_has_parts_but_no_sections() -> None:
    text = make(body_block())
    result = split_sections(text)
    check(result, text)
    assert len(result.parts) == 3 and result.toc_part_count == 0
    assert bodies(result) == []


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
    missing = [s for s in bodies(result) if s.extract_status != "EXTRACT_OK"]
    assert len(missing) == 1
    assert missing[0].char_start is None and missing[0].char_end is None
    assert [s.section_seq for s in result.sections] == list(
        range(1, len(result.sections) + 1)
    )
    # 못 찾은 절 앞 절은 부 끝까지
    assert bodies(result)[0].char_end == result.parts[0].char_end


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
    second = bodies(result)[1]
    assert text[second.char_start :].startswith("2. 투자전략")


def test_repeated_page_header_and_appendix_heading_do_not_split_body() -> None:
    # 본문 부마다 머리글 「제 1 부」가 반복되고, 제2부 안에 「제 2 부 [별첨1]」이 다시 나온다
    body = []
    for line in body_block():
        body.append(line)
        if line.strip().startswith(("제2부", "제3부")):
            body.append("제 1 부. 모집 또는 매출에 관한 사항")
        if line.strip().startswith("제2부"):
            body.append("제 2 부 [별첨1]. 모집합투자기구에 관한 사항")
    text = make(toc_block(), ["* 용어정리"], body)
    result = split_sections(text)
    check(result, text)
    assert [p.part_seq for p in result.parts] == [1, 2, 3]
    assert all(s.char_start is not None for s in result.sections)


def test_only_one_or_two_body_headings_after_toc_raises() -> None:
    # 목차는 제1~3부인데 본문에서 「제N부」 표제를 하나만 찾으면 목차 표제를 부로 쓰지 않는다
    body = [x for x in body_block() if not x.strip().startswith(("제2부", "제3부"))]
    with pytest.raises(SectionSplitError):
        split_sections(make(toc_block(), ["* 용어정리"], body))


def kinds(result) -> list[str]:
    return [s.section_kind for s in result.sections]


def test_summary_and_other_sections() -> None:
    summary = ["[요약정보]", "투자목적 및 투자전략", "[집합투자기구 공시 정보 안내]"]
    text = make(toc_block(), ["* 용어정리"], summary, body_block())
    result = split_sections(text)
    check(result, text)
    assert kinds(result)[:3] == ["other", "summary", "body"]
    other, summ = result.sections[0], result.sections[1]
    assert other.char_start == 0 and other.char_end == summ.char_start
    assert other.part_seq is None and other.source_section_no is None
    # 요약정보는 제목 줄부터 첫 본문 부 직전까지
    assert summ.title == "[요약정보]"
    assert text[summ.title_char_start : summ.title_char_end] == "[요약정보]"
    assert summ.char_end == result.parts[0].char_start
    assert [s.section_seq for s in result.sections] == list(
        range(1, len(result.sections) + 1)
    )


def test_summary_entry_inside_toc_is_skipped() -> None:
    # 목차 안 「<요약정보>」 항목은 다음 줄이 「제1부」라서 요약정보 시작이 아니다
    text = make(["<요약정보>"], toc_block(), ["<요약정보>", "내용"], body_block())
    result = split_sections(text)
    summ = next(s for s in result.sections if s.section_kind == "summary")
    assert summ.char_start == text.index("<요약정보>", 10)


def test_bare_summary_heading_is_fallback() -> None:
    text = make(toc_block(), ["\f   요약 정보", "내용"], body_block())
    assert "summary" in kinds(split_sections(text))


def test_no_summary_gives_only_leading_other() -> None:
    text = make(toc_block(), body_block())
    result = split_sections(text)
    assert kinds(result)[:1] == ["other"] and "summary" not in kinds(result)
    assert result.sections[0].char_end == result.parts[0].char_start


def test_toc_after_summary_is_other() -> None:
    text = make(["[요약정보]", "내용"], toc_block(), ["* 용어정리"], body_block())
    result = split_sections(text)
    check(result, text)
    assert kinds(result)[:3] == ["other", "summary", "other"]
    assert result.sections[1].char_end == text.index("제1부")


def test_wide_spaced_heading_from_layout_text_is_found() -> None:
    # pdfplumber layout은 글자 간격을 공백으로 늘려 표제 줄이 60자를 넘는다(공백 하나로 보고 잰다)
    body = [
        line.replace(" 투자위험요소", " " + " " * 12 + "투자위험요소")
        for line in body_block()
    ]
    body = [
        x.replace("제3부", "제3부" + " " * 40) if x.strip().startswith("제3부") else x
        for x in body
    ]
    text = make(toc_block(), ["* 용어정리"], body)
    result = split_sections(text)
    check(result, text)
    assert [p.part_seq for p in result.parts] == [1, 2, 3]


def test_summary_ends_at_page_start_of_toc_after_summary() -> None:
    cover = ["\f투자설명서 표지", "[목 차]"]
    text = make(
        ["[요약정보]", "내용"], cover, toc_block(), ["* 용어정리"], body_block()
    )
    result = split_sections(text)
    check(result, text)
    summ = result.sections[1]
    assert summ.section_kind == "summary" and text[summ.char_end - 1] == "\f"
    assert result.sections[2].section_kind == "other"
    assert text[result.sections[2].char_start :].startswith("투자설명서 표지")


def test_side_tab_letters_in_toc_and_heading() -> None:
    # 목차 옆 세로 글자(CONTENTS)가 줄 앞에 붙은 형태
    toc = [
        "N" + " " * 8 + line if line.startswith("   ") else line for line in toc_block()
    ]
    toc[0] = "T      " + toc[0]
    text = make(toc, ["* 용어정리"], body_block())
    result = split_sections(text)
    check(result, text)
    assert result.toc_part_count == 3 and result.toc_section_count == 5
