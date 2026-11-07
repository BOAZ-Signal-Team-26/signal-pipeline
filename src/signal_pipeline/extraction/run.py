"""LLM 필드 추출 실행. 문서마다 필드 4개를 Bedrock에 보내고 결과를 파일과 staging.llm_field_extraction에 남긴다.

사용: SIGNAL_LOCAL_DATABASE_URL=postgresql://... AWS_BEARER_TOKEN_BEDROCK=... \\
    uv run python -m signal_pipeline.extraction.run ../signal-data --model lite|pro \\
    [--limit N] [--document-ids FILE] [--workers 8] [--budget-usd X] [--parser-version V] [--dry-run]

- 시작 때 raw.pipeline_run 행(EXTRACT, RUNNING)과 runs/{run_id}/run.json을 만들고, 끝에 SUCCEEDED·FAILED로 닫는다
- 필드 1건 처리 순서(io-schema.md 「재사용한 결과」·「결측 표기」)
  1. 재사용 키 6개가 같은 이전 행(OK·UNDETERMINED·NOT_APPLICABLE, 없으면 EVIDENCE_NOT_LOCATED)의 response.json을
     이번 입력으로 다시 변환. FAILED가 아니면 호출 없이 재사용 행을 만든다
  2. 아니면 호출. FAILED면 한 번 더 호출(실행 안에서 attempt_no 1, 2)
  출처 절이 하나도 없으면 호출하지 않는다(빈 입력은 Bedrock이 거부함). 변환기가 SOURCE_SECTION_MISSING으로 정한다
- 문서의 필드가 모두 끝나면 중복 제거(dedupe_document)를 반영하고 필드마다 is_selected 1개를 정한다
  (마지막 비FAILED 시도, 없으면 마지막 시도)
- 호출마다 예상 비용을 먼저 잡아 두고(진행 중인 호출 포함) --budget-usd를 넘게 되면 새 호출을 멈추고 실행을 FAILED로 닫는다.
  호출이 끝나면 예상 비용을 실제 비용으로 바꾼다
- 선택된 필드 중 FAILED 비율이 FAIL_RATE_MAX를 넘거나 성공한 필드가 없으면 실행을 FAILED로 닫는다
- DB 쓰기는 연결 하나를 잠금으로 나눠 쓴다. CLI는 autocommit이라 중간에 멈춰도 끝난 행은 남는다
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from itertools import groupby
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg

from signal_pipeline.common.runlog import RunLog
from signal_pipeline.extraction.bedrock import (
    MODELS,
    REGION,
    BedrockClient,
    cost_usd,
    response_text,
)
from signal_pipeline.extraction.convert import convert, dedupe_document, result_status
from signal_pipeline.extraction.inputs import FieldInput, build_field_inputs
from signal_pipeline.extraction.store import (
    Prompt,
    canonical,
    find_prior,
    insert_attempt,
    install_prompts,
    select_attempt,
    update_envelope,
    write_new,
    write_request,
    write_response,
)
from signal_pipeline.loading.local_load import SEARCH_PATH
from signal_pipeline.parsing.extract import parser_version as current_parser_version

MAX_ATTEMPTS = 2  # 실행 안에서 필드당 호출 상한(첫 호출 + FAILED 재호출 1회)
# 선택된 필드 중 FAILED 비율이 이 값을 넘으면 실행 FAILED(11월 7일 PM 결정)
FAIL_RATE_MAX = 0.2
EST_TOKENS_PER_CHAR = 1.0  # 예상 입력 토큰 = 글자 수 x 이 값. 한국어는 글자당 1토큰 미만이라 넉넉히 잡는 쪽
DB_ENV = "SIGNAL_LOCAL_DATABASE_URL"
KST = ZoneInfo("Asia/Seoul")
NO_INPUT = json.dumps(
    {
        "status": "NOT_FOUND",
        "value": None,
        "evidence": [],
        "reason_code": "NOT_IN_DOCUMENT",
        "notes": "입력 절 없음, 호출 생략",
    }
)


@dataclass
class Context:
    conn: psycopg.Connection
    data_root: Path
    run_id: str
    client: BedrockClient
    prompts: dict[str, Prompt]
    budget_usd: float | None
    lock: threading.Lock = field(default_factory=threading.Lock)
    stats: Counter = field(default_factory=Counter)
    cost: float = 0.0
    reserved: float = 0.0  # 진행 중인 호출의 예상 비용 합
    stop_reason: str | None = None

    def reserve(self, system: str, text: str) -> float | None:
        """호출 1건의 예상 비용을 잡아 두고 돌려준다. 상한을 넘게 되면 None.

        예상 = (프롬프트 + 입력 글자 수) x EST_TOKENS_PER_CHAR 입력 토큰 + maxTokens 출력 토큰
        """
        estimate = cost_usd(
            self.client.model,
            int((len(system) + len(text)) * EST_TOKENS_PER_CHAR),
            self.client.params["maxTokens"],
        )
        with self.lock:
            if (
                self.budget_usd is not None
                and self.cost + self.reserved + estimate > self.budget_usd
            ):
                self.stop_reason = f"budget {self.budget_usd} USD 도달(누적 {self.cost:.4f}, 진행 중 예상 {self.reserved:.4f})"
                return None
            self.reserved += estimate
            self.stats["calls"] += 1
            return estimate

    def charge(
        self, estimate: float, input_tokens: int | None, output_tokens: int | None
    ) -> None:
        """잡아 둔 예상 비용을 실제 비용으로 바꾼다."""
        with self.lock:
            self.stats["input_tokens"] += input_tokens or 0
            self.stats["output_tokens"] += output_tokens or 0
            self.reserved -= estimate
            self.cost += cost_usd(
                self.client.model, input_tokens or 0, output_tokens or 0
            )
            if self.budget_usd is not None and self.cost > self.budget_usd:
                self.stop_reason = (
                    f"budget {self.budget_usd} USD 초과(누적 {self.cost:.4f})"
                )


def _insert(
    ctx: Context, fi: FieldInput, n: int, envelope: dict, **cols
) -> tuple[int, dict]:
    with ctx.lock:
        eid = insert_attempt(
            ctx.conn,
            ctx.run_id,
            fi,
            n,
            ctx.prompts[fi.field_name],
            ctx.client.model,
            ctx.client.params,
            envelope,
            **cols,
        )
    return eid, envelope


def _reuse(ctx: Context, fi: FieldInput) -> tuple[int, dict] | None:
    prompt = ctx.prompts[fi.field_name]
    with ctx.lock:
        prior = find_prior(ctx.conn, fi, prompt, ctx.client.model, ctx.client.params)
    if prior is None:
        return None
    raw = (ctx.data_root / prior["raw_response_path"]).read_bytes()
    envelope = convert(fi, response_text(raw))
    if result_status(envelope) == "FAILED":  # 이번 입력으로는 변환 실패 → 재호출
        return None
    reused_from = {"run_id": prior["run_id"], "extraction_id": prior["extraction_id"]}
    write_request(
        ctx.data_root,
        ctx.run_id,
        fi,
        1,
        prompt,
        ctx.client.model,
        ctx.client.params,
        reused_from,
    )
    ctx.stats["reused"] += 1
    return _insert(
        ctx,
        fi,
        1,
        envelope,
        raw_response_path=prior["raw_response_path"],
        response_sha256=prior["response_sha256"],
        input_tokens=None,
        output_tokens=None,
    )


def process_field(ctx: Context, fi: FieldInput) -> list[tuple[int, dict]]:
    """필드 1건의 시도들 [(extraction_id, envelope)]. 상한에 걸려 아무것도 못 했으면 빈 목록."""
    prompt = ctx.prompts[fi.field_name]
    model, params = ctx.client.model, ctx.client.params
    if not fi.sections:
        write_request(ctx.data_root, ctx.run_id, fi, 1, prompt, model, params)
        ctx.stats["no_input"] += 1
        none = {
            "raw_response_path": None,
            "response_sha256": None,
            "input_tokens": None,
            "output_tokens": None,
        }
        return [_insert(ctx, fi, 1, convert(fi, NO_INPUT), **none)]
    reused = _reuse(ctx, fi)
    if reused:
        return [reused]
    attempts: list[tuple[int, dict]] = []
    for n in range(1, MAX_ATTEMPTS + 1):
        estimate = ctx.reserve(prompt.text, fi.input_text)
        if estimate is None:
            break
        write_request(ctx.data_root, ctx.run_id, fi, n, prompt, model, params)
        result = ctx.client.converse(prompt.text, fi.input_text)
        ctx.charge(estimate, result.input_tokens, result.output_tokens)
        path = sha = None
        if result.raw is not None:
            path, sha = write_response(ctx.data_root, ctx.run_id, fi, n, result.raw)
        envelope = convert(fi, result.text, call_error=result.error)
        attempts.append(
            _insert(
                ctx,
                fi,
                n,
                envelope,
                raw_response_path=path,
                response_sha256=sha,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )
        )
        if result_status(envelope) != "FAILED":
            break
    return attempts


def _selected(attempts: list[tuple[int, dict]]) -> tuple[int, dict]:
    ok = [a for a in attempts if result_status(a[1]) != "FAILED"]
    return (ok or attempts)[-1]


def process_document(ctx: Context, fis: list[FieldInput]) -> None:
    chosen: dict[str, tuple[int, dict]] = {}
    for fi in fis:
        attempts = process_field(ctx, fi)
        if attempts:
            chosen[fi.field_name] = _selected(attempts)
    envelopes = {name: env for name, (_, env) in chosen.items()}
    key_risk = next((fi for fi in fis if fi.field_name == "key_risk_phrases"), None)
    deduped = dedupe_document(envelopes, key_risk)
    with ctx.lock:
        for name, (eid, env) in chosen.items():
            if deduped[name] != env:
                update_envelope(ctx.conn, eid, deduped[name])
            select_attempt(ctx.conn, eid)


def _by_document(fis: list[FieldInput]) -> list[list[FieldInput]]:
    return [list(g) for _, g in groupby(fis, key=lambda fi: fi.document_id)]


def _status_counts(conn, run_id: str) -> dict[str, int]:
    rows = conn.execute(
        "SELECT field_name || ':' || coalesce(value_json->>'status', result_status), count(*)"
        " FROM llm_field_extraction WHERE run_id = %s AND is_selected GROUP BY 1 ORDER BY 1",
        (run_id,),
    ).fetchall()
    return dict(rows)


def _fail_reason(conn, run_id: str) -> tuple[int, str | None]:
    """(선택된 FAILED 행 수, 실행을 FAILED로 닫을 사유 또는 None)."""
    selected, failed = conn.execute(
        "SELECT count(*), count(*) FILTER (WHERE result_status = 'FAILED')"
        " FROM llm_field_extraction WHERE run_id = %s AND is_selected",
        (run_id,),
    ).fetchone()
    rate = failed / selected if selected else 0.0
    if rate > FAIL_RATE_MAX or selected == failed:
        return failed, f"필드 실패율 {rate:.0%}({failed}/{selected})"
    return failed, None


def run_extraction(
    conn: psycopg.Connection,
    data_root: Path,
    client: BedrockClient,
    *,
    parser_version: str,
    document_ids: list[int] | None = None,
    limit: int | None = None,
    workers: int = 8,
    budget_usd: float | None = None,
) -> dict:
    """실행 1회. 요약 dict(run_id, status, reason, calls, reused, 토큰, cost_usd, status_counts)."""
    data_root = Path(data_root)
    fis, exclusions = build_field_inputs(conn, document_ids, parser_version)
    docs = _by_document(fis)[:limit]
    prompts = install_prompts(data_root)
    config = {
        "data_root": str(data_root.resolve()),
        "model": client.model,
        "model_params": client.params,
        "region": REGION,
        "parser_version": parser_version,
        "prompts": {
            n: {"prompt_id": p.prompt_id, "path": p.path, "sha256": p.sha256}
            for n, p in prompts.items()
        },
        "document_ids": document_ids,
        "limit": limit,
        "budget_usd": budget_usd,
    }
    log = RunLog(
        data_root, datetime.now(KST).date().isoformat(), config, run_kind="EXTRACT"
    )
    run = log.run
    with conn.transaction():
        conn.execute(
            "INSERT INTO pipeline_run (run_id, run_kind, baseline_date, status, config_manifest, config_sha256, started_at)"
            " VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)",
            (
                run["run_id"],
                "EXTRACT",
                run["baseline_date"],
                "RUNNING",
                run["config_manifest"],
                run["config_sha256"],
                run["started_at"],
            ),
        )
    write_new(
        log.dir / "llm" / "excluded_etf.json",
        json.dumps(exclusions, ensure_ascii=False, indent=1).encode("utf-8"),
    )
    ctx = Context(conn, data_root, log.run_id, client, prompts, budget_usd)
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for future in [pool.submit(process_document, ctx, doc) for doc in docs]:
            try:
                future.result()
            except Exception as error:  # noqa: BLE001 — 문서 하나가 실패해도 나머지는 끝까지 돌리고 실행을 FAILED로 닫는다
                errors.append(f"{type(error).__name__}: {error}")
    failed, fail_reason = _fail_reason(conn, log.run_id)
    reason = ctx.stop_reason or (errors[0] if errors else None) or fail_reason
    status = "FAILED" if reason else "SUCCEEDED"
    summary = {
        "run_id": log.run_id,
        "status": status,
        "reason": reason,
        "documents": len(docs),
        "calls": ctx.stats["calls"],
        "reused": ctx.stats["reused"],
        "no_input": ctx.stats["no_input"],
        "input_tokens": ctx.stats["input_tokens"],
        "output_tokens": ctx.stats["output_tokens"],
        "cost_usd": round(ctx.cost, 6),
        "errors": len(errors),
        "failed": failed,
        "excluded_etf": len(exclusions),
        "status_counts": _status_counts(conn, log.run_id),
    }
    with conn.transaction():
        conn.execute(
            "UPDATE pipeline_run SET status = %s, completed_at = now() WHERE run_id = %s",
            (status, log.run_id),
        )
    log.finish(status, summary)
    return summary


def _read_ids(path: str) -> list[int]:
    return [
        int(line)
        for line in Path(path).read_text(encoding="utf-8").split()
        if line.strip()
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("data_root", type=Path)
    ap.add_argument("--model", choices=sorted(MODELS), required=True)
    ap.add_argument("--limit", type=int, help="앞에서부터 문서 N건")
    ap.add_argument("--document-ids", help="document_id 목록 파일(줄마다 1개)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--budget-usd", type=float)
    ap.add_argument(
        "--parser-version",
        default=current_parser_version(),
        help="입력 절의 파서 버전(기본: 추출기와 같은 값)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="입력만 조립해 건수를 보이고 호출·기록하지 않음",
    )
    args = ap.parse_args()

    url = os.environ.get(DB_ENV)
    if not url:
        print(f"{DB_ENV} 환경 변수가 필요하다", file=sys.stderr)
        return 2
    ids = _read_ids(args.document_ids) if args.document_ids else None
    with psycopg.connect(
        url, options=f"-c search_path={SEARCH_PATH}", autocommit=True
    ) as conn:
        if args.dry_run:
            fis, exclusions = build_field_inputs(conn, ids, args.parser_version)
            docs = _by_document(fis)[: args.limit]
            chosen = [fi for doc in docs for fi in doc]
            print(
                canonical(
                    {
                        "documents": len(docs),
                        "field_inputs": len(chosen),
                        "no_input": sum(not fi.sections for fi in chosen),
                        "input_chars": sum(len(fi.input_text) for fi in chosen),
                        "excluded_etf": len(exclusions),
                    }
                )
            )
            return 0
        client = BedrockClient(MODELS[args.model])
        try:
            summary = run_extraction(
                conn,
                args.data_root,
                client,
                parser_version=args.parser_version,
                document_ids=ids,
                limit=args.limit,
                workers=args.workers,
                budget_usd=args.budget_usd,
            )
        finally:
            client.close()
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if summary["status"] == "SUCCEEDED" else 1


if __name__ == "__main__":
    sys.exit(main())
