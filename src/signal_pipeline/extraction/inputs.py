"""LLM 추출 입력 조립. 문서·필드마다 출처 절 텍스트를 이어 붙이고 input_sha256과 request.json의 inputs를 만든다.

규칙(docs/io-schema.md 「추출 필드 목록」·「입력 참조」, storage-and-failure-rules.md 「LLM 호출 저장」)
- 절 선택: 제2부 N절 = part_seq=2 and source_section_no='N', 요약정보 = section_kind='summary',
  표지 = section_kind='other' and section_seq=1(500개 문서 모두 section_seq=1이 표지 other. other 중 section_seq>1은 표지가 아님).
  같은 라벨이 여럿이면 section_seq가 가장 작은 절을 고른다(현재 데이터에는 중복 없음).
- 텍스트는 strip·정규화 없이 그대로 쓴다. 해시 = sha256(UTF-8). section_text에 CR은 없다(적재 데이터 0건). 있어도 고치지 않는다.
- 출처 절이 없거나 extract_status가 EXTRACT_OK가 아니면 missing에 라벨을 올리고 텍스트에 넣지 않는다.
  절 전체 사용이므로 「NOT_FOUND 허용 조건」의 나머지 조건(절 전체 포함)은 항상 만족한다.
- ETF(보고서명에 '상장지수')는 환매 대신 상장 매매를 하므로 redemption_terms 입력을 만들지 않고 exclusions에 남긴다.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from psycopg.rows import dict_row

FIELDS = (
    "principal_loss_notice",
    "key_risk_phrases",
    "fee_structure",
    "redemption_terms",
)
FIELD_SOURCES: dict[str, tuple[str, ...]] = {
    "principal_loss_notice": ("표지", "제2부 10절"),
    "key_risk_phrases": ("제2부 10절",),
    "fee_structure": ("요약정보", "제2부 13절"),
    "redemption_terms": ("제2부 11절",),
}
SEP = "\n\n"
OK = "EXTRACT_OK"


@dataclass(frozen=True)
class SectionText:
    label: str
    section_id: int
    char_start: int
    text: str
    # inputs[] 항목용. 기본값은 DB 없는 단위 테스트를 위한 것
    raw_object_id: int | None = None
    raw_sha256: str | None = None
    parser_version: str | None = None


@dataclass(frozen=True)
class FieldInput:
    document_id: int
    raw_object_id: int | None
    field_name: str
    sections: tuple[SectionText, ...]
    missing: tuple[str, ...]
    input_text: str
    input_sha256: str
    inputs: tuple[dict, ...]


def is_etf(report_name: str | None) -> bool:
    return "상장지수" in (report_name or "")


def is_feeder_like(report_name: str | None) -> bool:
    name = report_name or ""
    return "재간접" in name or "자투자" in name


def section_label(row: Mapping[str, Any]) -> str | None:
    """절 행이 어느 출처 라벨인지. 출처가 아니면 None."""
    if row["section_kind"] == "summary":
        return "요약정보"
    if row["section_kind"] == "other" and row["section_seq"] == 1:
        return "표지"
    if row["part_seq"] == 2 and row["source_section_no"]:
        return f"제2부 {row['source_section_no']}절"
    return None


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _by_label(rows: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    """라벨별 대표 절. 중복이면 section_seq 최소."""
    picked: dict[str, Mapping[str, Any]] = {}
    for row in sorted(rows, key=lambda r: r["section_seq"]):
        label = section_label(row)
        if label and label not in picked:
            picked[label] = row
    return picked


def _usable(row: Mapping[str, Any] | None) -> bool:
    return (
        row is not None
        and row["extract_status"] == OK
        and row["section_text"] is not None
        and row["char_start"] is not None
    )


def build_inputs_entries(sections: Sequence[SectionText]) -> tuple[dict, ...]:
    """request.json inputs[]. 같은 (원본, 파서 버전)에서 연달아 온 절은 한 항목의 section_ids로 묶는다."""
    entries: list[dict] = []
    for s in sections:
        key = (s.raw_object_id, s.parser_version)
        if (
            entries
            and (entries[-1]["raw_object_id"], entries[-1]["parser_version"]) == key
        ):
            entries[-1]["section_ids"].append(s.section_id)
        else:
            entries.append(
                {
                    "raw_object_id": s.raw_object_id,
                    "raw_sha256": s.raw_sha256,
                    "parser_version": s.parser_version,
                    "section_ids": [s.section_id],
                }
            )
    return tuple(entries)


def assemble_field_input(
    document_id: int, field_name: str, rows: Iterable[Mapping[str, Any]]
) -> FieldInput:
    """문서 1건의 절 행들로 필드 입력 1건을 만든다(DB 없음)."""
    picked = _by_label(rows)
    found: list[SectionText] = []
    missing: list[str] = []
    for label in FIELD_SOURCES[field_name]:
        row = picked.get(label)
        if not _usable(row):
            missing.append(label)
            continue
        found.append(
            SectionText(
                label=label,
                section_id=row["section_id"],
                char_start=row["char_start"],
                text=row["section_text"],
                raw_object_id=row["raw_object_id"],
                raw_sha256=row["raw_sha256"],
                parser_version=row["parser_version"],
            )
        )
    text = SEP.join(s.text for s in found)
    return FieldInput(
        document_id=document_id,
        raw_object_id=found[0].raw_object_id if found else None,
        field_name=field_name,
        sections=tuple(found),
        missing=tuple(missing),
        input_text=text,
        input_sha256=sha256_text(text),
        inputs=build_inputs_entries(found),
    )


def assemble_document(
    doc: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> tuple[list[FieldInput], dict | None]:
    """문서 1건 → (필드 입력들, ETF 제외 기록 또는 None)."""
    etf = is_etf(doc["report_name"])
    fields = [f for f in FIELDS if not (etf and f == "redemption_terms")]
    inputs = [assemble_field_input(doc["document_id"], f, rows) for f in fields]
    exclusion = None
    if etf:
        exclusion = {
            "document_id": doc["document_id"],
            "rcept_no": doc.get("rcept_no"),
            "source_doc_key": doc["source_doc_key"],
            "report_name": doc["report_name"],
            "field_name": "redemption_terms",
            "feeder_like": is_feeder_like(doc["report_name"]),
        }
    return inputs, exclusion


DOC_SQL = """
SELECT document_id, source_doc_key, rcept_no, report_name FROM raw.document
WHERE %(ids)s::bigint[] IS NULL OR document_id = ANY(%(ids)s)
ORDER BY document_id
"""
SECTION_SQL = """
SELECT s.document_id, s.section_id, s.raw_object_id, s.parser_version, s.section_seq, s.part_seq,
       s.source_section_no, s.section_kind, s.char_start, s.extract_status, s.section_text,
       r.sha256 AS raw_sha256
