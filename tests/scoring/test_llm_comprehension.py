"""LLM 이해도 평가 실행기 단위 테스트."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from signal_pipeline.extraction.bedrock import MODELS, CallResult
from signal_pipeline.scoring.llm_comprehension import (
    ComprehensionQuestion,
    grade_answer,
    normalize_answer,
    parse_model_answer,
    run_evaluation,
    spearman_correlation,
)


@dataclass
class _RecordingClient:
    responses: list[CallResult]
    model: str = MODELS["lite"]
    calls: list[tuple[str, str]] = field(default_factory=list)

    def converse(self, system: str, user: str) -> CallResult:
        res = self.responses[len(self.calls)]
        self.calls.append((system, user))
        return res


def _sample_question(
    rcept_no: str,
    qid: str,
    gold: str = "2",
    doc_text: str = "이 펀드의 총보수는 연 1.25%입니다.",
    cdi_pct: float | None = 50.0,
) -> ComprehensionQuestion:
    return ComprehensionQuestion(
        rcept_no=rcept_no,
        question_id=qid,
        fca_level="정보 회상",
        question="이 펀드의 총보수는 얼마인가요?",
        choices=["연 0.50%", "연 1.25%", "연 2.00%", "무료"],
        gold_answer=gold,
        document_text=doc_text,
        cdi_percentile=cdi_pct,
    )


def test_normalize_and_grade_answer() -> None:
    assert normalize_answer("②") == "2"
    assert normalize_answer("2번") == "2"
    assert normalize_answer("(2)") == "2"
    assert grade_answer("②", "2") is True
    assert grade_answer("1번", "2") is False


def test_parse_model_answer_handles_plain_and_fenced_json() -> None:
    assert parse_model_answer('{"answer": "2", "reason": "문서 명시"}') == "2"
    assert parse_model_answer('```json\n{"answer": "②", "reason": "ok"}\n```') == "②"
    assert (
        parse_model_answer('정답은 아래와 같습니다.\n{"answer": "3", "reason": "문서"}')
        == "3"
    )
    assert parse_model_answer("정답은 2번입니다") is None


def test_run_evaluation_isolates_without_doc_and_computes_info_gain_and_ceiling() -> (
    None
):
    q1 = _sample_question(
        "20260901000001", "Q1", gold="2", doc_text="비밀문구-DOC1", cdi_pct=20.0
    )
    q2 = _sample_question(
        "20260901000002", "Q2", gold="1", doc_text="비밀문구-DOC2", cdi_pct=80.0
    )

    # q1: without_doc 오답(0.0) -> with_doc 정답(1.0) => info_gain = +1.0, ceiling = False
    # q2: without_doc 정답(1.0) -> with_doc 정답(1.0) => info_gain =  0.0, ceiling = True
    client = _RecordingClient(
        responses=[
            CallResult(
                text=json.dumps({"answer": "1"}), input_tokens=200, output_tokens=30
            ),
            CallResult(
                text=json.dumps({"answer": "2"}), input_tokens=500, output_tokens=30
            ),
            CallResult(
                text=json.dumps({"answer": "1"}), input_tokens=200, output_tokens=30
            ),
            CallResult(
                text=json.dumps({"answer": "1"}), input_tokens=500, output_tokens=30
            ),
        ]
    )
    trials, summary = run_evaluation([q1, q2], client=client, budget_usd=1.0)

    assert len(trials) == 4
    # without_doc 호출에는 문서 본문이 절대 들어가지 않음
    assert "비밀문구-DOC1" not in client.calls[0][1]
    assert "비밀문구-DOC1" in client.calls[1][1]
    assert "비밀문구-DOC2" not in client.calls[2][1]
    assert "비밀문구-DOC2" in client.calls[3][1]

    by_doc = {row["rcept_no"]: row for row in summary["per_document"]}
    assert by_doc["20260901000001"]["info_gain"] == 1.0
    assert by_doc["20260901000001"]["ceiling_effect_flag"] is False
    assert by_doc["20260901000002"]["info_gain"] == 0.0
    assert by_doc["20260901000002"]["ceiling_effect_flag"] is True


def test_truncation_flag_and_fail_on_truncation() -> None:
    long_q = _sample_question("20260901000001", "Q1", doc_text="가" * 500)
    client = _RecordingClient(
        responses=[
            CallResult(text='{"answer": "1"}', input_tokens=100, output_tokens=20),
            CallResult(text='{"answer": "2"}', input_tokens=100, output_tokens=20),
        ]
    )
    trials, summary = run_evaluation(
        [long_q],
        client=client,
        budget_usd=1.0,
        max_input_chars=100,
        fail_on_truncation=False,
    )
    assert trials[0].input_truncated is False
    assert trials[1].input_truncated is True
    assert trials[1].original_doc_chars == 500
    assert trials[1].sent_doc_chars == 100
    assert summary["truncated_trials"] == 1

    client2 = _RecordingClient(
        responses=[
            CallResult(text='{"answer": "1"}', input_tokens=100, output_tokens=20)
        ]
    )
    with pytest.raises(ValueError, match="입력 잘림"):
        run_evaluation(
            [long_q],
            client=client2,
            budget_usd=1.0,
            max_input_chars=100,
            fail_on_truncation=True,
        )


def test_spearman_correlation_direction() -> None:
    # CDI 백분위가 높을수록 info_gain이 작으면 음의 상관(-1.0)
    assert spearman_correlation([10.0, 50.0, 90.0], [0.75, 0.5, 0.25]) == -1.0
    assert spearman_correlation([10.0, 50.0], [0.75, 0.5]) is None


def test_budget_limit_stops_evaluation_and_excludes_unpaired_from_info_gain() -> None:
    q = _sample_question("20260901000001", "Q1")
    client = _RecordingClient(
        responses=[
            CallResult(
                text='{"answer": "2"}', input_tokens=100_000, output_tokens=100_000
            ),
            CallResult(text='{"answer": "2"}', input_tokens=100, output_tokens=20),
        ]
    )
    trials, summary = run_evaluation([q], client=client, budget_usd=0.01)
    assert len(trials) == 1
    assert summary["stopped_by_budget"] is True
    assert summary["seed"] is None
    doc_row = summary["per_document"][0]
    assert doc_row["paired_trials"] == 0
    assert doc_row["unpaired_trials"] == 1
    assert doc_row["info_gain"] is None


def test_duplicate_question_id_raises() -> None:
    q = _sample_question("20260901000001", "Q1")
    client = _RecordingClient(responses=[])
    with pytest.raises(ValueError, match="중복 문항"):
        run_evaluation([q, q], client=client, budget_usd=1.0)
