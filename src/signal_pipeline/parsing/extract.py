"""DART 투자설명서 본문 PDF → 텍스트·부/절 구조 추출. 한 번 돌리면 실행 기록과 요약을 남긴다.

입력:  {RAW_ROOT}/raw/dart/{접수번호}/body_pdf__v{n}.pdf (접수번호별 최신 판)
출력:  {RAW_ROOT}/derived/{raw_sha256}/{parser_version}/text.txt, structure.json
       {RAW_ROOT}/runs/{run_id}/extraction_attempts.jsonl, run.json
규칙: docs/storage-and-failure-rules.md 「파생 텍스트·실행 스냅숏 경로」「추출 실패와 절 품질」.
이미 추출된 결과(structure.json의 text_sha256이 text.txt와 같음)는 건너뛴다.

용례: RAW_ROOT=... uv run python -m signal_pipeline.parsing.extract [--limit N] [--workers 4]
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pdfplumber

from signal_pipeline.common.runlog import RunLog
from signal_pipeline.common.storage import RawStore, is_pdf, sha256_hex, write_atomic
from signal_pipeline.parsing import parallel
from signal_pipeline.parsing.dart_sections import (
    SectionSplitError,
    SplitResult,
    invariant_violations,
    split_sections,
)
from signal_pipeline.parsing.pdf_layout import PdfLayout, PdfTextError, read_pdf
from signal_pipeline.parsing.regions import (
    bookmark_check,
    page_furniture_regions,
    table_regions,
)

# 후처리·부절 분할·구간 규칙을 바꾸면 올린다
# 2: 절을 앞 절 뒤에서만 찾음. 3: 본문 부를 반복·되돌아간 표제를 건너뛰며 고름
# 4: pdftotext → pdfplumber(PR #49 4-3), 요약정보·other 구간, 표·머리글 구간, 모든 EXTRACT_OK에 structure.json
PREP_VERSION = 4
SCHEMA_VERSION = 2
OCR_MIN_CHARS = 100  # 공백 제외 글자 수가 이보다 적으면 OCR 후보
FILE_TIMEOUT_SECONDS = 300  # 파일 1건 제한. pdfplumber는 502건 평균 수 초~수십 초
DEFAULT_WORKERS = 4
# 잠정값. 실측으로 검증되지 않았다
SHORT_TEXT_CHARS = 500
BROKEN_RATIO = 0.3
BROKEN_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f�]")
PRODUCER_FAMILIES = ("word", "itext", "oz", "adobe", "gaaiho", "ezpdf", "foxit")


def parser_version() -> str:
    """예: pdfplumber-0.11_prep-4 (형식 규칙: 소문자·숫자·`.`·`-`·`_`)."""
    major_minor = ".".join(pdfplumber.__version__.split(".")[:2])
    return f"pdfplumber-{major_minor}_prep-{PREP_VERSION}"


def producer_family(producer: str) -> str:
    lowered = producer.lower()
    return next((f for f in PRODUCER_FAMILIES if f in lowered), "other")


def quality_flags(section_text: str) -> list[str]:
    """절 본문 품질 신호(잠정값, 실패 아님)."""
    flags = []
    if len(section_text) < SHORT_TEXT_CHARS:
        flags.append("SHORT_TEXT")
    if (
        section_text
        and len(BROKEN_CONTROL.findall(section_text)) / len(section_text)
        >= BROKEN_RATIO
    ):
        flags.append("BROKEN_CHARS")
    return flags


def build_structure(
    layout: PdfLayout,
    split: SplitResult | None,
    *,
    raw_sha256: str,
    version: str,
    source_key: str,
    raw_storage_path: str,
    text_path: str,
    text_sha256: str,
) -> dict[str, object]:
    """structure.json 내용. split이 None이면(「제N부」 없음) parts·sections는 빈 목록."""
    text = layout.text
    sections = []
    for sec in split.sections if split else []:
        found = sec.char_start is not None and sec.char_end is not None
        flags = (
            quality_flags(text[sec.char_start : sec.char_end])
            if found and sec.section_kind == "body"
            else []
        )
        sections.append(
            {
                "section_seq": sec.section_seq,
                "section_kind": sec.section_kind,
                "part_seq": sec.part_seq,
                "source_section_no": sec.source_section_no,
                "title": sec.title,
                "title_char_start": sec.title_char_start,
                "title_char_end": sec.title_char_end,
                "char_start": sec.char_start,
                "char_end": sec.char_end,
                "extract_status": sec.extract_status,
                "quality_flags": flags,
                "canonical_section_code": None,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "raw_sha256": raw_sha256,
        "parser_version": version,
        "source_key": source_key,
        "raw_storage_path": raw_storage_path,
        "text_path": text_path,
        "text_sha256": text_sha256,
        "text_length": len(text),
        "structure_status": "AVAILABLE" if split else "UNAVAILABLE",
        "headings_source": "BOOKMARK" if layout.bookmarks else "RULE",
        "pdf_producer": layout.producer,
        "page_starts": layout.page_starts,
        "parts": [asdict(p) for p in split.parts] if split else [],
        "sections": sections,
        "toc_section_count": split.toc_section_count if split else 0,
        "toc_part_count": split.toc_part_count if split else 0,
        "page_furniture_regions": page_furniture_regions(text),
        "table_regions": table_regions(text, layout.tables),
        "bookmark_count": len(layout.bookmarks),
        "bookmark_check": bookmark_check(layout.bookmarks, split),
        "blocks": None,
        "missing_regions": [],
    }


@dataclass
class FileResult:
    """파일 1건 처리 결과. record는 extraction_attempts.jsonl 한 줄, 나머지는 요약용."""

    record: dict[str, object]
    structure: dict[str, object] | None = None
    text_length: int | None = None
    flags: list[str] = field(default_factory=list)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _record(
    run_id: str, raw_path: str, sha: str | None, key: str, version: str, started: str
) -> dict:
    """키 순서가 고정된 기록 틀. 처리 결과로 칸을 채운다."""
    return {
        "run_id": run_id,
        "raw_object_id": None,
        "raw_sha256": sha,
        "raw_storage_path": raw_path,
        "source_key": key,
        "parser_version": version,
        "action": "EXTRACTED",
        "extract_status": None,
        "structure_status": "UNAVAILABLE",
        "error_reason": None,
        "text_path": None,
        "text_sha256": None,
        "text_length": None,
        "structure_path": None,
        "structure_sha256": None,
        "section_count": None,
        "section_found_count": None,
        "started_at": started,
        "finished_at": None,
    }


def _existing(root: Path, text_rel: str, struct_rel: str) -> dict | None:
    """structure.json이 있고 text_sha256이 text.txt와 같으면 그 내용. 아니면 None."""
    try:
        structure = json.loads((root / struct_rel).read_text(encoding="utf-8"))
        text_hash = sha256_hex((root / text_rel).read_bytes())
    except (OSError, ValueError):
        return None
    return structure if structure.get("text_sha256") == text_hash else None


def _fill_ok(rec: dict, structure: dict, struct_rel: str, struct_sha: str) -> None:
    """EXTRACT_OK 기록 칸 채우기. section_count는 본문(body) 절만 센다(적중률 분모)."""
    rec["extract_status"] = "EXTRACT_OK"
    rec["structure_status"] = structure["structure_status"]
    rec["text_path"], rec["text_sha256"] = (
        structure["text_path"],
        structure["text_sha256"],
    )
    rec["text_length"] = structure["text_length"]
    rec["structure_path"], rec["structure_sha256"] = struct_rel, struct_sha
    body = [s for s in structure["sections"] if s["section_kind"] == "body"]
    rec["section_count"] = len(body)
    rec["section_found_count"] = sum(s["char_start"] is not None for s in body)


def process_file(root: Path, pdf: Path, run_id: str, version: str) -> FileResult:
    started = _now()
    data = pdf.read_bytes()
    sha = sha256_hex(data)
    raw_rel = str(pdf.relative_to(root))
    rec = _record(run_id, raw_rel, sha, pdf.parent.name, version, started)
    base = f"derived/{sha}/{version}"
    text_rel, struct_rel = f"{base}/text.txt", f"{base}/structure.json"

    def done(status: str, reason: str | None = None) -> FileResult:
        rec["extract_status"], rec["error_reason"], rec["finished_at"] = (
            status,
            reason,
            _now(),
        )
        return FileResult(rec)

    existing = _existing(root, text_rel, struct_rel)
    if existing:  # 구조 없음(UNAVAILABLE)도 EXTRACT_OK면 다시 추출하지 않는다
        rec["action"] = "SKIPPED_EXISTING_OK"
        raw = (root / struct_rel).read_bytes()
        _fill_ok(rec, existing, struct_rel, sha256_hex(raw))
        rec["finished_at"] = _now()
        return _ok(rec, existing)

    if not is_pdf(data):
        return done("EXTRACT_UNSUPPORTED_FORMAT", "PDF 시그니처(%PDF-)가 없다")
    try:
        layout = read_pdf(pdf)
    except PdfTextError as exc:
        return done("EXTRACT_FAILED", str(exc))
    text = layout.text
    if len(re.sub(r"\s", "", text)) < OCR_MIN_CHARS:
        return done(
            "OCR_CANDIDATE",
            f"공백 제외 {len(re.sub(r'\s', '', text))}자 (<{OCR_MIN_CHARS})",
        )

    text_bytes = text.encode("utf-8")
    text_sha = sha256_hex(text_bytes)
    try:
        split = split_sections(text)
    except SectionSplitError:
        split = None
    if split is not None:
        problems = invariant_violations(split, len(text))
        if problems:
            return done(
                "EXTRACT_FAILED", "절 구간 불변식 위반: " + "; ".join(problems[:5])
            )
    structure = build_structure(
        layout,
        split,
        raw_sha256=sha,
        version=version,
        source_key=rec["source_key"],
        raw_storage_path=raw_rel,
        text_path=text_rel,
        text_sha256=text_sha,
    )
    (root / base).mkdir(parents=True, exist_ok=True)
    write_atomic(root / text_rel, text_bytes)  # text.txt → structure.json 순서
    raw = json.dumps(structure, ensure_ascii=False, indent=1).encode("utf-8")
    write_atomic(root / struct_rel, raw)
    _fill_ok(rec, structure, struct_rel, sha256_hex(raw))
    rec["finished_at"] = _now()
    return _ok(rec, structure)


def _ok(rec: dict, structure: dict) -> FileResult:
    flags = [f for s in structure["sections"] for f in s["quality_flags"]]
    return FileResult(rec, structure, rec["text_length"], flags)


def _percentile(values: list[float], q: float) -> float | None:
    """가장 가까운 순위 방식 분위수. 값이 없으면 None."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def _table_stats(docs: list[dict]) -> dict[str, object]:
    """표 안 글자 비율(문서별 표 구간 길이 합 ÷ 글자 수)의 중앙값. 전체와 생성 도구별."""
    by_family: dict[str, list[float]] = {}
    for d in docs:
        if not d["text_length"]:
            continue
        inside = sum(t["char_end"] - t["char_start"] for t in d["table_regions"])
        family = producer_family(d.get("pdf_producer", ""))
        by_family.setdefault(family, []).append(inside / d["text_length"])
    every = [v for values in by_family.values() for v in values]
    return {
        "docs_without_table": sum(not d["table_regions"] for d in docs),
        "ratio_median": statistics.median(every) if every else None,
        "ratio_median_by_producer": {
            f: {"docs": len(v), "median": round(statistics.median(v), 3)}
            for f, v in sorted(by_family.items())
        },
        "tables_with_sentences": sum(
            t["has_sentences"] for d in docs for t in d["table_regions"]
        ),
        "tables": sum(len(d["table_regions"]) for d in docs),
    }