FROM staging.section s JOIN raw.raw_object r USING (raw_object_id)
WHERE s.document_id = ANY(%(ids)s)
  AND (s.section_kind = 'summary' OR (s.section_kind = 'other' AND s.section_seq = 1) OR s.part_seq = 2)
ORDER BY s.document_id, s.section_seq
"""


def build_field_inputs(
    conn, document_ids: Iterable[int] | None = None
) -> tuple[list[FieldInput], list[dict]]:
    """DB에서 읽어 (필드 입력, ETF 제외 기록)을 돌려준다. 문서 순서·필드 순서 고정."""
    ids = None if document_ids is None else list(document_ids)
    with conn.cursor(row_factory=dict_row) as cur:
        docs = cur.execute(DOC_SQL, {"ids": ids}).fetchall()
        by_doc: dict[int, list[dict]] = {}
        for row in cur.execute(SECTION_SQL, {"ids": [d["document_id"] for d in docs]}):
            by_doc.setdefault(row["document_id"], []).append(row)
    field_inputs: list[FieldInput] = []
    exclusions: list[dict] = []
    for doc in docs:
        inputs, exclusion = assemble_document(doc, by_doc.get(doc["document_id"], []))
        field_inputs.extend(inputs)
        if exclusion:
            exclusions.append(exclusion)
    return field_inputs, exclusions
