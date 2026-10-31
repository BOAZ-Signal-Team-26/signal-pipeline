"""DART 수집 원본 + prep-7 절 분할 결과를 로컬 PostgreSQL에 적재한다(document, raw_object, file_extraction, section).

사용: DATABASE_URL=postgresql://... uv run python -m signal_pipeline.loading.local_load DATA_DIR [--checksum]

- 파서 버전은 기본으로 추출기와 같은 값(extract.parser_version()). 추출 기록은 그 버전의 마지막 전체 실행
  (runs/extract-*/)의 extraction_attempts.jsonl 한 개에서만 읽는다(--run-id로 지정 가능).
- 표는 raw·staging·mart 스키마에 있다(docs/data-model.md 「물리 결정」 6). 접속할 때 검색 경로를 지정하므로
  SQL은 스키마 없는 표 이름을 쓴다.
- 문서 종류·정정 여부·보고서명은 목록 응답(raw/dart/_list/)의 report_nm에서 수집기와 같은 규칙(classify_report)으로 정한다.
  본문 PDF 파일명(「간이」 포함 여부)은 문서 종류에 쓰지 않는다. document는 접수 단위이기 때문이다.
- 다시 적재 방식: 4개 표와 pipeline_run을 `TRUNCATE ... RESTART IDENTITY`로 비운 뒤 정렬 순서대로 넣는다.
  자연키가 같고 입력이 같으면 ID 발급 순서도 같아 두 번 실행해도 결과가 같다. PostgreSQL은 참조하는 표를
  모두 나열하거나 CASCADE를 요구하므로 CASCADE를 쓴다. CASCADE로 같이 비워질 하위 표(score 등)에 행이 있거나,
  비울 표에 이 스크립트가 넣지 않는 행(DART 밖 출처 문서·원본, EXTRACT가 아닌 실행)이 있으면 `--force` 없이는 멈춘다.
- 실행 전체가 트랜잭션 하나다. 중간에 실패하면 이전 상태 그대로다.
- file_extraction.created_run_id가 pipeline_run을 참조(NOT NULL)하므로 그 실행 1행만 pipeline_run에 넣는다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import psycopg
from psycopg.types.json import Jsonb

from signal_pipeline.collectors.dart import LIST_FOLDER, Kind, classify_report
from signal_pipeline.common.storage import encode_source_key, sha256_hex
from signal_pipeline.parsing.extract import parser_version

SOURCE = "dart"
SEARCH_PATH = "raw,staging,mart"
RCEPT_RE = re.compile(r"^\d{14}$")
# viewer_tree는 raw_object.file_role CHECK에 없어 적재하지 않는다
ROLE_FORMAT = {
    "body_pdf": ("pdf", "application/pdf"),
    "cover_html": ("html", "text/html"),
    "cover_xml": ("zip", "application/zip"),
}
# TRUNCATE 대상. 스키마를 붙여 써서 검색 경로와 무관하게 같은 표를 가리킨다
TABLES = (
    "staging.section",
    "staging.file_extraction",
    "raw.raw_object",
    "raw.document",
    "raw.pipeline_run",
)
CHECKSUM_ORDER = {
    "pipeline_run": "run_id",
    "document": "document_id",
    "raw_object": "raw_object_id",
    "file_extraction": "raw_object_id, parser_version",
    "section": "section_id",
}


@dataclass
class Rows:
    """적재할 행 묶음. raw/file_extraction/section은 document 접수번호·raw 키로 부모를 가리킨다."""

    pipeline_run: dict[str, Any]
    documents: list[dict[str, Any]] = field(default_factory=list)
    raw_objects: list[dict[str, Any]] = field(default_factory=list)
    extractions: list[dict[str, Any]] = field(default_factory=list)
    sections: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def pick_run(data: Path, parser: str, run_id: str | None) -> str:
    """해당 파서 버전의 끝난 전체 실행(limit 없음, SUCCEEDED) 중 마지막. 중단된 실행은 RUNNING으로 남는다. 이름이 시각 순이라 정렬로 고른다."""
    if run_id:
        return run_id
    found = []
    for run_json in sorted(data.glob("runs/extract-*/run.json")):
        run = _json(run_json)
        config = json.loads(run["config_manifest"])
        if (
            config.get("parser_version") == parser
            and config.get("limit") is None
            and run.get("status") == "SUCCEEDED"
            and (run_json.parent / "extraction_attempts.jsonl").exists()
        ):
            found.append(run["run_id"])
    if not found:
        raise ValueError(f"{parser}의 전체 추출 실행을 찾지 못했다")
    return found[-1]


def list_records(data: Path) -> dict[str, dict[str, Any]]:
    """목록 응답 전체 → 접수번호별 목록 레코드. 같은 접수번호가 여러 번 나오면 파일 이름 순 마지막 값."""
    records: dict[str, dict[str, Any]] = {}
    for page in sorted((data / "raw" / SOURCE / LIST_FOLDER).glob("*/page-*__v*.json")):
        for item in _json(page).get("list", []):
            records[item["rcept_no"]] = item
    return records


def _document_row(rcept_no: str, record: dict[str, Any] | None) -> dict[str, Any]:
    if record is None:
        raise ValueError(f"목록 응답에 접수번호가 없다: {rcept_no}")
    kind, correction = classify_report(record["report_nm"])
    if kind is not Kind.PROSPECTUS:
        raise ValueError(f"투자설명서가 아닌 접수다: {rcept_no} {record['report_nm']}")
    return {
        "source_doc_key": rcept_no,
        "source_key_payload": {"rcept_no": rcept_no},
        "source_record_payload": record,
        "rcept_no": rcept_no,
        "document_type": kind.value,
        "report_name": record["report_nm"],
        "is_correction": correction,
        "received_date": date(
            int(rcept_no[:4]), int(rcept_no[4:6]), int(rcept_no[6:8])
        ),
    }


def _raw_row(data: Path, meta_path: Path) -> dict[str, Any]:
    """.meta.json 한 개 → raw_object 행. 바이트 크기·SHA-256이 meta와 다르면 중단한다."""
    meta = _json(meta_path)
    file_path = meta_path.with_name(meta_path.name.removesuffix(".meta.json"))
    content = file_path.read_bytes()
    if len(content) != meta["size"] or sha256_hex(content) != meta["sha256"]:
        raise ValueError(f"원본 바이트가 meta와 다르다: {file_path}")
    body_format, content_type = ROLE_FORMAT[meta["file_role"]]
    name = unquote(meta["file_name"]) if meta.get("file_name") else file_path.name
    key = encode_source_key([meta["source_key"]])
    return {
        "rcept_no": meta["source_key"],
        "source_object_key": f"{key}/{meta['file_role']}",
        "version_seq": meta["version_seq"],
        "body_format": body_format,
        "original_file_name": name if meta.get("file_name") else None,
        "file_role": meta["file_role"],
        "sha256": meta["sha256"],
        "storage_path": str(file_path.relative_to(data)),
        "file_name": name,
        "content_type": content_type,
        "collected_at": meta["collected_at"],
        "request_params": {
            "endpoint": meta["endpoint"],
            "source_fields": meta["source_fields"],
        },
        "source_fields": meta["source_fields"],
    }


def _section_rows(
    structure: dict[str, Any], text: str, rcept_no: str, storage_path: str
) -> list[dict[str, Any]]:
    rows = []
    for s in structure["sections"]:
        start, end = s["char_start"], s["char_end"]
        if end is not None and end > len(text):
            raise ValueError(
                f"절 구간이 텍스트 길이를 넘는다: {rcept_no} #{s['section_seq']}"
            )
        rows.append(
            {
                "rcept_no": rcept_no,
                "storage_path": storage_path,
                "section_seq": s["section_seq"],
                "part_seq": s["part_seq"],
                "source_section_no": s["source_section_no"],
                "canonical_section_code": s["canonical_section_code"],
                "section_kind": s["section_kind"],
                "char_start": start,
                "char_end": end,
                "quality_flags": s["quality_flags"],
                "section_title": s["title"],
                "section_text": None if start is None else text[start:end],
                "extract_status": s["extract_status"],
            }
        )
    return rows


def _extraction_row(
    attempt: dict[str, Any], raw: dict[str, Any], parser: str, run_id: str
) -> dict[str, Any]:
    if attempt["raw_sha256"] != raw["sha256"] or attempt["parser_version"] != parser:
        raise ValueError(f"추출 기록과 원본이 맞지 않는다: {raw['rcept_no']}")
    return {
        "rcept_no": raw["rcept_no"],
        "storage_path": raw["storage_path"],
        "parser_version": parser,
        "created_run_id": run_id,
        "extract_status": attempt["extract_status"],
        "canonical_text_path": attempt["canonical_text_path"],
        "canonical_text_sha256": attempt["canonical_text_sha256"],
        "structure_manifest_path": attempt["structure_manifest_path"],
        "structure_manifest_sha256": attempt["structure_manifest_sha256"],
        "structure_status": attempt["structure_status"],
        "text_length": attempt["text_length"],
        "error_reason": attempt["error_reason"],
        "extracted_at": attempt["finished_at"],
    }


def build_rows(
    data: Path, parser: str | None = None, run_id: str | None = None
) -> Rows:
    """디스크 입력만 읽어 적재할 행을 만든다(DB 없음). 모든 목록은 자연키 순으로 정렬된다."""
    parser = parser or parser_version()
    run_id = pick_run(data, parser, run_id)
    listed = list_records(data)
    run_dir = data / "runs" / run_id
    run = _json(run_dir / "run.json")
    attempts = {
        a["source_key"]: a
        for a in map(
            json.loads,
            (run_dir / "extraction_attempts.jsonl")
            .read_text(encoding="utf-8")
            .splitlines(),
        )
    }
    rows = Rows(
        pipeline_run={
            "run_id": run_id,
            "run_kind": run["run_kind"],
            "is_official": run["is_official"],
            "baseline_date": run["baseline_date"],
            "status": run["status"],
            "config_manifest": json.loads(run["config_manifest"]),
            "config_sha256": run["config_sha256"],
            "started_at": run["started_at"],
            "completed_at": run["completed_at"],
        }
    )
    for folder in sorted((data / "raw" / SOURCE).iterdir()):
        if not RCEPT_RE.match(folder.name):
            continue  # _list 등 목록 페이지 폴더
        rcept_no = folder.name
        raws = [
            _raw_row(data, p)
            for p in sorted(folder.glob("*.meta.json"))
            if _json(p)["file_role"] in ROLE_FORMAT
        ]
        body = next((r for r in raws if r["file_role"] == "body_pdf"), None)
        rows.documents.append(_document_row(rcept_no, listed.get(rcept_no)))
        rows.raw_objects.extend(raws)
        if body is None:
            rows.skipped.append(
                f"{rcept_no}: body_pdf 없음, file_extraction·section 없음"
            )
            continue
        attempt = attempts.get(rcept_no)
        if attempt is None:
            raise ValueError(f"추출 기록이 없다: {rcept_no}")
        rows.extractions.append(_extraction_row(attempt, body, parser, run_id))
        if not attempt["structure_manifest_path"]:
            rows.skipped.append(
                f"{rcept_no}: 추출 {attempt['extract_status']}, section 없음"
            )
            continue
        rows.sections.extend(_structure_sections(data, attempt, rcept_no, body, parser))
    return rows


def _structure_sections(
    data: Path,
    attempt: dict[str, Any],
    rcept_no: str,
    body: dict[str, Any],
    parser: str,
) -> list[dict[str, Any]]:
    """structure.json·text.txt 해시를 추출 기록과 대조한 뒤 절 행을 만든다."""
    struct_bytes = (data / attempt["structure_manifest_path"]).read_bytes()
    text_bytes = (data / attempt["canonical_text_path"]).read_bytes()
    if (
        sha256_hex(struct_bytes) != attempt["structure_manifest_sha256"]
        or sha256_hex(text_bytes) != attempt["canonical_text_sha256"]
    ):
        raise ValueError(f"derived 파일 해시가 추출 기록과 다르다: {rcept_no}")
    structure = json.loads(struct_bytes)
    if (
        structure["raw_sha256"] != body["sha256"]
        or structure["parser_version"] != parser
    ):
        raise ValueError(f"structure.json이 원본·파서 버전과 다르다: {rcept_no}")
    text = text_bytes.decode("utf-8")
    if len(text) != attempt["text_length"]:
        raise ValueError(f"text_length 불일치: {rcept_no}")
    return _section_rows(structure, text, rcept_no, body["storage_path"])


INSERT_DOCUMENT = """
insert into document (source, source_doc_key, source_key_payload, source_record_payload, rcept_no,
  document_type, report_name, is_correction, received_date)
