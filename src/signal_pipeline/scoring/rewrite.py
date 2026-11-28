"""제2부 10절(투자위험)·13절(수수료와 보수) 쉬운 문장 변환 실행기.

- 변환문은 점수 산출과 기준집단에 넣지 않고 표시·검증에만 쓴다(11월 25일 PM 결정).
- 의미 보존 검사(rewrite_check.py)를 통과하지 못한 변환문은 display_allowed=False로 표시를 차단한다.
- 대시보드 화면 3(section_scores.parquet) 합류에 바로 쓸 수 있는 JSONL 형식으로 기록한다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from signal_pipeline.extraction.bedrock import (
    MODELS,
    BedrockClient,
    CallResult,
    cost_usd,
)
from signal_pipeline.scoring.rewrite_check import (
    VALID_SECTION_KINDS,
    check_meaning_preservation,
)

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "easy_rewrite_v1.md"


class ConverseClient(Protocol):
    model: str

    def converse(self, system: str, user: str) -> CallResult: ...


@dataclass(frozen=True)
class RewriteInput:
    """쉬운 문장 변환 입력 1건."""

    rcept_no: str
    part_no: int | None
    section_no: int | None
    section_title: str
    section_kind: str
    original_excerpt: str


@dataclass(frozen=True)
class RewriteRecord:
    """쉬운 문장 변환 및 의미 보존 검사 결과 1건."""

    rcept_no: str
    part_no: int | None
    section_no: int | None
    section_title: str
    section_kind: str
    original_excerpt: str
    simplified_text: str | None
    meaning_preserved: bool
    display_allowed: bool
    missing_items: list[str]
    model: str
    prompt_sha256: str
    input_sha256: str
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    error: str | None


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_prompt(prompt_path: Path = PROMPT_PATH) -> tuple[str, str]:
    """프롬프트 텍스트와 SHA-256 해시를 반환한다."""
    text = prompt_path.read_text(encoding="utf-8").strip()
    return text, _sha256_text(text)


def infer_section_kind(part_no: int | None, section_no: int | None) -> str:
    """부·절 번호에서 의미 보존 검사 기준 종류를 추론한다."""
    if part_no == 2 and section_no == 10:
        return "section_10"
    if part_no == 2 and section_no == 13:
        return "section_13"
    return "general"


def rewrite_one(
    client: ConverseClient,
    item: RewriteInput,
    *,
    system_prompt: str,
    prompt_sha256: str,
) -> RewriteRecord:
    """단일 절 발췌문을 변환하고 의미 보존 검사를 적용한다."""
    if item.section_kind not in VALID_SECTION_KINDS:
        raise ValueError(f"지원하지 않는 section_kind: {item.section_kind}")

    input_sha = _sha256_text(item.original_excerpt)
    user_msg = (
        f"[대상 절] {item.section_title}\n\n[원문]\n{item.original_excerpt.strip()}"
    )
    res = client.converse(system=system_prompt, user=user_msg)
    call_cost: float | None = None
    if res.input_tokens is not None and res.output_tokens is not None:
        call_cost = round(
            cost_usd(client.model, res.input_tokens, res.output_tokens), 6
        )

    if res.error or not res.text:
        return RewriteRecord(
            rcept_no=item.rcept_no,
            part_no=item.part_no,
            section_no=item.section_no,
            section_title=item.section_title,
            section_kind=item.section_kind,
            original_excerpt=item.original_excerpt,
            simplified_text=None,
            meaning_preserved=False,
            display_allowed=False,
            missing_items=["호출 실패"],
            model=client.model,
            prompt_sha256=prompt_sha256,
            input_sha256=input_sha,
            input_tokens=res.input_tokens,
            output_tokens=res.output_tokens,
            cost_usd=call_cost,
            error=res.error or "빈 응답",
        )

    rewritten = res.text.strip()
    check = check_meaning_preservation(
        item.original_excerpt,
        rewritten,
        section_kind=item.section_kind,
    )
    return RewriteRecord(
        rcept_no=item.rcept_no,
        part_no=item.part_no,
        section_no=item.section_no,
        section_title=item.section_title,
        section_kind=item.section_kind,
        original_excerpt=item.original_excerpt,
        simplified_text=rewritten,
        meaning_preserved=check.passed,
        display_allowed=check.passed,
        missing_items=check.missing_items,
        model=client.model,
        prompt_sha256=prompt_sha256,
        input_sha256=input_sha,
        input_tokens=res.input_tokens,
        output_tokens=res.output_tokens,
        cost_usd=call_cost,
        error=None,
    )


def run_batch(
    items: list[RewriteInput],
    *,
    client: ConverseClient,
    budget_usd: float,
    prompt_path: Path = PROMPT_PATH,
) -> tuple[list[RewriteRecord], dict[str, Any]]:
    """입력 목록을 순차 변환하며 예산 상한 초과 시 즉시 중단한다."""
    if budget_usd <= 0:
        raise ValueError("budget_usd는 0보다 커야 한다")

    system_prompt, prompt_sha = load_prompt(prompt_path)
    records: list[RewriteRecord] = []
    spent = 0.0
    stopped_by_budget = False

    for item in items:
        if spent >= budget_usd:
            stopped_by_budget = True
            break
        rec = rewrite_one(
            client,
            item,
            system_prompt=system_prompt,
            prompt_sha256=prompt_sha,
        )
        records.append(rec)
        if rec.cost_usd is not None:
            spent += rec.cost_usd

    passed = sum(1 for r in records if r.display_allowed)
    blocked = sum(1 for r in records if not r.display_allowed and r.error is None)
    failed = sum(1 for r in records if r.error is not None)
    summary = {
        "total_inputs": len(items),
        "processed": len(records),
        "display_allowed": passed,
        "blocked_by_meaning_check": blocked,
        "call_failed": failed,
        "spent_usd": round(spent, 6),
        "budget_usd": budget_usd,
        "stopped_by_budget": stopped_by_budget,
        "model": client.model,
        "prompt_sha256": prompt_sha,
    }
    return records, summary


def load_inputs_jsonl(path: Path) -> list[RewriteInput]:
    """입력 JSONL에서 변환 대상 절 목록을 읽는다."""
    items: list[RewriteInput] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            stripped = line.strip()
            if not stripped:
                continue
            raw = json.loads(stripped)
            part_no = raw.get("part_no")
            section_no = raw.get("section_no")
            kind = raw.get("section_kind") or infer_section_kind(part_no, section_no)
            excerpt = str(raw.get("original_excerpt", "")).strip()
            if not excerpt:
                raise ValueError(f"{path}:{line_no} original_excerpt가 비어 있음")
            items.append(
                RewriteInput(
                    rcept_no=str(raw["rcept_no"]),
                    part_no=part_no,
                    section_no=section_no,
                    section_title=str(raw["section_title"]),
                    section_kind=kind,
                    original_excerpt=excerpt,
                )
            )
    return items


def main() -> None:
    parser = argparse.ArgumentParser(description="투자설명서 10절·13절 쉬운 문장 변환")
    parser.add_argument("--inputs-jsonl", type=Path, required=True)
    parser.add_argument("--out-jsonl", type=Path, required=True)
    parser.add_argument("--model", choices=sorted(MODELS.keys()), default="lite")
    parser.add_argument("--budget-usd", type=float, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    items = load_inputs_jsonl(args.inputs_jsonl)
    if args.dry_run:
        prompt_text, prompt_sha = load_prompt()
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "inputs": len(items),
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
        records, summary = run_batch(items, client=client, budget_usd=args.budget_usd)
    finally:
        client.close()

    args.out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    try:
        created.append(args.out_jsonl)
        with args.out_jsonl.open("w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")

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
