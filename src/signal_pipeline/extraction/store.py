"""LLM 호출 저장: 프롬프트 자산, 시도별 request.json·response.json, staging.llm_field_extraction 행, 적재 검증.

규칙(storage-and-failure-rules.md 「LLM 호출 저장」·「실행 폴더 불변」·assets/, io-schema.md 「입력 참조」·「재사용한 결과」)
- 프롬프트: assets/prompts/{필드}__v1__{sha256 앞 12자}.md. 이미 있으면 해시가 같을 때만 재사용
- 시도 폴더: runs/{run_id}/llm/{document_id}/{field_name}/attempt-{n}/. 파일은 새로 만들기만 하고 덮어쓰지 않음
- model_params는 키 정렬·한 줄 JSON(canonical)으로 비교한다. DB 칼럼은 jsonb라 같은 값이면 같다
- 재사용 키 6개: document_id, field_name, input_sha256, prompt_sha256, model_name, model_params
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from signal_pipeline.extraction.convert import result_status, selected_evidence
from signal_pipeline.extraction.inputs import FIELDS, FieldInput, sha256_text

PROMPT_VERSION = 1
REUSABLE = ("OK", "UNDETERMINED", "NOT_APPLICABLE")
RECONVERT = "EVIDENCE_NOT_LOCATED"


@dataclass(frozen=True)
class Prompt:
    field_name: str
    prompt_id: str
    sha256: str
    path: str  # data_root 기준 상대경로
    text: str


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_new(path: Path, data: bytes) -> None:
    """새 파일만 쓴다. 있으면 FileExistsError(실행 폴더·assets 불변)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)


def install_prompts(data_root: Path) -> dict[str, Prompt]:
    """프롬프트 템플릿 4개를 assets/prompts/에 복사하고 필드별 식별 정보를 돌려준다."""
    out: dict[str, Prompt] = {}
    for name in FIELDS:
        data = (
            resources.files("signal_pipeline.extraction") / "prompts" / f"{name}.md"
        ).read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        rel = f"assets/prompts/{name}__v{PROMPT_VERSION}__{sha[:12]}.md"
        target = Path(data_root) / rel
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != sha:
                raise ValueError(f"자산 해시 불일치: {rel}")
        else:
            write_new(target, data)
        out[name] = Prompt(
            name, f"{name}:v{PROMPT_VERSION}", sha, rel, data.decode("utf-8")
        )
    return out


def attempt_dir(run_id: str, fi: FieldInput, attempt_no: int) -> str:
    return f"runs/{run_id}/llm/{fi.document_id}/{fi.field_name}/attempt-{attempt_no}"


def write_request(
    data_root: Path,
    run_id: str,
    fi: FieldInput,
    attempt_no: int,
    prompt: Prompt,
    model: str,
    params: dict,
    reused_from: dict | None = None,
) -> None:
    request = {
        "document_id": fi.document_id,
        "field_name": fi.field_name,
        "attempt_no": attempt_no,
        "prompt_id": prompt.prompt_id,
        "prompt_sha256": prompt.sha256,
        "model_name": model,
        "model_params": params,
        "inputs": list(fi.inputs),
        "input_text": fi.input_text,
        "input_sha256": fi.input_sha256,
    }
    if reused_from:
        request["reused_from"] = reused_from
    path = Path(data_root) / attempt_dir(run_id, fi, attempt_no) / "request.json"
    write_new(path, json.dumps(request, ensure_ascii=False, indent=1).encode("utf-8"))


def write_response(
    data_root: Path, run_id: str, fi: FieldInput, attempt_no: int, raw: bytes
) -> tuple[str, str]:
    """원응답 바이트 그대로 저장. (상대경로, sha256)."""
    rel = f"{attempt_dir(run_id, fi, attempt_no)}/response.json"
    write_new(Path(data_root) / rel, raw)
    return rel, hashlib.sha256(raw).hexdigest()


PRIOR_SQL = """
SELECT extraction_id, run_id, result_status, raw_response_path, response_sha256
FROM llm_field_extraction
WHERE document_id = %(document_id)s AND field_name = %(field_name)s AND input_sha256 = %(input_sha256)s
  AND prompt_sha256 = %(prompt_sha256)s AND model_name = %(model_name)s AND model_params = %(model_params)s::jsonb
  AND raw_response_path IS NOT NULL
  AND (result_status = ANY(%(reusable)s) OR (result_status = 'FAILED' AND error_reason = %(reconvert)s))
ORDER BY (result_status <> 'FAILED') DESC, extraction_id DESC
LIMIT 1
"""


def find_prior(
    conn, fi: FieldInput, prompt: Prompt, model: str, params: dict
) -> dict | None:
    """재사용 후보: 키 6개가 같고 OK·UNDETERMINED·NOT_APPLICABLE인 이전 행. 없으면 EVIDENCE_NOT_LOCATED 행(재변환 대상)."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            PRIOR_SQL,
            {
                "document_id": fi.document_id,
                "field_name": fi.field_name,
                "input_sha256": fi.input_sha256,
                "prompt_sha256": prompt.sha256,
                "model_name": model,
                "model_params": canonical(params),
                "reusable": list(REUSABLE),
                "reconvert": RECONVERT,
            },
        ).fetchone()


INSERT_SQL = """
INSERT INTO llm_field_extraction (run_id, document_id, raw_object_id, field_name, attempt_no, model_name,
  prompt_sha256, input_sha256, input_tokens, output_tokens, result_status, value_json, evidence_section_id,
  evidence_char_start, evidence_char_end, model_params, raw_response_path, response_sha256, error_reason, extracted_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, now())
