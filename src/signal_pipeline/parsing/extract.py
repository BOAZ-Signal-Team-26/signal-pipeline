"""DART 투자설명서 본문 PDF → 텍스트·부/절 구조 추출. 한 번 돌리면 실행 기록과 요약을 남긴다.

입력:  {RAW_ROOT}/raw/dart/{접수번호}/body_pdf__v{n}.pdf (접수번호별 최신 판)
출력:  {RAW_ROOT}/derived/{raw_sha256}/{parser_version}/text.txt, structure.json
       {RAW_ROOT}/runs/{run_id}/extraction_attempts.jsonl, run.json
규칙: docs/storage-and-failure-rules.md 「파생 텍스트·실행 스냅숏 경로」「추출 실패와 절 품질」.
이미 추출된 결과(structure.json의 canonical_text_sha256이 text.txt와 같음)는 건너뛴다.
단 표 분리가 실패한 결과(table_split_status = FAILED)는 다음 실행에서 다시 추출한다(PR #49 4-6).
실행 기록은 파일 하나가 끝날 때마다 덧붙인다(실행 도중 멈춰도 끝난 파일의 기록은 남음).

용례: RAW_ROOT=... uv run python -m signal_pipeline.parsing.extract [--limit N] [--workers 2]
동시 작업 수 기본값은 환경 변수 EXTRACT_WORKERS, 없으면 2(PR #28 Airflow 동시 작업 2).
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
from collections import Counter
from dataclasses import asdict, dataclass
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
    emphasis_blocks,
    page_furniture_blocks,
    subheading_blocks,
    summary_label_blocks,
    table_blocks,
)

# 후처리·부절 분할·구간 규칙·structure.json 형식을 바꾸면 올린다
# 2: 절을 앞 절 뒤에서만 찾음. 3: 본문 부를 반복·되돌아간 표제를 건너뛰며 고름
# 4: pdftotext → pdfplumber(PR #49 4-3), 요약정보·other 구간, 표·머리글 구간, 모든 EXTRACT_OK에 structure.json
# 5: PR #49 4-6 형식(blocks 5종, 표 분리 상태, 책갈피 없으면 대조 null), PR #43 필드 이름
# 6: 목차·본문 절 제목이 앞부분만 같아도 찾음, 앞 문장에 붙은 「제N부」 표제를 찾음(PR #51 표본 검토)
# 7: 목차 「기타 … 관련회사」 합본 절을 본문의 관련회사별 절로 나눔(sections `in_toc`, `toc_replaced_sections`)
# 8: 다른 부를 언급하는 문장을 부 표제로 잡지 않음, 같은 번호의 비슷한 제목 줄을 절 시작으로 받음(#60)
PREP_VERSION = 8
CONTRACT_VERSION = 3
OCR_MIN_CHARS = 100  # 공백 제외 글자 수가 이보다 적으면 OCR 후보
FILE_TIMEOUT_SECONDS = 300  # 파일 1건 제한. pdfplumber는 502건 평균 수 초~수십 초
DEFAULT_WORKERS = 2
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


def structure_status(split: SplitResult | None, table_split_status: str) -> str:
    """부·절 구조가 없으면 UNAVAILABLE, 있는데 표 분리만 실패하면 PARTIAL."""
    if split is None:
        return "UNAVAILABLE"
    return "AVAILABLE" if table_split_status == "OK" else "PARTIAL"


def build_blocks(layout: PdfLayout, split: SplitResult | None) -> list[dict]:
    """structure.json `blocks`. 시작 위치 순(같으면 끝 위치, 종류 순)."""
    text = layout.text
    tables = table_blocks(text, layout.tables)
    furniture = page_furniture_blocks(text)
    skip = [(b["char_start"], b["char_end"]) for b in tables + furniture]
    blocks = (
        tables
        + furniture
        + subheading_blocks(text, split, skip)
        + summary_label_blocks(layout.first_column_cells, split)
        + emphasis_blocks(layout.emphasis)
    )
    return sorted(blocks, key=lambda b: (b["char_start"], b["char_end"], b["kind"]))


def build_structure(
    layout: PdfLayout,
    split: SplitResult | None,
    *,
    raw_sha256: str,
    version: str,
    source_key: str,
    raw_storage_path: str,
    canonical_text_path: str,
    canonical_text_sha256: str,
) -> dict[str, object]:
    """structure.json 내용(PR #49 4-6). split이 None이면(「제N부」 없음) parts·sections는 빈 목록."""
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
                "in_toc": sec.in_toc,
                "quality_flags": flags,
                "canonical_section_code": None,
            }
        )
    return {
        "contract_version": CONTRACT_VERSION,
        "raw_sha256": raw_sha256,
        "parser_version": version,
        "source_key": source_key,
        "raw_storage_path": raw_storage_path,
        "canonical_text_path": canonical_text_path,
        "canonical_text_sha256": canonical_text_sha256,
        "text_length": len(text),
        "structure_status": structure_status(split, layout.table_split_status),
        "table_split_status": layout.table_split_status,
        "pdf_producer": layout.producer,
        "page_starts": layout.page_starts,
        "parts": [asdict(p) for p in split.parts] if split else [],
        "sections": sections,
        "toc_section_count": split.toc_section_count if split else 0,
        "toc_part_count": split.toc_part_count if split else 0,
        "toc_replaced_sections": [
            {"part_seq": part, "source_section_no": no, "title": title}
            for part, no, title in (split.toc_replaced if split else [])
        ],
        "bookmark_count": len(layout.bookmarks),
        "bookmark_check": bookmark_check(layout.bookmarks, split),
        "blocks": build_blocks(layout, split),
        "missing_regions": [],
    }


