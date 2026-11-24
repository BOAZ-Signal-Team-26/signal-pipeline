"""DART 투자설명서 문서를 fund_group(fund_key)으로 묶고 표지 위험등급을 대표 등급으로 적재한다.

범위(이슈 #96): staging.distributor(운용사), staging.fund_group, staging.match_failure만 쓴다.
상품(클래스) 행과 document_product는 만들지 않는다. DART 표지에서 클래스별 코드·이름을 확정할 수 없고
product.etf_confidence가 NOT NULL이라 값을 지어내야 하기 때문(금투협·공공데이터포털 마스터가 들어올 때 만듦).

규칙: signal_pipeline.matching.fund_key. fund_key는 한 번 발급하면 바뀌지 않는다(FGnnnnnn).
다시 돌리면 기존 묶음은 fund_key·이름·created_run_id를 그대로 두고 대표 등급 칼럼과 등급 상태만 새로 계산한다.

사용: DATABASE_URL=postgresql://... uv run python -m signal_pipeline.matching.fund_group \\
        --grades-csv ../signal-data/exports/risk_grade/prospectus_cover__20261124.csv [--verify-only]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import secrets
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from signal_pipeline.extraction.store import canonical
from signal_pipeline.matching.fund_key import (
    CONFLICT,
    OK,
    RULE_VERSION,
    CoverGrade,
    Doc,
    GradePick,
    Group,
    build_groups,
    fund_name,
    group_key,
    pick_grade,
)

KST = timezone(timedelta(hours=9))
SOURCE = "fund_group"
KEY_FORMAT = "FG{:06d}"
KEY_PATTERN = re.compile(r"^FG(\d{6})$")
DOCS_SQL = """
SELECT document_id, rcept_no, report_name, received_date,
       source_record_payload->>'corp_code' AS corp_code,
       source_record_payload->>'corp_name' AS corp_name
