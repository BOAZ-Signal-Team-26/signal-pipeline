"""PDF → canonical text + 표 영역 + 책갈피 (pdfplumber).

PR #49 4-3: 눈에 보이지 않는 그림 요소(흰색으로 채우고 외곽선 없는 사각형, 흰색 선)를 뺀 페이지에서
텍스트(layout)와 표(find_tables 기본 설정)를 같이 얻는다. 표를 찾은 도구와 텍스트를 만든 도구가 같아서
표의 페이지 영역(bbox)을 텍스트 글자 범위로 바꿀 수 있다.
순수 함수(is_white·is_invisible·trim_page·table_char_ranges)와 pdfplumber 호출(read_pdf)을 나눴다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber
from pdfplumber.utils.text import TextMap, WordExtractor

Bbox = tuple[float, float, float, float]  # (x0, top, x1, bottom)
CharTuple = tuple[
    str, dict | None
]  # pdfplumber TextMap.tuples 원소(글자, 원래 PDF 글자)

PAGE_BREAK = "\f"
WHITE_TOLERANCE = 1e-3
# 줄바꿈으로 오해될 글자는 공백으로 바꾼다(LF·쪽 구분 \f 이외의 줄 구분 글자 제거)
_REPLACED = {"\r": " ", "\f": " ", "\x00": " "}  # \x00: 일부 PDF가 공백을 NUL로 냄


class PdfTextError(Exception):
    """PDF 열기·텍스트화 실패."""


@dataclass(frozen=True)
class PdfLayout:
    text: str
    page_starts: list[int]  # 쪽별 시작 글자 위치(text 안)
    tables: list[tuple[int, int]]  # 표 영역 [start, end) 글자 범위
    bookmarks: list[tuple[int, str]] = field(default_factory=list)  # (단계, 제목)
    producer: str = ""  # PDF 메타데이터 Producer(생성 도구별 집계용)


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


def table_char_ranges(
    origins: list[dict | None], bboxes: list[Bbox]
) -> list[tuple[int, int]]:
    """표 bbox → 쪽 텍스트 안 글자 범위 [시작, 끝). 글자 중심이 bbox 안에 있는 첫 글자부터 끝 글자까지.

    표 안에 글자가 하나도 없으면 그 표는 뺀다.
    """
    ranges = []
    for bbox in bboxes:
        hits = [i for i, o in enumerate(origins) if o is not None and _inside(o, bbox)]
        if hits:
            ranges.append((hits[0], hits[-1] + 1))
    return sorted(ranges)


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


def read_pdf(path: Path) -> PdfLayout:
    """PDF 1건 → canonical text(쪽 사이는 \\f)·표 글자 범위·책갈피."""
    pages: list[str] = []
    page_starts: list[int] = []
    tables: list[tuple[int, int]] = []
    offset = 0
    try:
        with pdfplumber.open(path) as pdf:
            bookmarks = read_outlines(pdf)
            producer = str((pdf.metadata or {}).get("Producer") or "")
            for page in pdf.pages:
                visible = page.filter(lambda o: not is_invisible(o))
                text, origins = trim_page(layout_textmap(visible).tuples)
                bboxes = [t.bbox for t in visible.find_tables()]
                tables += [
                    (offset + s, offset + e)
                    for s, e in table_char_ranges(origins, bboxes)
                ]
                page_starts.append(offset)
                pages.append(text)
                offset += len(text) + len(PAGE_BREAK)
                page.flush_cache()
    except Exception as exc:
        raise PdfTextError(f"pdfplumber {type(exc).__name__}: {exc}"[:200]) from exc
    return PdfLayout(PAGE_BREAK.join(pages), page_starts, tables, bookmarks, producer)
