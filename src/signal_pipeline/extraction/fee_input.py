"""fee_structure 입력에 덧붙이는 수수료 표 정리본(이슈 #99).

파서가 만든 derived/{raw_sha256}/fee-table-v1/fee_tables.json(status OK)을 읽어 클래스별 행 텍스트로 바꾼다.
- 정리본은 참고용 입력이다. 셀 텍스트는 PDF 표에서 잘리거나 공백이 사라질 수 있어 근거(quote) 위치는
  계속 원문 절에서 찾는다. 프롬프트도 quote를 원문에서 하라고 지시한다
- 정리본이 붙은 입력은 클래스마다 근거 1개 이상을 요구한다(convert.py). 표를 읽지 못한 문서는 현행 유지
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

VERSION = "fee-table-v1"
HEADER = "[수수료 표 정리본: PDF 표를 자동으로 정리한 참고용. quote는 이 정리본이 아니라 위 원문에서 한다]"


@dataclass(frozen=True)
class FeeTable:
    text: str  # 입력 텍스트에 붙는 정리본
    path: str  # data_root 기준 상대 경로
    sha256: str  # 파일 바이트 해시


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
    return FeeTable(text, rel, hashlib.sha256(raw).hexdigest()) if text else None
