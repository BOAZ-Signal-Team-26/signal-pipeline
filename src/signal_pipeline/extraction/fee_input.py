"""fee_structure 입력에 덧붙이는 수수료 표 정리본(이슈 #99).

파서가 만든 derived/{raw_sha256}/fee-table-v1/fee_tables.json(status OK)을 읽어 클래스별 행 텍스트로 바꾼다.
- 정리본은 참고용 입력이다. 셀 텍스트는 PDF 표에서 잘리거나 공백이 사라질 수 있어 근거(quote) 위치는
  계속 원문 절에서 찾는다. 프롬프트도 quote를 원문에서 하라고 지시한다
- 정리본이 붙은 입력은 클래스마다 근거 1개 이상을 요구한다(convert.py). 표를 읽지 못한 문서는 현행 유지
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

VERSION = "fee-table-v1"
HEADER = "[수수료 표 정리본: PDF 표를 자동으로 정리한 참고용. quote는 이 정리본이 아니라 위 원문에서 한다]"


@dataclass(frozen=True)
class FeeRow:
    label: str  # 공백을 지운 클래스 이름
    total: str | None  # 「총보수」 열 원문 셀
    peer: str | None  # 「동종유형」 열 원문 셀. 열이 없으면 None


@dataclass(frozen=True)
class FeeTable:
    text: str  # 입력 텍스트에 붙는 정리본
    path: str  # data_root 기준 상대 경로
    sha256: str  # 파일 바이트 해시
    rows: tuple[
        FeeRow, ...
    ] = ()  # 보수 표(「총보수」 열이 있는 첫 표)의 행. 값 보정에 씀


def table_path(raw_sha256: str) -> str:
    return f"derived/{raw_sha256}/{VERSION}/fee_tables.json"


def render(data: Mapping[str, Any]) -> str | None:
    """정리본 텍스트. status가 OK가 아니거나 행이 없으면 None."""
    if data.get("status") != "OK":
        return None
    lines = [HEADER]
    for i, table in enumerate(data.get("tables") or [], 1):
        if not table.get("rows"):
            continue
        pages = ", ".join(str(p) for p in table["pages"])
        lines.append(f"표 {i} ({pages}쪽)")
        lines += [_row_line(table["columns"], r) for r in table["rows"]]
    return "\n".join(lines) if len(lines) > 1 else None


def _row_line(columns: list[str], row: Mapping[str, Any]) -> str:
    """한 행을 「클래스: 열=값; 열=값」으로. 모델이 칸 위치를 세다가 열을 잘못 잡지 않게 열 이름을 값마다 붙임.

    빈 칸은 뺀다. 클래스 이름이 비어 있으면 「(클래스 이름 없음)」.
    """
    pairs = [f"{c}={v}" for c, v in zip(columns, row["cells"]) if v]
    return f"{row['label'] or '(클래스 이름 없음)'}: {'; '.join(pairs)}"


def read(data_root: Path, raw_sha256: str) -> FeeTable | None:
    """정리본 파일을 읽는다. 파일이 없거나 표를 못 읽은 문서면 None. 다른 원본 파일이면 중단."""
    rel = table_path(raw_sha256)
    try:
        raw = (Path(data_root) / rel).read_bytes()
    except FileNotFoundError:
        return None
    data = json.loads(raw)
    if data.get("version") != VERSION or data.get("raw_sha256") != raw_sha256:
        raise ValueError(f"수수료 표 정리본의 버전·원본 해시가 경로와 다름: {rel}")
    text = render(data)
    if not text:
        return None
    return FeeTable(text, rel, hashlib.sha256(raw).hexdigest(), fee_rows(data))


def _bare(text: str | None) -> str:
    return re.sub(r"\s+", "", text or "")


def fee_rows(data: Mapping[str, Any]) -> tuple[FeeRow, ...]:
    """「총보수」 열이 있는 첫 표의 행. 기간별로 보수가 내려가는 펀드는 첫 표(최초 기간)만 씀."""
    for table in data.get("tables") or []:
        cols = [_bare(c) for c in table["columns"]]
        if "총보수" not in cols:
            continue
        ti = cols.index("총보수")
        pi = next((i for i, c in enumerate(cols) if "동종유형" in c), None)
        return tuple(
            FeeRow(
                _bare(r["label"]),
                r["cells"][ti],
                None if pi is None else r["cells"][pi],
            )
            for r in table["rows"]
        )
    return ()


def _rate(cell: str | None, blank_is_null: bool) -> tuple[bool, dict | None]:
    """셀 → (읽었는지, 금액). 「-」는 (True, None), 숫자가 아닌 셀은 (False, None).

    빈 칸: 총보수는 병합 셀이라 값이 첫 행에만 들어간 경우가 있어 읽지 않음(모델 값 유지).
    동종유형 총보수는 비교 유형이 없는 클래스(온라인슈퍼, 개인연금 등)라 비어 있는 경우가 대부분이라 null.
    11월 28일 실측: 동종유형 빈 칸에서 모델 값을 남기면 15개 중 대부분이 기타비용이나 총보수를 옮긴 값이었음
    """
    text = _bare(cell).removesuffix("%")
    if text == "-" or (not text and blank_is_null):
        return True, None
    if not text:
        return False, None
    try:
        return True, {"amount": float(text), "unit": "%"}
    except ValueError:
        return False, None


def _code_in(short: str, long: str) -> bool:
    """짧은 이름이 긴 이름 안에 클래스 코드로 들어 있는지: 「(A)」 괄호 코드이거나 「A(…)」처럼 맨 앞 코드.

    「A」가 「…(Ae)」나 「AG(…)」에 글자로만 들어 있는 경우를 같은 클래스로 보지 않기 위함.
    """
    return f"({short})" in long or (
        long.startswith(short) and len(long) > len(short) and long[len(short)] == "("
    )


def _name_index(name: str | None, rows: tuple[FeeRow, ...]) -> int | None:
    """이름으로 맞춘 행 번호. 정확히 같은 이름 하나, 없으면 클래스 코드로 맞는 행 하나. 아니면 None."""
    key = _bare(name)
    if not key:
        return None
    exact = [i for i, r in enumerate(rows) if r.label == key]
    if len(exact) == 1:
        return exact[0]
    coded = [
        i
        for i, r in enumerate(rows)
        if r.label and (_code_in(r.label, key) or _code_in(key, r.label))
    ]
    return coded[0] if len(coded) == 1 else None


def _mapping(classes: list[dict], rows: tuple[FeeRow, ...]) -> list[int | None]:
    """클래스마다 맞춘 행 번호. 이름으로 못 맞춘 클래스는 행 수가 같고, 이름으로 맞춘 클래스가 모두
    같은 순서의 행에 맞았을 때만 같은 순서의 행을 씀(순서가 하나라도 어긋나면 순서 매칭을 쓰지 않음)."""
    by_name = [_name_index(c["class_name"], rows) for c in classes]
    in_order = len(rows) == len(classes) and all(
        j is None or j == i for i, j in enumerate(by_name)
    )
    return [
        j if j is not None else (i if in_order else None) for i, j in enumerate(by_name)
    ]


def correct(value: dict, table: FeeTable | None) -> tuple[dict, str | None]:
    """total_fee·peer_total_fee를 정리본의 「총보수」「동종유형」 열 값으로 바꾼다(이슈 #99).

    모델이 「총보수·비용」을 총보수로 고르는 열 오류를 막기 위함. 행을 못 맞추거나 셀이 숫자가 아니면 모델 값 유지.
    반환: (새 value, 바꾼 개수 메모 또는 None)
    """
    if table is None or not table.rows:
        return value, None
    classes, n_total, n_peer = [], 0, 0
    mapping = _mapping(value["classes"], table.rows)
    for cls, j in zip(value["classes"], mapping):
        row = None if j is None else table.rows[j]
        new = dict(cls)
        if row is not None:
            ok, total = _rate(row.total, blank_is_null=False)
            if ok and total != cls["total_fee"]:
                new["total_fee"], n_total = total, n_total + 1
            ok, peer = _rate(row.peer, blank_is_null=True)
            if row.peer is not None and ok and peer != cls["peer_total_fee"]:
                new["peer_total_fee"], n_peer = peer, n_peer + 1
        classes.append(new)
    if not (n_total or n_peer):
        return value, None
    note = f"표 정리본 값으로 보정: 총보수 {n_total}개, 동종유형 총보수 {n_peer}개({VERSION})"
    return {**value, "classes": classes}, note
