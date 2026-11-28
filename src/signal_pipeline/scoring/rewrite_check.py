"""쉬운 문장 변환의 의미 보존 검사(docs/scoring-and-population.md 11월 25일 PM 결정).

원문과 변환문을 대조해 아래 4가지를 검사한다. 하나라도 빠지거나 왜곡되면 표시하지 않는다.
1. 숫자: 수수료율·보수율(%, bp) — 누락 및 원문에 없는 새 비율 생성 모두 차단(bp ↔ % 등가 허용)
2. 위험등급: 1~6등급 — 누락 및 원문에 없는 등급 생성 모두 차단
3. 원금 손실 고지: 원문에 원금·원본 손실/비보장 고지가 있으면 변환문에도 필수(「손실이 없다」「원금을 보장한다」 같은 부정·왜곡 문맥 차단)
4. 점검표 핵심어: 원문에 등장한 10절(투자위험)·13절(수수료) 핵심 개념어 보존
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

# 비율(% 또는 bp). 앞뒤 숫자가 이어지지 않는 독립 수치 추출 (한국어 조사 결합 허용: "50bp입니다")
_PERCENT_RE = re.compile(r"(?<![0-9.])(\d+(?:\.\d+)?)\s*(%|퍼센트)")
_BP_RE = re.compile(r"(?<![0-9.])(\d+(?:\.\d+)?)\s*bp(?![a-zA-Z])", re.IGNORECASE)

# 1~6등급: 두 자리 숫자 끝자리(예: 12등급)를 오탐하지 않도록 앞 숫자 경계 확인
_GRADE_RE = re.compile(r"(?<![0-9])([1-6])\s*등급")

# 원금 손실 / 원본 비보장 고지 판별 패턴
_PRINCIPAL_LOSS_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:원금|투자원금|원본|투자원본).{0,25}(?:손실|보장하지|돌려받지\s*못|감소)"
    ),
    re.compile(r"(?:손실|비보장).{0,15}(?:원금|원본)"),
)

# 원금 손실 부정·원금 보장 왜곡 문맥 차단 패턴
_PRINCIPAL_LOSS_NEGATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:원금|투자원금|원본|투자원본).{0,20}손실.{0,12}(?:없|안\s*남|발생하지\s*않|않습니다)"
    ),
    re.compile(r"(?:원금|투자원금|원본|투자원본).{0,15}보장(?:합|됩|해|받|하)"),
)

# 점검표 핵심어 개념 사전(원문에 해당 개념이 있으면 변환문에도 같은 개념의 표현이 1개 이상 있어야 함)
_COMMON_CONCEPTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("예금자보호 제외", ("예금자보호", "예금보험공사")),
)

_SECTION_10_CONCEPTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("위험등급 변경·상이 유의", ("변경될 수", "달라질 수", "다를 수", "바뀔 수")),
    ("환율 변동 위험", ("환율", "외국 통화", "외화", "환헤지")),
    ("금리 변동 위험", ("금리", "이자율")),
    (
        "신용·부도 위험",
        ("신용위험", "신용 위험", "채무불이행", "부도", "투자부적격", "신용등급"),
    ),
    (
        "유동성·환매 제한 위험",
        ("유동성", "환매가 연기", "환매 연기", "제때 팔기", "매각이 어렵"),
    ),
    ("파생상품 위험", ("파생상품", "선물", "옵션", "레버리지")),
)

_SECTION_13_CONCEPTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("총보수", ("총보수", "총 보수")),
    ("판매수수료", ("판매수수료", "판매 수수료", "선취", "후취")),
    ("환매수수료", ("환매수수료", "환매 수수료")),
    ("동종유형 비교", ("동종유형", "동종 유형", "비슷한 유형", "유사 펀드")),
    ("운용보수", ("운용보수", "운용 보수", "집합투자업자보수", "집합투자업자 보수")),
    ("판매보수", ("판매보수", "판매 보수", "판매회사보수", "판매회사 보수")),
    ("기타비용", ("기타비용", "기타 비용", "증권거래비용", "거래비용")),
)

VALID_SECTION_KINDS = frozenset({"section_10", "section_13", "general"})


@dataclass(frozen=True)
class MeaningCheckResult:
    """의미 보존 검사 결과. passed가 False이면 대시보드에 변환문을 표시하지 않는다."""

    passed: bool
    missing_rates: tuple[str, ...] = field(default_factory=tuple)
    extra_rates: tuple[str, ...] = field(default_factory=tuple)
    missing_grades: tuple[int, ...] = field(default_factory=tuple)
    extra_grades: tuple[int, ...] = field(default_factory=tuple)
    missing_principal_loss: bool = False
    negated_principal_loss: bool = False
    missing_concepts: tuple[str, ...] = field(default_factory=tuple)
    empty_rewrite: bool = False

    @property
    def missing_items(self) -> list[str]:
        items: list[str] = []
        if self.empty_rewrite:
            items.append("변환문 비어 있음")
        if self.missing_rates:
            items.append(f"수치 누락({', '.join(self.missing_rates)})")
        if self.extra_rates:
            items.append(f"원문에 없는 수치 생성({', '.join(self.extra_rates)})")
        if self.missing_grades:
            grades_str = ", ".join(f"{g}등급" for g in self.missing_grades)
            items.append(f"위험등급 누락({grades_str})")
        if self.extra_grades:
            grades_str = ", ".join(f"{g}등급" for g in self.extra_grades)
            items.append(f"원문에 없는 위험등급 생성({grades_str})")
        if self.negated_principal_loss:
            items.append("원금손실 고지 왜곡(손실 없음·보장 표현)")
        elif self.missing_principal_loss:
            items.append("원금손실 고지 누락")
        if self.missing_concepts:
            items.append(f"핵심어 누락({', '.join(self.missing_concepts)})")
        return items


def _normalize_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def _format_decimal(dec: Decimal) -> str:
    text = format(dec.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _normalize_decimal(raw: str) -> str:
    try:
        dec = Decimal(raw)
    except InvalidOperation:
        return raw
    return _format_decimal(dec)


def extract_rates(text: str) -> set[str]:
    """문장에서 비율(%, bp)을 정규화한 문자열 집합으로 추출한다."""
    norm = _normalize_text(text)
    found: set[str] = set()
    for match in _PERCENT_RE.finditer(norm):
        found.add(f"{_normalize_decimal(match.group(1))}%")
    for match in _BP_RE.finditer(norm):
        found.add(f"{_normalize_decimal(match.group(1))}bp")
    return found


def _rate_to_percent_value(rate_str: str) -> Decimal | None:
    """비율 문자열을 퍼센트 단위 Decimal로 환산한다(50bp == 0.5%)."""
    try:
        if rate_str.endswith("bp"):
            return Decimal(rate_str[:-2]) / Decimal(100)
        if rate_str.endswith("%"):
            return Decimal(rate_str[:-1])
    except InvalidOperation:
        return None
    return None


def _rate_value_map(rates: set[str]) -> dict[Decimal, str]:
    mapped: dict[Decimal, str] = {}
    for raw in sorted(rates):
        val = _rate_to_percent_value(raw)
        if val is not None:
            mapped.setdefault(val.normalize(), raw)
    return mapped


def extract_risk_grades(text: str) -> set[int]:
    """문장에서 위험등급(1~6)을 정수 집합으로 추출한다."""
    norm = _normalize_text(text)
    return {int(m.group(1)) for m in _GRADE_RE.finditer(norm)}


def has_negated_principal_loss(text: str) -> bool:
    """원금 손실이 없다거나 원금을 보장한다는 왜곡 문맥이 있는지 판별한다."""
    norm = _normalize_text(text)
    # 「원본을 보장하지 않/아니」·「비보장」은 정상 고지이므로 왜곡 패턴 매칭에서 제외
    cleaned = re.sub(r"보장하지\s*(?:않|아니)|비보장", "보전안함", norm)
    return any(
        pat.search(cleaned) is not None for pat in _PRINCIPAL_LOSS_NEGATION_PATTERNS
    )


def has_principal_loss_notice(text: str) -> bool:
    """원금 손실 또는 원본 비보장 고지가 정상 문맥으로 포함되었는지 판별한다."""
    if has_negated_principal_loss(text):
        return False
    norm = _normalize_text(text)
    return any(pat.search(norm) is not None for pat in _PRINCIPAL_LOSS_PATTERNS)


def _concepts_for_section(section_kind: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if section_kind == "section_10":
        return _COMMON_CONCEPTS + _SECTION_10_CONCEPTS
    if section_kind == "section_13":
        return _COMMON_CONCEPTS + _SECTION_13_CONCEPTS
    return _COMMON_CONCEPTS + _SECTION_10_CONCEPTS + _SECTION_13_CONCEPTS


def _has_any_phrase(norm_text: str, phrases: tuple[str, ...]) -> bool:
    compact = re.sub(r"\s+", "", norm_text)
    for phrase in phrases:
        if phrase in norm_text or re.sub(r"\s+", "", phrase) in compact:
            return True
    return False


def check_meaning_preservation(
    original: str,
    rewritten: str,
    *,
    section_kind: str = "general",
) -> MeaningCheckResult:
    """원문과 변환문의 의미 보존 여부를 검사한다."""
    if section_kind not in VALID_SECTION_KINDS:
        raise ValueError(f"지원하지 않는 section_kind: {section_kind}")

    if not rewritten or not rewritten.strip():
        return MeaningCheckResult(passed=False, empty_rewrite=True)

    orig_norm = _normalize_text(original)
    rewr_norm = _normalize_text(rewritten)

    orig_rate_map = _rate_value_map(extract_rates(orig_norm))
    rewr_rate_map = _rate_value_map(extract_rates(rewr_norm))
    missing_rates = tuple(
        sorted(orig_rate_map[val] for val in set(orig_rate_map) - set(rewr_rate_map))
    )
    extra_rates = tuple(
        sorted(rewr_rate_map[val] for val in set(rewr_rate_map) - set(orig_rate_map))
    )

    orig_grades = extract_risk_grades(orig_norm)
    rewr_grades = extract_risk_grades(rewr_norm)
    missing_grades = tuple(sorted(orig_grades - rewr_grades))
    extra_grades = tuple(sorted(rewr_grades - orig_grades))

    orig_loss = has_principal_loss_notice(orig_norm)
    negated_loss = has_negated_principal_loss(rewr_norm)
    rewr_loss = has_principal_loss_notice(rewr_norm)
    missing_loss = orig_loss and not rewr_loss

    missing_concepts: list[str] = []
    for label, phrases in _concepts_for_section(section_kind):
        if _has_any_phrase(orig_norm, phrases) and not _has_any_phrase(
            rewr_norm, phrases
        ):
            missing_concepts.append(label)

    passed = not (
        missing_rates
        or extra_rates
        or missing_grades
        or extra_grades
        or missing_loss
        or negated_loss
        or missing_concepts
    )
    return MeaningCheckResult(
        passed=passed,
        missing_rates=missing_rates,
        extra_rates=extra_rates,
        missing_grades=missing_grades,
        extra_grades=extra_grades,
        missing_principal_loss=missing_loss,
        negated_principal_loss=negated_loss,
        missing_concepts=tuple(missing_concepts),
    )
