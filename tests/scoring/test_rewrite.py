"""쉬운 문장 변환 및 의미 보존 검사 단위 테스트."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from signal_pipeline.extraction.bedrock import MODELS, CallResult
from signal_pipeline.scoring.rewrite import (
    RewriteInput,
    infer_section_kind,
    rewrite_one,
    run_batch,
)
from signal_pipeline.scoring.rewrite_check import (
    check_meaning_preservation,
    extract_rates,
    extract_risk_grades,
    has_principal_loss_notice,
)

SAMPLE_SEC10 = (
    "이 투자신탁은 원본을 보장하지 않습니다. 투자원본의 전부 또는 일부에 대한 손실의 위험이 존재합니다. "
    "최근 3년간 수익률 변동성이 12.50%로 2등급(높은 위험)에 해당합니다. "
    "위험등급은 추후 결산 시마다 변경될 수 있으며, 외국 통화로 표시된 자산에 투자해 환율 변동 위험에 노출됩니다. "
    "이 상품은 예금자보호법에 따라 보호되지 않습니다."
)

SAMPLE_SEC13 = (
    "클래스 A의 선취 판매수수료는 납입금액의 1.00% 이내이며, "
    "총보수는 연 1.25%(운용보수 0.60%, 판매보수 0.60%)입니다. "
    "동종유형 총보수는 연 1.10%이며 기타비용은 별도 발생합니다."
)


@dataclass
class _FakeClient:
    responses: list[CallResult]
    model: str = MODELS["lite"]
    idx: int = 0

    def converse(self, system: str, user: str) -> CallResult:
        res = self.responses[self.idx]
        self.idx += 1
        return res


def test_extract_rates_normalizes_trailing_zeros_and_bp() -> None:
    assert extract_rates("총보수 연 1.00%, 추가 0.50%, 스프레드 25bp") == {
        "1%",
        "0.5%",
        "25bp",
    }


def test_extract_risk_grades_ignores_two_digit_numbers() -> None:
    assert extract_risk_grades("6등급 중 2등급이며 12등급은 해당 없음") == {2, 6}


def test_has_principal_loss_notice() -> None:
    assert has_principal_loss_notice("투자한 원금을 돌려받지 못할 수 있습니다.")
    assert has_principal_loss_notice("이 투자신탁은 원본을 보장하지 아니합니다.")
    assert not has_principal_loss_notice("이 펀드는 국내 주식에 주로 투자합니다.")


def test_meaning_check_passes_for_faithful_section_10_rewrite() -> None:
    rewritten = (
        "이 펀드는 투자한 원금을 돌려받지 못할 수 있습니다(원금 손실 가능). "
        "최근 3년 수익률 변동성이 12.5%여서 2등급(높은 위험)입니다. "
        "위험등급은 앞으로 바뀔 수 있고, 외화 자산에 투자하므로 환율이 변하면 손실이 날 수 있습니다. "
        "예금자보호 대상이 아닙니다."
    )
    res = check_meaning_preservation(SAMPLE_SEC10, rewritten, section_kind="section_10")
    assert res.passed is True
    assert res.missing_items == []


def test_meaning_check_blocks_missing_rate_in_section_13() -> None:
    rewritten = (
        "클래스 A는 가입할 때 판매수수료가 1% 이내입니다. "
        "총보수는 연 1.25%(운용보수 0.6%, 판매보수 0.6%)이고 기타비용이 따로 붙습니다. "
        "비슷한 유형의 평균 총보수와 비교해 보세요."
    )
    res = check_meaning_preservation(SAMPLE_SEC13, rewritten, section_kind="section_13")
    assert res.passed is False
    assert "1.1%" in res.missing_rates


def test_meaning_check_blocks_missing_or_invented_grade() -> None:
    missing = (
        "원금 손실이 날 수 있습니다. 수익률 변동성은 12.5%입니다. "
        "등급은 바뀔 수 있고 환율 변동 위험이 있으며 예금자보호가 안 됩니다."
    )
    res1 = check_meaning_preservation(SAMPLE_SEC10, missing, section_kind="section_10")
    assert res1.passed is False
    assert res1.missing_grades == (2,)

    invented = (
        "원금 손실이 날 수 있습니다. 변동성 12.5%로 2등급이며 1등급 수준입니다. "
        "등급은 바뀔 수 있고 환율 변동 위험이 있으며 예금자보호가 안 됩니다."
    )
    res2 = check_meaning_preservation(SAMPLE_SEC10, invented, section_kind="section_10")
    assert res2.passed is False
    assert res2.extra_grades == (1,)


def test_meaning_check_blocks_missing_principal_loss_notice() -> None:
    rewritten = (
        "최근 3년 변동성이 12.5%로 2등급입니다. "
        "등급은 바뀔 수 있고 환율 위험이 있으며 예금자보호가 안 됩니다."
    )
    res = check_meaning_preservation(SAMPLE_SEC10, rewritten, section_kind="section_10")
    assert res.passed is False
    assert res.missing_principal_loss is True


def test_meaning_check_blocks_negated_principal_loss_and_invented_rates() -> None:
    negated = (
        "이 펀드는 원금 손실이 없습니다. 최근 3년 변동성이 12.5%로 2등급입니다. "
        "등급은 바뀔 수 있고 환율 위험이 있으며 예금자보호가 안 됩니다."
    )
    res_neg = check_meaning_preservation(
        SAMPLE_SEC10, negated, section_kind="section_10"
    )
    assert res_neg.passed is False
    assert res_neg.negated_principal_loss is True

    invented_rate = (
        "클래스 A는 선취 판매수수료 1% 이내, 총보수 연 1.25%(운용보수 0.6%, 판매보수 0.6%), "
        "동종유형 총보수 연 1.1%, 기타비용 별도이며 기대수익률은 연 10%입니다."
    )
    res_rate = check_meaning_preservation(
        SAMPLE_SEC13, invented_rate, section_kind="section_13"
    )
    assert res_rate.passed is False
    assert "10%" in res_rate.extra_rates

    # 50bp ↔ 0.5% 등가 변환은 허용
    res_eq = check_meaning_preservation(
        "총보수는 연 50bp입니다.",
        "총보수는 연 0.5%입니다.",
        section_kind="section_13",
    )
    assert res_eq.passed is True


def test_meaning_check_blocks_missing_concept() -> None:
    rewritten = (
        "원금 손실이 날 수 있습니다. 최근 3년 변동성 12.5%로 2등급입니다. "
        "등급은 바뀔 수 있으며 예금자보호가 안 됩니다."
    )
    res = check_meaning_preservation(SAMPLE_SEC10, rewritten, section_kind="section_10")
    assert res.passed is False
    assert "환율 변동 위험" in res.missing_concepts


def test_meaning_check_rejects_empty_and_invalid_kind() -> None:
    assert check_meaning_preservation(SAMPLE_SEC10, "   ").passed is False
    with pytest.raises(ValueError, match="section_kind"):
        check_meaning_preservation(SAMPLE_SEC10, "문장", section_kind="unknown")


def test_infer_section_kind() -> None:
    assert infer_section_kind(2, 10) == "section_10"
    assert infer_section_kind(2, 13) == "section_13"
    assert infer_section_kind(2, 11) == "general"


def test_rewrite_one_and_batch_budget_stop() -> None:
    good = (
        "클래스 A의 선취 판매수수료는 1% 이내입니다. "
        "총보수는 연 1.25%(운용보수 0.6%, 판매보수 0.6%)이고, "
        "비슷한 유형 총보수는 연 1.1%이며 기타비용은 별도입니다."
    )
    bad = "클래스 A는 수수료가 저렴합니다."
    client = _FakeClient(
        responses=[
            CallResult(text=good, input_tokens=1000, output_tokens=500),
            CallResult(text=bad, input_tokens=1000, output_tokens=200),
        ]
    )
    item1 = RewriteInput(
        "20260901000001", 2, 13, "제2부 13절 보수 및 수수료", "section_13", SAMPLE_SEC13
    )
    item2 = RewriteInput(
        "20260901000002", 2, 13, "제2부 13절 보수 및 수수료", "section_13", SAMPLE_SEC13
    )

    rec = rewrite_one(client, item1, system_prompt="sys", prompt_sha256="sha")
    assert rec.display_allowed is True
    assert rec.meaning_preserved is True
    assert rec.cost_usd is not None and rec.cost_usd > 0

    client2 = _FakeClient(
        responses=[
            CallResult(text=bad, input_tokens=100000, output_tokens=100000),
            CallResult(text=good, input_tokens=1000, output_tokens=500),
        ]
    )
    records, summary = run_batch([item1, item2], client=client2, budget_usd=0.01)
    assert len(records) == 1
    assert records[0].display_allowed is False
    assert summary["blocked_by_meaning_check"] == 1
    assert summary["stopped_by_budget"] is True