def _bookmark_stats(docs: list[dict]) -> dict[str, object]:
    marked = [d for d in docs if d["headings_source"] == "BOOKMARK"]
    total = (
        {
            k: sum(d["bookmark_check"][k] for d in marked)
            for k in marked[0]["bookmark_check"]
        }
        if marked
        else {}
    )
    g = total.get
    return {
        "docs": len(marked),
        "part_recall": _ratio(g("matched_parts", 0), g("bookmark_parts", 0)),
        "part_precision": _ratio(g("matched_parts", 0), g("rule_parts", 0)),
        "section_recall": _ratio(g("matched_sections", 0), g("bookmark_sections", 0)),
        "section_precision": _ratio(g("matched_sections", 0), g("rule_sections", 0)),
        "counts": total,
    }


def summarize(
    results: list[FileResult], version: str, elapsed: float
) -> dict[str, object]:
    recs = [r.record for r in results]
    n = len(recs)
    status = {}
    for r in recs:
        status[r["extract_status"]] = status.get(r["extract_status"], 0) + 1
    ok = status.get("EXTRACT_OK", 0)
    reasons: dict[str, int] = {}
    for r in recs:
        if r["extract_status"] != "EXTRACT_OK":
            key = str(r["error_reason"]).split(":")[0][:60]
            reasons[key] = reasons.get(key, 0) + 1
    file_fail = n - ok
    unavailable = [
        r["source_key"]
        for r in recs
        if r["extract_status"] == "EXTRACT_OK"
        and r["structure_status"] == "UNAVAILABLE"
    ]
    all_docs = [r.structure for r in results if r.structure]
    docs = [d for d in all_docs if d["structure_status"] == "AVAILABLE"]
    toc_docs = [d for d in docs if d["toc_part_count"] > 0]
    secs = [s for d in docs for s in d["sections"] if s["section_kind"] == "body"]
    found_secs = [s for s in secs if s["char_start"] is not None]
    rates = [
        sum(
            s["char_start"] is not None and s["section_kind"] == "body"
            for s in d["sections"]
        )
        / d["toc_section_count"]
        for d in docs
        if d["toc_section_count"] > 0
    ]
    lengths = [r.text_length for r in results if r.text_length]
    short = sum("SHORT_TEXT" in s["quality_flags"] for s in found_secs)
    return {
        "N_files": n,
        "extract_ok": ok,
        "extract_ok_ratio": ok / n if n else None,
        "status_counts": status,
        "skipped_existing": sum(r["action"] == "SKIPPED_EXISTING_OK" for r in recs),
        "file_fail": {
            "count": file_fail,
            "ratio": file_fail / n if n else None,
            "by_reason": reasons,
        },
        "document_fail": {
            "part_not_detected": len(unavailable),
            "ratio_of_extract_ok": len(unavailable) / ok if ok else None,
            "source_keys": unavailable,
        },
        "part_hit": {
            # 목차에 부가 4개만 있는 문서가 있어 문서별로 목차 부 수를 넘지 않게 센다
            "found": sum(min(len(d["parts"]), d["toc_part_count"]) for d in toc_docs),
            "toc": sum(d["toc_part_count"] for d in toc_docs),
            "all_5_docs": sum(len(d["parts"]) == 5 for d in docs),
            "split_attempted_docs": len(docs),
        },
        "section_hit": {
            "found": len(found_secs),
            "toc": sum(d["toc_section_count"] for d in docs),
            "per_doc_min": min(rates) if rates else None,
            "per_doc_p10": _percentile(rates, 0.1),
            "per_doc_median": statistics.median(rates) if rates else None,
        },
        "summary_section_docs": sum(
            any(s["section_kind"] == "summary" for s in d["sections"]) for d in docs
        ),
        "furniture_docs": sum(bool(d["page_furniture_regions"]) for d in all_docs),
        "tables": _table_stats(all_docs),
        "bookmark_vs_rule": _bookmark_stats(all_docs),
        "quality": {
            "short_text_sections": short,
            "short_text_ratio": short / len(found_secs) if found_secs else None,
            "broken_chars_sections": sum(
                "BROKEN_CHARS" in s["quality_flags"] for s in found_secs
            ),
            "text_length_min": min(lengths) if lengths else None,
            "text_length_median": statistics.median(lengths) if lengths else None,
            "text_length_max": max(lengths) if lengths else None,
            "note": f"{SHORT_TEXT_CHARS}자·{BROKEN_RATIO:.0%} 기준은 미검증 잠정값",
        },
        "env": {
            "parser_version": version,
            "machine": platform.machine(),
            "elapsed_seconds": round(elapsed, 1),
        },
    }


