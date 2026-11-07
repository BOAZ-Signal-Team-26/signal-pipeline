"""LLM 원응답을 추출 결과 envelope(value_json)로 변환·검증(docs/io-schema.md 「LLM 추출 결과 JSON 공통 계약」). 순수 함수.

변환·검증 순서(처음 실패한 단계의 reason_code)
1. 호출 오류 → CALL_FAILED  2. JSON 파싱 → PARSE_FAILED  3. envelope·value 구조 → SCHEMA_INVALID
4. quote 위치 찾기(FOUND) → EVIDENCE_NOT_LOCATED. 정확 → 공백 무시 → 근사(0.9) → 연쇄 정렬(문장 필드) → 토큰 근접(fee_structure).
   근사·연쇄 정렬은 quote와 원문 구간의 숫자 값이 같아야 받는다
   key_risk_phrases는 못 찾은 원소만 지우고 하나라도 남으면 FOUND
5. 출처 절 확인(NOT_FOUND) → UNDETERMINED(SOURCE_SECTION_MISSING)  6. 문서 단위 중복 제거(dedupe_document)  7. 적재 검증(validate_envelope)

모델 응답: {"status", "value", "evidence": [{"quote"}], "reason_code", "notes"}. 절 식별자·위치는 변환기가 채운다.
"""

from __future__ import annotations

import json
import re
from typing import Any

from signal_pipeline.extraction import align
from signal_pipeline.extraction.inputs import FieldInput, SectionText
from signal_pipeline.extraction.schema import VALIDATORS, validate_value

CONTRACT_VERSION = 1
FOUND, NOT_FOUND, UNDETERMINED, NOT_APPLICABLE, FAILED = (
    "FOUND",
    "NOT_FOUND",
    "UNDETERMINED",
    "NOT_APPLICABLE",
    "FAILED",
)
RESULT_STATUS = {
    FOUND: "OK",
    NOT_FOUND: "OK",
    UNDETERMINED: "UNDETERMINED",
    NOT_APPLICABLE: "NOT_APPLICABLE",
    FAILED: "FAILED",
}
REASON_CODES: dict[str, set[str | None]] = {
    FOUND: {None},
    NOT_FOUND: {"NOT_IN_DOCUMENT"},
    UNDETERMINED: {"AMBIGUOUS", "SOURCE_SECTION_MISSING"},
    NOT_APPLICABLE: {"OUT_OF_SCOPE"},
    FAILED: {"CALL_FAILED", "PARSE_FAILED", "SCHEMA_INVALID", "EVIDENCE_NOT_LOCATED"},
}
# 모델이 고를 수 있는 상태와 그 reason_code. reason_code가 null이면 이 값으로 채운다
MODEL_REASON = {
    FOUND: None,
    NOT_FOUND: "NOT_IN_DOCUMENT",
    UNDETERMINED: "AMBIGUOUS",
    NOT_APPLICABLE: "OUT_OF_SCOPE",
}
PLN, KRP, FEE = "principal_loss_notice", "key_risk_phrases", "fee_structure"
WS_CHARS = " \t\n\r\f\v"
WS = re.compile(f"[{WS_CHARS}]+")
TOKEN = re.compile(f"[{WS_CHARS}]+|.", re.DOTALL)
FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)
EVIDENCE_KEYS = {"section_id", "char_start", "char_end", "quote"}


def _notes(*parts: str | None) -> str | None:
    joined = "; ".join(p for p in parts if p)
    return joined or None


def _envelope(
    field_name: str,
    status: str,
    *,
    value: Any = None,
    raw_text: str | None = None,
    reason_code: str | None = None,
    evidence: list[dict] | None = None,
    checked: list[int] | None = None,
    notes: str | None = None,
) -> dict:
    return {
        "contract_version": CONTRACT_VERSION,
        "field_name": field_name,
        "status": status,
        "value": value,
        "raw_text": raw_text,
        "reason_code": reason_code,
        "evidence": evidence or [],
        "checked_section_ids": checked or [],
        "notes": notes,
    }


def _failed(fi: FieldInput, reason_code: str, notes: str | None) -> dict:
    return _envelope(fi.field_name, FAILED, reason_code=reason_code, notes=notes)


def _parse(text: str | None) -> dict | None:
    """JSON 객체 하나. ```json 울타리는 벗긴다. 객체가 아니면 None."""
    if not text:
        return None
    body = text.strip()
    fenced = FENCE.match(body)
    try:
        data = json.loads(fenced.group(1) if fenced else body)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _collapse(text: str) -> str:
    return WS.sub(" ", text).strip()


