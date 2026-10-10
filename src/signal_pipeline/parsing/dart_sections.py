"""DART 투자설명서 본문 텍스트를 부·절 단위로 나눈다(순수 함수, I/O 없음).

알고리즘은 research/scripts/dart_sections.py에서 옮겼다(근거: docs/records/phase1-erd/dart-section-split.md).
- 「제N부」 표제 행의 첫 오름차순 묶음(셋 이상)이 목차다. 그 뒤에서 번호가 커지는 표제만 골라 본문 부로 본다.
  그 뒤에 표제가 없으면 목차 없는 문서로 보고, 1~2개뿐이면 구조를 만들지 않는다
- 목차에서 부별 절 목록을 읽고, 본문에서 정규화한 제목 앞부분이 일치하는 줄을 절 시작으로 본다
- 결과는 줄 번호가 아니라 글자 위치(text 안의 반열린 구간 [start, end))로 낸다
- 부·절 체계 밖 앞부분은 요약정보(`summary`)와 표지·목차·유의사항(`other`) 구간으로 함께 낸다(PR #49 4-2 ⑤)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

# 「제N부」로 시작하고 그 줄에 표제만 있는 행. 들여쓰기는 조건에 넣지 않는다.
# 숫자 앞뒤 공백(「제 3 부」)과 표제가 다음 줄에 있는 경우(「제1부」만 있는 줄)도 받는다.
# 10월 10일 20건 실측에서 이 두 형태 때문에 5건 중 4건이 「제N부 미검출」로 실패했다.
PART = re.compile(r"^제\s*([1-5])\s*부\.?(?:\s+(\S.*))?$")
# 목차 줄 끝의 점선과 쪽 번호(「제1부 모집 … ........ 13」). 떼지 않으면 MAX_HEAD를 넘어 걸러진다.
LEADER = re.compile(r"\s*[.·ㆍ…]{4,}\s*\d*\s*$")
# 목차 옆에 세로로 쓴 「CONTENTS」 글자(줄 앞 대문자 한 글자)가 layout 텍스트에서 줄 앞에 붙을 수 있다(10월 10일 502건 중 7건)
SIDE_TAB = re.compile(r"^[A-Z]\s+(?=제)")
TOC_SEC = re.compile(r"^\s*(?:[A-Z]\s+)?(\d{1,2})\.\s*(.+?)\s*$")
MAX_HEAD = 60
# 요약정보 시작: 줄 시작의 「[요약정보]」·「<요약정보>」(10월 10일 501건 실측 483건).
# 없으면 줄에 「요약정보」만 있는 표제(예: 「요약 정보」)를 쓴다. 모두 첫 「제N부」 앞에서만 찾는다
SUMMARY_MARK = re.compile(r"^\s*[\[<]\s*요\s*약\s*정\s*보\s*[\]>]")
SUMMARY_BARE = re.compile(r"^\s*요\s*약\s*정\s*보\s*$")

FOUND = "EXTRACT_OK"
NOT_FOUND = "SECTION_BOUNDARY_NOT_FOUND"

Mark = tuple[int, int, str]  # (줄 번호, 부 번호, 표제)


class SectionSplitError(Exception):
    """「제N부」 표제를 찾지 못해 부·절 구조를 만들 수 없다."""


@dataclass(frozen=True)
class Part:
    part_seq: int
    title: str
    char_start: int
    char_end: int


@dataclass(frozen=True)
class Section:
    """section_kind가 summary·other이면 part_seq·source_section_no는 None."""

    section_seq: int
    section_kind: str  # body / summary / other
    part_seq: int | None
    source_section_no: str | None
    title: str | None  # 본문 줄의 제목. 못 찾은 절은 목차의 제목, other는 None
    title_char_start: int | None
    title_char_end: int | None
    char_start: int | None
    char_end: int | None
    extract_status: str


@dataclass(frozen=True)
class SplitResult:
    parts: list[Part]
    sections: list[Section]
    toc_section_count: int
    toc_part_count: int  # 목차 묶음에서 읽은 부 수. 목차가 없으면 0


def part_marks(lines: list[str]) -> list[Mark]:
    """「제N부」 표제 행 목록."""
    marks: list[Mark] = []
    for index, line in enumerate(lines):
        stripped = SIDE_TAB.sub("", LEADER.sub("", line.strip()))
        match = PART.match(stripped)
        # layout 텍스트는 글자 간격을 공백으로 늘려 표제 줄이 길어지므로 연속 공백은 하나로 보고 잰다
        if match and len(re.sub(r"\s+", " ", stripped)) < MAX_HEAD:
            marks.append((index, int(match.group(1)), stripped))
    return marks


def part_runs(marks: list[Mark]) -> list[list[Mark]]:
    """「제N부」 표제 행을 오름차순 묶음으로 나눈다.

    들여쓰기로 목차와 본문을 가를 수 없다(문서마다 제각각). 대신 순서는 일정하다:
    제1~5부가 오름차순으로 한 번 나오면 목차, 다시 한 번 나오면 본문이다.
    """
    runs: list[list[Mark]] = []
    for mark in marks:
        if runs and mark[1] > runs[-1][-1][1]:
            runs[-1].append(mark)
        else:
            runs.append([mark])
    return runs


def ascending(marks: list[Mark]) -> list[Mark]:
    """앞에서 고른 부보다 번호가 큰 표제만 차례로 고른다.

    본문에는 쪽 머리글로 반복되는 「제 1 부」, 「제 2 부 [별첨1]」 같은 표제가 섞여
    오름차순 묶음이 끊긴다(10월 10일 502건 실측). 반복·되돌아간 표제는 건너뛴다.
    """
    picked: list[Mark] = []
    for mark in marks:
        if not picked or mark[1] > picked[-1][1]:
            picked.append(mark)
    return picked


def toc(
    lines: list[str], run: list[Mark], stop: int
) -> dict[int, list[tuple[int, str]]]:
    """목차 묶음에서 부별 절 목록을 읽는다.

    `*` 로 시작하는 줄에서 멈춘다(목차 끝 「* 용어정리」 뒤 간이투자설명서의 번호 항목 제외).
    절 번호가 부 안에서 되돌아가면 목차가 끝난 것이다(제5부 뒤 번호 목록 제외).
    """
    found: dict[int, list[tuple[int, str]]] = {}
    edges = [m[0] for m in run] + [stop]
    for index, (_, part, _) in enumerate(run):
        found[part] = []
        for line in lines[edges[index] + 1 : edges[index + 1]]:
            if line.strip().startswith("*"):
                break
            # 목차 절 줄 끝의 점선·쪽 번호를 떼야 제목 앞부분 대조에 쪽 번호가 섞이지 않는다
            section = TOC_SEC.match(LEADER.sub("", line))
            if not section:
                continue
            number = int(section.group(1))
            if found[part] and number <= found[part][-1][0]:
                break
            found[part].append((number, section.group(2).strip()))
    return found


def normalize(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", text)


def _find_start(
    body: list[tuple[int, str]], number: int, name: str, after: int
) -> int | None:
    """본문 줄(줄 번호, 정규화 텍스트) 중 `after` 뒤의 절 시작 줄 번호. 못 찾으면 None.

    앞 절보다 뒤에서만 찾는다. 뒤 절 제목이 앞쪽 본문 줄에 맞으면 구간이 거꾸로 잡힌다
    (10월 10일 502건 실측 12건).
    """
    body = [(i, text) for i, text in body if i > after]
    key = normalize(name)
    head = normalize(f"{number}.") + key[:12]
    spot = next((i for i, text in body if text.startswith(head)), None)
    if spot is None:
        spot = next(
            (
                i
                for i, text in body
                if key[:14] and key[:14] in text and len(text) < len(key) + 30
            ),
            None,
        )
    return spot


def _next_is_part(lines: list[str], index: int) -> bool:
    """다음 비어 있지 않은 줄이 「제N부」 표제면 True. 목차 속 「<요약정보>」 항목을 거르는 데 쓴다."""
    for line in lines[index + 1 :]:
        if line.strip():
            return PART.match(LEADER.sub("", line.strip())) is not None
    return False


def find_summary(lines: list[str], limit: int) -> int | None:
    """요약정보 시작 줄 번호(0부터, `limit` 앞에서만). 없으면 None."""
    for pattern in (SUMMARY_MARK, SUMMARY_BARE):
        for index in range(min(limit, len(lines))):
            if pattern.match(lines[index]) and not _next_is_part(lines, index):
                return index
    return None


def _line_section(
    kind: str, lines: list[str], offsets: list[int], index: int, end: int
) -> Section:
    title_end = offsets[index] + len(lines[index].rstrip())
    return Section(
        0, kind, None, None, lines[index].strip(), offsets[index], title_end,
        offsets[index], end, FOUND,
    )  # fmt: skip


def _other(start: int, end: int) -> list[Section]:
    if end <= start:
        return []
    return [Section(0, "other", None, None, None, None, None, start, end, FOUND)]


def split_sections(text: str) -> SplitResult:
    """텍스트 → 부·절 구조. 「제N부」가 없으면 SectionSplitError."""
    lines = text.split("\n")
    # 줄 시작 글자 위치. "\n".join(lines) == text 이므로 줄마다 길이 + 1
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line) + 1)

    marks = part_marks(lines)
    runs = [r for r in part_runs(marks) if len(r) >= 3]
    if not runs:
        raise SectionSplitError("「제N부」 표제를 찾지 못했다")
    # 첫 묶음 = 목차. 그 뒤에서 부를 셋 이상 고르면 본문, 아니면 목차 없는 문서
    first = runs[0]
    body_run = ascending([m for m in marks if m[0] > first[-1][0]])
    if len(body_run) >= 3:
        contents = toc(lines, first, body_run[0][0])
        toc_part_count = len(first)
    elif body_run:
        # 목차 뒤 본문 표제가 1~2개면 목차를 부로 쓸 수도, 본문만으로 나눌 수도 없다
        # (10월 10일 502건 실측 0건)
        raise SectionSplitError(
            f"목차 뒤 본문 「제N부」 표제가 {len(body_run)}개뿐이다"
        )
    else:
        contents: dict[int, list[tuple[int, str]]] = {}
        body_run = ascending([m for m in marks if m[0] >= first[0][0]])
        toc_part_count = 0

    parts: list[Part] = []
    body: list[Section] = []
    bounds = [m[0] for m in body_run] + [len(lines)]
    for index, (start, part, title) in enumerate(body_run):
        end = bounds[index + 1]
        part_start = offsets[start]
        part_end = offsets[end] if end < len(lines) else len(text)
        parts.append(Part(part, title, part_start, part_end))

        lined = [(i, normalize(lines[i])) for i in range(start + 1, end)]
        spots: list[tuple[int, str, int | None]] = []
        last = start
        for number, name in contents.get(part, []):
            spot = _find_start(lined, number, name, last)
            spots.append((number, name, spot))
            last = spot if spot is not None else last
        # 찾은 절의 끝 = 다음으로 찾은 절의 시작, 마지막이면 부의 끝
        starts = [offsets[s] for _, _, s in spots if s is not None]
        ends = iter(starts[1:] + [part_end])
        for number, name, spot in spots:
            found = spot is not None
            body.append(
                Section(
                    section_seq=0,
                    section_kind="body",
                    part_seq=part,
                    source_section_no=str(number),
                    title=lines[spot].strip() if found else name,
                    title_char_start=offsets[spot] if found else None,
                    title_char_end=(
                        offsets[spot] + len(lines[spot].rstrip()) if found else None
                    ),
                    char_start=offsets[spot] if found else None,
                    char_end=next(ends) if found else None,
                    extract_status=FOUND if found else NOT_FOUND,
                )
            )
    front = _front_sections(text, lines, offsets, body_run[0][0], first[0][0])
    sections = [
        replace(sec, section_seq=seq) for seq, sec in enumerate(front + body, 1)
    ]
    return SplitResult(
        parts, sections, sum(len(v) for v in contents.values()), toc_part_count
    )


def _front_sections(
    text: str,
    lines: list[str],
    offsets: list[int],
    body_line: int,
    toc_line: int,
) -> list[Section]:
    """첫 본문 부 앞의 요약정보(summary)·그 밖(other) 구간. 글자 위치 순.

    끝 경계(10월 10일 502건 텍스트를 열어 확인):
    - 요약정보 뒤에 목차가 없으면 첫 본문 부 직전까지. 요약정보 뒤에는 「[집합투자기구 공시 정보 안내]」
      상자뿐이고 곧바로 「제1부」 본문이 이어진다
    - 요약정보(간이투자설명서 부분) 뒤에 정식 투자설명서의 표지·목차가 오는 문서(109건)는
      목차가 있는 쪽의 시작(쪽 구분 \\f)까지가 요약정보이고, 그 뒤 본문 부 앞까지는 other
    """
    body_start = offsets[body_line] if body_line < len(lines) else len(text)
    spot = find_summary(lines, body_line)
    if spot is None:
        return _other(0, body_start)
    summary_end = body_start
    if spot < toc_line < body_line:
        page_start = text.rfind("\f", 0, offsets[toc_line]) + 1
        summary_end = page_start if page_start > offsets[spot] else offsets[toc_line]
    return [
        *_other(0, offsets[spot]),
        _line_section("summary", lines, offsets, spot, summary_end),
        *_other(summary_end, body_start),
    ]


def invariant_violations(result: SplitResult, text_length: int) -> list[str]:
    """절 구간 규칙 위반 목록. 빈 목록이면 통과(docs/data-model.md 적재 검증 7번)."""
    problems: list[str] = []
    prev_end = 0
    for expected_seq, sec in enumerate(result.sections, 1):
        where = f"절 {sec.section_kind} {sec.part_seq}부 {sec.source_section_no}"
        if sec.section_seq != expected_seq:
            problems.append(f"{where}: section_seq {sec.section_seq} != {expected_seq}")
        if sec.char_start is None or sec.char_end is None:
            if sec.char_start is not None or sec.char_end is not None:
                problems.append(f"{where}: start·end 중 하나만 None")
            continue
        if not 0 <= sec.char_start < sec.char_end <= text_length:
            problems.append(
                f"{where}: 구간 [{sec.char_start}, {sec.char_end}) 범위 위반"
            )
        elif sec.char_start < prev_end:
            problems.append(f"{where}: 앞 절과 겹침")
        prev_end = max(prev_end, sec.char_end)
    return problems
