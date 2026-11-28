"""대시보드 공통 상수·점검표 메타데이터·공개 식별자 규칙."""

from __future__ import annotations

CONTRACT_VERSION = "dashboard-export-v1"

DISCLAIMER_TEXT = (
    "자동 판정 결과이며 법적 판단이 아닙니다. "
    "금융소비자보호법 제19조 설명서와 DART 투자설명서는 다른 문서이며, "
    "공모펀드 상품정보 부분을 투자설명서로 대리 판정한 결과입니다."
)

REWRITE_DISCLAIMER_TEXT = (
    "AI가 만든 참고용 예시이며 법적 효력이 없습니다. "
    "의미 보존 검사(수수료율·위험등급·원금손실 고지·핵심어)를 통과한 변환문만 표시합니다."
)

# docs/scoring-and-population.md 「점검표 v0 판정 대상 (11월 4일 확정)」 기준
AXIS4_ITEMS: list[dict[str, str]] = [
    {
        "item": "나1",
        "item_name": "투자목적, 투자대상, 투자전략",
        "legal_basis": "금소법 19조①1호나목1)",
        "source_section": "제2부 7·8·9절",
    },
    {
        "item": "나2",
        "item_name": "원금손실 가능성 고지와 주요 위험",
        "legal_basis": "금소법 19조①1호나목2)",
        "source_section": "표지, 제2부 10절",
    },
    {
        "item": "3.1",
        "item_name": "위험등급 산정 기준",
        "legal_basis": "금소법 19조①1호나목3) / 시행령 13조③",
        "source_section": "제2부 10절",
    },
    {
        "item": "3.2",
        "item_name": "위험등급 이유",
        "legal_basis": "금소법 19조①1호나목3) / 시행령 13조③",
        "source_section": "제2부 10절",
    },
    {
        "item": "3.3",
        "item_name": "위험등급 의미와 유의사항",
        "legal_basis": "금소법 19조①1호나목3) / 시행령 13조③",
        "source_section": "제2부 10절",
    },
    {
        "item": "3.4",
        "item_name": "위험등급 표지 요약",
        "legal_basis": "금소법 19조①1호나목3) / 감독규정 13조①",
        "source_section": "표지",
    },
    {
        "item": "4.1",
        "item_name": "수수료와 보수",
        "legal_basis": "금소법 19조①1호나목4) / 시행령 13조④1호",
        "source_section": "제2부 13절",
    },
    {
        "item": "4.2",
        "item_name": "환매 조건과 환매수수료",
        "legal_basis": "금소법 19조①1호나목4) / 시행령 13조④3호",
        "source_section": "제2부 11절 나목",
    },
    {
        "item": "4.3",
        "item_name": "계약의 해지·해제(펀드 해지 대리판정)",
        "legal_basis": "금소법 19조①1호나목4) / 시행령 13조④2호",
        "source_section": "제5부 2절",
    },
    {
        "item": "11.2",
        "item_name": "예금자보호 대상이 아님을 고지",
        "legal_basis": "금소법 19조①4호 / 시행령 13조⑧2호",
        "source_section": "표지 「투자결정시 유의사항」",
    },
]

AXIS4_ITEM_MAP: dict[str, dict[str, str]] = {row["item"]: row for row in AXIS4_ITEMS}
AXIS4_ITEM_ORDER: list[str] = [row["item"] for row in AXIS4_ITEMS]

STATUS_ORDER: list[str] = ["있음", "없음", "판정 불가", "적용 대상 아님"]
STATUS_COLORS: dict[str, str] = {
    "있음": "#1B7F5C",
    "없음": "#D9383A",
    "판정 불가": "#D98A1B",
    "적용 대상 아님": "#7C8694",
}

# docs/io-schema.md 「공개 식별자 규칙」: 대시보드 내보내기 파일에 금지된 내부 칼럼
FORBIDDEN_EXPORT_COLUMNS: frozenset[str] = frozenset(
    {
        "score_id",
        "target_key",
        "raw_object_id",
        "file_path",
        "local_path",
        "source_file",
        "text_path",
    }
)


def assert_public_columns(columns: list[str] | set[str], table_name: str) -> None:
    """공개 금지 내부 식별자 칼럼이 포함되면 예외를 발생시킨다."""
    bad = sorted(FORBIDDEN_EXPORT_COLUMNS.intersection(columns))
    if bad:
        raise ValueError(f"{table_name}에 공개 금지 칼럼이 포함됨: {', '.join(bad)}")