def format_report(s: dict[str, object]) -> str:
    """사람이 읽는 요약."""
    pct = lambda v: "-" if v is None else f"{v:.1%}"
    ff, df, ph, sh, q = (
        s["file_fail"],
        s["document_fail"],
        s["part_hit"],
        s["section_hit"],
        s["quality"],
    )
    tb, bm = s["tables"], s["bookmark_vs_rule"]
    lines = [
        (
            f"텍스트화 {s['extract_ok']}/{s['N_files']} ({pct(s['extract_ok_ratio'])}), "
            f"재사용 {s['skipped_existing']}, 상태 {s['status_counts']}"
        ),
        f"파일 실패 {ff['count']} ({pct(ff['ratio'])}) {ff['by_reason']}",
        f"제N부 미검출 {df['part_not_detected']} ({pct(df['ratio_of_extract_ok'])}) {df['source_keys']}",
        f"부 적중 {ph['found']}/{ph['toc']}, 5부 모두 {ph['all_5_docs']}/{ph['split_attempted_docs']}",
        (
            f"절 적중 {sh['found']}/{sh['toc']}, 문서별 최소 {pct(sh['per_doc_min'])} "
            f"p10 {pct(sh['per_doc_p10'])} 중앙 {pct(sh['per_doc_median'])}"
        ),
        f"요약정보 구간 문서 {s['summary_section_docs']}, 머리글 구간 문서 {s['furniture_docs']}",
        (
            f"표 {tb['tables']}개(문장 포함 {tb['tables_with_sentences']}), 표 없는 문서 {tb['docs_without_table']}, "
            f"표 안 글자 비율 중앙 {pct(tb['ratio_median'])} {tb['ratio_median_by_producer']}"
        ),
        (
            f"책갈피 문서 {bm['docs']}: 부 재현율 {pct(bm['part_recall'])} 정밀도 {pct(bm['part_precision'])}, "
            f"절 재현율 {pct(bm['section_recall'])} 정밀도 {pct(bm['section_precision'])}"
        ),
        (
            f"품질 SHORT_TEXT {q['short_text_sections']} ({pct(q['short_text_ratio'])}), "
            f"BROKEN_CHARS {q['broken_chars_sections']}, 글자수 최소/중앙/최대 "
            f"{q['text_length_min']}/{q['text_length_median']}/{q['text_length_max']} ({q['note']})"
        ),
        f"환경 {s['env']}",
    ]
    return "\n".join(lines)


