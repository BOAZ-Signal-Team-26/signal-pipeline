"""PDF → canonical text + 표 영역 + 책갈피 (pdfplumber).

PR #49 4-3: 눈에 보이지 않는 그림 요소(흰색으로 채우고 외곽선 없는 사각형, 흰색 선)를 뺀 페이지에서
텍스트(layout)와 표(find_tables 기본 설정)를 같이 얻는다. 표를 찾은 도구와 텍스트를 만든 도구가 같아서
표의 페이지 영역(bbox)을 텍스트 글자 범위로 바꿀 수 있다.
표 찾기만 실패하면 파일 전체를 실패로 두지 않고 표 분리 상태를 FAILED로 낸다(PR #49 4-6).
강조(PR #49 4-5): 굵은 글꼴, 외곽선 덧그리기(PDF 글자 그리기 방식 Tr 1·2·5·6), 유채색 글자.
순수 함수(is_white·is_invisible·trim_page·table_char_ranges·cell_label·emphasis_runs)와
pdfplumber 호출(read_pdf)을 나눴다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

import pdfplumber
from pdfplumber.page import PDFPageAggregatorWithMarkedContent
from pdfplumber.utils.text import TextMap, WordExtractor

Bbox = tuple[float, float, float, float]  # (x0, top, x1, bottom)
CharTuple = tuple[
    str, dict | None
]  # pdfplumber TextMap.tuples 원소(글자, 원래 PDF 글자)

PAGE_BREAK = "\f"
WHITE_TOLERANCE = 1e-3
BOLD_FONT = re.compile(r"bold|black|heavy", re.IGNORECASE)
STROKE_RENDER_MODES = {1, 2, 5, 6}  # 글자 외곽선을 그리는 방식(채움+외곽선 포함)
# 이보다 채도가 낮으면 무채색으로 보고 색을 null로 둔다. MS Word 문서 본문이 짙은 회색(0.23, 0.22, 0.22)이라
# 「검정만 null」로 하면 본문 전체가 강조가 된다
CHROMA_MIN = 0.15
# 줄바꿈으로 오해될 글자는 공백으로 바꾼다(LF·쪽 구분 \f 이외의 줄 구분 글자 제거)
_REPLACED = {"\r": " ", "\f": " ", "\x00": " "}  # \x00: 일부 PDF가 공백을 NUL로 냄


Emphasis = tuple[int, int, str | None, str | None]  # (시작, 끝, 굵기 방식, 색)
Label = tuple[int, int, str]  # (시작, 끝, 칸 글자)


class PdfTextError(Exception):
    """PDF 열기·텍스트화 실패."""


@dataclass(frozen=True)
class PdfLayout:
    text: str
    page_starts: list[int]  # 쪽별 시작 글자 위치(text 안)
    tables: list[tuple[int, int]]  # 표 영역 [start, end) 글자 범위
    bookmarks: list[tuple[int, str]] = field(default_factory=list)  # (단계, 제목)
    producer: str = ""  # PDF 메타데이터 Producer(생성 도구별 집계용)
    first_column_cells: list[Label] = field(default_factory=list)  # 표 첫 열 칸
    emphasis: list[Emphasis] = field(default_factory=list)
    table_split_status: str = "OK"  # OK / FAILED
    table_split_error: str | None = None


def _track_render_mode() -> None:
    """pdfplumber 글자에 외곽선 덧그리기 여부(`stroke`)를 붙인다.

    pdfminer는 글자의 그리기 방식(Tr)을 글자 객체에 남기지 않는다. 그래서 글자열을 그릴 때 방식을
    기억해 두고 글자를 만들 때 붙인다. `stroke`는 pdfplumber가 글자 dict로 옮기는 속성 이름이다.
    """
    cls = PDFPageAggregatorWithMarkedContent
    if getattr(cls, "_tracks_render_mode", False):
        return
    render_string, render_char = cls.render_string, cls.render_char

    def string(self, textstate, *args, **kwargs):  # type: ignore[no-untyped-def]
        self._render_mode = textstate.render
        return render_string(self, textstate, *args, **kwargs)

    def char(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        adv = render_char(self, *args, **kwargs)
        if self.cur_item._objs:
            mode = getattr(self, "_render_mode", 0)
            self.cur_item._objs[-1].stroke = mode in STROKE_RENDER_MODES
        return adv

    cls.render_string, cls.render_char = string, char
    cls._tracks_render_mode = True


_track_render_mode()


def is_white(color: object) -> bool:
    """흰색이면 True. 숫자가 아닌 색(패턴 이름 등)·색 없음은 보이는 것으로 본다."""
    if isinstance(color, (int, float)):
        color = (color,)
    if not isinstance(color, (tuple, list)) or not color:
        return False
    if not all(isinstance(v, (int, float)) for v in color):
        return False
    if len(color) in (1, 3):  # 회색조·RGB: 1이 흰색
        return all(abs(v - 1) < WHITE_TOLERANCE for v in color)
    if len(color) == 4:  # CMYK: 0이 흰색
        return all(abs(v) < WHITE_TOLERANCE for v in color)
    return False


def is_invisible(obj: dict) -> bool:
    """흰색으로 채우고 외곽선 없는 사각형, 흰색 선."""
    kind = obj.get("object_type")
    if kind == "rect":
        return (
            bool(obj.get("fill"))
            and not obj.get("stroke")
            and is_white(obj.get("non_stroking_color"))
        )
    if kind == "line":
        return is_white(obj.get("stroking_color"))
    return False


def layout_textmap(page) -> TextMap:
    """쪽의 layout 텍스트맵. 글자를 위에서 아래로 다시 정렬한다.

    `page.get_textmap(layout=True)`는 글자가 PDF 내용 순서대로 이미 줄 순서라고 가정한다(presorted).
    쪽 머리글을 본문보다 나중에 그린 PDF에서는 머리글(「제3부 …」)이 쪽 끝으로 밀려
    제목 줄을 못 찾는다(10월 10일 502건 실측 41건). 그래서 정렬을 켠 상태로 직접 만든다.
    """
    words = WordExtractor().extract_wordmap(page.chars)
    return words.to_textmap(
        layout=True,
        layout_width=page.width,
        layout_height=page.height,
        layout_bbox=page.bbox,
    )


def trim_page(tuples: list[CharTuple]) -> tuple[str, list[dict | None]]:
    """layout 글자 목록 → (쪽 텍스트, 글자별 원래 PDF 글자). 줄 끝 공백과 쪽 앞뒤 빈 줄을 떼고 줄바꿈으로 끝낸다."""
    lines: list[list[CharTuple]] = [[]]
    for char, origin in tuples:
        if char == "\n":
            lines.append([])
        else:
            lines[-1].append((_REPLACED.get(char, char), origin))
    for line in lines:
        while line and line[-1][0].isspace():
            line.pop()
    while lines and not lines[-1]:
        lines.pop()
    first = next((i for i, line in enumerate(lines) if line), len(lines))
    lines = lines[first:]
    text: list[str] = []
    origins: list[dict | None] = []
    for index, line in enumerate(lines):
        if index:
            text.append("\n")
            origins.append(None)
        for char, origin in line:
            text.append(char)
            origins.append(origin)
    if text:  # pdftotext처럼 쪽의 마지막 줄도 줄바꿈으로 끝낸 뒤 \f가 이어지게 한다
        text.append("\n")
        origins.append(None)
    return "".join(text), origins


def _inside(origin: dict, bbox: Bbox) -> bool:
    x = (origin["x0"] + origin["x1"]) / 2
    y = (origin["top"] + origin["bottom"]) / 2
    return bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3]


def _hits(origins: list[dict | None], bbox: Bbox) -> list[int]:
    return [i for i, o in enumerate(origins) if o is not None and _inside(o, bbox)]


def table_char_ranges(
    origins: list[dict | None], bboxes: list[Bbox]
) -> list[tuple[int, int]]:
    """표 bbox → 쪽 텍스트 안 글자 범위 [시작, 끝). 글자 중심이 bbox 안에 있는 첫 글자부터 끝 글자까지.

    표 안에 글자가 하나도 없으면 그 표는 뺀다.
    """
    ranges = []
    for bbox in bboxes:
        hits = _hits(origins, bbox)
        if hits:
            ranges.append((hits[0], hits[-1] + 1))
    return sorted(ranges)


def cell_label(text: str, origins: list[dict | None], bbox: Bbox) -> Label | None:
    """칸 bbox → (시작, 끝, 칸 글자). 여러 줄이면 줄마다 칸 안 글자 구간을 공백 하나로 잇는다.

    범위는 칸의 첫 글자부터 끝 글자까지라 여러 줄 칸이면 옆 칸 글자가 범위 안에 들어간다.
    """
    hits = _hits(origins, bbox)
    if not hits:
        return None
    pieces, start = [], hits[0]
    for prev, cur in pairwise(hits):
        if "\n" in text[prev:cur]:
            pieces.append(text[start : prev + 1])
            start = cur
    pieces.append(text[start : hits[-1] + 1])
    label = " ".join(" ".join(pieces).split())
    return (hits[0], hits[-1] + 1, label) if label else None


def hex_color(color: object) -> str | None:
    """유채색이면 #RRGGBB. 무채색(검정·회색·흰색)·읽을 수 없는 색은 None."""
    if isinstance(color, (int, float)):
        color = (color,)
    if not isinstance(color, (tuple, list)) or not color:
        return None
    if not all(isinstance(v, (int, float)) for v in color):
        return None
    if len(color) == 3:
        rgb = tuple(color)
    elif len(color) == 4:  # CMYK → RGB
        c, m, y, k = color
        rgb = ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    else:  # 회색조
        return None
    if max(rgb) - min(rgb) < CHROMA_MIN:
        return None
    return "#" + "".join(f"{round(min(max(v, 0), 1) * 255):02X}" for v in rgb)