def digest(structure: dict) -> dict[str, object]:
    """실행 요약에 필요한 값만. 부모 프로세스가 파일마다 structure 전체를 들고 있지 않게 한다."""
    body = [s for s in structure["sections"] if s["section_kind"] == "body"]
    found = [s for s in body if s["char_start"] is not None]
    blocks = structure["blocks"]
    tables = [b for b in blocks if b["kind"] == "table"]
    return {
        "structure_status": structure["structure_status"],
        "table_split_status": structure["table_split_status"],
        "text_length": structure["text_length"],
        "pdf_producer": structure["pdf_producer"],
        "parts": len(structure["parts"]),
        "toc_part_count": structure["toc_part_count"],
        "toc_section_count": structure["toc_section_count"],
        # 목차 절 중 범위를 찾았거나 본문 절로 대신한 수. toc_section_count를 넘지 않는다
        "body_found": sum(s["in_toc"] for s in found)
        + len(structure["toc_replaced_sections"]),
        "body_only": sum(not s["in_toc"] for s in found),
        "short_text": sum("SHORT_TEXT" in s["quality_flags"] for s in found),
        "broken_chars": sum("BROKEN_CHARS" in s["quality_flags"] for s in found),
        "has_summary": any(
            s["section_kind"] == "summary" for s in structure["sections"]
        ),
        "block_counts": dict(Counter(b["kind"] for b in blocks)),
        "tables": len(tables),
        "tables_with_sentences": sum(b["has_sentences"] for b in tables),
        "table_chars": sum(b["char_end"] - b["char_start"] for b in tables),
        "bookmark_check": structure["bookmark_check"],
    }


@dataclass
class FileResult:
    """파일 1건 처리 결과. record는 extraction_attempts.jsonl 한 줄, doc은 요약용 값(digest)."""

    record: dict[str, object]
    doc: dict[str, object] | None = None


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
        "table_split_status": None,
        "error_reason": None,
        "canonical_text_path": None,
        "canonical_text_sha256": None,
        "text_length": None,
        "structure_manifest_path": None,
        "structure_manifest_sha256": None,
        "section_count": None,
        "section_found_count": None,
        "started_at": started,
        "finished_at": None,
    }


def _existing(root: Path, text_rel: str, struct_rel: str) -> dict | None:
    """다시 쓸 수 있는 structure.json 내용. 아니면 None.

    canonical_text_sha256이 text.txt와 같고 표 분리가 실패하지 않은 결과만 다시 쓴다.
    """
    try:
        structure = json.loads((root / struct_rel).read_text(encoding="utf-8"))
        text_hash = sha256_hex((root / text_rel).read_bytes())
    except (OSError, ValueError):
        return None
    if structure.get("canonical_text_sha256") != text_hash:
        return None
    return structure if structure.get("table_split_status") != "FAILED" else None


