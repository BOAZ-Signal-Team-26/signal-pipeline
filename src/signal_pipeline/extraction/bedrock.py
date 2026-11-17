"""Bedrock Converse 동기 호출. Bedrock API 키를 bearer token으로 쓴다(AWS_BEARER_TOKEN_BEDROCK, 10-31 결정).

- 429·5xx·시간 초과·연결 오류는 1·2·4·8·16초 간격으로 재시도(최초 1회 + 최대 5회). 그 밖의 4xx는 바로 실패
  분류는 common/http.py의 classify_status를 그대로 쓴다
- 키는 요청 헤더에만 둔다. 오류 문장·응답 바이트에 키 문자열이 섞여 오면 지운다(기록에 인증값 원문을 남기지 않음)
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from urllib.parse import quote

import httpx

from signal_pipeline.common.http import Outcome, classify_status

TOKEN_ENV = "AWS_BEARER_TOKEN_BEDROCK"
REGION = "ap-northeast-2"
MODELS = {
    "lite": "global.amazon.nova-2-lite-v1:0",
    "pro": "apac.amazon.nova-pro-v1:0",
}
# 1M 토큰당 USD (입력, 출력)
# ponytail: 11-06 기준 손으로 옮긴 값. AWS 가격표(Bedrock Pricing, 서울·cross-region)와 다시 대조할 것
PRICES = {
    MODELS["lite"]: (0.30, 2.50),
    MODELS["pro"]: (0.80, 3.20),
}
MAX_TOKENS = 4096
RETRY = (Outcome.RETRYABLE_FAILED, Outcome.RATE_LIMITED)


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = PRICES[model]
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


@dataclass
class CallResult:
    """호출 1건(재시도 포함)의 최종 결과. error가 None이면 성공."""

    text: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    raw: bytes | None = None  # 마지막 응답 바이트 그대로. 응답이 없었으면 None
    error: str | None = None
    # 시도마다 "200", "HTTP 429", "ReadTimeout" 등
    tries: list[str] = field(default_factory=list)


def _text(raw: bytes) -> tuple[str, int | None, int | None]:
    """Converse 응답 → (텍스트, 입력 토큰, 출력 토큰). 형식이 다르면 KeyError·ValueError."""
    data = json.loads(raw)
    blocks = data["output"]["message"]["content"]
    usage = data.get("usage") or {}
    text = "".join(b["text"] for b in blocks if "text" in b)
    return text, usage.get("inputTokens"), usage.get("outputTokens")


def response_text(raw: bytes) -> str | None:
    """저장된 response.json에서 모델 텍스트만 꺼낸다(재사용·재변환용). 형식이 다르면 None."""
    try:
        return _text(raw)[0]
    except (KeyError, IndexError, TypeError, ValueError):
        return None


class BedrockClient:
    """스레드 여러 개가 같이 써도 된다(httpx.Client는 스레드 안전)."""

    def __init__(
        self,
        model: str,
        region: str = REGION,
        max_tokens: int = MAX_TOKENS,
        timeout: float = 300.0,
        max_retries: int = 5,
        backoff_base: float = 1.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        token = os.environ.get(TOKEN_ENV)
        if not token:
            raise RuntimeError(f"{TOKEN_ENV} 환경 변수가 필요하다")
        self.model = model
        self.params = {"maxTokens": max_tokens, "temperature": 0}
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self._token = token.encode()
        self._url = f"https://bedrock-runtime.{region}.amazonaws.com/model/{quote(model, safe='')}/converse"
        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
            follow_redirects=False,  # 키가 다른 호스트로 넘어가지 않게
            transport=transport,  # 테스트에서 가짜 응답을 넣을 때만 쓴다
        )

    def close(self) -> None:
        self._client.close()

    def _clean(self, data: bytes) -> bytes:
        return data.replace(self._token, b"***")

    def converse(self, system: str, user: str) -> CallResult:
        payload = {
            "system": [{"text": system}],
            "messages": [{"role": "user", "content": [{"text": user}]}],
            "inferenceConfig": self.params,
        }
        result = CallResult()
        for attempt_no in range(1, self.max_retries + 2):
            try:
                response = self._client.post(self._url, json=payload)
            except httpx.TransportError as error:  # 타임아웃·연결 오류
                outcome, result.raw = Outcome.RETRYABLE_FAILED, None
                reason = self._clean(
                    f"{type(error).__name__}: {error}".encode()
                ).decode()
            else:
                outcome = classify_status(response.status_code)
                result.raw = self._clean(response.content)
                reason = None
                if outcome is not Outcome.SUCCESS:
                    reason = f"HTTP {response.status_code}: {result.raw[:300].decode(errors='replace')}"
            result.tries.append(reason or "200")
            result.error = reason
            if outcome not in RETRY or attempt_no > self.max_retries:
                break
            time.sleep(self.backoff_base * 2 ** (attempt_no - 1))

        if result.error is None:
            try:
                result.text, result.input_tokens, result.output_tokens = _text(
                    result.raw
                )
            except (KeyError, IndexError, TypeError, ValueError) as error:
                result.error = f"응답 형식 오류: {type(error).__name__}"
        return result