def latest_pdfs(store: RawStore) -> list[Path]:
    """접수번호별 최신 body_pdf 1건."""
    base = store.root / "raw" / "dart"
    folders = sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []
    found = (store.latest("dart", f.name, "body_pdf", "pdf") for f in folders)
    return [p for p in found if p is not None]


def _failed(
    root: Path, pdf: Path, run_id: str, version: str, reason: str
) -> FileResult:
    """파일 1건이 실패한 기록. 원본 해시는 읽을 수 있으면 채운다."""
    started = _now()
    try:
        sha = sha256_hex(pdf.read_bytes())
    except OSError:
        sha = None
    rec = _record(
        run_id, str(pdf.relative_to(root)), sha, pdf.parent.name, version, started
    )
    rec["extract_status"] = "EXTRACT_FAILED"
    rec["error_reason"] = reason[:200]
    rec["finished_at"] = _now()
    return FileResult(rec)


def _process_isolated(root: Path, pdf: Path, run_id: str, version: str) -> FileResult:
    """파일 1건의 예상 밖 오류(읽기 실패, 깨진 structure.json 등)가 실행 전체를 멈추지 않게 한다."""
    try:
        return process_file(root, pdf, run_id, version)
    except Exception as exc:  # noqa: BLE001 — 파일 단위 격리. 사유는 기록에 남김
        return _failed(
            root, pdf, run_id, version, f"예상 밖 오류 {type(exc).__name__}: {exc}"
        )