RETURNING extraction_id
"""


def _status_columns(envelope: dict) -> tuple:
    status = result_status(envelope)
    error = envelope["reason_code"] if status == "FAILED" else None
    return (status, Jsonb(envelope), *selected_evidence(envelope)), error


def insert_attempt(
    conn,
    run_id: str,
    fi: FieldInput,
    attempt_no: int,
    prompt: Prompt,
    model: str,
    params: dict,
    envelope: dict,
    *,
    raw_response_path: str | None,
    response_sha256: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
) -> int:
    cols, error = _status_columns(envelope)
    return conn.execute(
        INSERT_SQL,
        (
            run_id,
            fi.document_id,
            fi.raw_object_id,
            fi.field_name,
            attempt_no,
            model,
            prompt.sha256,
            fi.input_sha256,
            input_tokens,
            output_tokens,
            *cols,
            canonical(params),
            raw_response_path,
            response_sha256,
            error,
        ),
    ).fetchone()[0]


def update_envelope(conn, extraction_id: int, envelope: dict) -> None:
    """문서 단위 중복 제거 결과를 반영한다(value_json·상태·근거 칼럼)."""
    cols, error = _status_columns(envelope)
    conn.execute(
        "UPDATE llm_field_extraction SET result_status = %s, value_json = %s, evidence_section_id = %s,"
        " evidence_char_start = %s, evidence_char_end = %s, error_reason = %s WHERE extraction_id = %s",
        (*cols, error, extraction_id),
    )


def select_attempt(conn, extraction_id: int) -> None:
    conn.execute(
        "UPDATE llm_field_extraction SET is_selected = true WHERE extraction_id = %s",
        (extraction_id,),
    )


CHECK_SELECTED_SQL = """
SELECT document_id, field_name, count(*) FILTER (WHERE is_selected) AS selected
FROM llm_field_extraction WHERE run_id = %s
GROUP BY document_id, field_name HAVING count(*) FILTER (WHERE is_selected) <> 1
ORDER BY document_id, field_name
"""


def check_selected(conn, run_id: str) -> list[dict]:
    """(run_id, document_id, field_name)마다 is_selected가 정확히 1개인지. 어긋난 묶음만 돌려준다."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(CHECK_SELECTED_SQL, (run_id,)).fetchall()


def verify_run(conn, data_root: Path, run_id: str) -> list[str]:
    """적재 검증. 위반 문장 목록(빈 목록이면 통과).

    - request.json의 input_text sha256 = input_sha256 칼럼
    - evidence_* 칼럼 = value_json.evidence[0]
    - FAILED 행은 error_reason이 있음
    - response.json 바이트 sha256 = response_sha256
    - inputs의 원본 파일이 같은 document_id 소속
    - is_selected가 묶음마다 1개
    """
    root = Path(data_root)
    errors: list[str] = []
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            "SELECT * FROM llm_field_extraction WHERE run_id = %s ORDER BY extraction_id",
            (run_id,),
        ).fetchall()
        for row in rows:
            where = (
                f"{row['document_id']}/{row['field_name']}/attempt-{row['attempt_no']}"
            )
            request_path = root / f"runs/{run_id}/llm/{where}/request.json"
            request = json.loads(request_path.read_text(encoding="utf-8"))
            if (
                sha256_text(request["input_text"]) != row["input_sha256"]
                or request["input_sha256"] != row["input_sha256"]
            ):
                errors.append(f"{where}: input_sha256 불일치")
            evidence = (row["value_json"] or {}).get("evidence") or [{}]
            first = tuple(
                evidence[0].get(k) for k in ("section_id", "char_start", "char_end")
            )
            if first != (
                row["evidence_section_id"],
                row["evidence_char_start"],
                row["evidence_char_end"],
            ):
                errors.append(f"{where}: 근거 칼럼 ≠ value_json.evidence[0]")
            if row["result_status"] == "FAILED" and not row["error_reason"]:
                errors.append(f"{where}: FAILED인데 error_reason 없음")
            if row["raw_response_path"]:
                raw = (root / row["raw_response_path"]).read_bytes()
                if hashlib.sha256(raw).hexdigest() != row["response_sha256"]:
                    errors.append(f"{where}: response_sha256 불일치")
            raw_ids = [e["raw_object_id"] for e in request["inputs"]]
            if raw_ids:
                foreign = cur.execute(
                    "SELECT raw_object_id FROM raw_object WHERE raw_object_id = ANY(%s)"
                    " AND document_id IS DISTINCT FROM %s",
                    (raw_ids, row["document_id"]),
                ).fetchall()
                if foreign:
                    errors.append(
                        f"{where}: 다른 문서의 원본 {[f['raw_object_id'] for f in foreign]}"
                    )
    errors += [
        f"{v['document_id']}/{v['field_name']}: is_selected {v['selected']}개"
        for v in check_selected(conn, run_id)
    ]
    return errors
