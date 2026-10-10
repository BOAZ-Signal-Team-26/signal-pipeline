"""canonical text 위에 표시하는 구간과 책갈피 대조(순수 함수, I/O 없음).

- page_furniture_regions: 쪽 머리글·쪽 번호 줄(PR #49 4-2 ④). 텍스트에서 지우지 않고 구간만 낸다
- table_regions: 표 글자 범위 + 칸 안 문장 여부(PR #49 4-3)
- bookmark_check: 규칙으로 찾은 부·절을 PDF 책갈피와 대조(PR #49 4-2 「제목 찾는 순서」 3)
"""

from __future__ import annotations

import re
from collections import Counter

from signal_pipeline.parsing.dart_sections import PART, SplitResult, normalize

FURNITURE_SHARE = 0.3  # 쪽의 30% 이상에서 반복되는 첫·끝 줄
FURNITURE_MIN_PAGES = 3  # 쪽 수가 적을 때 우연한 반복을 막는 바닥값(명세에 없는 보완)
PAGE_NUMBER = re.compile(r"^[-\s]*\d+(\s*/\s*\d+)?[-\s]*$")
SENTENCE_END = re.compile(r"다\.(?=\s|$)")
BOOK_SECTION = re.compile(r"^\s*(\d{1,2})\s*\.\s*(\S.*)$")


def _page_spans(text: str) -> list[tuple[int, int]]:
    """쪽별 [시작, 끝) 글자 범위. 쪽 사이 "\\f"는 어느 쪽에도 넣지 않는다."""
    spans, start = [], 0
    for page in text.split("\f"):
        spans.append((start, start + len(page)))
        start += len(page) + 1
    return spans


def _digit_mask(line: str) -> str:
    return re.sub(r"\d+", "#", line.strip())


def page_furniture_regions(text: str) -> list[dict[str, int]]:
    """쪽마다 첫·끝 줄(공백 제외) 중 숫자를 #로 바꿨을 때 쪽의 30% 이상에서 반복되는 줄과,
    쪽 번호만 있는 끝 줄의 글자 범위. 글자 위치 순."""
    edges: list[list[tuple[int, int, str]]] = []  # 쪽별 (줄 시작, 줄 끝, 줄 내용)
    for start, end in _page_spans(text):
        found, pos = [], start
        for line in text[start:end].split("\n"):
            if line.strip():
                found.append((pos, pos + len(line.rstrip()), line))
            pos += len(line) + 1
        edges.append(found[:1] + found[-1:] if len(found) > 1 else found)
    pages = len(edges)
    counts: Counter[str] = Counter()
    for page in edges:
        counts.update({_digit_mask(line) for _, _, line in page})
    need = max(FURNITURE_MIN_PAGES, FURNITURE_SHARE * pages)
    repeated = {key for key, n in counts.items() if key and n >= need}
    picked: set[tuple[int, int]] = set()
    for page in edges:
        for index, (start, end, line) in enumerate(page):
            is_last = index == len(page) - 1
            if _digit_mask(line) in repeated or (
                is_last and PAGE_NUMBER.match(line.strip())
            ):
                picked.add((start, end))
    return [{"char_start": s, "char_end": e} for s, e in sorted(picked)]


def table_regions(
    text: str, ranges: list[tuple[int, int]]
) -> list[dict[str, int | bool]]:
    """표 글자 범위마다 칸 안에 「다.」로 끝나는 문장이 있는지(has_sentences)를 붙인다."""
    return [
        {
            "char_start": s,
            "char_end": e,
            "has_sentences": SENTENCE_END.search(text[s:e]) is not None,
        }
        for s, e in sorted(ranges)
    ]


def bookmark_check(
    bookmarks: list[tuple[int, str]], split: SplitResult | None
) -> dict[str, int]:
    """책갈피의 부(「제N부」)·절(「N.」) 제목과 규칙으로 찾은 부·절을 대조한 개수.

    절은 (부 번호, 절 번호)로 맞춘다. 책갈피에서 절의 부 번호는 직전 「제N부」 책갈피를 따른다.
    """
    book_parts: set[int] = set()
    book_secs: set[tuple[int, int]] = set()
    current = 0
    for _, title in bookmarks:
        part = PART.match(title.strip())
        if part:
            current = int(part.group(1))
            book_parts.add(current)
            continue
        sec = BOOK_SECTION.match(title)
        if sec and current and normalize(sec.group(2)):
            book_secs.add((current, int(sec.group(1))))
    rule_parts = {p.part_seq for p in split.parts} if split else set()
    rule_secs = (
        {
            (s.part_seq, int(s.source_section_no))
            for s in split.sections
            if s.section_kind == "body" and s.char_start is not None
        }
        if split
        else set()
    )
    return {
        "bookmark_parts": len(book_parts),
        "bookmark_sections": len(book_secs),
        "rule_parts": len(rule_parts),
        "rule_sections": len(rule_secs),
        "matched_parts": len(book_parts & rule_parts),
        "matched_sections": len(book_secs & rule_secs),
    }