def char_style(origin: dict) -> tuple[str | None, str | None] | None:
    """(굵기 방식, 색). 굵은 글꼴이면 font, 외곽선 덧그리기면 stroke. 강조가 없으면 None."""
    if BOLD_FONT.search(str(origin.get("fontname", ""))):
        method: str | None = "font"
    elif origin.get("stroke") is True:
        method = "stroke"
    else:
        method = None
    color = hex_color(origin.get("non_stroking_color"))
    return (method, color) if method or color else None


def emphasis_runs(text: str, origins: list[dict | None]) -> list[Emphasis]:
    """같은 강조가 이어지는 글자 구간. 공백은 앞뒤가 같은 강조면 구간에 포함하고, 줄바꿈에서 끊는다."""
    runs: list[Emphasis] = []
    current: tuple[int, int, tuple[str | None, str | None]] | None = None
    for index, (char, origin) in enumerate(zip(text, origins)):
        if char == "\n":
            current = None
            continue
        if char.isspace():
            continue
        style = char_style(origin) if origin is not None else None
        if style is None:
            current = None
        elif current and current[2] == style:
            current = (current[0], index + 1, style)
            runs[-1] = (current[0], current[1], *style)
        else:
            current = (index, index + 1, style)
            runs.append((index, index + 1, *style))
    return runs


