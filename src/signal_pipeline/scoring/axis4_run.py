"""축 4(고지 충실도) 점검표 판정 실행. 문서마다 10항목을 판정해 mart.score에 남기고 CSV를 만든다.

사용: DATABASE_URL=postgresql://... RAW_ROOT=../signal-data \\
    uv run python -m signal_pipeline.scoring.axis4_run [data_root] --llm-run-id ID \\
    [--parser-version V] [--document-ids FILE] [--limit N] [--dry-run]
data_root를 생략하면 RAW_ROOT를 쓴다. 종료 코드: 0 성공, 1 실행이 FAILED, 2 입력·설정 오류

- 시작 때 raw.pipeline_run 행(SCORE, RUNNING, upstream_run_id = LLM 추출 실행)과 runs/{run_id}/run.json을 만들고
  끝에 SUCCEEDED·FAILED로 닫는다. 예외면 FAILED로 닫은 뒤 다시 올린다
- LLM 추출 실행은 EXTRACT이면서 SUCCEEDED여야 한다
- 대상 = 투자설명서 전체(runs/{run_id}/selection.json). 계획 슬롯(문서 x 항목)은 input_manifest.jsonl과 PENDING 행으로 남긴다
- 적재 검증(axis4_store.verify_run)을 통과해야 SUCCEEDED. --dry-run은 DB·파일에 쓰지 않고 항목별 판정 분포만 출력한다
- 입력 절의 파서 버전은 LLM 추출 실행의 config_manifest 값이다. --parser-version이 다르면 거부한다
- 실행 산출 파일은 runs/{run_id}/axis4/ 아래에 둔다

SCORE DAG 편입 때 바꿀 것(이번에는 하지 않음)
- RUN_ID 환경 변수로 기존 실행을 열고 pipeline_run INSERT·UPDATE를 건너뛰기. --llm-run-id 기본값을 자기 SCORE 실행의 upstream으로
- S3 직접 읽기·쓰기 대신 로컬 작업 폴더를 쓰고 DAG 마감 작업이 올리는 방식(architecture.md 2-4) 유지
- 문서 200건 단위 분할 처리
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg

from signal_pipeline.common.runlog import RunLog
from signal_pipeline.common.storage import write_new
from signal_pipeline.extraction.store import canonical
from signal_pipeline.loading.local_load import SEARCH_PATH
from signal_pipeline.scoring import axis4_store as store
from signal_pipeline.scoring.axis4_export import export_csv
from signal_pipeline.scoring.axis4_inputs import build_doc_inputs
from signal_pipeline.scoring.axis4_rules import ITEMS, judge_document, validate_keywords

DB_ENV = "DATABASE_URL"
ROOT_ENV = "RAW_ROOT"
KST = ZoneInfo("Asia/Seoul")
ARTIFACT_DIR = "axis4"  # runs/{run_id}/axis4/. SCORE DAG의 같은 실행에서 다른 작업 파일과 이름이 겹치지 않게 한다


def resolve_parser_version(conn, llm_run_id: str, explicit: str | None) -> str:
    """LLM 추출 실행이 EXTRACT/SUCCEEDED인지 보고, 그 실행이 쓴 파서 버전을 돌려준다. 명시값이 다르면 ValueError."""
    row = conn.execute(
        "SELECT run_kind, status, config_manifest->>'parser_version' FROM pipeline_run WHERE run_id = %s",
        (llm_run_id,),
    ).fetchone()
    if row is None or row[:2] != ("EXTRACT", "SUCCEEDED"):
        raise ValueError(
            f"LLM 추출 실행이 EXTRACT/SUCCEEDED가 아님: {llm_run_id} {row and row[:2]}"
        )
    used = row[2]
    if not used:
        raise ValueError(f"LLM 추출 실행에 parser_version 기록이 없음: {llm_run_id}")
    if explicit and explicit != used:
        raise ValueError(
            f"--parser-version {explicit}이 LLM 추출 실행의 {used}와 다름: {llm_run_id}"
        )
    return used


def _error_tag(error: BaseException) -> str:
    """실행 기록에 남길 오류 설명. 메시지 원문(DB 호스트·사용자 이름이 들어갈 수 있음) 대신 타입과 SQLSTATE만."""
    sqlstate = getattr(error, "sqlstate", None)
    return f"{type(error).__name__}" + (f" SQLSTATE {sqlstate}" if sqlstate else "")


def _judge_all(docs, keywords) -> list[tuple[int, list]]:
    return [(d.document_id, judge_document(d, keywords)) for d in docs]


def dry_run(conn, llm_run_id: str, parser_version: str | None, ids, limit) -> dict:
    """저장 없이 판정 분포만. {"documents": N, "status_counts": {"3.1:MET": n, ...}}."""
    parser_version = resolve_parser_version(conn, llm_run_id, parser_version)
    keywords = validate_keywords(json.loads(store.read_asset().decode("utf-8")))
    _, docs = build_doc_inputs(conn, llm_run_id, parser_version, ids, limit)
    counts = Counter(
        f"{j.item}:{j.status}" for _, js in _judge_all(docs, keywords) for j in js
    )
    return {"documents": len(docs), "status_counts": dict(sorted(counts.items()))}


def run_axis4(
    conn: psycopg.Connection,
    data_root: Path,
    llm_run_id: str,
    *,
    parser_version: str | None = None,
    document_ids: list[int] | None = None,
    limit: int | None = None,
) -> dict:
    """실행 1회. 요약 dict(run_id, status, reason, documents, rows, violations, csv, status_counts)."""
    data_root = Path(data_root)
    parser_version = resolve_parser_version(conn, llm_run_id, parser_version)
    asset = store.install_keywords(data_root)
    store.register_metrics(conn, asset)
    docs, inputs = build_doc_inputs(
        conn, llm_run_id, parser_version, document_ids, limit
    )
    config = {
        "purpose": "development",
        "parser_version": parser_version,
        "llm_run_id": llm_run_id,
        "selection_policy_version": store.SELECTION_POLICY,
        "rule_version": store.RULE_VERSION,
        "keyword_asset": {
            "path": asset.path,
            "sha256": asset.sha256,
            "version": asset.version,
        },
        "document_ids": document_ids,
        "limit": limit,
    }
    log = RunLog(
        data_root, datetime.now(KST).date().isoformat(), config, run_kind="SCORE"
    )
    run = log.run
    run["upstream_run_id"] = llm_run_id
    log._write_run()
    try:
        with conn.transaction():
            conn.execute(
                "INSERT INTO pipeline_run (run_id, run_kind, upstream_run_id, baseline_date, status, config_manifest,"
                " config_sha256, started_at) VALUES (%s, 'SCORE', %s, %s, 'RUNNING', %s::jsonb, %s, %s)",
                (
                    run["run_id"],
                    llm_run_id,
                    run["baseline_date"],
                    run["config_manifest"],
                    run["config_sha256"],
                    run["started_at"],
                ),
            )
        ids = [d["document_id"] for d in docs]
        selection = write_new_json(
            log.dir / ARTIFACT_DIR / "selection.json",
            {
                "selection_policy_version": store.SELECTION_POLICY,
                "documents": [
                    {k: d[k] for k in ("document_id", "rcept_no", "source_doc_key")}
                    for d in docs
                ],
            },
        )
        slots = "".join(
            json.dumps(
                {
                    "document_id": d,
                    "target_key": store.target_key(d),
                    "metric_key": store.metric_key(i, asset.version),
                    "assessor_key": store.ASSESSOR,
                },
                ensure_ascii=False,
            )
            + "\n"
            for d in ids
            for i in ITEMS
        ).encode("utf-8")
        write_new(log.dir / ARTIFACT_DIR / "input_manifest.jsonl", slots)
        store.insert_pending(conn, log.run_id, ids, asset.version)
        with conn.transaction():
            for document_id, judgments in _judge_all(inputs, asset.data):
                store.update_judgments(
                    conn, log.run_id, document_id, judgments, asset.version
                )
        violations = store.verify_run(conn, log.run_id, len(ids))
        csv_path = export_csv(conn, data_root, log.run_id)
        reason = (
            f"적재 검증 위반 {len(violations)}건: {violations[0]}"
            if violations
            else None
        )
        status = "FAILED" if reason else "SUCCEEDED"
        summary = {
            "run_id": log.run_id,
            "status": status,
            "reason": reason,
            "documents": len(ids),
            "rows": len(ids) * len(ITEMS),
            "violations": len(violations),
            "csv": str(csv_path.relative_to(data_root)),
            "status_counts": store.status_counts(conn, log.run_id),
        }
        _close(conn, log, data_root, status, summary, selection=selection)
    except BaseException as error:
        _close_failed(conn, log, data_root, error)
        raise
    return summary


def _close_failed(conn, log: RunLog, data_root: Path, error: BaseException) -> None:
    """FAILED 마감. DB 마감이 실패해도 run.json은 따로 FAILED로 닫는다. 마감 실패가 원래 예외를 가리지 않게 한다."""
    summary = {"stopped_by": _error_tag(error)}
    try:
        _close(conn, log, data_root, "FAILED", summary)
        return
    except Exception as close_error:  # noqa: BLE001
        print(
            f"경고: 실행 {log.run_id}의 DB 기록을 FAILED로 마감하지 못함({_error_tag(close_error)})",
            file=sys.stderr,
        )
    try:
        log.finish("FAILED", summary)
    except Exception as close_error:  # noqa: BLE001
        print(
            f"경고: 실행 {log.run_id}의 run.json을 FAILED로 마감하지 못함({_error_tag(close_error)})",
            file=sys.stderr,
        )


def write_new_json(path: Path, value: object) -> Path:
    write_new(path, json.dumps(value, ensure_ascii=False, indent=1).encode("utf-8"))
    return path


def _digest(path: Path, data_root: Path) -> tuple[str, str]:
    return str(path.relative_to(data_root)), hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def _close(
    conn,
    log: RunLog,
    data_root: Path,
    status: str,
    summary: dict,
    selection: Path | None = None,
) -> None:
    """pipeline_run과 run.json을 닫는다. 입력(계획 슬롯)·선택 manifest의 경로와 해시를 함께 적는다."""
    manifest = log.dir / ARTIFACT_DIR / "input_manifest.jsonl"
    cols: dict[str, str | None] = {
        "input_manifest_path": None,
        "input_manifest_sha256": None,
        "selection_manifest_path": None,
        "selection_manifest_sha256": None,
    }
    if manifest.exists():
        cols["input_manifest_path"], cols["input_manifest_sha256"] = _digest(
            manifest, data_root
        )
    if selection is not None:
        cols["selection_manifest_path"], cols["selection_manifest_sha256"] = _digest(
            selection, data_root
        )
    with conn.transaction():
        conn.execute(
            "UPDATE pipeline_run SET status = %s, completed_at = now(), input_manifest_path = %s,"
            " input_manifest_sha256 = %s, selection_manifest_path = %s, selection_manifest_sha256 = %s"
            " WHERE run_id = %s AND status = 'RUNNING'",
            (status, *cols.values(), log.run_id),
        )
    log.finish(status, summary)
    # RunLog에 입력 manifest를 지정하는 공개 방법이 없다(finish가 raw_objects.jsonl로 고정). 기존 모듈을 안 건드리려고 private을 씀
    log.run.update(cols)
    log._write_run()


def _read_ids(path: str) -> list[int]:
    return [int(x) for x in Path(path).read_text(encoding="utf-8").split() if x.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "data_root", type=Path, nargs="?", help=f"데이터 루트(기본: {ROOT_ENV})"
    )
    ap.add_argument("--llm-run-id", required=True, help="입력 LLM 추출 실행 run_id")
    ap.add_argument("--limit", type=int, help="앞에서부터 문서 N건")
    ap.add_argument("--document-ids", help="document_id 목록 파일(줄마다 1개)")
    ap.add_argument(
        "--parser-version",
        help="입력 절의 파서 버전(기본: LLM 추출 실행이 쓴 값. 다르면 거부)",
    )
    ap.add_argument("--dry-run", action="store_true", help="저장 없이 판정 분포만 출력")
    args = ap.parse_args()
    if args.data_root is None:
        if not os.environ.get(ROOT_ENV):
            ap.error(f"data_root 인자나 {ROOT_ENV} 환경 변수가 필요하다")
        args.data_root = Path(os.environ[ROOT_ENV])
    url = os.environ.get(DB_ENV)
    if not url:
        print(f"{DB_ENV} 환경 변수가 필요하다", file=sys.stderr)
        return 2
    ids = _read_ids(args.document_ids) if args.document_ids else None
    try:
        with psycopg.connect(
            url, options=f"-c search_path={SEARCH_PATH}", autocommit=True
        ) as conn:
            if args.dry_run:
                print(
                    canonical(
                        dry_run(
                            conn, args.llm_run_id, args.parser_version, ids, args.limit
                        )
                    )
                )
                return 0
            summary = run_axis4(
                conn,
                args.data_root,
                args.llm_run_id,
                parser_version=args.parser_version,
                document_ids=ids,
                limit=args.limit,
            )
    except ValueError as error:
        print(f"입력 오류: {error}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if summary["status"] == "SUCCEEDED" else 1


if __name__ == "__main__":
    sys.exit(main())