def _check(field_name: str, data: dict) -> list[str]:
    """3단계: 모델 응답의 envelope·value 구조."""
    if field_name not in VALIDATORS:
        return [f"모르는 field_name: {field_name}"]
    status = data.get("status")
    if status not in MODEL_REASON:
        return [f"status 값이 허용 목록 밖: {status!r}"]
    errs = []
    if not (data.get("notes") is None or isinstance(data["notes"], str)):
        errs.append("notes: 문자열·null 아님")
    if data.get("reason_code") not in {None, MODEL_REASON[status]}:
        errs.append(
            f"reason_code {data['reason_code']!r}가 status {status}와 맞지 않음"
        )
    if status != FOUND:
        return errs + (
            [] if data.get("value") is None else ["FOUND가 아닌데 value가 있음"]
        )
    evidence = data.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return errs + ["FOUND인데 evidence가 비었음"]
    if not all(
        isinstance(e, dict)
        and isinstance(e.get("quote"), str)
        and _collapse(e["quote"])
        for e in evidence
    ):
        return errs + ["evidence 원소가 {quote: 비지 않은 문자열}이 아님"]
    return errs + validate_value(field_name, data.get("value"), len(evidence))


def _collapse_map(text: str, sep: str = " ") -> tuple[str, list[int]]:
    """연속 공백을 sep로 바꾼 텍스트와, 바꾼 텍스트 글자마다 원래 위치."""
    chars, pos = [], []
    for m in TOKEN.finditer(text):
        if m.group()[0] not in WS_CHARS:
            chars.append(m.group())
            pos.append(m.start())
        elif sep:
            chars.append(sep)
            pos.append(m.start())
    return "".join(chars), pos


def _evidence(sec: SectionText, start: int, end: int) -> dict:
    return {
        "section_id": sec.section_id,
        "char_start": sec.char_start + start,
        "char_end": sec.char_start + end,
        "quote": sec.text[start:end],
    }


def _locate(
    index: list[tuple[SectionText, str, list[int]]], quote: str, bare: bool = False
) -> tuple[dict | None, int]:
    """4단계: 절 하나 안에서만 찾는다. (inputs 순서로 첫 근거, 전체 일치 수)."""
    q = WS.sub("", quote) if bare else _collapse(quote)
    first, count = None, 0
    for sec, norm, pos in index:
        n = norm.count(q)
        if n and first is None:
            i = norm.find(q)
            first = _evidence(sec, pos[i], pos[i + len(q) - 1] + 1)
        count += n
    return first, count


FUZZY_MIN = 0.9  # 근사 일치 하한(11월 7일 PM 결정)
# 이보다 짧은 인용은 근사 일치하지 않음. 「A클래스 1%」와 「C클래스 1%」처럼 한두 글자 차이가 다른 행을 뜻함
FUZZY_MIN_CHARS = 20


def _fuzzy(
    bare: list[tuple[SectionText, str, list[int]]], quote: str, chain: bool
) -> tuple[dict | None, float]:
    """공백을 뺀 절 텍스트에서 기준점마다 근사 일치, 안 되면 연쇄 정렬(chain=True일 때). (근거, 유사도).

    숫자 값이 quote와 다른 후보는 버린다(원문 2.00%를 1.00%로 바꾼 인용을 받지 않음).
    """
    q = WS.sub("", quote)
    if len(q) < FUZZY_MIN_CHARS:
        return None, 0.0
    best, best_chain = (0.0, None), (0.0, None)
    for sec, norm, pos in bare:
        for g in align.anchors(q, norm):
            r, s, e = align.fuzzy(q, norm, g)
            if r > best[0] and align.same_numbers(q, norm[s:e]):
                best = (r, (sec, pos, s, e))
            c = align.chain(q, norm, g) if chain else None
            if c and c[0] > best_chain[0] and align.same_numbers(q, c[3]):
                best_chain = (c[0], (sec, pos, c[1], c[2]))
    if best[0] >= FUZZY_MIN:
        r, (sec, pos, s, e) = best
    elif best_chain[1]:
        r, (sec, pos, s, e) = best_chain
    else:
        return None, best[0]
    return _evidence(sec, pos[s], pos[e - 1] + 1), r


def _class_names(value: Any) -> tuple[str, ...]:
    """fee_structure value의 클래스 이름 목록. 다른 필드는 빈 튜플."""
    if not isinstance(value, dict) or not isinstance(value.get("classes"), list):
        return ()
    return tuple(
        c["class_name"]
        for c in value["classes"]
        if isinstance(c, dict) and c.get("class_name")
    )