values (%(source)s, %(source_doc_key)s, %(payload)s, %(record)s, %(rcept_no)s, %(document_type)s,
  %(report_name)s, %(is_correction)s, %(received_date)s)
returning document_id"""
INSERT_RAW = """
insert into raw_object (document_id, source, source_object_key, version_seq, body_format, original_file_name,
  file_role, sha256, storage_path, file_name, content_type, collected_at, request_params, collect_status)
values (%(document_id)s, %(source)s, %(source_object_key)s, %(version_seq)s, %(body_format)s,
  %(original_file_name)s, %(file_role)s, %(sha256)s, %(storage_path)s, %(file_name)s, %(content_type)s,
  %(collected_at)s, %(request_params)s, 'success')
returning raw_object_id"""
INSERT_RUN = """
insert into pipeline_run (run_id, run_kind, is_official, baseline_date, status, config_manifest,
  config_sha256, started_at, completed_at)
values (%(run_id)s, %(run_kind)s, %(is_official)s, %(baseline_date)s, %(status)s, %(config_manifest)s,
  %(config_sha256)s, %(started_at)s, %(completed_at)s)"""
INSERT_EXTRACTION = """
insert into file_extraction (raw_object_id, parser_version, created_run_id, extract_status, canonical_text_path,
  canonical_text_sha256, structure_manifest_path, structure_manifest_sha256, structure_status, text_length,
  error_reason, extracted_at)
