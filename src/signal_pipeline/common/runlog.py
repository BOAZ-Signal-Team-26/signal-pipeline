"""실행 기록. DB 가동 전이라 ERD의 실행·요청 표를 파일로 남긴다.

{RAW_ROOT}/runs/{run_id}/
- run.json          ERD pipeline_run 칼럼
- attempts.jsonl    ERD collection_attempt. 요청 시도 1번 = 1줄
- raw_objects.jsonl 이번 실행이 만들거나 다시 쓴 원본 목록. 실행 종료 시 input_manifest가 된다

DB가 없어 정수 ID를 쓸 수 없는 칸은 다음 값으로 대신한다. DB 적재 때 이 값으로 ID를 찾아 붙인다.
- document_id   → document_key (DART는 접수번호. 문서 유일키 (source, source_doc_key)와 같은 값)
- raw_object_id → storage_path (RAW_ROOT 기준 상대경로)
"""

from __future__ import annotations

import hashlib
import json
import secrets
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from signal_pipeline.common.http import FetchResult, Outcome
from signal_pipeline.common.storage import StoredObject


def new_run_id(kind: str = "extract", now: datetime | None = None) -> str:
    """예: extract-20261005T013000Z-a3f9 (UTC 시각 + 임의 4글자)."""
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    return f"{kind}-{stamp}-{secrets.token_hex(2)}"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class RunLog:
    def __init__(
        self,
        raw_root: str | Path,
        baseline_date: str,
        config: dict[str, object],
        run_kind: str = "EXTRACT",
        run_id: str | None = None,
    ) -> None:
        self.root = Path(raw_root)
        self.run_id = run_id or new_run_id(run_kind.lower())
        self.dir = self.root / "runs" / self.run_id
        self.dir.mkdir(parents=True, exist_ok=False)
        self.outcomes: Counter[str] = Counter()
        self._attempt_id = 0
        config_manifest = _canonical_json(config)
        self.run = {
            "run_id": self.run_id,
            "run_kind": run_kind,
            "upstream_run_id": None,
            "is_official": False,
            "baseline_date": baseline_date,
            "status": "RUNNING",
            "config_manifest": config_manifest,
            "config_sha256": hashlib.sha256(config_manifest.encode()).hexdigest(),
            "input_manifest_path": None,
            "input_manifest_sha256": None,
            "started_at": _now(),
            "completed_at": None,
            "summary": {},
        }
        self._write_run()

    def _write_run(self) -> None:
        (self.dir / "run.json").write_text(
            json.dumps(self.run, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    def append(self, name: str, record: dict[str, object]) -> None:
        with (self.dir / name).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def log_fetch(
        self,
        result: FetchResult,
        *,
        source: str,
        request_key: str,
        document_key: str | None = None,
        storage_path: str | None = None,
        source_result_code: str | None = None,
        result_count: int | None = None,
        final_outcome: Outcome | None = None,
        final_error: str | None = None,
    ) -> Outcome:
        """시도마다 1줄. 마지막 시도에는 크롤러가 내용을 보고 내린 판정을 덮어쓴다.

        예: HTTP 200이지만 status 014가 온 document.xml → final_outcome=EMPTY 또는 PERMANENT_FAILED
        """
        last = len(result.tries)
        outcome = result.outcome
        for index, attempt in enumerate(result.tries, 1):
            is_last = index == last
            outcome = (final_outcome or attempt.outcome) if is_last else attempt.outcome
            reason = (
                (final_error or attempt.error_reason)
                if is_last
                else attempt.error_reason
            )
            self._attempt_id += 1
            self.append(
                "attempts.jsonl",
                {
                    "attempt_id": self._attempt_id,
                    "run_id": self.run_id,
                    "source": source,
                    "request_key": request_key,
                    "attempt_no": attempt.attempt_no,
                    "endpoint": result.endpoint,
                    "request_params": _canonical_json(result.request_params),
                    "document_key": document_key,
                    "storage_path": storage_path if is_last else None,
                    "http_status": attempt.http_status,
                    "source_result_code": source_result_code if is_last else None,
                    "result_count": result_count if is_last else None,
                    "outcome": str(outcome),
                    "error_reason": reason,
                    "attempted_at": attempt.attempted_at,
                },
            )
        self.outcomes[str(outcome)] += 1
        return outcome

    def log_object(
        self,
        stored: StoredObject,
        *,
        source: str,
        file_role: str,
        document_key: str | None,
    ) -> None:
        self.append(
            "raw_objects.jsonl",
            {
                "source": source,
                "file_role": file_role,
                "document_key": document_key,
                "storage_path": stored.storage_path,
                "sha256": stored.sha256,
                "version_seq": stored.version_seq,
                "size": stored.size,
                "reused": stored.reused,
            },
        )

    def finish(self, status: str, summary: dict[str, object]) -> None:
        """SUCCEEDED 또는 FAILED로 닫는다. 완료된 실행은 manifest 경로와 해시를 가진다."""
        manifest = self.dir / "raw_objects.jsonl"
        manifest.touch()
        self.run["input_manifest_path"] = str(manifest.relative_to(self.root))
        self.run["input_manifest_sha256"] = hashlib.sha256(
            manifest.read_bytes()
        ).hexdigest()
        self.run["status"] = status
        self.run["completed_at"] = _now()
        self.run["summary"] = {"outcomes": dict(self.outcomes), **summary}
        self._write_run()
