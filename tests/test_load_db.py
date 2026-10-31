"""실제 PostgreSQL에 DDL을 적용하고 load()·점검을 돌리는 테스트. TEST_DATABASE_URL이 없으면 건너뛴다.

TEST_DATABASE_URL은 지워도 되는 빈 DB를 가리켜야 한다. 각 테스트는 트랜잭션 안에서 돌고 끝나면 롤백한다.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from test_local_load import PARSER, TEXT, _fixture

from signal_pipeline.loading.load_checks import rules
from signal_pipeline.loading.local_load import SEARCH_PATH, build_rows, load

URL = os.environ.get("TEST_DATABASE_URL")
MIGRATIONS = Path(__file__).resolve().parents[1] / "db" / "migrations"
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL 없음")


@pytest.fixture
def loaded(tmp_path: Path) -> Iterator[tuple[psycopg.Connection, Path]]:
    assert URL
    with psycopg.connect(URL, options=f"-c search_path={SEARCH_PATH}") as conn:
        for path in sorted(MIGRATIONS.glob("*.sql")):
            conn.execute(path.read_text(encoding="utf-8"))
        _fixture(tmp_path)
        load(conn, build_rows(tmp_path), PARSER)
        yield conn, tmp_path
        conn.rollback()


def _failed(conn: psycopg.Connection, data: Path) -> set[str]:
    with conn.cursor() as cur:
        return {desc for _, desc, _, ok in rules(cur, data) if not ok}


def test_loaded_fixture_passes_rules(loaded: tuple[psycopg.Connection, Path]) -> None:
    assert _failed(*loaded) == set()


def test_extract_ok_section_without_range_fails(
    loaded: tuple[psycopg.Connection, Path],
) -> None:
    conn, data = loaded
    # 한쪽만 NULL은 DDL(section_char_range_check)이 막는다. 범위·본문이 모두 NULL인 EXTRACT_OK 절은 DDL을 통과한다
    conn.execute(
        "update section set char_start = null, char_end = null, section_text = null"
        " where extract_status = 'EXTRACT_OK'"
    )
    assert "EXTRACT_OK 절의 범위·본문 결측" in _failed(conn, data)


def test_overlapping_sections_fail(loaded: tuple[psycopg.Connection, Path]) -> None:
    conn, data = loaded
    conn.execute(
        "insert into section (document_id, raw_object_id, parser_version, section_seq, section_kind,"
        " char_start, char_end, quality_flags, section_text, extract_status)"
        " select document_id, raw_object_id, parser_version, 3, 'body', 3, 6, '[]', %s, 'EXTRACT_OK'"
        " from section where section_seq = 1",
        (TEXT[3:6],),
    )
    failed = _failed(conn, data)
    assert any(d.startswith("형제 구간 겹침") for d in failed)
    assert not any(d.startswith("section_text") for d in failed)  # 본문은 맞음


def test_section_text_mismatch_fails(loaded: tuple[psycopg.Connection, Path]) -> None:
    conn, data = loaded
    conn.execute("update section set section_text = 'XYZ' where section_seq = 1")
    assert any(d.startswith("section_text = text.txt") for d in _failed(conn, data))


@pytest.mark.parametrize(
    "sql",
    [
        "update document set source = 'fss_sanction'",
        "update raw_object set source = 'kofia_disclosure'",
        "update pipeline_run set run_kind = 'SCORE', upstream_run_id = run_id",
    ],
)
def test_reload_stops_on_foreign_rows(
    loaded: tuple[psycopg.Connection, Path], sql: str
) -> None:
    conn, data = loaded
    conn.execute(sql)
    with pytest.raises(RuntimeError, match="--force"):
        load(conn, build_rows(data), PARSER)
    load(conn, build_rows(data), PARSER, force=True)
