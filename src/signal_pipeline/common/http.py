"""HTTP 요청 공통 계층. 간격 유지, 재시도, 결과 분류를 한곳에서 처리한다.

규칙의 근거
- 호출 간격 1초 이상, 동시 요청 1개: docs/data-sources.md 「공통 수집 규칙」
- 타임아웃·5xx는 지수 백오프로 재시도(최초 1회 + 재시도 최대 5회), 401·403은 재시도 없이 중단,
  429는 한도 정책을 따름: docs/storage-and-failure-rules.md 「재시도와 워터마크」
- 결과 분류는 ERD `attempt_outcome_enum` 6종을 그대로 쓴다(docs/schema.dbml)
- 기록에 인증값 원문을 남기지 않는다: docs/storage-and-failure-rules.md 「원본 보관」

HTTP 200이어도 내용상 실패인 경우(예: OPEN DART document.xml의 status 014, PDF 자리에 온 오류 HTML)는
소스마다 판정이 달라 이 모듈이 아니라 각 크롤러가 판정한다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Self

import httpx

# 기록에서 빼는 인증 인자 이름. 소스별 이름은 docs/data-sources.md 각 절
SECRET_PARAM_NAMES = frozenset({"crtfc_key", "serviceKey", "authKey", "AUTH_KEY"})


class Outcome(StrEnum):
    """ERD attempt_outcome_enum."""

    SUCCESS = "SUCCESS"
    EMPTY = "EMPTY"
    RETRYABLE_FAILED = "RETRYABLE_FAILED"
    PERMANENT_FAILED = "PERMANENT_FAILED"
    CONFIG_ERROR = "CONFIG_ERROR"
    RATE_LIMITED = "RATE_LIMITED"


@dataclass
class Try:
    """요청 한 번의 시도. attempts.jsonl 한 줄의 재료가 된다."""

    attempt_no: int
    attempted_at: str
    http_status: int | None
    outcome: Outcome
    error_reason: str | None


@dataclass
class FetchResult:
    """재시도를 포함한 요청 1건의 최종 결과."""

    endpoint: str
    request_params: dict[str, str]
    outcome: Outcome
    http_status: int | None = None
    content: bytes | None = None
    content_type: str = ""
    error_reason: str | None = None
    tries: list[Try] = field(default_factory=list)


def classify_status(status: int) -> Outcome:
    if status == 200:
        return Outcome.SUCCESS
    if status in (401, 403):
        return Outcome.CONFIG_ERROR
    if status == 429:
        return Outcome.RATE_LIMITED
    if status >= 500:
        return Outcome.RETRYABLE_FAILED
    return Outcome.PERMANENT_FAILED


def redact(params: dict[str, str] | None) -> dict[str, str]:
    return {k: v for k, v in (params or {}).items() if k not in SECRET_PARAM_NAMES}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class HttpClient:
    """요청을 한 번에 하나씩, 최소 간격을 지켜 보낸다."""

    def __init__(
        self,
        user_agent: str,
        min_interval: float = 1.0,
        timeout: float = 60.0,
        max_retries: int = 5,
        backoff_base: float = 1.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self._client = httpx.Client(
            headers={"User-Agent": user_agent},
            timeout=timeout,
            follow_redirects=True,
            transport=transport,  # 테스트에서 가짜 응답을 넣을 때만 쓴다
        )
        self._last_end = 0.0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _wait_interval(self) -> None:
        remaining = self.min_interval - (time.monotonic() - self._last_end)
        if remaining > 0:
            time.sleep(remaining)

    def fetch(
        self,
        url: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> FetchResult:
        """GET 1건. 재시도 가능한 실패면 1·2·4·8·16초 간격으로 다시 보낸다."""
        result = FetchResult(
            endpoint=url.split("?")[0],
            request_params=redact(params),
            outcome=Outcome.RETRYABLE_FAILED,
        )
        for attempt_no in range(1, self.max_retries + 2):
            self._wait_interval()
            attempted_at = _now()
            try:
                response = self._client.get(url, params=params, headers=headers)
            except httpx.TransportError as error:  # 타임아웃·연결 오류
                status, outcome, reason = None, Outcome.RETRYABLE_FAILED, repr(error)
            else:
                status = response.status_code
                outcome = classify_status(status)
                reason = None if outcome is Outcome.SUCCESS else f"HTTP {status}"
                result.content = response.content
                result.content_type = response.headers.get("content-type", "")
            finally:
                self._last_end = time.monotonic()

            result.tries.append(Try(attempt_no, attempted_at, status, outcome, reason))
            result.http_status, result.outcome, result.error_reason = (
                status,
                outcome,
                reason,
            )
            if outcome is not Outcome.RETRYABLE_FAILED or attempt_no > self.max_retries:
                break
            time.sleep(self.backoff_base * 2 ** (attempt_no - 1))

        if result.outcome is not Outcome.SUCCESS:
            result.content = None
        return result