FROM raw.document WHERE document_type = '투자설명서' ORDER BY document_id
"""


@dataclass(frozen=True)
class Summary:
    run_id: str
    groups: int
    created: int
    graded: int
    status_counts: dict[str, int]
    failures: dict[str, int]


def load_docs(conn: psycopg.Connection) -> list[Doc]:
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(DOCS_SQL).fetchall()
    missing = [
        r["document_id"] for r in rows if not r["corp_code"] or not r["corp_name"]
    ]
    if missing:
        raise ValueError(f"운용사 corp_code/corp_name이 없는 문서: {missing[:5]}")
    return [Doc(**r) for r in rows]


def read_grades(path: Path, docs: list[Doc]) -> dict[int, CoverGrade]:
    """표지 등급 CSV를 읽는다. 문서 번호와 접수번호가 DB와 어긋나면 중단(다른 DB용 파일 방지)."""
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = {int(r["document_id"]): r for r in csv.DictReader(f)}
    out: dict[int, CoverGrade] = {}
    for doc in docs:
        row = rows.get(doc.document_id)
        if row is None or row["접수번호"] != doc.rcept_no:
            raise ValueError(
                f"등급 CSV가 DB와 맞지 않음: document_id={doc.document_id}"
            )
        grade = int(row["위험등급"]) if row["위험등급"] else None
        out[doc.document_id] = CoverGrade(grade, row["결측사유"] or None)
    return out


def distributor_type(name: str) -> str:
    return "운용사" if "운용" in name else "미상"


def ensure_distributors(cur: psycopg.Cursor, docs: Iterable[Doc]) -> dict[str, int]:
    """corp_code마다 distributor 행 하나. 이미 있으면 그대로 쓴다."""
    ids: dict[str, int] = {}
    for doc in docs:
        if doc.corp_code in ids:
            continue
        row = cur.execute(
            "SELECT distributor_id FROM staging.distributor WHERE corp_code = %s ORDER BY 1 LIMIT 1",
            (doc.corp_code,),
        ).fetchone()
        if row is None:
            row = cur.execute(
                "INSERT INTO staging.distributor (corp_code, distributor_name, distributor_type)"
                " VALUES (%s, %s, %s) RETURNING distributor_id",
                (doc.corp_code, doc.corp_name, distributor_type(doc.corp_name)),
            ).fetchone()
        assert row is not None
        ids[doc.corp_code] = row[0]
    return ids


def _next_key_number(cur: psycopg.Cursor) -> int:
    nums = [
        int(m.group(1))
        for (k,) in cur.execute("SELECT fund_key FROM staging.fund_group").fetchall()
        if (m := KEY_PATTERN.match(k))
    ]
    return max(nums, default=0) + 1


def _evidence(group: Group, corp_code: str) -> dict:
    first = group.docs[0]
    return {
        "rule_version": RULE_VERSION,
        "group_key": group.key,
        "corp_code": corp_code,
        "first_document_id": first.document_id,
        "first_rcept_no": first.rcept_no,
        "first_report_name": first.report_name,
    }


def _status(pick: GradePick, run_id: str) -> dict:
    return {"status": pick.status, "run_id": run_id, **pick.detail}


def upsert_groups(
    cur: psycopg.Cursor,
    groups: list[Group],
    grades: dict[int, CoverGrade],
    manager_ids: dict[str, int],
    run_id: str,
) -> tuple[dict[str, str], list[tuple[Group, str, GradePick]], int]:
    """묶음을 넣거나 갱신한다. 반환: (group_key별 fund_key, (묶음, fund_key, 등급 판정) 목록, 새로 만든 수)."""
    existing = {
        (r[0], r[1]): r[2]
        for r in cur.execute(
            "SELECT manager_id, grouping_evidence->>'group_key', fund_key FROM staging.fund_group"
        ).fetchall()
    }
    number = _next_key_number(cur)
    created = 0
    picks: list[tuple[Group, str, GradePick]] = []
    for group in groups:
        manager_id = manager_ids[group.corp_code]
        pick = pick_grade(group, grades)
        fund_key = existing.get((manager_id, group.key))
        grade_cols = (
            pick.grade,
            pick.source_document_id,
            "PROSPECTUS_COVER" if pick.status == OK else None,
        )
        if fund_key is None:
            fund_key = KEY_FORMAT.format(number)
            number += 1
            created += 1
            evidence = {
                **_evidence(group, group.corp_code),
                "risk_grade_status": _status(pick, run_id),
            }
            cur.execute(
                "INSERT INTO staging.fund_group (fund_key, canonical_name, manager_id, created_run_id,"
                " grouping_evidence, representative_risk_grade, risk_grade_source_document_id,"
                " risk_grade_source_kind) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    fund_key,
                    group.canonical_name,
                    manager_id,
                    run_id,
                    Jsonb(evidence),
                    *grade_cols,
                ),
            )
        else:
            cur.execute(
                "UPDATE staging.fund_group SET representative_risk_grade = %s,"
                " risk_grade_source_document_id = %s, risk_grade_source_kind = %s,"
                " grouping_evidence = grouping_evidence || jsonb_build_object('risk_grade_status', %s::jsonb)"
                " WHERE fund_key = %s",
                (*grade_cols, Jsonb(_status(pick, run_id)), fund_key),
            )
        picks.append((group, fund_key, pick))
    return {g.key: k for g, k, _ in picks}, picks, created


def _record_failure(
    cur: psycopg.Cursor,
    run_id: str,
    reason: str,
    key_value: str,
    note: str,
    normalized: str | None = None,
    document_id: int | None = None,
) -> int:
    """같은 (소스, 사유, 시도 키)의 미해결 행이 있으면 새로 넣지 않는다. 넣었으면 1."""
    dup = cur.execute(
        "SELECT 1 FROM staging.match_failure WHERE source = %s AND failure_reason_code = %s"
        " AND attempted_key_value = %s AND status <> '해결'",
        (SOURCE, reason, key_value),
    ).fetchone()
    if dup:
        return 0
    cur.execute(
        "INSERT INTO staging.match_failure (run_id, target_type, source, attempted_key_value,"
        " normalized_value, failure_reason_code, attempted_at, status, related_document_id,"
        " resolution_note) VALUES (%s, 'product', %s, %s, %s, %s, now(), '미해결', %s, %s)",
        (run_id, SOURCE, key_value, normalized, reason, document_id, note),
    )
    return 1


def record_failures(
    cur: psycopg.Cursor,
    run_id: str,
    unparsed: list[Doc],
    picks: list[tuple[Group, str, GradePick]],
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for doc in unparsed:
        counts["NORMALIZE_FAILED"] += _record_failure(
            cur,
            run_id,
            "NORMALIZE_FAILED",
            doc.report_name,
            canonical(
                {"detail": "접수 제목에서 펀드명을 뽑지 못함", "rcept_no": doc.rcept_no}
            ),
            document_id=doc.document_id,
        )
    for group, fund_key, pick in picks:
        if pick.status != CONFLICT:
            continue
        note = canonical(
            {
                "detail": "같은 펀드 묶음의 문서 표지 등급이 서로 달라 대표 등급을 고르지 않음",
                "value_source": "DART 투자설명서 표지(운용사 공시)",
                **pick.detail,
            }
        )
        counts["AMBIGUOUS"] += _record_failure(
            cur, run_id, "AMBIGUOUS", fund_key, note, normalized=group.key
        )
    return dict(counts)


def start_run(
    conn: psycopg.Connection, config: dict, baseline: date, commit: bool = True
) -> str:
    run_id = f"match-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{secrets.token_hex(2)}"
    conn.execute(
        "INSERT INTO raw.pipeline_run (run_id, run_kind, is_official, baseline_date, status,"
        " config_manifest, config_sha256, started_at) VALUES (%s, 'EXTRACT', false, %s, 'RUNNING',"
        " %s, %s, now())",
        (
            run_id,
            baseline,
            Jsonb(config),
            hashlib.sha256(canonical(config).encode()).hexdigest(),
        ),
    )
    if commit:  # 실패해도 RUNNING 행이 남아 FAILED로 닫을 수 있게 바로 확정. 테스트는 롤백하려고 끔
        conn.commit()
    return run_id


def finish_run(conn: psycopg.Connection, run_id: str, status: str) -> None:
    conn.execute(
        "UPDATE raw.pipeline_run SET status = %s, completed_at = now()"
        " WHERE run_id = %s AND status = 'RUNNING'",
        (status, run_id),
    )
    conn.commit()


def run(conn: psycopg.Connection, grades_csv: Path, baseline: date) -> Summary:
    docs = load_docs(conn)
    grades = read_grades(grades_csv, docs)
    config = {
        "stage": "fund_group",
        "rule_version": RULE_VERSION,
        "grades_csv": {
            "name": grades_csv.name,
            "sha256": hashlib.sha256(grades_csv.read_bytes()).hexdigest(),
        },
        "document_count": len(docs),
    }
    run_id = start_run(conn, config, baseline)
    try:
        groups, unparsed = build_groups(docs)
        with conn.cursor() as cur:
            manager_ids = ensure_distributors(cur, docs)
            _, picks, created = upsert_groups(cur, groups, grades, manager_ids, run_id)
            failures = record_failures(cur, run_id, unparsed, picks)
        conn.commit()
    except BaseException:
        conn.rollback()
        finish_run(conn, run_id, "FAILED")
        raise
    violations = verify(conn)
    finish_run(conn, run_id, "FAILED" if violations else "SUCCEEDED")
    if violations:
        raise RuntimeError("적재 검증 위반: " + "; ".join(violations))
    return Summary(
        run_id,
        len(groups),
        created,
        sum(1 for _, _, p in picks if p.status == OK),
        dict(Counter(p.status for _, _, p in picks)),
        failures,
    )


def verify(conn: psycopg.Connection) -> list[str]:
    """위반 목록(빈 목록이면 통과)."""
    bad: list[str] = []
    one = lambda sql: conn.execute(sql).fetchone()[0]
    checks = {
        "등급이 있는데 근거 문서·구분이 없는 묶음": "SELECT count(*) FROM staging.fund_group WHERE representative_risk_grade IS NOT NULL"
        " AND (risk_grade_source_document_id IS NULL OR risk_grade_source_kind IS NULL)",
        "등급이 없는데 근거가 남은 묶음": "SELECT count(*) FROM staging.fund_group WHERE representative_risk_grade IS NULL"
        " AND (risk_grade_source_document_id IS NOT NULL OR risk_grade_source_kind IS NOT NULL)",
        "같은 운용사에서 group_key가 겹치는 묶음": "SELECT count(*) FROM (SELECT 1 FROM staging.fund_group"
        " GROUP BY manager_id, grouping_evidence->>'group_key' HAVING count(*) > 1) t",
        "created_run_id가 없는 실행을 가리키는 묶음": "SELECT count(*) FROM staging.fund_group g"
        " LEFT JOIN raw.pipeline_run r ON r.run_id = g.created_run_id WHERE r.run_id IS NULL",
    }
    for label, sql in checks.items():
        if n := one(sql):
            bad.append(f"{label} {n}")
    bad += _verify_sources(conn)
    bad += _verify_coverage(conn)
    return bad


def _verify_sources(conn: psycopg.Connection) -> list[str]:
    """등급이 있는 묶음마다 근거 문서가 투자설명서이고 같은 운용사·같은 group_key인지 다시 계산해 대조."""
    sql = (
        "SELECT g.fund_key, g.grouping_evidence->>'group_key', g.grouping_evidence->>'corp_code',"
        " d.document_type, d.report_name, d.source_record_payload->>'corp_code', dist.corp_code"
        " FROM staging.fund_group g JOIN raw.document d ON d.document_id = g.risk_grade_source_document_id"
        " JOIN staging.distributor dist ON dist.distributor_id = g.manager_id"
        " WHERE g.representative_risk_grade IS NOT NULL"
    )
    bad = []
    rows = conn.execute(sql).fetchall()
    for key, gkey, corp, dtype, rname, doc_corp, mgr_corp in rows:
        name = fund_name(rname or "")
        if dtype != "투자설명서" or name is None or group_key(name) != gkey:
            bad.append(f"{key}: 근거 문서의 fund_key 규칙 결과가 묶음과 다름")
        elif not (corp == doc_corp == mgr_corp):
            bad.append(f"{key}: 근거 문서의 운용사가 묶음과 다름")
    n_graded = conn.execute(
        "SELECT count(*) FROM staging.fund_group WHERE representative_risk_grade IS NOT NULL"
    ).fetchone()[0]
    if n_graded != len(rows):
        bad.append("근거 문서가 raw.document에 없는 등급 묶음")
    return bad


def _verify_coverage(conn: psycopg.Connection) -> list[str]:
    """모든 투자설명서가 묶음 하나에 들어가거나 NORMALIZE_FAILED로 기록돼 있는지."""
    docs = load_docs(conn)
    groups, unparsed = build_groups(docs)
    have = {
        (c, k)
        for c, k in conn.execute(
            "SELECT dist.corp_code, g.grouping_evidence->>'group_key' FROM staging.fund_group g"
            " JOIN staging.distributor dist ON dist.distributor_id = g.manager_id"
        ).fetchall()
    }
    bad = []
    if missing := [g.key for g in groups if (g.corp_code, g.key) not in have]:
        bad.append(f"묶음이 없는 문서 그룹 {len(missing)}")
    failed = {
        r[0]
        for r in conn.execute(
            "SELECT related_document_id FROM staging.match_failure"
            " WHERE source = %s AND failure_reason_code = 'NORMALIZE_FAILED'",
            (SOURCE,),
        ).fetchall()
    }
    if lost := [d.document_id for d in unparsed if d.document_id not in failed]:
        bad.append(f"NORMALIZE_FAILED 기록이 없는 문서 {len(lost)}")
    return bad


def report(conn: psycopg.Connection) -> str:
    rows = conn.execute(
        "SELECT grouping_evidence->'risk_grade_status'->>'status', count(*)"
        " FROM staging.fund_group GROUP BY 1 ORDER BY 1"
    ).fetchall()
    fails = conn.execute(
        "SELECT failure_reason_code, count(*) FROM staging.match_failure WHERE source = %s GROUP BY 1",
        (SOURCE,),
    ).fetchall()
    n = conn.execute("SELECT count(*) FROM staging.fund_group").fetchone()[0]
    return f"fund_group {n}, 등급 상태 {dict(rows)}, match_failure {dict(fails)}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--grades-csv", type=Path)
    ap.add_argument("--baseline-date", type=date.fromisoformat)
    ap.add_argument("--verify-only", action="store_true")
    args = ap.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL 환경 변수가 필요하다", file=sys.stderr)
        return 2
    with psycopg.connect(url) as conn:
        if args.verify_only:
            bad = verify(conn)
            print(report(conn))
            print("검증:", "통과" if not bad else "; ".join(bad))
            return 1 if bad else 0
        if not args.grades_csv:
            print("--grades-csv가 필요하다", file=sys.stderr)
            return 2
        baseline = args.baseline_date or datetime.now(KST).date()
        summary = run(conn, args.grades_csv, baseline)
        print(summary)
        print(report(conn))
        print("검증: 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
