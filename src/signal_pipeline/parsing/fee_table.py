"""투자설명서 제2부 13절 수수료·보수 표 → 정규화 JSON (이슈 #99).

입력:  DB의 투자설명서 목록, staging.section(파서판 pdfplumber-0.11_prep-9)의 13절 글자 범위,
       {data_root}/derived/{raw_sha256}/pdfplumber-0.11_prep-9/structure.json 의 page_starts,
       {data_root}/raw/dart/{접수번호}/body_pdf__v{n}.pdf
출력:  {out_root}/derived/{raw_sha256}/fee-table-v1/fee_tables.json (새 파일만 씀, 있으면 건너뜀)
표 하나의 정규화는 fee_table_rows. 여기서는 쪽 연결(다음 쪽 위쪽의 머리글 없는 표 이어 붙이기),
상태 판정, 파일 입출력을 한다.

용례: DATABASE_URL=... uv run python -m signal_pipeline.parsing.fee_table ../signal-data \
        --out-root ../signal-data [--limit N] [--rcept-no X] [--workers 8]
"""

from __future__ import annotations

import argparse
import bisect
import json
import os
import re
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

from signal_pipeline.parsing import parallel
from signal_pipeline.parsing.fee_table_rows import (
    ROWS,
    PageTable,
    finish_rows,
    has_number,
    is_class_label,
    normalize_table,
)

VERSION = "fee-table-v1"
SECTION_PARSER_VERSION = "pdfplumber-0.11_prep-9"
CONTINUATION_TOP = 0.2  # 이어지는 표는 쪽 높이의 위 20% 안에서 시작

DOCS_SQL = """
SELECT d.rcept_no, d.report_name, o.storage_path, o.sha256, s.char_start, s.char_end
FROM raw.document d
LEFT JOIN raw.raw_object o ON o.document_id = d.document_id AND o.file_role = 'body_pdf'
LEFT JOIN LATERAL (
  SELECT char_start, char_end FROM staging.section s
  WHERE s.document_id = d.document_id AND s.parser_version = %(pv)s AND s.part_seq = 2
    AND s.source_section_no = '13' AND s.char_start IS NOT NULL
  ORDER BY s.section_seq LIMIT 1) s ON true
WHERE d.document_type = '투자설명서' AND (%(rcept_no)s::text IS NULL OR d.rcept_no = %(rcept_no)s)
ORDER BY d.rcept_no
"""


def fund_name(report_name: str | None) -> str:
    """「[기재정정]투자설명서(집합투자증권)(펀드 이름)」 → 「펀드 이름」."""
    tail = re.sub(r"^.*?투자설명서(\(집합투자증권\))?", "", report_name or "")
    return tail[1:-1] if tail.startswith("(") and tail.endswith(")") else tail


def _continues(prev: PageTable, nxt: PageTable) -> bool:
    return (
        nxt.headerless
        and nxt.first_on_page
        and nxt.top < CONTINUATION_TOP
        and prev.orientation == ROWS
        and not prev.headerless
        and prev.pages[-1] == nxt.page - 1
        and len(prev.columns) == len(nxt.columns)
    )


def join_pages(tables: list[PageTable]) -> list[PageTable]:
    """쪽·위치 순 표 목록에서 머리글 없는 이어짐 표를 앞쪽 마지막 표에 붙인다.
    붙일 곳이 없는 머리글 없는 표는 버린다. 기간별 표처럼 머리글이 있는 표는 따로 둔다."""
    out: list[PageTable] = []
    for t in tables:
        if not t.headerless:
            out.append(replace(t, pages=(t.page,)))
        elif out and _continues(out[-1], t):
            prev = out[-1]
            pages = prev.pages if t.page in prev.pages else (*prev.pages, t.page)
            out[-1] = replace(prev, entries=prev.entries + t.entries, pages=pages)
    return out


def page_tables(
    raw_pages: list[tuple[int, list[tuple[float, list]]]], default_label: str
) -> list[PageTable]:
    """[(쪽 번호, [(위쪽 위치 비율, extract 결과), ...]), ...] → 쪽 연결 전 표 목록."""
    out: list[PageTable] = []
    for page, tables in raw_pages:
        first_top = min((top for top, _ in tables), default=None)
        for top, raw in sorted(tables, key=lambda x: x[0]):
            for t in normalize_table(raw, page, top, default_label):
                out.append(replace(t, first_on_page=top == first_top))
    return out


def to_json_tables(tables: list[PageTable], default_label: str) -> list[dict]:
    out = []
    for t in tables:
        rows = finish_rows(t.entries, default_label)
        if rows:
            out.append(
                {
                    "pages": list(t.pages),
                    "orientation": t.orientation,
                    "columns": list(t.columns),
                    "rows": rows,
                }
            )
    return out


def is_ok(tables: list[dict], fund: str) -> bool:
    return any(
        (is_class_label(r["label"]) or (fund and r["label"] == fund))
        and any(map(has_number, r["cells"]))
        for t in tables
        for r in t["rows"]
    )


