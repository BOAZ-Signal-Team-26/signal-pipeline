"""제2부 13절 수수료·보수 표 한 개(pdfplumber `Table.extract()` 결과)를 정규화하는 순수 함수.

pdfplumber 원시 표의 문제와 처리:
- 머리글이 여러 행에 나뉨(「집합투」/「자업자」/「보수」) → 열마다 위에서 아래로 이어 붙이고 공백 제거
- 여러 열에 걸친 상위 머리글(「지급비율(연간, %)」) → 값 열을 2개 이상 덮으면 열 이름에서 뺀다
- 값 열 머리글이 옆의 빈 열에 찍힘 → 이름 없는 값 열은 바로 오른쪽(없으면 왼쪽) 머리글 전용 열 이름을 쓴다
- 모든 데이터 행이 빈 열 → 버린다
- 종류 이름이 두 행에 나뉨(「수수료선취-」/「오프라인(A)」) → 값 없는 행의 이름을 앞(또는 뒤) 행에 붙인다
- 방향: ROWS(종류가 행), TRANSPOSED(종류가 열, 행으로 바꿈), VERTICAL_SINGLE(보수 이름이 첫 열, 값 열 1개)
셀 값은 줄바꿈·NUL 문자만 지우고 그대로 둔다(숫자 정규화 안 함).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

ROWS, TRANSPOSED, VERTICAL_SINGLE = "ROWS", "TRANSPOSED", "VERTICAL_SINGLE"

# 머리글(또는 보수 이름) 판정: 이 중 2개 이상이면 수수료·보수 표
KEYWORDS = (
    "집합투자업자",
    "판매회사",
    "신탁업자",
    "사무관리",
    "총보수",
    "동종유형",
    "총보수·비용",
    "판매수수료",
    "선취",
    "후취",
    "환매수수료",
)
# 보수 이름만(종류 이름에도 나오는 선취·후취 제외). 종류 이름과 보수 이름 구별에 쓴다
FEE_NAMES = tuple(k for k in KEYWORDS if k not in ("선취", "후취"))
DOTS = str.maketrans({"ㆍ": "·", "ᆞ": "·", "∙": "·", "・": "·", "•": "·"})
NUM_RE = re.compile(r"\d+(\.\d+)?\s*%|\d*\.\d+")
EMPTY_VALUE_RE = re.compile(r"^(-|－|―|없음|해당없음|해당사항없음)$")
CLASS_RE = re.compile(
    r"(종류|클래스|class|수수료.{0,3}(징구|선취|후취)|투자신탁|투자회사|펀드|\([a-z][a-z0-9\-]*\)"
    r"|^[a-z](-?[a-z0-9]+)*형?$|[a-z]-?[a-z0-9]*형)",
    re.IGNORECASE,
)
SKIP_LABEL_RE = re.compile(r"^(지급시기|부과시기|구분|합계)")
NOTE_RE = re.compile(r"^(※|\*|주\d*\)|\(주\d*\))")

Cell = str | None
Grid = list[list[Cell]]


@dataclass(frozen=True)
class Entry:
    """정규화 중인 행. is_data = 값 셀(숫자·「-」 등)이 하나라도 있음."""

    label: str
    cells: tuple[str, ...]
    is_data: bool


@dataclass(frozen=True)
class PageTable:
    """한 쪽에서 읽은 표. ROWS는 쪽 연결 뒤 finish_rows로 행을 확정한다."""

    page: int
    top: float
    orientation: str
    columns: tuple[str, ...]
    entries: tuple[Entry, ...]
    headerless: bool = False  # 값 열 머리글이 없음 → 앞쪽 표의 이어짐 후보
    first_on_page: bool = False
    pages: tuple[int, ...] = field(default=())


def clean(cell: Cell) -> str:
    return (cell or "").replace("\n", "").replace("\x00", "")


def squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def is_value(cell: Cell) -> bool:
    text = squash(clean(cell))
    return bool(NUM_RE.search(text) or EMPTY_VALUE_RE.match(text))


def has_number(text: str) -> bool:
    return bool(NUM_RE.search(text))


def kw_count(
    texts: list[str] | tuple[str, ...], words: tuple[str, ...] = KEYWORDS
) -> int:
    joined = "".join(texts).translate(DOTS)
    return sum(word in joined for word in words)


def is_class_label(label: str) -> bool:
    return bool(
        CLASS_RE.search(label)
        and not kw_count([label], FEE_NAMES)
        and not SKIP_LABEL_RE.match(label)
    )


def _lead(row: list[Cell]) -> int:
    return next((j for j, c in enumerate(row) if squash(clean(c))), len(row))


def _first_value(row: list[Cell]) -> int | None:
    """행의 첫 값 셀 위치. 맨 앞 셀이 값이면 이름 없는 행이므로 그 셀부터 값으로 본다."""
    lead = _lead(row)
    start = lead if lead < len(row) and is_value(row[lead]) else lead + 1
    return next((j for j in range(start, len(row)) if is_value(row[j])), None)


def split_blocks(grid: Grid) -> list[Grid]:
    """값 행 뒤에 값 없이 셀 3개 이상이 찬 행(새 머리글)이 오면 거기서 블록을 나눈다."""
    blocks: list[Grid] = []
    current: Grid = []
    prev_data = False
    for row in grid:
        data = _first_value(row) is not None
        filled = sum(bool(squash(clean(c))) for c in row)
        if current and prev_data and not data and filled >= 3:
            blocks.append(current)
            current = []
        current.append(row)
        prev_data = data
    return [*blocks, current] if current else blocks


def _spans_values(head: Grid, r: int, j: int, value_cols: set[int]) -> bool:
    """(r, j)가 그 범위의 첫 글자 칸이고, 오른쪽 None 셀까지 합쳐 값 열 2개 이상을 덮고, 그 아래 행에
    같은 범위 안 하위 머리글이 2개 이상 있는 상위 머리글인가. pdfplumber는 행에 없는 칸도
    None으로 채우므로 None만으로는 병합 셀인지 알 수 없어 범위 안 가장 위 칸으로 한정한다."""
    k = j
    while k + 1 < len(head[r]) and head[r][k + 1] is None:
        k += 1
    span = range(j, k + 1)
    if any(clean(row[c]).strip() for row in head[:r] for c in span):
        return False
    if len(value_cols & set(span)) < 2:
        return False
    return any(
        sum(bool(clean(row[c]).strip()) for c in span) >= 2 for row in head[r + 1 :]
    )


def _header_names(head: Grid, width: int, value_cols: set[int]) -> list[str]:
    names = []
    for j in range(width):
        parts = [
            clean(row[j])
            for r, row in enumerate(head)
            if clean(row[j]) and not _spans_values(head, r, j, value_cols)
        ]
        names.append(squash("".join(parts)))
    return names


def _align_names(names: list[str], value_cols: list[int], first: int) -> list[str]:
    """이름 없는 값 열은 바로 옆(오른쪽 먼저)의 머리글 전용 열 이름을 쓴다."""
    out, used = list(names), set()
    for j in value_cols:
        if out[j]:
            continue
        for n in (j + 1, j - 1):
            if (
                first <= n < len(names)
                and n not in value_cols
                and names[n]
                and n not in used
            ):
                out[j] = names[n]
                used.add(n)
                break
    return out


def _pad(grid: Grid) -> Grid:
    width = max(len(r) for r in grid)
    return [list(r) + [None] * (width - len(r)) for r in grid]


def parse_block(block: Grid) -> tuple[list[str], list[Entry], int] | None:
    """블록 → (값 열 이름들, 행들, 머리글 행 수). 값 행이 없으면 None."""
    grid = _pad(block)
    firsts = [(i, f) for i, r in enumerate(grid) if (f := _first_value(r)) is not None]
    if not firsts:
        return None
    h, first = firsts[0][0], min(f for _, f in firsts)
    data = grid[h:]
    value_cols = [
        j for j in range(first, len(grid[0])) if any(clean(r[j]).strip() for r in data)
    ]
    names = _align_names(
        _header_names(grid[:h], len(grid[0]), set(value_cols)), value_cols, first
    )

    def entry(row: list[Cell], is_data: bool) -> Entry:
        label = squash("".join(clean(c) for c in row[:first]))
        return Entry(label, tuple(clean(row[j]) for j in value_cols), is_data)

    head_labels = [entry(r, False) for r in grid[:h]]
    rows = [entry(r, _first_value(r) is not None) for r in data]
    columns = [names[j] for j in value_cols]
    if not any(columns):  # 머리글 없는 표: 앞 행들은 이어지는 종류 이름 조각
        return columns, [e for e in head_labels if e.label] + rows, 0
    return columns, rows, h


def _incomplete(label: str) -> bool:
    return label.endswith(("-", "·", ",", "(")) or label.count("(") > label.count(")")


def _join_cells(a: tuple[str, ...], b: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(x + y for x, y in zip(a, b, strict=False))


def merge_labels(entries: list[Entry] | tuple[Entry, ...]) -> list[Entry]:
    """값 없는 행(종류 이름 조각)을 앞 행에 붙인다. 앞 행 이름이 완결되고 조각이
    「-」 등으로 끝나면 뒤 행 앞에 붙인다. 각주(※, 주1) 등) 조각은 버린다."""
    out: list[Entry] = []
    pending = ""
    for e in entries:
        if e.is_data:
            out.append(replace(e, label=pending + e.label))
            pending = ""
        elif not e.label or NOTE_RE.match(e.label):
            continue
        elif out and (_incomplete(out[-1].label) or not _incomplete(e.label)):
            last = out[-1]
            out[-1] = replace(
                last, label=last.label + e.label, cells=_join_cells(last.cells, e.cells)
            )
        else:
            pending += e.label
    return out


def finish_rows(entries: tuple[Entry, ...], default_label: str) -> list[dict]:
    """종류 이름 조각을 합치고 지급시기·구분 같은 비종류 행을 뺀 최종 행."""
    rows = [e for e in merge_labels(entries) if not SKIP_LABEL_RE.match(e.label)]
    if len(rows) == 1 and not rows[0].label:
        rows = [replace(rows[0], label=default_label)]
    return [{"label": e.label, "cells": list(e.cells)} for e in rows]


def _flip(
    columns: list[str], entries: list[Entry], default_label: str
) -> tuple[str, list, list]:
    """보수 이름이 행에 있는 표 → (방향, 보수 이름 열, 종류 행)."""
    fees = merge_labels(entries)
    keep = [k for k, name in enumerate(columns) if "시기" not in name]
    fee_names = tuple(e.label for e in fees)
    if len(keep) == 1:
        name = columns[keep[0]]
        label = name if is_class_label(name) else default_label
        return (
            VERTICAL_SINGLE,
            list(fee_names),
            [Entry(label, tuple(e.cells[keep[0]] for e in fees), True)],
        )
    rows = [Entry(columns[k], tuple(e.cells[k] for e in fees), True) for k in keep]
    return TRANSPOSED, list(fee_names), rows


def classify_block(
    block: Grid, default_label: str
) -> tuple[str, list[str], list[Entry], bool] | None:
    """블록 → (방향, 열, 행, 머리글 없음). 수수료·보수 표도 이어짐 후보도 아니면 None."""
    parsed = parse_block(block)
    if parsed is None:
        return None
    columns, entries, _ = parsed
    labels = [e.label for e in entries]
    row_fees, col_fees = kw_count(labels, FEE_NAMES), kw_count(columns, FEE_NAMES)
    if row_fees >= 2 and row_fees > col_fees and any(columns):
        orientation, fee_names, rows = _flip(columns, entries, default_label)
        return orientation, fee_names, rows, False
    if kw_count(columns) >= 2:
        return ROWS, columns, entries, False
    if not any(columns) and any(e.is_data for e in entries):
        return ROWS, columns, entries, True
    return None


def normalize_table(
    raw: Grid, page: int, top: float, default_label: str = ""
) -> list[PageTable]:
    """원시 표 하나 → 수수료·보수 표(또는 이어짐 후보) 목록. 같은 표 안 TRANSPOSED 블록은
    보수 이름이 같으면 한 표로 합치고, ROWS 블록(기간별 표)은 따로 둔다."""
    out: list[PageTable] = []
    for block in split_blocks([r for r in raw if r]):
        got = classify_block(block, default_label)
        if got is None:
            continue
        orientation, columns, entries, headerless = got
        prev = out[-1] if out else None
        if (
            prev
            and orientation == TRANSPOSED == prev.orientation
            and tuple(columns) == prev.columns
        ):
            out[-1] = replace(prev, entries=prev.entries + tuple(entries))
            continue
        out.append(
            PageTable(
                page, top, orientation, tuple(columns), tuple(entries), headerless
            )
        )
    return out