def _place(
    fi: FieldInput, index: list, bare: list, quote: str, classes: tuple[str, ...] = ()
) -> tuple[dict | None, int, str | None]:
    """quote 하나의 (근거, 일치 수, 메모)."""
    located, n = _locate(index, quote)
    if located is None:
        located, n = _locate(bare, quote, bare=True)
    if located is not None:
        return located, n, None
    located, ratio = _fuzzy(bare, quote, chain=fi.field_name in (PLN, KRP))
    if located is not None:
        return located, 1, f"근사 일치 {ratio:.2f}"
    if fi.field_name == FEE and len(quote.split()) <= align.TOKEN_MAX:
        # PDF 표 셀이 다른 칸과 섞여 끊긴 경우. 인용에 없는 다른 클래스 이름이 구간에 끼면 버림
        others = tuple(c for c in classes if c and c not in quote)
        for sec in fi.sections:
            span, n = align.token_window(sec.text, quote, others)
            if span:
                return _evidence(sec, *span), n, "토큰 근접 일치"
    return None, 0, None


def _missing_note(fi: FieldInput) -> str | None:
    return f"출처 절 누락: {', '.join(fi.missing)}" if fi.missing else None


def _not_found(fi: FieldInput, notes: str | None) -> dict:
    """5단계: 출처 절이 모두 입력에 있을 때만 NOT_FOUND."""
    if fi.missing or not fi.sections:
        return _envelope(
            fi.field_name,
            UNDETERMINED,
            reason_code="SOURCE_SECTION_MISSING",
            notes=_notes(notes, _missing_note(fi)),
        )
    checked = [s.section_id for s in fi.sections]
    return _envelope(
        fi.field_name,
        NOT_FOUND,
        reason_code="NOT_IN_DOCUMENT",
        checked=checked,
        notes=notes,
    )


def _raw_text(field_name: str, value: Any, evidence: list[dict]) -> str:
    """principal_loss_notice는 value와 같음. 나머지는 근거 원문 구간을 줄바꿈으로 이음."""
    return value if field_name == PLN else "\n".join(e["quote"] for e in evidence)


def _fuzzy_value(field_name: str, value: Any, evidence: list[dict], at: list[int]):
    """근사 일치한 문장 필드는 모델이 고쳐 쓴 문장 대신 원문 구간을 값으로 씀."""
    if not at:
        return value
    if field_name == PLN:
        return evidence[0]["quote"]
    if field_name == KRP:
        return [evidence[i]["quote"] if i in at else v for i, v in enumerate(value)]
    return value


def _found(fi: FieldInput, data: dict) -> dict:
    index = [(s, *_collapse_map(s.text)) for s in fi.sections]
    # PDF 줄바꿈이 단어 중간을 끊으므로(「노\n출」) 못 찾으면 공백을 모두 지우고 다시 찾음
    bare = [(s, *_collapse_map(s.text, "")) for s in fi.sections]
    evidence, keep, extra_notes, fuzzy_at, lost = [], [], [], [], []
    classes = _class_names(data.get("value"))
    for i, e in enumerate(data["evidence"]):
        located, n, note = _place(fi, index, bare, e["quote"], classes)
        if located is None:
            lost.append(e["quote"])
            if fi.field_name != KRP:
                break
            continue
        if note:
            fuzzy_at.append(len(evidence))
            extra_notes.append(note)
        evidence.append(located)
        keep.append(i)
        if n > 1:
            extra_notes.append(f"다중 일치 {n}회")
    if lost and (fi.field_name != KRP or not evidence):
        return _failed(fi, "EVIDENCE_NOT_LOCATED", f"근거를 찾지 못함: {lost[0][:80]}")
    value = data["value"]
    if lost:
        value = [value[i] for i in keep]
        extra_notes.append(f"근거 없는 문장 {len(lost)}개 삭제")
    value = _fuzzy_value(fi.field_name, value, evidence, fuzzy_at)
    return _envelope(
        fi.field_name,
        FOUND,
        value=value,
        raw_text=_raw_text(fi.field_name, value, evidence),
        evidence=evidence,
        notes=_notes(data.get("notes"), *extra_notes, _missing_note(fi)),
    )


def convert(
    fi: FieldInput, response_text: str | None, call_error: str | None = None
) -> dict:
    """필드 1건 변환(1~5단계)."""
    if call_error is not None:
        return _failed(fi, "CALL_FAILED", call_error)
    data = _parse(response_text)
    if data is None:
        return _failed(
            fi, "PARSE_FAILED", "응답이 JSON 객체가 아님. 원응답은 response.json"
        )
    errs = _check(fi.field_name, data)
    if errs:
        return _failed(fi, "SCHEMA_INVALID", "; ".join(errs))
    status, notes = data["status"], data.get("notes")
    if status == FOUND:
        return _found(fi, data)
    if status == NOT_FOUND:
        return _not_found(fi, notes)
    return _envelope(
        fi.field_name, status, reason_code=MODEL_REASON[status], notes=notes
    )