def _fill_ok(rec: dict, structure: dict, struct_rel: str, struct_sha: str) -> None:
    """EXTRACT_OK 기록 칸 채우기. section_count는 본문(body) 절만 센다(적중률 분모)."""
    rec["extract_status"] = "EXTRACT_OK"
    rec["structure_status"] = structure["structure_status"]
    rec["table_split_status"] = structure["table_split_status"]
    rec["canonical_text_path"] = structure["canonical_text_path"]
    rec["canonical_text_sha256"] = structure["canonical_text_sha256"]
    rec["text_length"] = structure["text_length"]
    rec["structure_manifest_path"] = struct_rel
    rec["structure_manifest_sha256"] = struct_sha
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
    if (
        existing
    ):  # 구조 없음(UNAVAILABLE)도 표 분리가 실패하지 않았으면 다시 추출하지 않는다
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
        canonical_text_path=text_rel,
        canonical_text_sha256=text_sha,
    )
    (root / base).mkdir(parents=True, exist_ok=True)
    write_atomic(root / text_rel, text_bytes)  # text.txt → structure.json 순서
    raw = json.dumps(structure, ensure_ascii=False, indent=1).encode("utf-8")
    write_atomic(root / struct_rel, raw)
    _fill_ok(rec, structure, struct_rel, sha256_hex(raw))
    if (
        layout.table_split_error
    ):  # 파일은 성공. 같은 PDF가 계속 실패하면 같은 사유가 반복된다
        rec["error_reason"] = f"표 분리 실패: {layout.table_split_error}"
    rec["finished_at"] = _now()
    return _ok(rec, structure)


def _ok(rec: dict, structure: dict) -> FileResult:
    return FileResult(rec, digest(structure))