values (%(raw_object_id)s, %(parser_version)s, %(created_run_id)s, %(extract_status)s, %(canonical_text_path)s,
  %(canonical_text_sha256)s, %(structure_manifest_path)s, %(structure_manifest_sha256)s, %(structure_status)s,
  %(text_length)s, %(error_reason)s, %(extracted_at)s)"""
INSERT_SECTION = """
insert into section (document_id, raw_object_id, parser_version, section_seq, part_seq, source_section_no,
  canonical_section_code, section_kind, char_start, char_end, quality_flags, section_title, section_text,
  extract_status)
values (%(document_id)s, %(raw_object_id)s, %(parser_version)s, %(section_seq)s, %(part_seq)s,
  %(source_section_no)s, %(canonical_section_code)s, %(section_kind)s, %(char_start)s, %(char_end)s,
  %(quality_flags)s, %(section_title)s, %(section_text)s, %(extract_status)s)"""


def _returning(cur: psycopg.Cursor, sql: str, params: dict[str, Any]) -> int:
    cur.execute(sql, params)
    row = cur.fetchone()
    if row is None:
        raise RuntimeError("RETURNING 결과가 없다")
    return row[0]


# CASCADE로 같이 비워질 표: TABLES를 직접·간접으로 참조하는 표. 표 이름 문자열은 검색 경로에 따라
# 스키마가 붙거나 빠지므로 oid로 따라가고, 출력만 「스키마.표」로 만든다
CASCADE_TABLES = """
with recursive refs(oid) as (
  select unnest(%(tables)s::regclass[])::oid
  union
  select c.conrelid from pg_constraint c join refs on c.confrelid = refs.oid
  where c.contype = 'f'
)
select format('%%I.%%I', n.nspname, t.relname)
from refs join pg_class t on t.oid = refs.oid join pg_namespace n on n.oid = t.relnamespace
where refs.oid <> all(%(tables)s::regclass[]::oid[])
order by 1"""


def nonempty_cascade_tables(cur: psycopg.Cursor) -> list[str]:
    """TRUNCATE CASCADE로 지워질 하위 표 중 행이 있는 표(「스키마.표」)."""
    cur.execute(CASCADE_TABLES, {"tables": list(TABLES)})
    tables = [t for (t,) in cur.fetchall()]
    # 표 이름은 카탈로그에서 format('%I.%I')로 만든 값이라 문자열로 이어도 안전하다
    return [
        t
        for t in tables
        if cur.execute(f"select exists(select 1 from {t})").fetchone()[0]
    ]


# 비울 표 안에서 이 스크립트가 넣지 않는 행. 같은 DB에 다른 출처 수집이나 SCORE 실행이 있으면 같이 지워진다
FOREIGN_ROWS = {
    "raw.document(DART 밖 출처)": "select count(*) from raw.document where source <> %(source)s",
    "raw.raw_object(DART 밖 출처)": "select count(*) from raw.raw_object where source <> %(source)s",
    "raw.pipeline_run(EXTRACT 아님)": "select count(*) from raw.pipeline_run where run_kind <> 'EXTRACT'",
}


def foreign_rows(cur: psycopg.Cursor) -> list[str]:
    """비울 표에 있는 DART 추출 밖의 행(「표(종류) N행」)."""
    out = []
    for name, sql in FOREIGN_ROWS.items():
        n = cur.execute(sql, {"source": SOURCE}).fetchone()[0]
        if n:
            out.append(f"{name} {n}행")
    return out


def load(
    conn: psycopg.Connection, rows: Rows, parser: str, force: bool = False
) -> None:
    """트랜잭션 안에서 비우고 다시 넣는다. 커밋·롤백은 호출한 쪽이 한다."""
    with conn.cursor() as cur:
        if not force and (busy := nonempty_cascade_tables(cur) + foreign_rows(cur)):
            raise RuntimeError(
                f"다시 적재하면 같이 지워질 행이 있다: {', '.join(busy)}. 지워도 되면 --force"
            )
        cur.execute(f"truncate {', '.join(TABLES)} restart identity cascade")
        cur.execute(
            INSERT_RUN,
            {
                **rows.pipeline_run,
                "config_manifest": Jsonb(rows.pipeline_run["config_manifest"]),
            },
        )
        doc_ids: dict[str, int] = {}
        for d in rows.documents:
            doc_ids[d["rcept_no"]] = _returning(
                cur,
                INSERT_DOCUMENT,
                {
                    **d,
                    "source": SOURCE,
                    "payload": Jsonb(d["source_key_payload"]),
                    "record": Jsonb(d["source_record_payload"]),
                },
            )
        raw_ids: dict[tuple[str, str], int] = {}
        for r in rows.raw_objects:
            params = {
                **r,
                "source": SOURCE,
                "document_id": doc_ids[r["rcept_no"]],
                "request_params": Jsonb(r["request_params"]),
            }
            raw_ids[(r["rcept_no"], r["storage_path"])] = _returning(
                cur, INSERT_RAW, params
            )
        cur.executemany(
            INSERT_EXTRACTION,
            [
                {**e, "raw_object_id": raw_ids[(e["rcept_no"], e["storage_path"])]}
                for e in rows.extractions
            ],
        )
        cur.executemany(
            INSERT_SECTION,
            [
                {
                    **s,
                    "document_id": doc_ids[s["rcept_no"]],
                    "raw_object_id": raw_ids[(s["rcept_no"], s["storage_path"])],
                    "parser_version": parser,
                    "quality_flags": Jsonb(s["quality_flags"]),
                }
                for s in rows.sections
            ],
        )


def table_checksums(conn: psycopg.Connection) -> dict[str, tuple[int, str]]:
    """표별 (행 수, 전체 내용 md5). 행 전체를 자연키 순으로 문자열로 이어 해시한다. 시각은 입력값이라 포함."""
    out = {}
    conn.execute(
        "set time zone 'UTC'"
    )  # timestamptz 문자열을 접속 설정과 무관하게 고정
    for table, order in CHECKSUM_ORDER.items():
        sql = (
            f"select count(*), coalesce(md5(string_agg(t::text, '|' order by {order})), '') "
            f"from {table} t"
        )
        row = conn.execute(sql).fetchone()
        if row is None:
            raise RuntimeError(f"{table} 집계 결과가 없다")
        out[table] = (row[0], row[1])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("data_dir", type=Path)
    ap.add_argument(
        "--parser-version", help="기본: 추출기와 같은 값(extract.parser_version())"
    )
    ap.add_argument(
        "--run-id",
        help="추출 기록을 읽을 실행(기본: 해당 파서 버전의 마지막 전체 실행)",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="같이 지워질 행(하위 표 score 등, DART 밖 출처 문서·원본, EXTRACT가 아닌 실행)이 있어도 비우고 적재",
    )
    ap.add_argument(
        "--checksum", action="store_true", help="적재 뒤 표별 행 수·내용 md5 출력"
    )
    args = ap.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL 환경 변수가 필요하다", file=sys.stderr)
        return 2
    started = time.monotonic()
    parser = args.parser_version or parser_version()
    rows = build_rows(args.data_dir, parser, args.run_id)
    print(
        f"입력 실행 {rows.pipeline_run['run_id']}, 읽기 {time.monotonic() - started:.1f}s"
    )
    # 정상 종료면 커밋, 예외면 롤백
    with psycopg.connect(url, options=f"-c search_path={SEARCH_PATH}") as conn:
        load(conn, rows, parser, args.force)
        if args.checksum:
            for table, (count, md5) in table_checksums(conn).items():
                print(f"{table}\t{count}\t{md5}")
    for line in rows.skipped:
        print("건너뜀:", line)
    print(f"완료 {time.monotonic() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