def _overlaps(a: dict, b: dict) -> bool:
    return (
        a["section_id"] == b["section_id"]
        and a["char_start"] < b["char_end"]
        and b["char_start"] < a["char_end"]
    )


def dedupe_document(
    envelopes: dict[str, dict], key_risk_input: FieldInput | None
) -> dict[str, dict]:
    """6단계: principal_loss_notice 근거와 한 글자라도 겹치는 key_risk_phrases 원소를 지운다. 새 dict를 돌려준다.

    모두 지워지면 NOT_FOUND이고 checked_section_ids를 이번 입력의 출처 절로 채워야 하므로 key_risk_input이 필요하다.
    """
    pln, krp = envelopes.get(PLN), envelopes.get(KRP)
    if not (pln and krp and pln["status"] == FOUND and krp["status"] == FOUND):
        return dict(envelopes)
    keep = [
        i
        for i, e in enumerate(krp["evidence"])
        if not any(_overlaps(e, p) for p in pln["evidence"])
    ]
    removed = len(krp["evidence"]) - len(keep)
    if not removed:
        return dict(envelopes)
    notes = _notes(krp["notes"], f"중복 제거로 {removed}개 삭제")
    if keep:
        evidence = [krp["evidence"][i] for i in keep]
        value = [krp["value"][i] for i in keep]
        new = {
            **krp,
            "value": value,
            "raw_text": _raw_text(KRP, value, evidence),
            "evidence": evidence,
            "notes": notes,
        }
    elif key_risk_input is None:
        raise ValueError(
            "key_risk_phrases 원소가 모두 지워졌는데 key_risk_input이 없음"
        )
    else:
        new = _not_found(key_risk_input, notes)
    return {**envelopes, KRP: new}


def result_status(envelope: dict) -> str:
    """llm_field_extraction.result_status 값(「상태값」 표)."""
    return RESULT_STATUS[envelope["status"]]


def _evidence_ok(e: Any) -> bool:
    return (
        isinstance(e, dict)
        and set(e) == EVIDENCE_KEYS
        and all(isinstance(e[k], int) for k in ("section_id", "char_start", "char_end"))
        and 0 <= e["char_start"] < e["char_end"]
        and isinstance(e["quote"], str)
    )


def validate_envelope(envelope: dict) -> list[str]:
    """7단계 적재 검증. 오류 문장 목록(빈 목록이면 통과)."""
    status = envelope.get("status")
    if status not in RESULT_STATUS:
        return [f"status 값이 허용 목록 밖: {status!r}"]
    errs = []
    if envelope.get("contract_version") != CONTRACT_VERSION:
        errs.append("contract_version != 1")
    if not isinstance(envelope.get("field_name"), str):
        errs.append("field_name 없음")
    if envelope.get("reason_code") not in REASON_CODES[status]:
        errs.append(
            f"reason_code {envelope.get('reason_code')!r}가 {status}와 맞지 않음"
        )
    if not (envelope.get("notes") is None or isinstance(envelope["notes"], str)):
        errs.append("notes: 문자열·null 아님")
    evidence, checked = envelope.get("evidence"), envelope.get("checked_section_ids")
    if status == FOUND:
        if not (
            isinstance(evidence, list) and evidence and all(map(_evidence_ok, evidence))
        ):
            errs.append("FOUND인데 evidence가 비었거나 형식이 틀림")
        if not isinstance(envelope.get("raw_text"), str):
            errs.append("FOUND인데 raw_text가 문자열 아님")
        if envelope.get("value") is None:
            errs.append("FOUND인데 value 없음")
        elif isinstance(evidence, list):
            errs += validate_value(
                envelope.get("field_name"), envelope["value"], len(evidence)
            )
    else:
        if envelope.get("value") is not None or envelope.get("raw_text") is not None:
            errs.append(f"{status}인데 value·raw_text가 null 아님")
        if evidence != []:
            errs.append(f"{status}인데 evidence가 빈 배열 아님")
    if status == NOT_FOUND:
        if not (
            isinstance(checked, list)
            and checked
            and all(isinstance(i, int) for i in checked)
        ):
            errs.append("NOT_FOUND인데 checked_section_ids 없음")
    elif checked != []:
        errs.append(f"{status}인데 checked_section_ids가 빈 배열 아님")
    return errs


def selected_evidence(envelope: dict) -> tuple[int | None, int | None, int | None]:
    """조회용 칼럼 evidence_section_id·char_start·char_end = evidence[0]."""
    if not envelope.get("evidence"):
        return None, None, None
    e = envelope["evidence"][0]
    return e["section_id"], e["char_start"], e["char_end"]
