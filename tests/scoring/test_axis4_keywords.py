"""축 4 키워드 자산(axis4_v0.json) 회귀 테스트. 정규식만 확인하고 DB는 쓰지 않는다."""

import json
import re
from pathlib import Path

import pytest

ASSET = (
    Path(__file__).resolve().parents[2]
    / "src/signal_pipeline/scoring/keywords/axis4_v0.json"
)
ITEMS = json.loads(ASSET.read_text(encoding="utf-8"))["items"]


def _hit(patterns: list[dict], text: str) -> bool:
    return any(re.search(p["re"], text) for p in patterns)


def test_every_regex_compiles():
    for group in ITEMS.values():
        for patterns in group.values():
            for p in patterns:
                re.compile(p["re"])


# 문서 예시: 한 문장이 방법과 측정값을 함께 담으면 3.1·3.2 모두 일치해야 한다
VALUE_SENTENCES = [
    "최근 3년 수익률 변동성이 12.3%로 2등급입니다.",
    "최근 3년  수익률  변동성이\n  12.3 %로   2 등급입니다.",
    "일간 수익률의 최대손실예상액(VaR)이 42.81%임에 따라 6등급 중 2등급에 해당됩니다.",
]


@pytest.mark.parametrize("text", VALUE_SENTENCES)
def test_value_and_grade_matches_3_1_and_3_2(text):
    assert _hit(ITEMS["3.1"]["any"], text)
    assert _hit(ITEMS["3.2"]["any"], text)


ASSET_SENTENCES = [
    "이 투자신탁은 주식에 투자하므로 6등급 중 2등급으로 분류됩니다.",
    "이 투자신탁은 주식에 투자하므로\n6등급  중  2 등급으로\n분류됩니다.",
]


@pytest.mark.parametrize("text", ASSET_SENTENCES)
def test_asset_reason_and_grade_matches_3_2(text):
    assert _hit(ITEMS["3.2"]["any"], text)


def test_table_cell_values_match_3_2():
    assert _hit(ITEMS["3.2"]["any"], "일간 수익률의 VaR 13.66% 3 ")
    assert _hit(ITEMS["3.2"]["any"], "VaR 모형 사용) 91.14% 1등급 (매우 높은 위험)")


# 등급만 말하는 문장과 일반 등급기준표 줄은 3.2에 일치하면 안 된다
NOT_3_2 = [
    "이 투자신탁은 6등급 중 2등급에 해당되는 높은 위험수준의 투자위험을 지니고 있습니다.",
    "이 투자신탁의 위험등급을 2등급으로 분류하였습니다.",
    "이 투자신탁은 2등급(높은 위험)으로 분류됩니다.",
    "연환산 표준편차 25% 초과 1등급",
    "최대손실률이 20%를 초과하는 파생결합증권에 주로 투자하는 집합투자기구 1등급",
    "97.5% VaR 50%초과 50%이하 30%이하 20%이하 10%이하 1%이하",
]


@pytest.mark.parametrize("text", NOT_3_2)
def test_grade_only_or_generic_table_is_not_3_2(text):
    assert not _hit(ITEMS["3.2"]["any"], text)


SCALE = (
    "1등급 매우 높은 위험 2등급 높은 위험 3등급 다소 높은 위험 "
    "4등급 보통 위험 5등급 낮은 위험 6등급 매우 낮은 위험"
)
CAUTION = "이 투자위험 등급은 집합투자업자가 분류한 것으로 판매회사의 분류 등급과는 상이할 수 있습니다."


def test_scale_meaning_and_caution_match():
    assert _hit(ITEMS["3.3"]["meaning"], SCALE)
    assert _hit(ITEMS["3.3"]["meaning"], SCALE.replace(" ", "\n"))
    assert _hit(ITEMS["3.3"]["caution"], CAUTION)


def test_six_grade_division_alone_is_not_meaning():
    text = "투자위험 등급을 6개의 등급으로 나눕니다. 위험등급은 변경될 수 있습니다."
    assert not _hit(ITEMS["3.3"]["meaning"], text)
    assert _hit(ITEMS["3.3"]["caution"], text)


def test_cover_grade_matches_3_4():
    text = "키움투자자산운용(주)는 이 투자신탁의 실제 수익률 변동성을 감안하여 6등급으로 분류하였습니다."
    assert _hit(ITEMS["3.4"]["any"], text)


def test_deposit_protection_matches_11_2():
    text = "이 집합투자증권은 「예금자보호법」에 따라 보호되지 않는 실적배당상품입니다."
    assert _hit(ITEMS["11.2"]["any"], text)
    assert _hit(ITEMS["11.2"]["any"], "예금자\n보호법에 따라 보호되지\n아니하며")
