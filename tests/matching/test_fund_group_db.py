"""fund_group 적재를 실제 PostgreSQL에서 돌리는 테스트. TEST_DATABASE_URL이 없으면 건너뛴다.

TEST_DATABASE_URL은 지워도 되는 빈 DB를 가리켜야 한다. 각 테스트는 트랜잭션 안에서 돌고 끝나면 롤백한다.
run()은 중간에 커밋하므로 테스트는 하위 함수를 직접 부른다(start_run은 commit=False).
"""

import os
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import psycopg
import pytest

from signal_pipeline.loading.local_load import SEARCH_PATH
from signal_pipeline.matching import fund_group as fg
from signal_pipeline.matching.fund_key import CoverGrade, Doc, build_groups

URL = os.environ.get("TEST_DATABASE_URL")
MIGRATIONS = Path(__file__).resolve().parents[2] / "db" / "migrations"
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL 없음")


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    assert URL
    with psycopg.connect(URL, options=f"-c search_path={SEARCH_PATH}") as c:
        for path in sorted(MIGRATIONS.glob("*.sql")):
            c.execute(path.read_text(encoding="utf-8"))
        yield c
        c.rollback()


def _insert_doc(conn: psycopg.Connection, i: int, name: str) -> Doc:
    rcept = f"2026090100{i:04d}"
    title = f"[기재정정]투자설명서(집합투자증권)({name})"
    conn.execute(
        "INSERT INTO raw.document (source, source_doc_key, source_key_payload, source_record_payload,"
        " rcept_no, document_type, report_name, received_date) VALUES ('dart', %s, '{}', %s, %s,"
        " '투자설명서', %s, '2026-09-01')",
        (
            rcept,
            psycopg.types.json.Jsonb(
                {"corp_code": "00000001", "corp_name": "가나자산운용"}
            ),
            rcept,
            title,
        ),
    )
    return fg.load_docs(conn)[-1]


def test_rerun_keeps_fund_key_and_verify(conn: psycopg.Connection) -> None:
    _insert_doc(conn, 1, "가나증권자투자신탁(주식)")
    _insert_doc(conn, 2, "가나증권자투자신탁(주식)종류A")
    _insert_doc(conn, 3, "가나증권자투자신탁1호(주식)")
    docs = fg.load_docs(conn)
    groups, _ = build_groups(docs)
    run_id = fg.start_run(conn, {"t": 1}, date(2026, 11, 25), commit=False)
    grades = {1: CoverGrade(2, None), 2: CoverGrade(2, None), 3: CoverGrade(4, None)}
    with conn.cursor() as cur:
        ids = fg.ensure_distributors(cur, docs)
        _, _, created = fg.upsert_groups(cur, groups, grades, ids, run_id)
        assert created == 2
        keys = dict(
            cur.execute(
                "SELECT canonical_name, fund_key FROM staging.fund_group"
            ).fetchall()
        )
        # 다시: 새 등급(충돌)이 들어와도 fund_key는 그대로, 등급은 비움
        grades2 = {**grades, 2: CoverGrade(5, None)}
        _, _, created2 = fg.upsert_groups(cur, groups, grades2, ids, run_id)
        assert created2 == 0
        assert keys == dict(
            cur.execute(
                "SELECT canonical_name, fund_key FROM staging.fund_group"
            ).fetchall()
        )
        conflict = cur.execute(
            "SELECT representative_risk_grade FROM staging.fund_group WHERE canonical_name = %s",
            ("가나증권자투자신탁(주식)",),
        ).fetchone()
        assert conflict == (None,)
    assert fg.verify(conn) == []


def test_verify_detects_grade_without_source(conn: psycopg.Connection) -> None:
    doc = _insert_doc(conn, 1, "가나증권투자신탁")
    run_id = fg.start_run(conn, {"t": 2}, date(2026, 11, 25), commit=False)
    groups, _ = build_groups([doc])
    with conn.cursor() as cur:
        ids = fg.ensure_distributors(cur, [doc])
        fg.upsert_groups(cur, groups, {1: CoverGrade(3, None)}, ids, run_id)
    assert fg.verify(conn) == []
    # CHECK 제약이 근거 없는 등급을 막는지
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE staging.fund_group SET risk_grade_source_kind = NULL")