def normalize_document(raw_pages: list, fund: str) -> tuple[str, list[dict]]:
    """쪽별 원시 표 → (상태, 표). 순수 함수."""
    if not any(tables for _, tables in raw_pages):
        return "NO_TABLE", []
    tables = to_json_tables(join_pages(page_tables(raw_pages, fund)), fund)
    return ("OK" if is_ok(tables, fund) else "UNREADABLE"), tables


def section_pages(data_root: Path, sha: str, start: int, end: int) -> list[int]:
    struct = json.loads(
        (
            data_root / f"derived/{sha}/{SECTION_PARSER_VERSION}/structure.json"
        ).read_text(encoding="utf-8")
    )
    starts = struct["page_starts"]
    p0 = bisect.bisect_right(starts, start) - 1
    p1 = bisect.bisect_right(starts, max(end - 1, start)) - 1
    return list(range(p0, p1 + 1))


def read_raw_tables(
    pdf_path: Path, pages: list[int]
) -> list[tuple[int, list[tuple[float, list]]]]:
    """쪽마다 보이지 않는 선·사각형을 뺀 뒤(파서와 같은 규칙) pdfplumber 기본 find_tables."""
    import pdfplumber

    from signal_pipeline.parsing.pdf_layout import is_invisible

    out = []
    with pdfplumber.open(pdf_path) as pdf:
        for i in pages:
            page = pdf.pages[i]
            visible = page.filter(lambda o: not is_invisible(o))
            found = [
                (t.bbox[1] / page.height, t.extract()) for t in visible.find_tables()
            ]
            out.append((i + 1, found))
            page.flush_cache()
    return out


def build_result(doc: dict, data_root: Path) -> dict:
    result = {
        "version": VERSION,
        "rcept_no": doc["rcept_no"],
        "raw_sha256": doc["sha256"],
        "section_parser_version": SECTION_PARSER_VERSION,
        "status": "",
        "tables": [],
        "note": None,
    }
    pdf_path = data_root / (doc["storage_path"] or "")
    if not doc["storage_path"] or not pdf_path.exists():
        return {**result, "status": "NO_PDF"}
    if doc["char_start"] is None:
        return {**result, "status": "NO_SECTION"}
    try:
        pages = section_pages(
            data_root, doc["sha256"], doc["char_start"], doc["char_end"]
        )
        raw = read_raw_tables(pdf_path, pages)
        status, tables = normalize_document(raw, fund_name(doc["report_name"]))
    except Exception as exc:  # noqa: BLE001 — 문서 하나의 실패는 상태로 남기고 계속
        return {
            **result,
            "status": "ERROR",
            "note": f"{type(exc).__name__}: {exc}"[:200],
        }
    note = f"pages {pages[0] + 1}-{pages[-1] + 1}" if status != "OK" else None
    return {**result, "status": status, "tables": tables, "note": note}


def output_path(out_root: Path, sha: str) -> Path:
    return out_root / f"derived/{sha}/{VERSION}/fee_tables.json"


def process(doc: dict, data_root: str, out_root: str) -> str:
    """문서 하나 처리 후 파일 저장. 상태를 돌려준다(자식 프로세스에서 실행)."""
    from signal_pipeline.common.storage import write_new

    result = build_result(doc, Path(data_root))
    if doc["sha256"]:
        body = json.dumps(result, ensure_ascii=False, indent=1).encode("utf-8")
        write_new(output_path(Path(out_root), doc["sha256"]), body)
    return result["status"]


def load_docs(rcept_no: str | None) -> list[dict]:
    import psycopg

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        cur = conn.execute(
            DOCS_SQL, {"pv": SECTION_PARSER_VERSION, "rcept_no": rcept_no}
        )
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("data_root", type=Path)
    ap.add_argument("--out-root", type=Path, required=True)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--rcept-no")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--timeout", type=float, default=300)
    args = ap.parse_args()
    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL 환경 변수가 필요하다", file=sys.stderr)
        return 2
    docs = load_docs(args.rcept_no)[: args.limit]
    # 출력 경로가 raw_sha256 기준이라 같은 PDF를 가진 문서는 접수번호가 빠른 것 하나만 처리
    first_by_sha = {d["sha256"]: d for d in reversed(docs) if d["sha256"]}
    unique = [d for d in docs if not d["sha256"] or first_by_sha[d["sha256"]] is d]
    todo = [
        d
        for d in unique
        if not (d["sha256"] and output_path(args.out_root, d["sha256"]).exists())
    ]
    jobs = [(d, str(args.data_root), str(args.out_root)) for d in todo]
    outcomes = parallel.run_isolated(
        process, jobs, workers=args.workers, timeout=args.timeout
    )
    counts = Counter(
        value if kind == "ok" else kind.upper() for kind, value in outcomes
    )
    print(
        f"문서 {len(docs)}, 같은 PDF 중복 {len(docs) - len(unique)}, "
        f"이미 있음(건너뜀) {len(unique) - len(todo)}, 처리 {len(todo)}"
    )
    print("상태:", dict(counts.most_common()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
