"""축 4(고지 충실도) 점검표 v0 항목 10개 판정. DB 없는 순수 함수.

규칙 정본: docs/scoring-and-population.md 「점검표 v0 판정 대상」·「결과 상태와 결측」
- 판정 4종: MET(있음) / UNMET(없음) / NOT_APPLICABLE(적용 대상 아님) / UNDETERMINED(판정 불가)
- 근거 위치 = 절 char_start + 절 텍스트 안 위치. 정규식은 정규화 없는 원문에 적용한다
- 없음(UNMET)이면 검사한 절(checked_section_ids)이 비어 있지 않다
- 출처 절이 없거나 쓸 수 없으면 UNDETERMINED/SOURCE_SECTION_MISSING. 절이 하나도 없는 문서는 10항목 모두 DOCUMENT_NOT_EXTRACTED
- LLM 항목(나2·4.1·4.2)의 공통 판정 불가: 선택 행 없음 LLM_NOT_RUN, FAILED INPUT_FAILED, 모델이 판정 불가면 그 사유
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from signal_pipeline.extraction.inputs import OK as EXTRACT_OK

MET, UNMET, NOT_APPLICABLE, UNDETERMINED = (
    "MET",
    "UNMET",
    "NOT_APPLICABLE",
    "UNDETERMINED",
)
ITEMS = ("나1", "나2", "3.1", "3.2", "3.3", "3.4", "4.1", "4.2", "4.3", "11.2")
SOURCE_MISSING = "SOURCE_SECTION_MISSING"
TOC_HEAD_CHARS = 300  # 목차 절 판정에 쓰는 절 본문 앞부분 길이
EVIDENCE_KEYS = ("section_id", "char_start", "char_end")
# 키워드 자산 shape: 항목 -> 필수 목록 이름
KEYWORD_SHAPE: dict[str, tuple[str, ...]] = {
    "3.1": ("any",),
    "3.2": ("any",),
    "3.3": ("meaning", "caution"),
    "3.4": ("any",),
    "11.2": ("any",),
    "body": ("pointer", "pointer_same_doc", "pointer_other_doc"),
    "toc": ("any",),
}
# 문장 끝: 마침표류 뒤 공백, 또는 다/요 뒤 줄바꿈. 그 밖의 줄바꿈은 문장 안 공백이다
_SENTENCE = re.compile(r"(?<=[.!?。])\s+|(?<=[다요])[ \t]*\n\s*")


@dataclass(frozen=True)
class SectionRow:
    section_id: int
    section_seq: int
    part_seq: int | None
    source_section_no: str | None
    section_kind: str
    section_title: str | None
    char_start: int | None
    char_end: int | None
    extract_status: str
    # 판정에 쓰는 절만 텍스트를 읽는다(그 밖의 절은 None일 수 있음)
    section_text: str | None


@dataclass(frozen=True)
class LlmRow:
    extraction_id: int
    result_status: str
    value_json: Mapping[str, Any] | None


@dataclass(frozen=True)
class DocInput:
    document_id: int
    sections: tuple[SectionRow, ...]
    llm: Mapping[str, LlmRow]  # field_name -> 선택된 행
    # 연결 상품 중 etf_confidence가 KRX_CONFIRMED인 것이 있음
    etf_confirmed: bool = False
    # 보고서명 규칙(extraction.inputs.is_etf). LLM 추출이 ETF를 뺀 기준과 같은 함수
    etf_by_name: bool = False


@dataclass(frozen=True)
class Judgment:
    item: str
    status: str
    reason_code: str | None = None  # MET·UNMET이면 None
    evidence: tuple[dict, ...] = ()
    checked_section_ids: tuple[int, ...] = ()
    matched: tuple[str, ...] = ()
    llm_extraction_ids: tuple[int, ...] = ()
    notes: str | None = None

    def __post_init__(self) -> None:
        if self.status == UNMET and not self.checked_section_ids:
            raise ValueError(f"{self.item}: 없음인데 검사한 절이 없음")
        if self.status in (MET, UNMET) and self.reason_code is not None:
            raise ValueError(f"{self.item}: {self.status}은 reason_code가 없음")
        if self.status not in (MET, UNMET) and not self.reason_code:
            raise ValueError(f"{self.item}: {self.status}은 reason_code 필수")


def validate_keywords(asset: Mapping[str, Any]) -> Mapping[str, Any]:
    """키워드 자산 shape 검사. 위반이면 ValueError, 통과하면 그대로 돌려준다. 정규식은 컴파일해 본다."""
    items = asset.get("items")
    if not isinstance(items, Mapping):
        raise ValueError("키워드 자산: items 없음")  # noqa: TRY004
    for item, names in KEYWORD_SHAPE.items():
        group = items.get(item)
        if not isinstance(group, Mapping):
            raise ValueError(f"키워드 자산: items.{item} 없음")  # noqa: TRY004
        for name in names:
            entries = group.get(name)
            if not isinstance(entries, list) or not entries:
                raise ValueError(
                    f"키워드 자산: items.{item}.{name}이 빈 목록이거나 없음"
                )
            ids = [e.get("id") if isinstance(e, Mapping) else None for e in entries]
            if not all(isinstance(i, str) and i for i in ids) or len(set(ids)) != len(
                ids
            ):
                raise ValueError(
                    f"키워드 자산: items.{item}.{name}의 id가 비었거나 중복"
                )
            for e in entries:
                try:
                    re.compile(e["re"])
                except (KeyError, TypeError, re.error) as error:
                    raise ValueError(
                        f"키워드 자산: items.{item}.{name}.{e['id']}의 re 오류: {error}"
                    ) from error
    return asset


def usable(sec: SectionRow | None) -> bool:
    return (
        sec is not None
        and sec.extract_status == EXTRACT_OK
        and sec.section_text is not None
        and sec.char_start is not None
    )


def _evidence(sec: SectionRow, start: int, end: int) -> dict:
    return {
        "section_id": sec.section_id,
        "char_start": sec.char_start + start,
        "char_end": sec.char_start + end,
    }


def _patterns(entries: Sequence[Mapping[str, str]]) -> list[tuple[str, re.Pattern]]:
    return [(e["id"], re.compile(e["re"])) for e in entries]


def _find_all(
    sections: Sequence[SectionRow], entries: Sequence[Mapping[str, str]]
) -> list[tuple[str, dict]]:
    """패턴마다 절 순서대로 처음 일치하는 곳 하나. [(패턴 id, 근거)]."""
    found = []
    for pid, pattern in _patterns(entries):
        for sec in sections:
            m = pattern.search(sec.section_text)
            if m:
                found.append((pid, _evidence(sec, m.start(), m.end())))
                break
    return found


def _label_section(doc: DocInput, part: int, no: str) -> SectionRow | None:
    """part_seq·source_section_no가 같은 절. 중복이면 section_seq 최소."""
    rows = [s for s in doc.sections if s.part_seq == part and s.source_section_no == no]
    return min(rows, key=lambda s: s.section_seq) if rows else None


def _is_toc(sec: SectionRow, keywords: Mapping[str, Any]) -> bool:
    """제목이나 본문 앞부분이 목차 패턴에 일치하면 목차 절."""
    head = (sec.section_title or "") + "\n" + sec.section_text[:TOC_HEAD_CHARS]
    return any(p.search(head) for _, p in _patterns(keywords["items"]["toc"]["any"]))


def _cover(doc: DocInput, keywords: Mapping[str, Any]) -> tuple[list[SectionRow], bool]:
    """표지 절(첫 body 절 앞의 other 절, 목차 제외)과 불완전 여부(읽지 못한 절이 있거나 표지가 없음)."""
    # body 절이 하나도 없으면 목차가 아닌 other 절 전체가 표지다
    first = min(
        (s.section_seq for s in doc.sections if s.section_kind == "body"),
        default=float("inf"),
    )
    others = sorted(
        (
            s
            for s in doc.sections
            if s.section_kind == "other" and s.section_seq < first
        ),
        key=lambda s: s.section_seq,
    )
    readable = [s for s in others if usable(s)]
    kept = [s for s in readable if not _is_toc(s, keywords)]
    return kept, len(readable) < len(others) or not kept


def _absent(
    item: str, sections: Sequence[SectionRow], incomplete: bool, **kw
) -> Judgment:
    """일치가 없을 때: 검사한 절이 온전하면 없음, 아니면 판정 불가."""
    if incomplete or not sections:
        return Judgment(item, UNDETERMINED, SOURCE_MISSING, **kw)
    return Judgment(
        item, UNMET, checked_section_ids=tuple(s.section_id for s in sections), **kw
    )


def _any_item(
    item: str, sections: Sequence[SectionRow], incomplete: bool, entries
) -> Judgment:
    hits = _find_all(sections, entries)
    if hits:
        return Judgment(
            item,
            MET,
            evidence=tuple(e for _, e in hits),
            matched=tuple(pid for pid, _ in hits),
            checked_section_ids=tuple(s.section_id for s in sections),
        )
    return _absent(item, sections, incomplete)


def _judge_33(sections: Sequence[SectionRow], keywords: Mapping[str, Any]) -> Judgment:
    """등급 체계의 뜻과 주의 문구가 모두 있어야 있음(AND)."""
    group = keywords["items"]["3.3"]
    meaning = _find_all(sections, group["meaning"])
    caution = _find_all(sections, group["caution"])
    if meaning and caution:
        return Judgment(
            "3.3",
            MET,
            evidence=tuple(e for _, e in meaning + caution),
            matched=tuple(
                [f"meaning:{p}" for p, _ in meaning]
                + [f"caution:{p}" for p, _ in caution]
            ),
            checked_section_ids=tuple(s.section_id for s in sections),
        )
    lacking = [
        n for n, hit in (("등급 체계의 뜻", meaning), ("주의 문구", caution)) if not hit
    ]
    return _absent("3.3", sections, False, notes=f"없는 것: {', '.join(lacking)}")


def _risk_item(item: str, doc: DocInput, keywords: Mapping[str, Any]) -> Judgment:
    """3.1·3.2·3.3. 출처 = 제2부 10절."""
    sec = _label_section(doc, 2, "10")
    sections = [sec] if usable(sec) else []
    if not sections:
        return Judgment(item, UNDETERMINED, SOURCE_MISSING)
    if item == "3.3":
        return _judge_33(sections, keywords)
    return _any_item(item, sections, False, keywords["items"][item]["any"])


def _cover_item(item: str, doc: DocInput, keywords: Mapping[str, Any]) -> Judgment:
    """3.4·11.2. 출처 = 표지."""
    sections, incomplete = _cover(doc, keywords)
    return _any_item(item, sections, incomplete, keywords["items"][item]["any"])


# ---- 본문 규칙(나1·4.3) ----


def _hit(patterns: Sequence[tuple[str, re.Pattern]], sentence: str) -> bool:
    """문장에서 패턴 하나라도 일치. 줄바꿈을 공백으로 바꾼 문장과 지운 문장(단어 중간 줄바꿈)에도 시도한다."""
    variants = (sentence, sentence.replace("\n", " "), sentence.replace("\n", ""))
    return any(p.search(v) for _, p in patterns for v in variants)


def _body_verdict(
    sec: SectionRow, keywords: Mapping[str, Any]
) -> tuple[str, dict | None, tuple[str, ...]]:
    """절 1개의 본문 판정. (종류, 근거, 일치한 패턴). 종류: MET / TITLE_ONLY / POINTER_OTHER_DOC / TITLE_NOT_LOCATED."""
    text = sec.section_text
    chars = "".join((sec.section_title or "").split())
    m = re.search(r"\s*".join(map(re.escape, chars)), text) if chars else None
    if not m:
        return "TITLE_NOT_LOCATED", None, ()
    remainder = text[: m.start()] + text[m.end() :]
    if not remainder.strip():
        return "TITLE_ONLY", None, ()
    idx = [
        i
        for i, c in enumerate(text)
        if not c.isspace() and not m.start() <= i < m.end()
    ]
    evidence = _evidence(sec, idx[0], idx[-1] + 1)
    group = keywords["items"]["body"]
    sentences = [s.strip() for s in _SENTENCE.split(remainder) if s.strip()]
    pointer = _patterns(group["pointer"])
    if not all(_hit(pointer, s) for s in sentences):
        return "MET", evidence, ()
    same = [
        f"pointer_same_doc:{i}"
        for i, p in _patterns(group["pointer_same_doc"])
        if any(_hit([(i, p)], s) for s in sentences)
    ]
    other = [
        f"pointer_other_doc:{i}"
        for i, p in _patterns(group["pointer_other_doc"])
        if any(_hit([(i, p)], s) for s in sentences)
    ]
    if same or not other:  # 같은 문서를 가리키거나 어느 쪽인지 모르면 있음
        return "MET", evidence, tuple(same)
    return "POINTER_OTHER_DOC", None, tuple(other)


BODY_NOTES = {
    "TITLE_ONLY": "제목만 있고 본문이 없음",
    "POINTER_OTHER_DOC": "본문이 다른 문서를 가리키기만 함",
    "TITLE_NOT_LOCATED": "절 텍스트에서 절 제목 위치를 찾지 못함",
    "MISSING": "출처 절이 없거나 쓸 수 없음",
}


def _body_item(
    item: str,
    labelled: Sequence[tuple[str, SectionRow | None]],
    keywords: Mapping[str, Any],
) -> Judgment:
    """제목 밖 본문이 있는 절들. 하나라도 확정 없음이면 없음, 아니고 하나라도 판정 못 하면 판정 불가."""
    results = []
    for label, sec in labelled:
        if usable(sec):
            results.append((label, sec, *_body_verdict(sec, keywords)))
        else:
            results.append((label, None, "MISSING", None, ()))
    notes = (
        "; ".join(
            f"{label}: {BODY_NOTES[kind]}"
            for label, _, kind, _, _ in results
            if kind != "MET"
        )
        or None
    )
    matched = tuple(m for *_, ms in results for m in ms)
    examined = tuple(sec.section_id for _, sec, *_ in results if sec)
    kinds = {kind for _, _, kind, _, _ in results}
    if kinds & {"TITLE_ONLY", "POINTER_OTHER_DOC"}:
        return Judgment(
            item, UNMET, checked_section_ids=examined, matched=matched, notes=notes
        )
    if kinds - {"MET"}:
        reason = SOURCE_MISSING if "MISSING" in kinds else "TITLE_NOT_LOCATED"
        return Judgment(item, UNDETERMINED, reason, matched=matched, notes=notes)
    return Judgment(
        item,
        MET,
        evidence=tuple(ev for _, _, _, ev, _ in results),
        checked_section_ids=examined,
        matched=matched,
    )


# ---- LLM 항목(나2·4.1·4.2) ----


def _view(row: LlmRow | None) -> tuple[str, str | None]:
    """선택 행 → (FOUND·NOT_FOUND·NOT_APPLICABLE·UNDETERMINED, 판정 불가 사유)."""
    if row is None:
        return UNDETERMINED, "LLM_NOT_RUN"
    if row.result_status == "FAILED":
        return UNDETERMINED, "INPUT_FAILED"
    env = row.value_json or {}
    status = env.get("status")
    if status in ("FOUND", "NOT_FOUND", NOT_APPLICABLE):
        return status, env.get("reason_code")
    return UNDETERMINED, env.get("reason_code") or "INPUT_FAILED"


def _llm_evidence(row: LlmRow) -> list[dict]:
    """value_json.evidence에서 quote를 뺀 세 키."""
    return [
        {k: e[k] for k in EVIDENCE_KEYS} for e in row.value_json.get("evidence", [])
    ]


def _checked(row: LlmRow) -> list[int]:
    return list((row.value_json or {}).get("checked_section_ids") or [])


def _ids(rows: Sequence[LlmRow | None]) -> tuple[int, ...]:
    return tuple(r.extraction_id for r in rows if r)


def _llm_item(
    item: str, field: str, doc: DocInput, source: SectionRow | None
) -> Judgment:
    """source = 출처 절. LLM이 검사한 절을 주지 않으면 이 절 id로 대신하고, 이 절도 없으면 판정 불가."""
    row = doc.llm.get(field)
    kind, reason = _view(row)
    ids = _ids([row])
    if kind == "FOUND":
        return Judgment(
            item, MET, evidence=tuple(_llm_evidence(row)), llm_extraction_ids=ids
        )
    if kind == "NOT_FOUND":
        checked = _checked(row) or ([source.section_id] if source else [])
        if not checked:
            return Judgment(item, UNDETERMINED, SOURCE_MISSING, llm_extraction_ids=ids)
        return Judgment(
            item, UNMET, checked_section_ids=tuple(checked), llm_extraction_ids=ids
        )
    return Judgment(item, UNDETERMINED, reason, llm_extraction_ids=ids)


def _judge_41(doc: DocInput) -> Judgment:
    sec13 = _label_section(doc, 2, "13")
    if not usable(sec13):
        return Judgment("4.1", UNDETERMINED, SOURCE_MISSING)
    return _llm_item("4.1", "fee_structure", doc, sec13)


def _judge_42(doc: DocInput) -> Judgment:
    if doc.etf_confirmed:
        return Judgment("4.2", NOT_APPLICABLE, "ETF_KRX_CONFIRMED")
    if doc.etf_by_name:
        return Judgment("4.2", NOT_APPLICABLE, "ETF_REPORT_NAME")
    row = doc.llm.get("redemption_terms")
    if _view(row)[0] == NOT_APPLICABLE:
        return Judgment(
            "4.2", NOT_APPLICABLE, "OUT_OF_SCOPE", llm_extraction_ids=_ids([row])
        )
    return _llm_item("4.2", "redemption_terms", doc, _label_section(doc, 2, "11"))


def _judge_na2(doc: DocInput) -> Judgment:
    sec10 = _label_section(doc, 2, "10")
    if not usable(sec10):
        return Judgment("나2", UNDETERMINED, SOURCE_MISSING)
    pln, krp = doc.llm.get("principal_loss_notice"), doc.llm.get("key_risk_phrases")
    views = [_view(pln), _view(krp)]
    ids = _ids([pln, krp])
    not_found = [r for r, (k, _) in zip((pln, krp), views) if k == "NOT_FOUND"]
    phrases = (krp.value_json or {}).get("value") if krp else None
    if not_found or (all(k == "FOUND" for k, _ in views) and not phrases):
        checked = sorted({i for r in not_found for i in _checked(r)}) or [
            sec10.section_id
        ]
        return Judgment(
            "나2", UNMET, checked_section_ids=tuple(checked), llm_extraction_ids=ids
        )
    if all(k == "FOUND" for k, _ in views):
        return Judgment(
            "나2",
            MET,
            evidence=tuple(_llm_evidence(pln) + _llm_evidence(krp)),
            llm_extraction_ids=ids,
        )
    reason = next(r for k, r in views if k != "FOUND")
    return Judgment("나2", UNDETERMINED, reason, llm_extraction_ids=ids)


def judge_document(doc: DocInput, keywords: Mapping[str, Any]) -> list[Judgment]:
    """문서 1건의 10항목 판정. 순서 = ITEMS."""
    if not doc.sections:
        return [Judgment(i, UNDETERMINED, "DOCUMENT_NOT_EXTRACTED") for i in ITEMS]
    body = [
        (f"제{p}부 {n}절", _label_section(doc, p, n))
        for p, n in ((2, "7"), (2, "8"), (2, "9"))
    ]
    judged = {
        "나1": _body_item("나1", body, keywords),
        "나2": _judge_na2(doc),
        "3.1": _risk_item("3.1", doc, keywords),
        "3.2": _risk_item("3.2", doc, keywords),
        "3.3": _risk_item("3.3", doc, keywords),
        "3.4": _cover_item("3.4", doc, keywords),
        "4.1": _judge_41(doc),
        "4.2": _judge_42(doc),
        "4.3": _body_item(
            "4.3", [("제5부 2절", _label_section(doc, 5, "2"))], keywords
        ),
        "11.2": _cover_item("11.2", doc, keywords),
    }
    return [judged[i] for i in ITEMS]
