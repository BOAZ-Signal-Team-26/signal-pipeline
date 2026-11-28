"""축 1·2 검증용 LLM 이해도 평가 실행기(docs/scoring-and-population.md 11월 25일 신설).

- 같은 문항을 문서 없이(without_doc) 1회, 문서를 주고(with_doc) 1회 독립 세션으로 호출한다.
- 두 조건이 모두 완료된 쌍(paired)을 기준으로 정답률 차이(info_gain = accuracy_with_doc - accuracy_without_doc)를
  「문서가 전달한 정보량」으로 기록한다.
- 문서 없이 정답률이 높은 경우(기본 0.75 이상) ceiling_effect_flag=True를 표시해
  차이가 작다는 이유만으로 나쁜 문서로 판정하지 않도록 한다.
- 입력 길이가 max_input_chars를 넘으면 잘림 여부(input_truncated)를 기록하거나 --fail-on-truncation으로 중단한다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from signal_pipeline.extraction.bedrock import (
    MODELS,
    BedrockClient,
    CallResult,
    cost_usd,
)

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "llm_comprehension_v1.md"
VALID_FCA_LEVELS = frozenset({"핵심 메시지", "정보 회상", "해석", "응용"})
CEILING_THRESHOLD = 0.75
DEFAULT_MAX_INPUT_CHARS = 60_000
SEED_NOTE = "Bedrock Converse inferenceConfig 미지원(temperature=0 고정)"

_CIRCLED_MAP = {"①": "1", "②": "2", "③": "3", "④": "4", "⑤": "5"}
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


class ConverseClient(Protocol):
    model: str

    def converse(self, system: str, user: str) -> CallResult: ...


@dataclass(frozen=True)
class ComprehensionQuestion:
    """이해도 평가 문항 1건(사람 이해도 조사와 공유)."""

    rcept_no: str
    question_id: str
    fca_level: str
    question: str
    choices: list[str]
    gold_answer: str
    document_text: str
    cdi_percentile: float | None = None


@dataclass(frozen=True)
class TrialRecord:
    """단일 조건(without_doc / with_doc) × 반복 1회 호출 기록."""

    rcept_no: str
    question_id: str
    fca_level: str
    condition: str  # "without_doc" | "with_doc"
    repeat_no: int
    raw_answer: str | None
    normalized_answer: str | None
    gold_answer: str
    is_correct: bool
    original_doc_chars: int
    sent_doc_chars: int
    input_truncated: bool
    model: str
    prompt_sha256: str
    temperature: float
    seed: None
    grading_rule: str
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    error: str | None


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_prompt(prompt_path: Path = PROMPT_PATH) -> tuple[str, str]:
    text = prompt_path.read_text(encoding="utf-8").strip()
    return text, _sha256_text(text)


def normalize_answer(value: str | None) -> str:
    """객관식 번호(①, 1번, 1.)와 단답형 공백·대소문자를 정규화한다."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", value).strip()
    for circled, digit in _CIRCLED_MAP.items():
        text = text.replace(circled, digit)
    choice_match = re.match(r"^\(?([1-5])\)?\s*(?:번|[.)])?$", text)
    if choice_match:
        return choice_match.group(1)
    return re.sub(r"\s+", " ", text).casefold()