def read_outlines(pdf: pdfplumber.PDF) -> list[tuple[int, str]]:
    """PDF 책갈피 (단계, 제목) 목록. 없거나 읽지 못하면 빈 목록."""
    try:
        return [
            (int(level), str(title).strip())
            for level, title, *_ in pdf.doc.get_outlines()
            if title
        ]
    except Exception:  # noqa: BLE001 — 책갈피 없음(PDFNoOutlines)·깨진 책갈피는 모두 「없음」
        return []


def _page_tables(
    page, text: str, origins: list[dict | None]
) -> tuple[list[tuple[int, int]], list[Label]]:
    """쪽의 표 글자 범위와 표 첫 열 칸. find_tables 오류는 호출한 쪽에서 표 분리 실패로 처리한다."""
    found = page.find_tables()
    ranges = table_char_ranges(origins, [t.bbox for t in found])
    cells = [
        cell_label(text, origins, row.cells[0])
        for t in found
        for row in t.rows
        if row.cells and row.cells[0] is not None
    ]
    return ranges, [c for c in cells if c is not None]


def read_pdf(path: Path) -> PdfLayout:
    """PDF 1건 → canonical text(쪽 사이는 \\f)·표 글자 범위·표 첫 열 칸·강조·책갈피.

    표 찾기에서 오류가 나면 텍스트는 그대로 내고 표 분리 상태만 FAILED(표·칸 없음)로 둔다.
    """
    pages: list[str] = []
    page_starts: list[int] = []
    tables: list[tuple[int, int]] = []
    cells: list[Label] = []
    emphasis: list[Emphasis] = []
    table_error: str | None = None
    offset = 0
    try:
        with pdfplumber.open(path) as pdf:
            bookmarks = read_outlines(pdf)
            producer = str((pdf.metadata or {}).get("Producer") or "")
            for number, page in enumerate(pdf.pages, 1):
                visible = page.filter(lambda o: not is_invisible(o))
                text, origins = trim_page(layout_textmap(visible).tuples)
                if table_error is None:
                    try:
                        ranges, labels = _page_tables(visible, text, origins)
                    except Exception as exc:  # noqa: BLE001 — 표만 실패. 사유는 기록에 남김
                        table_error = f"{number}쪽 {type(exc).__name__}: {exc}"[:200]
                    else:
                        tables += [(offset + s, offset + e) for s, e in ranges]
                        cells += [(offset + s, offset + e, t) for s, e, t in labels]
                emphasis += [
                    (offset + s, offset + e, m, c)
                    for s, e, m, c in emphasis_runs(text, origins)
                ]
                page_starts.append(offset)
                pages.append(text)
                offset += len(text) + len(PAGE_BREAK)
                page.flush_cache()
    except Exception as exc:
        raise PdfTextError(f"pdfplumber {type(exc).__name__}: {exc}"[:200]) from exc
    if table_error:
        tables, cells = [], []
    return PdfLayout(
        PAGE_BREAK.join(pages),
        page_starts,
        tables,
        bookmarks,
        producer,
        first_column_cells=cells,
        emphasis=emphasis,
        table_split_status="FAILED" if table_error else "OK",
        table_split_error=table_error,
    )