def run(
    root: Path,
    limit: int | None = None,
    *,
    workers: int = DEFAULT_WORKERS,
    timeout: float = FILE_TIMEOUT_SECONDS,
) -> dict[str, object]:
    began = time.monotonic()
    version = parser_version()
    pdfs = latest_pdfs(RawStore(root))[:limit]
    log = RunLog(
        root,
        datetime.now(UTC).date().isoformat(),
        {"parser_version": version, "limit": limit, "workers": workers},
    )
    outcomes = parallel.run_isolated(
        _process_isolated,
        [(root, pdf, log.run_id, version) for pdf in pdfs],
        workers=workers,
        timeout=timeout,
    )
    results = [
        value
        if state == "ok"
        else _failed(root, pdf, log.run_id, version, f"{state}: {value}")
        for pdf, (state, value) in zip(pdfs, outcomes, strict=True)
    ]
    for r in results:  # 실행 끝에 입력 순서대로 한 번 쓴다
        log.append("extraction_attempts.jsonl", r.record)
        log.outcomes[str(r.record["extract_status"])] += 1
    summary = summarize(results, version, time.monotonic() - began)
    log.finish("SUCCEEDED", summary)
    print(f"run_id {log.run_id}")
    print(format_report(summary))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, help="앞에서 N건만 처리")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    args = parser.parse_args()
    root = os.environ.get("RAW_ROOT")
    if not root:
        print("RAW_ROOT 환경 변수가 필요하다", file=sys.stderr)
        return 2
    run(Path(root), args.limit, workers=args.workers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
