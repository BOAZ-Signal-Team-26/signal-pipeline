"""Bedrock Converse 호출 테스트. 가짜 전송(httpx.MockTransport)만 쓰고 네트워크·실제 키를 쓰지 않는다."""

import json
from urllib.parse import unquote

import httpx
import pytest

from signal_pipeline.extraction.bedrock import (
    MODELS,
    TOKEN_ENV,
    BedrockClient,
    cost_usd,
)
from signal_pipeline.extraction.store import install_prompts

FAKE = "FAKE-BEDROCK-TOKEN-0000"


def converse_body(text: str, tin: int = 10, tout: int = 2) -> bytes:
    return json.dumps(
        {
            "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
            "stopReason": "end_turn",
            "usage": {
                "inputTokens": tin,
                "outputTokens": tout,
                "totalTokens": tin + tout,
            },
        }
    ).encode()


def client(handler, monkeypatch, model="lite") -> BedrockClient:
    monkeypatch.setenv(TOKEN_ENV, FAKE)
    return BedrockClient(
        MODELS[model], backoff_base=0, transport=httpx.MockTransport(handler)
    )


def test_request_shape_and_success(monkeypatch) -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=converse_body("{}"))

    result = client(handler, monkeypatch).converse("SYS", "USER")
    req = seen[0]
    assert req.url.host == "bedrock-runtime.ap-northeast-2.amazonaws.com"
    assert unquote(req.url.raw_path.decode()) == f"/model/{MODELS['lite']}/converse"
    assert ":" not in req.url.raw_path.decode().split("/")[2]  # 모델 ID는 URL 인코딩
    assert req.headers["authorization"] == f"Bearer {FAKE}"
    body = json.loads(req.content)
    assert body == {
        "system": [{"text": "SYS"}],
        "messages": [{"role": "user", "content": [{"text": "USER"}]}],
        "inferenceConfig": {"maxTokens": 4096, "temperature": 0},
    }
    assert (result.text, result.input_tokens, result.output_tokens, result.error) == (
        "{}",
        10,
        2,
        None,
    )
    assert result.raw == converse_body("{}")


def test_retry_429_and_5xx_then_success(monkeypatch) -> None:
    codes = iter([429, 503])

    def handler(request: httpx.Request) -> httpx.Response:
        code = next(codes, 200)
        return httpx.Response(
            code, content=converse_body("ok") if code == 200 else b"{}"
        )

    result = client(handler, monkeypatch).converse("S", "U")
    assert result.text == "ok" and len(result.tries) == 3


def test_timeout_exhausts_retries(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    c = client(handler, monkeypatch)
    result = c.converse("S", "U")
    assert result.text is None and result.raw is None
    assert (
        result.error.startswith("ReadTimeout")
        and len(result.tries) == c.max_retries + 1
    )


def test_4xx_not_retried_and_keeps_body_without_key(monkeypatch) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(400, content=f'{{"message":"bad {FAKE}"}}'.encode())

    result = client(handler, monkeypatch).converse("S", "U")
    assert len(calls) == 1 and result.text is None
    assert result.error.startswith("HTTP 400") and FAKE not in result.error
    assert result.raw is not None


def test_missing_token_fails_without_leaking(monkeypatch) -> None:
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    with pytest.raises(RuntimeError, match=TOKEN_ENV):
        BedrockClient(MODELS["lite"])


def test_cost_table() -> None:
    assert cost_usd(MODELS["lite"], 1_000_000, 1_000_000) == pytest.approx(2.80)
    assert cost_usd(MODELS["pro"], 1_000_000, 0) == pytest.approx(0.80)


def test_install_prompts_immutable(tmp_path) -> None:
    first = install_prompts(tmp_path)
    again = install_prompts(tmp_path)  # 같은 해시면 재사용
    assert first == again and len(first) == 4
    p = first["key_risk_phrases"]
    assert p.prompt_id == "key_risk_phrases:v1"
    assert p.path == f"assets/prompts/key_risk_phrases__v1__{p.sha256[:12]}.md"
    assert (tmp_path / p.path).read_text(encoding="utf-8") == p.text
