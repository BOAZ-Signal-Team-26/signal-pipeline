"""canonical text 위의 구간(structure.json `blocks` 원소)과 책갈피 대조(순수 함수, I/O 없음).

블록 원소 공통 필드는 kind, char_start, char_end(PR #49 4-6).
- page_furniture_blocks: 쪽 머리글·쪽 번호 줄(PR #49 4-2 ④). 텍스트에서 지우지 않고 구간만 낸다
- table_blocks: 표 글자 범위 + 칸 안 문장 여부(PR #49 4-3)
- subheading_blocks: 본문 절 안의 하위 제목 「가.」(level 1)·「(1)」(level 2)(PR #49 4-2 ②)
- summary_label_blocks: 요약정보 구간 안 표의 첫 열 칸 항목 이름
- emphasis_blocks: 굵기·색 강조(PR #49 4-5)
- bookmark_check: 규칙으로 찾은 부·절을 PDF 책갈피와 대조(PR #49 4-2 「제목 찾는 방법」 2)
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections import Counter

from signal_pipeline.parsing.dart_sections import PART, Section, SplitResult, normalize
from signal_pipeline.parsing.pdf_layout import Emphasis, Label

FURNITURE_SHARE = 0.3  # 쪽의 30% 이상에서 반복되는 첫·끝 줄
FURNITURE_MIN_PAGES = 3  # 쪽 수가 적을 때 우연한 반복을 막는 바닥값(명세에 없는 보완)
PAGE_NUMBER = re.compile(r"^[-\s]*\d+(\s*/\s*\d+)?[-\s]*$")
SENTENCE_END = re.compile(r"다\.(?=\s|$)")
BOOK_SECTION = re.compile(r"^\s*(\d{1,2})\s*\.\s*(\S.*)$")
# 줄 시작의 하위 제목. 표·머리글 안 줄은 뺀다(표 칸의 번호 목록을 제목으로 잡지 않게)
SUBHEADINGS = (
    (1, re.compile(r"^\s*[가나다라마바사아자차카타파하]\.\s*\S")),
    (2, re.compile(r"^\s*\(\d{1,2}\)\s*\S")),
)


def _page_spans(text: str) -> list[tuple[int, int]]:
    """쪽별 [시작, 끝) 글자 범위. 쪽 사이 "\\f"는 어느 쪽에도 넣지 않는다."""
    spans, start = [], 0
    for page in text.split("\f"):
        spans.append((start, start + len(page)))
        start += len(page) + 1
    return spans


def _digit_mask(line: str) -> str:
    return re.sub(r"\d+", "#", line.strip())


def page_furniture_blocks(text: str) -> list[dict[str, object]]:
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
    return [
        {"kind": "page_furniture", "char_start": s, "char_end": e}
        for s, e in sorted(picked)
    ]


def table_blocks(text: str, ranges: list[tuple[int, int]]) -> list[dict[str, object]]:
    """표 글자 범위마다 칸 안에 「다.」로 끝나는 문장이 있는지(has_sentences)를 붙인다."""
    return [
        {
            "kind": "table",
            "char_start": s,
            "char_end": e,
            "has_sentences": SENTENCE_END.search(text[s:e]) is not None,
        }
        for s, e in sorted(ranges)
    ]


class _Ranges:
    """겹치지 않게 정렬한 구간 목록에서 위치가 어느 구간 안인지 찾는다."""

    def __init__(self, ranges: list[tuple[int, int]]) -> None:
        merged: list[tuple[int, int]] = []
        for start, end in sorted(ranges):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        self.ranges = merged
        self.starts = [s for s, _ in merged]

    def __contains__(self, pos: int) -> bool:
        index = bisect_right(self.starts, pos) - 1
        return index >= 0 and pos < self.ranges[index][1]


def _heads(text: str, sec: Section, skip: _Ranges) -> list[tuple[int, int, int]]:
    """절 제목 줄 다음부터 절 끝까지의 하위 제목 줄 (수준, 줄 시작, 줄 끝)."""
    assert sec.title_char_end is not None and sec.char_end is not None
    start = text.find("\n", sec.title_char_end, sec.char_end)
    if start < 0:
        return []
    heads, pos = [], start + 1
    for line in text[pos : sec.char_end].split("\n"):
        if pos not in skip:
            level = next((lv for lv, rule in SUBHEADINGS if rule.match(line)), None)
            if level:
                heads.append((level, pos, pos + len(line.rstrip())))
        pos += len(line) + 1
    return heads


def subheading_blocks(
    text: str, split: SplitResult | None, skip: list[tuple[int, int]]
) -> list[dict[str, object]]:
    """범위를 찾은 본문 절 안의 하위 제목. 범위는 제목 줄 시작부터 다음 같은 수준 이상 제목 직전까지
    (없으면 절 끝). `skip`(표·머리글) 안에서 시작하는 줄은 제목으로 보지 않는다."""
    excluded = _Ranges(skip)
    blocks = []
    for sec in split.sections if split else []:
        if sec.section_kind != "body" or sec.char_start is None:
            continue
        heads = _heads(text, sec, excluded)
        for index, (level, start, title_end) in enumerate(heads):
            end = next(
                (s for lv, s, _ in heads[index + 1 :] if lv <= level), sec.char_end
            )
            blocks.append(
                {
                    "kind": "subheading",
                    "char_start": start,
                    "char_end": end,
                    "title": text[start:title_end].strip(),
                    "level": level,
                    "section_seq": sec.section_seq,
                    "title_char_start": start,
                    "title_char_end": title_end,
                }
            )
    return blocks


def summary_label_blocks(
    cells: list[Label], split: SplitResult | None
) -> list[dict[str, object]]:
    """요약정보 구간(section_kind = summary) 안에서 시작하는 표 첫 열 칸."""
    inside = _Ranges(
        [
            (s.char_start, s.char_end)
            for s in (split.sections if split else [])
            if s.section_kind == "summary"
            and s.char_start is not None
            and s.char_end is not None
        ]
    )
    return [
        {"kind": "summary_label", "char_start": s, "char_end": e, "text": label}
        for s, e, label in cells
        if s in inside
    ]


def emphasis_blocks(runs: list[Emphasis]) -> list[dict[str, object]]:
    return [
        {
            "kind": "emphasis",
            "char_start": s,
            "char_end": e,
            "bold": method is not None,
            "bold_method": method,
            "color": color,
        }
        for s, e, method, color in runs
    ]


def bookmark_check(
    bookmarks: list[tuple[int, str]], split: SplitResult | None
) -> dict[str, int] | None:
    """책갈피의 부(「제N부」)·절(「N.」) 제목과 규칙으로 찾은 부·절을 대조한 개수.

    절은 (부 번호, 절 번호)로 맞춘다. 책갈피에서 절의 부 번호는 직전 「제N부」 책갈피를 따른다.
    책갈피가 없으면 None(「하나도 안 맞음」과 구분). 숫자가 아닌 절 번호는 대조하지 않는다.
    """
    if not bookmarks:
        return None
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
            if s.section_kind == "body"
            and s.char_start is not None
            and (s.source_section_no or "").isdecimal()
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
