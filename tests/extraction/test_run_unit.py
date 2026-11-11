"""DB 없이 도는 실행 단위 테스트(비용 상한, 재사용)."""

from pathlib import Path

import httpx
import pytest

from signal_pipeline.extraction import run
from signal_pipeline.extraction.bedrock import MODELS, TOKEN_ENV, BedrockClient
from signal_pipeline.extraction.inputs import FieldInput, SectionText
from signal_pipeline.extraction.run import Context


@pytest.fixture
def make_ctx(tmp_path: Path, monkeypatch):
    def make(budget: float | None, prompts: dict | None = None) -> Context:
        monkeypatch.setenv(TOKEN_ENV, "FAKE-BEDROCK-TOKEN")
        transport = httpx.MockTransport(lambda request: httpx.Response(500))
        client = BedrockClient(MODELS["lite"], transport=transport)
        return Context(None, tmp_path, "r", client, prompts or {}, budget)

    return make


def test_budget_reserves_for_in_flight_calls(make_ctx) -> None:
    ctx = make_ctx(0.025)
    sys_text, text = "s" * 1000, "t" * 1000
    # 예상 = 2000 x 0.30/1M + 4096 x 2.50/1M = 0.01084달러
    first = ctx.reserve(sys_text, text)
    assert first and abs(first - 0.01084) < 1e-9
    second = ctx.reserve(sys_text, text)  # 진행 중 0.01084 + 0.01084 <= 0.025
    assert second
    ctx.charge(first, 1000, 100)  # 실제 0.00055달러로 바꿈
    ctx.charge(second, 1000, 100)
    assert ctx.reserve(sys_text, text) and ctx.stop_reason is None


def test_budget_stops_all_calls_after_cap(make_ctx) -> None:
    ctx = make_ctx(0.015)
    big, small = "t" * 1000, "t"
    first = ctx.reserve("s" * 1000, big)
    assert first
    assert not ctx.reserve("s" * 1000, big)  # 상한에 걸림
    assert ctx.stop_reason
    ctx.charge(first, 1000, 100)
    # 진행 중 호출이 끝나 여유가 생겨도, 작은 호출이어도 새로 나가지 않음
    assert not ctx.reserve("s", small)


def test_budget_overshoot_by_actual_cost_sets_stop_reason(make_ctx) -> None:
    ctx = make_ctx(0.02)
    reserved = ctx.reserve("s", "t")
    assert reserved and ctx.stop_reason is None
    ctx.charge(reserved, 100_000, 0)  # 0.03달러
    assert ctx.stop_reason and "budget" in ctx.stop_reason
    assert not ctx.reserve("s", "t")


def test_reuse_missing_response_file_falls_back_to_call(make_ctx, monkeypatch) -> None:
    field = "principal_loss_notice"
    ctx = make_ctx(None, {field: object()})
    prior = {
        "run_id": "old",
        "extraction_id": 1,
        "raw_response_path": "runs/old/x.json",
    }
    monkeypatch.setattr(run, "find_prior", lambda *args: prior)
    sec = SectionText("절0", 10, 0, "투자원금의 손실이 발생할 수 있습니다.")
    fi = FieldInput(1, 2, field, (sec,), (), sec.text, "0" * 64, ())
    assert run._reuse(ctx, fi) is None
