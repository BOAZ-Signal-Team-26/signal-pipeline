"""로컬 적재 결과 점검(읽기 전용). 11차 미팅 로컬 점검 체크리스트와 docs/data-model.md 「적재 검증 규칙」 중
적재한 표(document, raw_object, file_extraction, section, pipeline_run)에 해당하는 것을 DB 조회와 디스크 대조로 판정한다.

사용: DATABASE_URL=postgresql://... uv run python -m signal_pipeline.loading.load_checks DATA_DIR

- 하나라도 실패하면 종료 코드 1. 결과는 「번호 / 내용 / 값 / PASS·FAIL」 탭 구분 한 줄씩
- 기대 행 수는 디스크 입력(접수번호 폴더 수, 추출 기록 줄 수, structure.json 절 수)에서 다시 센다
- 원본 바이트와 derived/ 파일 해시는 전수, section_text와 text.txt 구간 대조는 표본(고정 시드)
- 규칙 2·3·5·8~11·13~15·18은 대상 표가 비어 있어 여기서 보지 않는다
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
from pathlib import Path
from typing import Any

import psycopg

from signal_pipeline.loading.local_load import RCEPT_RE, SEARCH_PATH, SOURCE
from signal_pipeline.parsing.extract import parser_version

CHECKS_DIR = Path(__file__).resolve().parents[3] / "db" / "checks"
SAMPLE = 200
Result = tuple[str, str, Any, bool]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _one(cur: psycopg.Cursor, sql: str) -> Any:
    row = cur.execute(sql).fetchone()
    if row is None:
        raise RuntimeError(f"조회 결과가 없다: {sql}")
    return row[0]


def expected_counts(data: Path, run_id: str) -> dict[str, int]:
    """디스크 입력에서 센 기대 행 수. run_id는 DB pipeline_run의 실행."""
    folders = [p for p in (data / "raw" / SOURCE).iterdir() if RCEPT_RE.match(p.name)]
    attempts = [
        json.loads(line)
        for line in (data / "runs" / run_id / "extraction_attempts.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    by_key = {a["source_key"]: a for a in attempts}
    sections = 0
    for folder in folders:
        attempt = by_key.get(folder.name)
        if attempt and attempt["structure_manifest_path"]:
            structure = json.loads(
                (data / attempt["structure_manifest_path"]).read_text(encoding="utf-8")
            )
            sections += len(structure["sections"])
    return {
        "document": len(folders),
        "file_extraction": sum(1 for f in folders if f.name in by_key),
        "section": sections,
    }


def checklist(cur: psycopg.Cursor, data: Path, parser: str) -> list[Result]:
    """11차 미팅 로컬 점검 체크리스트(DDL 적용·2회 실행 비교는 apply.py·local_load --checksum으로 따로)."""
    out: list[Result] = []
    run_id = _one(cur, "select run_id from pipeline_run where run_kind = 'EXTRACT'")
    want = expected_counts(data, run_id)
    got = {t: _one(cur, f"select count(*) from {t}") for t in want}
    out.append(("C2", "행 수(DB / 디스크)", f"{got} / {want}", got == want))

    orphans = [
        (
            "select count(*) from raw_object r left join document d using (document_id)"
            " where r.document_id is not null and d.document_id is null"
        ),
        (
            "select count(*) from file_extraction f left join raw_object r using (raw_object_id)"
            " where r.raw_object_id is null"
        ),
        (
            "select count(*) from section s left join file_extraction f using (raw_object_id, parser_version)"
            " where f.raw_object_id is null"
        ),
        (
            "select count(*) from section s join raw_object r using (raw_object_id)"
            " where r.document_id <> s.document_id"
        ),
    ]
    distributor = (CHECKS_DIR / "document_distributor.sql").read_text(encoding="utf-8")
    n = sum(_one(cur, sql) for sql in orphans)
    n += len(cur.execute(distributor).fetchall())
    out.append(("C3", "외래 키 고아(판매사 검증 쿼리 포함)", n, n == 0))

    total, null_range = cur.execute(
        "select count(*), count(*) filter (where char_start is null and char_end is null"
        " and section_text is null) from section where extract_status = 'SECTION_BOUNDARY_NOT_FOUND'"
    ).fetchone() or (0, 0)
    out.append(
        (
            "C4",
            "경계 실패 절 / 그중 범위·본문 NULL",
            f"{total} / {null_range}",
            total == null_range,
        )
    )

    versions = sorted(
        v
        for (v,) in cur.execute(
            "select parser_version from file_extraction union select parser_version from section"
        )
    )
    out.append(("C5", "파서 버전", versions, versions == [parser]))

    raws = cur.execute("select storage_path, sha256 from raw_object").fetchall()
    bad = sum(_sha(data / p) != h for p, h in raws)
    out.append(
        ("C6a", f"원본 바이트 SHA-256(전수 {len(raws)})", f"불일치 {bad}", bad == 0)
    )
    bad = 0
    for tp, th, sp, sh in cur.execute(
        "select canonical_text_path, canonical_text_sha256, structure_manifest_path,"
        " structure_manifest_sha256 from file_extraction where extract_status = 'EXTRACT_OK'"
    ):
        bad += _sha(data / tp) != th
        bad += bool(sp) and _sha(data / sp) != sh
    out.append(
        ("C6b", "text.txt·structure.json 경로·해시(전수)", f"불일치 {bad}", bad == 0)
    )
    return out


RULES = [
    (
        "R1",
        "식별자 공백",
        (
            "select count(*) from document where coalesce(trim(source), '') = ''"
            " or coalesce(trim(source_doc_key), '') = '' or source_key_payload = '{}'::jsonb"
        ),
    ),
    (
        "R1",
        "자연키 중복",
        (
            "select count(*) from (select 1 from document group by source, source_doc_key"
            " having count(*) > 1) t"
        ),
    ),
    (
        "R4",
        "version_seq·SHA-256 형식",
        (
            "select count(*) from raw_object where version_seq < 1"
            " or sha256 !~ '^[0-9a-f]{64}$'"
        ),
    ),
    (
        "R4",
        "같은 역할 파일 키 중복",
        (
            "select count(*) from (select 1 from raw_object"
            " group by document_id, file_role, source_object_key having count(*) > 1) t"
        ),
    ),
    (
        "R6",
        "수집 성공이 아닌 원본의 추출",
        (
            "select count(*) from file_extraction f join raw_object r"
            " using (raw_object_id) where r.collect_status <> 'success'"
        ),
    ),
    (
        "R6",
        "EXTRACT_OK 필수값 결측",
        (
            "select count(*) from file_extraction where extract_status = 'EXTRACT_OK'"
            " and (canonical_text_path is null or canonical_text_sha256 is null or text_length is null)"
        ),
    ),
    (
        "R6",
        "텍스트 없는 추출의 절",
        (
            "select count(*) from section s join file_extraction f"
            " using (raw_object_id, parser_version) where f.canonical_text_path is null"
        ),
    ),
    (
        "R7",
        "절 범위 위반",
        (
            "select count(*) from section s join file_extraction f using (raw_object_id, parser_version)"
            " where s.char_start is not null and not (0 <= s.char_start and s.char_start < s.char_end"
            " and s.char_end <= f.text_length)"
        ),
    ),
    (
        "R7",
        "본문 길이 ≠ 범위",
        (
            "select count(*) from section where char_start is not null"
            " and length(section_text) <> char_end - char_start"
        ),
    ),
    (
        "R7",
        "(파일, 파서 버전) 안 절 번호 중복",
        (
            "select count(*) from (select 1 from section"
            " group by raw_object_id, parser_version, section_seq having count(*) > 1) t"
        ),
    ),
    (
        "R12",
        "SUCCEEDED 아님 또는 설정 해시 형식",
        (
            "select count(*) from pipeline_run where status <> 'SUCCEEDED'"
            " or config_sha256 !~ '^[0-9a-f]{64}$'"
        ),
    ),
    (
        "R16",
        "EXTRACT 실행의 선택 manifest",
        (
            "select count(*) from pipeline_run where run_kind = 'EXTRACT'"
            " and (selection_manifest_path is not null or selection_manifest_sha256 is not null)"
        ),
    ),
    (
        "R17",
        "파서 버전 형식",
        (
            "select count(*) from file_extraction where parser_version !~ '^[a-z0-9._-]+$'"
        ),
    ),
    (
        "결측",
        "document 목록 기반 칼럼",
        (
            "select count(*) from document where report_name is null"
            " or is_correction is null or source_record_payload is null"
        ),
    ),
]


def rules(cur: psycopg.Cursor, data: Path) -> list[Result]:
    """data-model.md 적재 검증 규칙 중 적재한 표에 해당하는 것. 위반 행 수가 0이어야 통과."""
    out: list[Result] = [
        (key, desc, n, n == 0) for key, desc, sql in RULES for n in [_one(cur, sql)]
    ]
    ids = [
        i
        for (i,) in cur.execute(
            "select section_id from section where char_start is not null order by 1"
        )
    ]
    bad = 0
    for sid in random.Random(25).sample(ids, min(SAMPLE, len(ids))):
        row = cur.execute(
            "select f.canonical_text_path, s.char_start, s.char_end, s.section_text from section s"
            " join file_extraction f using (raw_object_id, parser_version) where section_id = %s",
            (sid,),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"절이 없다: {sid}")
        path, start, end, text = row
        bad += (data / path).read_text(encoding="utf-8")[start:end] != text
    out.append(
        (
            "R7",
            f"section_text = text.txt 구간(표본 {SAMPLE})",
            f"불일치 {bad}",
            bad == 0,
        )
    )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("data_dir", type=Path)
    ap.add_argument(
        "--parser-version", help="기본: 추출기와 같은 값(extract.parser_version())"
    )
    args = ap.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL 환경 변수가 필요하다", file=sys.stderr)
        return 2
    parser = args.parser_version or parser_version()
    with psycopg.connect(url, options=f"-c search_path={SEARCH_PATH}") as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            results = checklist(cur, args.data_dir, parser) + rules(cur, args.data_dir)
    for key, desc, value, ok in results:
        print(f"{key}\t{desc}\t{value}\t{'PASS' if ok else 'FAIL'}")
    failed = sum(not ok for *_, ok in results)
    print(f"실패 {failed}건" if failed else "모두 통과")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
