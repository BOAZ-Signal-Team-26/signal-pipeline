"""축 4 저장: 키워드 자산 설치, metric_definition 등록, PENDING 계획 행, 판정 UPDATE, 적재 검증.

규칙(docs/scoring-and-population.md 「결과 상태와 결측」, 이슈 #90 설계 결정)
- 키워드 자산: assets/keywords/axis4__v0__{sha256 앞 12자}.json. 이미 있으면 해시가 같을 때만 재사용
- metric_definition 10행: INSERT ... ON CONFLICT (metric_key) DO NOTHING 뒤 definition_sha256을 대조하고 다르면 ValueError
- score 행 = 문서 x 항목. 계획 때 PENDING/PLANNED로 넣고 판정 때 UPDATE(PENDING인 행만)
- OK는 MET=1, UNMET=0. 그 밖 raw_score는 NULL이고 reason_code가 있다
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from signal_pipeline.common.storage import write_new
from signal_pipeline.extraction.store import canonical
from signal_pipeline.scoring.axis4_rules import (
    ITEMS,
    MET,
    NOT_APPLICABLE,
    UNDETERMINED,
    UNMET,
    Judgment,
    validate_keywords,
)

ASSET_NAME = "axis4_v1.json"
ASSET_ID = "axis4"
ASSESSOR = "deterministic"
SELECTION_POLICY = "axis4-all-prospectus-v0"
CONTRACT_VERSION = 2
RULE_VERSION = "axis4-rules-v1"
RESULT_STATUS = {
    MET: "OK",
    UNMET: "OK",
    NOT_APPLICABLE: "NOT_APPLICABLE",
    UNDETERMINED: "UNDETERMINED",
}
ITEM_LABELS = {
    "나1": "투자목적·투자대상·투자전략",
    "나2": "원금손실 가능성 고지와 주요 위험",
    "3.1": "위험등급 산정 기준",
    "3.2": "위험등급 이유",
    "3.3": "위험등급 의미와 유의사항",
    "3.4": "위험등급 표지 요약",
    "4.1": "수수료와 보수",
    "4.2": "환매 조건과 환매수수료",
    "4.3": "계약의 해지·해제",
    "11.2": "예금자보호 대상이 아님을 고지",
}


@dataclass(frozen=True)
class KeywordAsset:
    path: str  # data_root 기준 상대경로
    sha256: str
    version: str  # 자산 파일의 version. 지표 버전이 된다
    data: dict[str, Any]


def metric_code(item: str) -> str:
    return "na" + item[1] if item.startswith("나") else item.replace(".", "_")


def metric_key(item: str, version: str) -> str:
    return f"disclosure_item_{metric_code(item)}:{version}"


def read_asset() -> bytes:
    return (
        resources.files("signal_pipeline.scoring") / "keywords" / ASSET_NAME
    ).read_bytes()


def install_keywords(data_root: Path) -> KeywordAsset:
    """키워드 자산을 assets/keywords/에 복사하고 shape를 검사한다. 이미 있는 파일은 해시가 같아야 한다."""
    raw = read_asset()
    data = validate_keywords(json.loads(raw.decode("utf-8")))
    sha = hashlib.sha256(raw).hexdigest()
    version = data.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"v\d+", version):
        raise ValueError(f"키워드 자산: version이 v숫자 형식이 아님: {version!r}")
    rel = f"assets/keywords/{ASSET_ID}__{version}__{sha[:12]}.json"
    target = Path(data_root) / rel
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != sha:
            raise ValueError(f"자산 해시 불일치: {rel}")
    else:
        write_new(target, raw)
    return KeywordAsset(rel, sha, version, data)


def definitions(asset: KeywordAsset) -> list[dict]:
    """metric_definition 행 10개(순서 = ITEMS). 설치한 키워드 자산의 경로·해시가 정의 해시에 들어간다."""
    rows = []
    for item in ITEMS:
        manifest = {
            "item": item,
            "label": ITEM_LABELS[item],
            "assessor_key": ASSESSOR,
            "rule_version": RULE_VERSION,
            "selection_policy_version": SELECTION_POLICY,
            "asset": {"path": asset.path, "sha256": asset.sha256},
        }
        rows.append(
            {
                "metric_key": metric_key(item, asset.version),
                "metric_id": f"disclosure_item_{metric_code(item)}",
                "version": asset.version,
                "manifest": manifest,
                "sha256": hashlib.sha256(canonical(manifest).encode()).hexdigest(),
            }
        )
    return rows


def register_metrics(conn, asset: KeywordAsset) -> None:
    """정의 10행을 넣고(있으면 그대로 둠) 저장된 definition_sha256이 코드와 같은지 대조한다."""
    defs = definitions(asset)
    with conn.transaction():
        for d in defs:
            conn.execute(
                "INSERT INTO mart.metric_definition (metric_key, metric_id, version, target_type, level, direction,"
                " definition_status, definition_manifest, definition_sha256)"
                " VALUES (%s, %s, %s, 'DOCUMENT', 'ATOMIC', 'HIGHER_IS_BETTER', 'DRAFT', %s, %s)"
                " ON CONFLICT (metric_key) DO NOTHING",
                (
                    d["metric_key"],
                    d["metric_id"],
                    d["version"],
                    Jsonb(d["manifest"]),
                    d["sha256"],
                ),
            )
        stored = dict(
            conn.execute(
                "SELECT metric_key, definition_sha256 FROM mart.metric_definition WHERE metric_key = ANY(%s)",
                ([d["metric_key"] for d in defs],),
            ).fetchall()
        )
    bad = [d["metric_key"] for d in defs if stored.get(d["metric_key"]) != d["sha256"]]
    if bad:
        raise ValueError(
            f"metric_definition 해시 불일치(실행 거부): {bad}. "
            "키워드 자산이 바뀌었으면 새 지표 버전(v0 → v1 등)이 필요하다"
        )


def metric_keys(version: str) -> list[str]:
    return [metric_key(i, version) for i in ITEMS]


def run_metric_keys(conn, run_id: str) -> list[str]:
    """실행이 쓴 지표 키 10개. 같은 실행의 다른 채점 행은 검증·집계·내보내기에서 제외한다."""
    row = conn.execute(
        "SELECT config_manifest->'keyword_asset'->>'version' FROM raw.pipeline_run WHERE run_id = %s",
        (run_id,),
    ).fetchone()
    if not row or not row[0]:
        raise ValueError(f"실행에 keyword_asset.version 기록이 없음: {run_id}")
    return metric_keys(row[0])


def target_key(document_id: int) -> str:
    return hashlib.sha256(
        canonical(
            {
                "contract_version": 3,
                "target_type": "DOCUMENT",
                "anchor": {"document_id": document_id},
                "selection_policy_version": SELECTION_POLICY,
            }
        ).encode()
    ).hexdigest()


def payload(j: Judgment) -> dict:
    return {
        "contract_version": CONTRACT_VERSION,
        "item": j.item,
        "status": j.status,
        "evidence": list(j.evidence),
        "checked_section_ids": list(j.checked_section_ids),
        "matched": list(j.matched),
        "llm_extraction_ids": list(j.llm_extraction_ids),
        "notes": j.notes,
    }


def insert_pending(conn, run_id: str, document_ids: list[int], version: str) -> int:
    """문서 x 항목 PENDING 행. 넣은 행 수."""
    rows = [
        (
            run_id,
            target_key(d),
            d,
            metric_key(item, version),
            Jsonb(
                {
                    "contract_version": CONTRACT_VERSION,
                    "item": item,
                    "status": "PENDING",
                }
            ),
        )
        for d in document_ids
        for item in ITEMS
    ]
    with conn.transaction(), conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO mart.score (run_id, target_type, target_key, document_id, metric_key, assessor_key,"
            " result_status, reason_code, normalization_status, score_payload, scored_at)"
            " VALUES (%s, 'DOCUMENT', %s, %s, %s, 'deterministic', 'PENDING', 'PLANNED', 'NOT_REQUESTED', %s, now())",
            rows,
        )
    return len(rows)


def update_judgments(
    conn, run_id: str, document_id: int, judgments: list[Judgment], version: str
) -> None:
    """문서 1건의 PENDING 행들을 판정으로 바꾼다. 바뀐 행 수가 판정 수와 다르면 ValueError."""
    rows = [
        (
            RESULT_STATUS[j.status],
            j.reason_code,
            {MET: 1, UNMET: 0}.get(j.status),
            Jsonb(payload(j)),
            run_id,
            target_key(document_id),
            metric_key(j.item, version),
            ASSESSOR,
        )
        for j in judgments
    ]
    with conn.cursor() as cur:
        cur.executemany(
            "UPDATE mart.score SET result_status = %s, reason_code = %s, raw_score = %s, score_payload = %s,"
            " scored_at = now() WHERE run_id = %s AND target_key = %s AND metric_key = %s AND assessor_key = %s"
            " AND result_status = 'PENDING'",
            rows,
        )
        if cur.rowcount != len(rows):
            raise ValueError(
                f"PENDING 행 수 불일치: 문서 {document_id} 판정 {len(rows)}건, 바뀐 행 {cur.rowcount}건"
            )


VERIFY_SQL = {
    "PENDING이 남음": "SELECT count(*) FROM mart.score WHERE run_id = %(run)s AND metric_key = ANY(%(keys)s) AND result_status = 'PENDING'",
    "OK 상태와 payload 판정 불일치": """
        SELECT count(*) FROM mart.score WHERE run_id = %(run)s AND metric_key = ANY(%(keys)s) AND NOT (
          (result_status = 'OK' AND ((score_payload->>'status' = 'MET' AND raw_score = 1)
                                  OR (score_payload->>'status' = 'UNMET' AND raw_score = 0)))
          OR (result_status <> 'OK' AND score_payload->>'status' IN ('NOT_APPLICABLE', 'UNDETERMINED', 'PENDING')
              AND raw_score IS NULL))""",
    "근거 절이 다른 문서이거나 범위 밖": """
        SELECT count(*) FROM mart.score sc, jsonb_array_elements(sc.score_payload->'evidence') e
        LEFT JOIN staging.section s ON s.section_id = (e->>'section_id')::bigint
        WHERE sc.run_id = %(run)s AND sc.metric_key = ANY(%(keys)s) AND (s.section_id IS NULL OR s.document_id <> sc.document_id
          OR (e->>'char_start')::int < s.char_start OR (e->>'char_end')::int > s.char_end
          OR (e->>'char_start')::int >= (e->>'char_end')::int)""",
    "검사한 절이 다른 문서": """
        SELECT count(*) FROM mart.score sc, jsonb_array_elements_text(sc.score_payload->'checked_section_ids') c
        LEFT JOIN staging.section s ON s.section_id = c::bigint
        WHERE sc.run_id = %(run)s AND sc.metric_key = ANY(%(keys)s) AND (s.section_id IS NULL OR s.document_id <> sc.document_id)""",
    "없음인데 검사한 절이 없음": """
        SELECT count(*) FROM mart.score WHERE run_id = %(run)s AND metric_key = ANY(%(keys)s) AND score_payload->>'status' = 'UNMET'
          AND jsonb_array_length(score_payload->'checked_section_ids') = 0""",
}


def verify_run(conn, run_id: str, documents: int) -> list[str]:
    """적재 검증. 위반 문장 목록(빈 목록이면 통과). 행 수 = 문서 수 x 항목 수."""
    errors = []
    keys = run_metric_keys(conn, run_id)
    (count,) = conn.execute(
        "SELECT count(*) FROM mart.score WHERE run_id = %s AND metric_key = ANY(%s)",
        (run_id, run_metric_keys(conn, run_id)),
    ).fetchone()
    if count != documents * len(ITEMS):
        errors.append(f"행 수 {count} != 문서 {documents} x 항목 {len(ITEMS)}")
    for message, sql in VERIFY_SQL.items():
        (n,) = conn.execute(sql, {"run": run_id, "keys": keys}).fetchone()
        if n:
            errors.append(f"{message}: {n}건")
    return errors


def status_counts(conn, run_id: str) -> dict[str, int]:
    """항목:판정 별 행 수. 예: {"3.1:MET": 480}."""
    rows = conn.execute(
        "SELECT score_payload->>'item' || ':' || (score_payload->>'status'), count(*) FROM mart.score"
        " WHERE run_id = %s AND metric_key = ANY(%s) GROUP BY 1 ORDER BY 1",
        (run_id, run_metric_keys(conn, run_id)),
    ).fetchall()
    return dict(rows)