def parse_model_answer(raw_text: str) -> str | None:
    """모델 응답 JSON에서 answer 값을 추출한다."""
    stripped = raw_text.strip()
    candidates: list[str] = []
    fence = _JSON_FENCE_RE.search(stripped)
    if fence:
        candidates.append(fence.group(1))
    candidates.append(stripped)
    if "{" in stripped and "}" in stripped:
        first, last = stripped.find("{"), stripped.rfind("}")
        if first < last:
            candidates.append(stripped[first : last + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and "answer" in parsed:
            val = parsed["answer"]
            return str(val).strip() if val is not None else None
    return None


def grade_answer(predicted: str | None, gold: str) -> bool:
    """정규화 정확 일치로 정답 여부를 채점한다."""
    if not predicted:
        return False
    return normalize_answer(predicted) == normalize_answer(gold)


def _format_question_block(item: ComprehensionQuestion) -> str:
    lines = [f"[문항] {item.question}"]
    if item.choices:
        lines.append("[보기]")
        for idx, choice in enumerate(item.choices, 1):
            lines.append(f"{idx}. {choice}")
    return "\n".join(lines)


def _build_user_message(
    item: ComprehensionQuestion,
    *,
    condition: str,
    max_input_chars: int,
    fail_on_truncation: bool,
) -> tuple[str, int, int, bool]:
    q_block = _format_question_block(item)
    if condition == "without_doc":
        return f"[조건] 문서 미제공\n\n{q_block}", 0, 0, False

    orig_len = len(item.document_text)
    truncated = orig_len > max_input_chars
    if truncated and fail_on_truncation:
        raise ValueError(
            f"{item.rcept_no}/{item.question_id}: 문서 길이 {orig_len}자가 "
            f"상한 {max_input_chars}자를 초과해 입력 잘림이 발생합니다."
        )
    sent_doc = item.document_text[:max_input_chars] if truncated else item.document_text
    msg = f"[조건] 문서 제공\n\n[문서]\n{sent_doc}\n\n{q_block}"
    return msg, orig_len, len(sent_doc), truncated


def _rank(values: list[float]) -> list[float]:
    """동점 평균 순위(1-based)를 계산한다."""
    indexed = sorted(enumerate(values), key=lambda pair: pair[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg_rank
        i = j + 1
    return ranks


def spearman_correlation(xs: list[float], ys: list[float]) -> float | None:
    """순수 파이썬으로 스피어만 순위 상관계수를 계산한다. 분산 0 또는 표본 3 미만이면 None."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    rx = _rank(xs)
    ry = _rank(ys)
    mx = sum(rx) / len(rx)
    my = sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    den_x = math.sqrt(sum((a - mx) ** 2 for a in rx))
    den_y = math.sqrt(sum((b - my) ** 2 for b in ry))
    if den_x == 0 or den_y == 0:
        return None
    return round(num / (den_x * den_y), 4)


def run_evaluation(
    questions: list[ComprehensionQuestion],
    *,
    client: ConverseClient,
    budget_usd: float,
    repeats: int = 1,
    max_input_chars: int = DEFAULT_MAX_INPUT_CHARS,
    fail_on_truncation: bool = False,
    prompt_path: Path = PROMPT_PATH,
) -> tuple[list[TrialRecord], dict[str, Any]]:
    """문항별 without_doc / with_doc 독립 세션 평가를 실행하고 문서별 요약과 상관을 계산한다."""
    if budget_usd <= 0:
        raise ValueError("budget_usd는 0보다 커야 한다")
    if repeats < 1:
        raise ValueError("repeats는 1 이상이어야 한다")

    seen_q: set[tuple[str, str]] = set()
    for q in questions:
        key = (q.rcept_no, q.question_id)
        if key in seen_q:
            raise ValueError(f"중복 문항이 있습니다: {q.rcept_no} / {q.question_id}")
        seen_q.add(key)

    system_prompt, prompt_sha = load_prompt(prompt_path)
    trials: list[TrialRecord] = []
    spent = 0.0
    stopped_by_budget = False
    grading_rule = "normalized_exact_match_v1"

    for item in questions:
        for repeat_no in range(1, repeats + 1):
            for condition in ("without_doc", "with_doc"):
                if spent >= budget_usd:
                    stopped_by_budget = True
                    break
                user_msg, orig_chars, sent_chars, truncated = _build_user_message(
                    item,
                    condition=condition,
                    max_input_chars=max_input_chars,
                    fail_on_truncation=fail_on_truncation,
                )
                # 조건·문항마다 새 단일 턴 호출(독립 세션 보장)
                res = client.converse(system=system_prompt, user=user_msg)
                call_cost: float | None = None
                if res.input_tokens is not None and res.output_tokens is not None:
                    call_cost = round(
                        cost_usd(client.model, res.input_tokens, res.output_tokens),
                        6,
                    )
                    spent += call_cost

                if res.error or not res.text:
                    trials.append(
                        TrialRecord(
                            rcept_no=item.rcept_no,
                            question_id=item.question_id,
                            fca_level=item.fca_level,
                            condition=condition,
                            repeat_no=repeat_no,
                            raw_answer=None,
                            normalized_answer=None,
                            gold_answer=item.gold_answer,
                            is_correct=False,
                            original_doc_chars=orig_chars,
                            sent_doc_chars=sent_chars,
                            input_truncated=truncated,
                            model=client.model,
                            prompt_sha256=prompt_sha,
                            temperature=0.0,
                            seed=None,
                            grading_rule=grading_rule,
                            input_tokens=res.input_tokens,
                            output_tokens=res.output_tokens,
                            cost_usd=call_cost,
                            error=res.error or "빈 응답",
                        )
                    )
                    continue

                parsed = parse_model_answer(res.text)
                norm = normalize_answer(parsed) if parsed is not None else None
                correct = grade_answer(parsed, item.gold_answer)
                parse_err = None if parsed is not None else "JSON answer 파싱 실패"
                trials.append(
                    TrialRecord(
                        rcept_no=item.rcept_no,
                        question_id=item.question_id,
                        fca_level=item.fca_level,
                        condition=condition,
                        repeat_no=repeat_no,
                        raw_answer=parsed,
                        normalized_answer=norm,
                        gold_answer=item.gold_answer,
                        is_correct=correct,
                        original_doc_chars=orig_chars,
                        sent_doc_chars=sent_chars,
                        input_truncated=truncated,
                        model=client.model,
                        prompt_sha256=prompt_sha,
                        temperature=0.0,
                        seed=None,
                        grading_rule=grading_rule,
                        input_tokens=res.input_tokens,
                        output_tokens=res.output_tokens,
                        cost_usd=call_cost,
                        error=parse_err,
                    )
                )
            if stopped_by_budget:
                break
        if stopped_by_budget:
            break

    summary = summarize_trials(
        questions,
        trials,
        model=client.model,
        prompt_sha256=prompt_sha,
        repeats=repeats,
        grading_rule=grading_rule,
        spent_usd=spent,
        budget_usd=budget_usd,
        stopped_by_budget=stopped_by_budget,
    )
    return trials, summary


def summarize_trials(
    questions: list[ComprehensionQuestion],
    trials: list[TrialRecord],
    *,
    model: str,
    prompt_sha256: str,
    repeats: int,
    grading_rule: str,
    spent_usd: float,
    budget_usd: float,
    stopped_by_budget: bool,
) -> dict[str, Any]:
    """두 조건이 모두 완료된 쌍(paired)을 기준으로 문서별 info_gain·최대치 효과·상관을 집계한다."""
    cdi_by_doc = {q.rcept_no: q.cdi_percentile for q in questions}
    docs_order = list(dict.fromkeys(q.rcept_no for q in questions))

    per_doc: list[dict[str, Any]] = []
    corr_x: list[float] = []
    corr_y: list[float] = []

    for rcept in docs_order:
        wo_map = {
            (t.question_id, t.repeat_no): t
            for t in trials
            if t.rcept_no == rcept and t.condition == "without_doc"
        }
        wi_map = {
            (t.question_id, t.repeat_no): t
            for t in trials
            if t.rcept_no == rcept and t.condition == "with_doc"
        }
        paired_keys = sorted(set(wo_map) & set(wi_map))
        wo_paired = [wo_map[k] for k in paired_keys]
        wi_paired = [wi_map[k] for k in paired_keys]

        acc_wo = (
            round(sum(t.is_correct for t in wo_paired) / len(wo_paired), 4)
            if wo_paired
            else None
        )
        acc_wi = (
            round(sum(t.is_correct for t in wi_paired) / len(wi_paired), 4)
            if wi_paired
            else None
        )
        gain = (
            round(acc_wi - acc_wo, 4)
            if acc_wo is not None and acc_wi is not None
            else None
        )
        ceiling = acc_wo is not None and acc_wo >= CEILING_THRESHOLD
        truncated = any(t.input_truncated for t in wi_paired)
        cdi_pct = cdi_by_doc.get(rcept)
        if cdi_pct is not None and gain is not None:
            corr_x.append(cdi_pct)
            corr_y.append(gain)
        per_doc.append(
            {
                "rcept_no": rcept,
                "cdi_percentile": cdi_pct,
                "paired_trials": len(paired_keys),
                "unpaired_trials": len(set(wo_map) ^ set(wi_map)),
                "accuracy_without_doc": acc_wo,
                "accuracy_with_doc": acc_wi,
                "info_gain": gain,
                "ceiling_effect_flag": ceiling,
                "any_input_truncated": truncated,
            }
        )

    return {
        "model": model,
        "prompt_sha256": prompt_sha256,
        "temperature": 0.0,
        "seed": None,
        "seed_note": SEED_NOTE,
        "repeats": repeats,
        "grading_rule": grading_rule,
        "ceiling_threshold": CEILING_THRESHOLD,
        "total_questions": len(questions),
        "total_trials": len(trials),
        "truncated_trials": sum(1 for t in trials if t.input_truncated),
        "error_trials": sum(1 for t in trials if t.error is not None),
        "spent_usd": round(spent_usd, 6),
        "budget_usd": budget_usd,
        "stopped_by_budget": stopped_by_budget,
        "spearman_cdi_vs_info_gain": spearman_correlation(corr_x, corr_y),
        "per_document": per_doc,
    }


def load_questions_jsonl(path: Path) -> list[ComprehensionQuestion]:
    """문항 JSONL 파일을 읽어 검증한다."""
    items: list[ComprehensionQuestion] = []
    seen: set[tuple[str, str]] = set()
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            stripped = line.strip()
            if not stripped:
                continue
            raw = json.loads(stripped)
            rcept_no = str(raw["rcept_no"]).strip()
            question_id = str(raw["question_id"]).strip()
            if (rcept_no, question_id) in seen:
                raise ValueError(
                    f"{path}:{line_no} 중복 문항: {rcept_no} / {question_id}"
                )
            seen.add((rcept_no, question_id))

            fca_level = str(raw["fca_level"]).strip()
            if fca_level not in VALID_FCA_LEVELS:
                raise ValueError(f"{path}:{line_no} 알 수 없는 fca_level: {fca_level}")
            doc_text = str(raw.get("document_text", "")).strip()
            if not doc_text:
                raise ValueError(f"{path}:{line_no} document_text가 비어 있음")
            cdi_val = raw.get("cdi_percentile")
            items.append(
                ComprehensionQuestion(
                    rcept_no=rcept_no,
                    question_id=question_id,
                    fca_level=fca_level,
                    question=str(raw["question"]).strip(),
                    choices=[str(c).strip() for c in (raw.get("choices") or [])],
                    gold_answer=str(raw["gold_answer"]).strip(),
                    document_text=doc_text,
                    cdi_percentile=float(cdi_val) if cdi_val is not None else None,
                )
            )
    return items


def main() -> None:
    parser = argparse.ArgumentParser(
        description="축 1·2 검증용 LLM 이해도 평가(문서 미제공 vs 제공)"
    )
    parser.add_argument("--questions-jsonl", type=Path, required=True)
    parser.add_argument("--out-jsonl", type=Path, required=True)
    parser.add_argument("--model", choices=sorted(MODELS.keys()), default="lite")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--max-input-chars", type=int, default=DEFAULT_MAX_INPUT_CHARS)
    parser.add_argument("--fail-on-truncation", action="store_true")
    parser.add_argument("--budget-usd", type=float, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    questions = load_questions_jsonl(args.questions_jsonl)
    if args.dry_run:
        prompt_text, prompt_sha = load_prompt()
        truncated_docs = sum(
            1 for q in questions if len(q.document_text) > args.max_input_chars
        )
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "questions": len(questions),
                    "planned_calls": len(questions) * args.repeats * 2,
                    "truncated_questions": truncated_docs,
                    "model": MODELS[args.model],
                    "prompt_chars": len(prompt_text),
                    "prompt_sha256": prompt_sha,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    summary_path = args.out_jsonl.with_suffix(".summary.json")
    if args.budget_usd is None:
        raise SystemExit("--dry-run이 아니면 --budget-usd가 필수입니다.")
    if args.out_jsonl.exists():
        raise SystemExit(f"기존 출력 파일을 덮어쓰지 않습니다: {args.out_jsonl}")
    if summary_path.exists():
        raise SystemExit(f"기존 요약 파일을 덮어쓰지 않습니다: {summary_path}")

    client = BedrockClient(model=MODELS[args.model])
    try:
        trials, summary = run_evaluation(
            questions,
            client=client,
            budget_usd=args.budget_usd,
            repeats=args.repeats,
            max_input_chars=args.max_input_chars,
            fail_on_truncation=args.fail_on_truncation,
        )
    finally:
        client.close()

    args.out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    try:
        created.append(args.out_jsonl)
        with args.out_jsonl.open("w", encoding="utf-8") as fh:
            for trial in trials:
                fh.write(json.dumps(asdict(trial), ensure_ascii=False) + "\n")

        created.append(summary_path)
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception:
        for path in created:
            if path.exists():
                path.unlink()
        raise
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
