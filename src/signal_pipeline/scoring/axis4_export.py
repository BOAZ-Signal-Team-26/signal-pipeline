"""축 4 판정 CSV. {data_root}/exports/runs/{run_id}/axis4_judgments.csv (UTF-8 BOM, 새 파일만 씀).

칼럼: 번호, 접수번호, 항목, 판정값(있음/없음/판정 불가/적용 대상 아님), 근거절, 인용문장_또는_사유
- 있음: 근거절 = 근거가 있는 절, 인용 = 근거 구간 원문(공백 줄임, QUOTE_MAX자까지)
- 그 밖: 근거절 = 검사한 절, 사유 = reason_code와 notes
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from psycopg.rows import dict_row

from signal_pipeline.common.storage import write_new
from signal_pipeline.scoring.axis4_rules import ITEMS
from signal_pipeline.scoring.axis4_store import run_metric_keys

COLUMNS = ("번호", "접수번호", "항목", "판정값", "근거절", "인용문장_또는_사유")
VALUE_TEXT = {
    "MET": "있음",
    "UNMET": "없음",
    "UNDETERMINED": "판정 불가",
    "NOT_APPLICABLE": "적용 대상 아님",
}
QUOTE_MAX = 200
SCORE_SQL = """
SELECT d.rcept_no, d.document_id, sc.score_payload, sc.reason_code
FROM mart.score sc JOIN raw.document d USING (document_id)
WHERE sc.run_id = %s AND sc.assessor_key = 'deterministic' AND sc.metric_key = ANY(%s)
"""
SECTION_SQL = """
SELECT section_id, part_seq, source_section_no, section_kind, section_title, char_start, section_text
FROM staging.section WHERE section_id = ANY(%s)
"""


def section_label(sec: dict) -> str:
    if sec["part_seq"] and sec["source_section_no"]:
        return f"제{sec['part_seq']}부 {sec['source_section_no']}절"
    return "표지" if sec["section_kind"] == "other" else (sec["section_title"] or "")


def _quote(sec: dict, ev: dict) -> str:
    text = sec["section_text"][
        ev["char_start"] - sec["char_start"] : ev["char_end"] - sec["char_start"]
    ]
    text = " ".join(text.split())
    return text if len(text) <= QUOTE_MAX else text[:QUOTE_MAX] + "…"


def _row(number: int, rcept: str, row: dict, sections: dict[int, dict]) -> list:
    p = row["score_payload"]
    evidence = p["evidence"]
    if evidence:
        ids = list(dict.fromkeys(e["section_id"] for e in evidence))
        quotes = [_quote(sections[e["section_id"]], e) for e in evidence]
        detail = " / ".join(quotes)
    else:
        ids = p["checked_section_ids"]
        detail = ": ".join(x for x in (row["reason_code"], p["notes"]) if x)
    labels = "; ".join(section_label(sections[i]) for i in ids if i in sections)
    return [number, rcept, p["item"], VALUE_TEXT[p["status"]], labels, detail]


def export_csv(conn, data_root: Path, run_id: str) -> Path:
    """CSV를 쓰고 경로를 돌려준다. 문서 순서(document_id) 다음 항목 순서(ITEMS)."""
    with conn.cursor(row_factory=dict_row) as cur:
        scores = cur.execute(
            SCORE_SQL, (run_id, run_metric_keys(conn, run_id))
        ).fetchall()
        ids = {
            i
            for r in scores
            for i in [e["section_id"] for e in r["score_payload"]["evidence"]]
            + r["score_payload"]["checked_section_ids"]
        }
        sections = {s["section_id"]: s for s in cur.execute(SECTION_SQL, (list(ids),))}
    scores.sort(
        key=lambda r: (r["document_id"], ITEMS.index(r["score_payload"]["item"]))
    )
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    for n, r in enumerate(scores, 1):
        writer.writerow(_row(n, r["rcept_no"], r, sections))
    path = Path(data_root) / "exports" / "runs" / run_id / "axis4_judgments.csv"
    write_new(path, out.getvalue().encode("utf-8-sig"))
    return path