def _percentile(values: list[float], q: float) -> float | None:
    """가장 가까운 순위 방식 분위수. 값이 없으면 None."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def _table_stats(docs: list[dict]) -> dict[str, object]:
    """표 안 글자 비율(문서별 표 구간 길이 합 ÷ 글자 수)의 중앙값. 전체와 생성 도구별.

    표 분리가 실패한 문서는 표 위치를 모르므로 비율에서 뺀다.
    """
    split = [d for d in docs if d["table_split_status"] == "OK"]
    by_family: dict[str, list[float]] = {}
    for d in split:
        if d["text_length"]:
            family = producer_family(d["pdf_producer"])
            by_family.setdefault(family, []).append(d["table_chars"] / d["text_length"])
    every = [v for values in by_family.values() for v in values]
    return {
        "split_failed_docs": len(docs) - len(split),
        "docs_without_table": sum(not d["tables"] for d in split),
        "ratio_median": statistics.median(every) if every else None,
        "ratio_median_by_producer": {
            f: {"docs": len(v), "median": round(statistics.median(v), 3)}
            for f, v in sorted(by_family.items())
        },
        "tables_with_sentences": sum(d["tables_with_sentences"] for d in split),
        "tables": sum(d["tables"] for d in split),
    }


def _bookmark_stats(docs: list[dict]) -> dict[str, object]:
    marked = [d["bookmark_check"] for d in docs if d["bookmark_check"] is not None]
    total = Counter()
    for check in marked:
        total.update(check)
    g = total.get
    return {
        "docs": len(marked),
        "part_recall": _ratio(g("matched_parts", 0), g("bookmark_parts", 0)),
        "part_precision": _ratio(g("matched_parts", 0), g("rule_parts", 0)),
        "section_recall": _ratio(g("matched_sections", 0), g("bookmark_sections", 0)),
        "section_precision": _ratio(g("matched_sections", 0), g("rule_sections", 0)),
        "counts": dict(total),
    }


def summarize(
    results: list[FileResult], version: str, elapsed: float
) -> dict[str, object]:
    recs = [r.record for r in results]
    n = len(recs)
    status = Counter(r["extract_status"] for r in recs)
    ok = status.get("EXTRACT_OK", 0)
    reasons = Counter(
        str(r["error_reason"]).split(":")[0][:60]
        for r in recs
        if r["extract_status"] != "EXTRACT_OK"
    )
    file_fail = n - ok
    unavailable = [
        r["source_key"]
        for r in recs
        if r["extract_status"] == "EXTRACT_OK"
        and r["structure_status"] == "UNAVAILABLE"
    ]
    all_docs = [r.doc for r in results if r.doc]
    docs = [d for d in all_docs if d["structure_status"] != "UNAVAILABLE"]
    toc_docs = [d for d in docs if d["toc_part_count"] > 0]
    found = sum(d["body_found"] for d in docs)
    rates = [
        d["body_found"] / d["toc_section_count"]
        for d in docs
        if d["toc_section_count"] > 0
    ]
    lengths = [d["text_length"] for d in all_docs if d["text_length"]]
    short = sum(d["short_text"] for d in docs)
    blocks = Counter()
    for d in all_docs:
        blocks.update(d["block_counts"])
    return {
        "N_files": n,
        "extract_ok": ok,
        "extract_ok_ratio": ok / n if n else None,
        "status_counts": dict(status),
        "skipped_existing": sum(r["action"] == "SKIPPED_EXISTING_OK" for r in recs),
        "file_fail": {
            "count": file_fail,
            "ratio": file_fail / n if n else None,
            "by_reason": dict(reasons),
        },
        "document_fail": {
            "part_not_detected": len(unavailable),
            "ratio_of_extract_ok": len(unavailable) / ok if ok else None,
            "source_keys": unavailable,
        },
        "part_hit": {
            # 목차에 부가 4개만 있는 문서가 있어 문서별로 목차 부 수를 넘지 않게 센다
            "found": sum(min(d["parts"], d["toc_part_count"]) for d in toc_docs),
            "toc": sum(d["toc_part_count"] for d in toc_docs),
            "all_5_docs": sum(d["parts"] == 5 for d in docs),
            "split_attempted_docs": len(docs),
        },
        "section_hit": {
            "found": found,
            "toc": sum(d["toc_section_count"] for d in docs),
            "body_only": sum(d["body_only"] for d in docs),
            "per_doc_min": min(rates) if rates else None,
            "per_doc_p10": _percentile(rates, 0.1),
            "per_doc_median": statistics.median(rates) if rates else None,
        },
        "summary_section_docs": sum(d["has_summary"] for d in docs),
        "furniture_docs": sum(
            d["block_counts"].get("page_furniture", 0) > 0 for d in all_docs
        ),
        "blocks": dict(sorted(blocks.items())),
        "tables": _table_stats(all_docs),
        "bookmark_vs_rule": _bookmark_stats(all_docs),
        "quality": {
            "short_text_sections": short,
            "short_text_ratio": short / found if found else None,
            "broken_chars_sections": sum(d["broken_chars"] for d in docs),
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
            f"절 적중 {sh['found']}/{sh['toc']}(목차에 없는 본문 절 {sh['body_only']}), 문서별 최소 {pct(sh['per_doc_min'])} "
            f"p10 {pct(sh['per_doc_p10'])} 중앙 {pct(sh['per_doc_median'])}"
        ),
        f"요약정보 구간 문서 {s['summary_section_docs']}, 머리글 구간 문서 {s['furniture_docs']}",
        f"블록 {s['blocks']}",
        (
            f"표 분리 실패 문서 {tb['split_failed_docs']}, "
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


def default_workers() -> int:
    """동시 작업 수. 실행 설정(환경 변수 EXTRACT_WORKERS)에서 받는다."""
    return int(os.environ.get("EXTRACT_WORKERS") or DEFAULT_WORKERS)


def run(
    root: Path,
    limit: int | None = None,
    *,
    workers: int | None = None,
    timeout: float = FILE_TIMEOUT_SECONDS,
) -> dict[str, object]:
    began = time.monotonic()
    version = parser_version()
    workers = workers or default_workers()
    pdfs = latest_pdfs(RawStore(root))[:limit]
    log = RunLog(
        root,
        datetime.now(UTC).date().isoformat(),
        {"parser_version": version, "limit": limit, "workers": workers},
    )
    results: list[FileResult | None] = [None] * len(pdfs)

    def record(index: int, outcome: tuple[str, object]) -> None:
        """파일 하나가 끝날 때마다 실행 기록에 덧붙인다(끝난 순서)."""
        state, value = outcome
        result = (
            value
            if state == "ok"
            else _failed(root, pdfs[index], log.run_id, version, f"{state}: {value}")
        )
        log.append("extraction_attempts.jsonl", result.record)
        log.outcomes[str(result.record["extract_status"])] += 1
        results[index] = result

    parallel.run_isolated(
        _process_isolated,
        [(root, pdf, log.run_id, version) for pdf in pdfs],
        workers=workers,
        timeout=timeout,
        on_result=record,
    )
    done = [r for r in results if r is not None]
    summary = summarize(done, version, time.monotonic() - began)
    log.finish("SUCCEEDED", summary)
    print(f"run_id {log.run_id}")
    print(format_report(summary))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, help="앞에서 N건만 처리")
    parser.add_argument(
        "--workers", type=int, help="동시 작업 수(기본: EXTRACT_WORKERS 또는 2)"
    )
    args = parser.parse_args()
    root = os.environ.get("RAW_ROOT")
    if not root:
        print("RAW_ROOT 환경 변수가 필요하다", file=sys.stderr)
        return 2
    run(Path(root), args.limit, workers=args.workers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
