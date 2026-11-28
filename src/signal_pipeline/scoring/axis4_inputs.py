"""축 4 판정 입력 조립. 문서·절·선택된 LLM 행·ETF 여부를 읽어 DocInput으로 만든다.

- 문서 = extraction/inputs.py DOC_SQL(투자설명서 전체. 대표본 선택은 적용하지 않음)
- 절 = 지정한 parser_version 것만. 한 문서의 절이 원본 둘 이상에서 오면 섞지 않고 ValueError
- 절 텍스트는 판정에 쓰는 절(other, 제2부 7·8·9·10·13절, 제5부 2절)만 읽는다. 나머지는 위치·종류만 읽는다
- LLM 행 = 지정한 LLM 추출 실행의 is_selected 행
- ETF = 연결 상품 중 KRX_CONFIRMED가 있음(etf_confirmed), 또는 보고서명 규칙 is_etf(etf_by_name. LLM 추출과 같은 함수)
"""

from __future__ import annotations

from collections.abc import Iterable

from psycopg.rows import dict_row

from signal_pipeline.extraction.inputs import DOC_SQL, is_etf
from signal_pipeline.scoring.axis4_rules import DocInput, LlmRow, SectionRow

TEXT_COND = (
    "(s.section_kind = 'other'"
    " OR (s.part_seq = 2 AND s.source_section_no = ANY(ARRAY['7','8','9','10','13']))"
    " OR (s.part_seq = 5 AND s.source_section_no = '2'))"
)
SECTION_SQL = f"""
SELECT s.document_id, s.section_id, s.raw_object_id, s.section_seq, s.part_seq, s.source_section_no,
       s.section_kind, s.section_title, s.char_start, s.char_end, s.extract_status,
       CASE WHEN {TEXT_COND} THEN s.section_text END AS section_text
FROM staging.section s
WHERE s.document_id = ANY(%(ids)s) AND s.parser_version = %(parser)s
ORDER BY s.document_id, s.section_seq, s.section_id
"""
LLM_SQL = """
SELECT extraction_id, document_id, field_name, result_status, value_json
FROM staging.llm_field_extraction
WHERE run_id = %(run)s AND is_selected AND document_id = ANY(%(ids)s)
"""
ETF_SQL = """
SELECT dp.document_id FROM staging.document_product dp JOIN staging.product p USING (product_id)
WHERE dp.document_id = ANY(%(ids)s)
GROUP BY dp.document_id HAVING bool_or(p.etf_confidence = 'KRX_CONFIRMED')
"""
SECTION_FIELDS = tuple(SectionRow.__dataclass_fields__)


def build_doc_inputs(
    conn,
    llm_run_id: str,
    parser_version: str,
    document_ids: Iterable[int] | None = None,
    limit: int | None = None,
) -> tuple[list[dict], list[DocInput]]:
    """(문서 행들, DocInput들). 문서 순서는 document_id. limit은 앞에서부터 N건."""
    ids = None if document_ids is None else list(document_ids)
    with conn.cursor(row_factory=dict_row) as cur:
        docs = cur.execute(DOC_SQL, {"ids": ids}).fetchall()[:limit]
        doc_ids = [d["document_id"] for d in docs]
        sections: dict[int, list[dict]] = {}
        for row in cur.execute(SECTION_SQL, {"ids": doc_ids, "parser": parser_version}):
            sections.setdefault(row["document_id"], []).append(row)
        llm: dict[int, dict[str, LlmRow]] = {}
        for row in cur.execute(LLM_SQL, {"run": llm_run_id, "ids": doc_ids}):
            llm.setdefault(row["document_id"], {})[row["field_name"]] = LlmRow(
                row["extraction_id"], row["result_status"], row["value_json"]
            )
        etf = {r["document_id"] for r in cur.execute(ETF_SQL, {"ids": doc_ids})}
    mixed = {
        doc: sorted({r["raw_object_id"] for r in rows})
        for doc, rows in sections.items()
        if len({r["raw_object_id"] for r in rows}) > 1
    }
    if mixed:
        raise ValueError(
            f"파서 버전 {parser_version}에서 원본이 둘 이상인 문서(document_id: raw_object_id 목록): {mixed}"
        )
    inputs = [
        DocInput(
            document_id=d["document_id"],
            sections=tuple(
                SectionRow(**{k: r[k] for k in SECTION_FIELDS})
                for r in sections.get(d["document_id"], [])
            ),
            llm=llm.get(d["document_id"], {}),
            etf_confirmed=d["document_id"] in etf,
            etf_by_name=is_etf(d["report_name"]),
        )
        for d in docs
    ]
    return docs, inputs
