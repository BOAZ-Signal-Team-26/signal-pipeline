"""필드별 value 구조 검증(docs/io-schema.md 「필드별 value 구조 (초안)」). 순수 함수.

validate_value는 오류 문장 목록을 돌려준다. 빈 목록이면 통과. 키는 정한 것만 허용(빠지거나 남으면 오류).
"""

from __future__ import annotations

from typing import Any

KEY_RISK_MAX = 5
LOAD_KEYS = {"rate", "basis", "condition", "text"}
CLASS_KEYS = {"class_name", "front_load", "back_load", "total_fee", "peer_total_fee"}
TIER_KEYS = {"period", "basis", "rate", "applies_to"}


def _str_or_none(x: Any) -> bool:
    return x is None or isinstance(x, str)


def _amount_ok(x: Any) -> bool:
    """{"amount": 숫자, "unit": 문자열} 또는 null."""
    if x is None:
        return True
    return (
        isinstance(x, dict)
        and set(x) == {"amount", "unit"}
        and isinstance(x["amount"], int | float)
        and not isinstance(x["amount"], bool)
        and isinstance(x["unit"], str)
        and bool(x["unit"])
    )


def _keys(x: Any, keys: set[str], where: str) -> list[str]:
    if not isinstance(x, dict):
        return [f"{where}: 객체가 아님"]
    return [] if set(x) == keys else [f"{where}: 키 {sorted(x)} != {sorted(keys)}"]


def _load(x: Any, where: str) -> list[str]:
    if x is None:  # 원문에 칸이 없음
        return []
    errs = _keys(x, LOAD_KEYS, where)
    if errs:
        return errs
    if not _amount_ok(x["rate"]):
        errs.append(f"{where}.rate: 숫자 형식 아님")
    errs += [
        f"{where}.{k}: 문자열·null 아님"
        for k in ("basis", "condition", "text")
        if not _str_or_none(x[k])
    ]
    return errs


def _fee_structure(value: Any, n_evidence: int) -> list[str]:
    errs = _keys(value, {"classes"}, "value")
    if errs:
        return errs
    classes = value["classes"]
    if not isinstance(classes, list) or not classes:
        return ["classes: 1개 이상 목록 아님"]
    for i, c in enumerate(classes):
        where = f"classes[{i}]"
        ce = _keys(c, CLASS_KEYS, where)
        if ce:
            errs += ce
            continue
        if not _str_or_none(c["class_name"]):
            errs.append(f"{where}.class_name: 문자열·null 아님")
        errs += _load(c["front_load"], f"{where}.front_load") + _load(
            c["back_load"], f"{where}.back_load"
        )
        errs += [
            f"{where}.{k}: 숫자 형식 아님"
            for k in ("total_fee", "peer_total_fee")
            if not _amount_ok(c[k])
        ]
    return errs


def _redemption_terms(value: Any, n_evidence: int) -> list[str]:
    errs = _keys(value, {"tiers"}, "value")
    if errs:
        return errs
    tiers = value["tiers"]
    if not isinstance(tiers, list):  # 빈 목록 허용(환매수수료 없음, 필드 규칙 4)
        return ["tiers: 목록 아님"]
    for i, t in enumerate(tiers):
        where = f"tiers[{i}]"
        te = _keys(t, TIER_KEYS, where)
        if te:
            errs += te
            continue
        if not isinstance(t["period"], str):
            errs.append(f"{where}.period: 문자열 아님")
        if not _str_or_none(t["basis"]):
            errs.append(f"{where}.basis: 문자열·null 아님")
        if not _amount_ok(t["rate"]):
            errs.append(f"{where}.rate: 숫자 형식 아님")
        a = t["applies_to"]
        if not (
            a is None
            or (isinstance(a, list) and a and all(isinstance(s, str) for s in a))
        ):
            errs.append(f"{where}.applies_to: 문자열 목록·null 아님")
    return errs


def _key_risk_phrases(value: Any, n_evidence: int) -> list[str]:
    if not (
        isinstance(value, list)
        and 1 <= len(value) <= KEY_RISK_MAX
        and all(isinstance(s, str) for s in value)
    ):
        return [f"value: 문자열 1~{KEY_RISK_MAX}개 목록 아님"]
    return (
        []
        if n_evidence == len(value)
        else [f"evidence {n_evidence}개 != value {len(value)}개"]
    )


def _principal_loss_notice(value: Any, n_evidence: int) -> list[str]:
    errs = (
        []
        if isinstance(value, str) and value
        else ["value: 빈 문자열이거나 문자열 아님"]
    )
    return errs + ([] if n_evidence == 1 else [f"evidence {n_evidence}개, 1개여야 함"])


VALIDATORS = {
    "fee_structure": _fee_structure,
    "redemption_terms": _redemption_terms,
    "key_risk_phrases": _key_risk_phrases,
    "principal_loss_notice": _principal_loss_notice,
}


def validate_value(field_name: str, value: Any, n_evidence: int) -> list[str]:
    """FOUND일 때 value 구조와 근거 개수 검증."""
    check = VALIDATORS.get(field_name)
    return check(value, n_evidence) if check else [f"모르는 field_name: {field_name}"]
