"""db/apply.py(마이그레이션 이력 표)를 실제 PostgreSQL에서 확인한다. TEST_DATABASE_URL이 없으면 건너뛴다.

apply.py는 파일마다 커밋하므로 트랜잭션 롤백으로 되돌릴 수 없다. 테스트마다 TEST_DATABASE_URL 서버에
임시 DB를 만들고 끝나면 지운다. TEST_DATABASE_URL 계정에 CREATE DATABASE 권한이 있어야 한다.
"""

import importlib.util
import os
import re
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

URL = os.environ.get("TEST_DATABASE_URL")
ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL 없음")

_spec = importlib.util.spec_from_file_location("db_apply", ROOT / "db" / "apply.py")
assert _spec and _spec.loader
apply_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(apply_mod)
MigrationError = apply_mod.MigrationError


@pytest.fixture
def db_url() -> Iterator[str]:
    assert URL
    name = f"apply_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(URL, autocommit=True) as admin:
        admin.execute(sql.SQL("create database {}").format(sql.Identifier(name)))
    params = conninfo_to_dict(URL)
    params["dbname"] = name
    try:
        yield make_conninfo(**params)
    finally:
        with psycopg.connect(URL, autocommit=True) as admin:
            admin.execute(
                sql.SQL("drop database if exists {} with (force)").format(
                    sql.Identifier(name)
                )
            )


def _connect(url: str) -> psycopg.Connection:
    return psycopg.connect(url, autocommit=True)


def _write(folder: Path, name: str, text: str) -> None:
    (folder / name).write_text(text, encoding="utf-8")


def _exists(conn: psycopg.Connection, table: str) -> bool:
    return conn.execute("select to_regclass(%s)", (table,)).fetchone()[0] is not None


def _history(conn: psycopg.Connection) -> list[str]:
    rows = conn.execute("select filename from public.schema_migrations order by 1")
    return [r[0] for r in rows.fetchall()]


def test_real_migrations_apply_once(db_url: str) -> None:
    paths = sorted(apply_mod.MIGRATIONS.glob("*.sql"))
    files = [p.name for p in paths]
    created = sum(
        len(re.findall(r"(?im)^\s*create\s+table\b", p.read_text(encoding="utf-8")))
        for p in paths
    )
    with _connect(db_url) as conn:
        assert apply_mod.apply(conn) == files
        assert apply_mod.apply(conn) == []
        tables = conn.execute(
            "select count(*) from pg_tables where schemaname in ('raw', 'staging', 'mart')"
        ).fetchone()[0]
        assert tables == created
        assert _history(conn) == files
        assert {s.state for s in apply_mod.status(conn)} == {"applied"}


def test_only_new_file_is_applied(db_url: str, tmp_path: Path) -> None:
    _write(tmp_path, "001_a.sql", "create table public.t1 (a int);")
    with _connect(db_url) as conn:
        assert apply_mod.apply(conn, tmp_path) == ["001_a.sql"]
        _write(tmp_path, "002_b.sql", "create table public.t2 (a int);")
        assert [s.state for s in apply_mod.status(conn, tmp_path)] == [
            "applied",
            "pending",
        ]
        assert apply_mod.apply(conn, tmp_path) == ["002_b.sql"]
        assert _exists(conn, "public.t2")


def test_changed_file_stops_before_applying(db_url: str, tmp_path: Path) -> None:
    _write(tmp_path, "001_a.sql", "create table public.t1 (a int);")
    with _connect(db_url) as conn:
        apply_mod.apply(conn, tmp_path)
        _write(tmp_path, "001_a.sql", "create table public.t1 (a int, b int);")
        _write(tmp_path, "002_b.sql", "create table public.t2 (a int);")
        with pytest.raises(MigrationError, match="내용이 바뀐 파일: 001_a.sql"):
            apply_mod.apply(conn, tmp_path)
        assert not _exists(conn, "public.t2")
        assert [s.state for s in apply_mod.status(conn, tmp_path)] == [
            "changed",
            "pending",
        ]


def test_failed_file_is_rolled_back(db_url: str, tmp_path: Path) -> None:
    _write(tmp_path, "001_a.sql", "create table public.t1 (a int);")
    _write(
        tmp_path,
        "002_b.sql",
        "create table public.t2 (a int);\nselect * from public.no_such_table;",
    )
    _write(tmp_path, "003_c.sql", "create table public.t3 (a int);")
    with _connect(db_url) as conn:
        with pytest.raises(MigrationError, match="002_b.sql 적용 실패"):
            apply_mod.apply(conn, tmp_path)
        assert _history(conn) == ["001_a.sql"]
        assert _exists(conn, "public.t1")
        assert not _exists(conn, "public.t2")  # 같은 파일의 앞 문장도 롤백
        assert not _exists(conn, "public.t3")  # 뒤 파일은 적용하지 않음


def test_new_file_sorting_before_last_applied_stops(
    db_url: str, tmp_path: Path
) -> None:
    _write(tmp_path, "002_b.sql", "create table public.t2 (a int);")
    with _connect(db_url) as conn:
        apply_mod.apply(conn, tmp_path)
        _write(tmp_path, "001_a.sql", "create table public.t1 (a int);")
        assert [s.state for s in apply_mod.status(conn, tmp_path)] == [
            "out_of_order",
            "applied",
        ]
        with pytest.raises(MigrationError, match="이름이 앞서는 새 파일: 001_a.sql"):
            apply_mod.apply(conn, tmp_path)
        assert not _exists(conn, "public.t1")


@pytest.mark.parametrize(
    "body",
    [
        # 같은 줄 `;` 뒤의 COMMIT(리뷰 재현)
        "create table public.t2 (a int); commit; select * from public.no_such_table;",
        "create table public.t2 (a int);\nCOMMIT;",
        "begin;\ncreate table public.t2 (a int);",
        "create table public.t2 (a int);\n  savepoint s1;",
        "create table public.t2 (a int);\nend;",
    ],
)
def test_transaction_control_stops_before_applying(
    db_url: str, tmp_path: Path, body: str
) -> None:
    _write(tmp_path, "001_a.sql", "create table public.t1 (a int);")
    _write(tmp_path, "002_b.sql", body)
    with _connect(db_url) as conn:
        with pytest.raises(
            MigrationError, match="트랜잭션 제어 문장이 있는 파일: 002_b.sql"
        ):
            apply_mod.apply(conn, tmp_path)
        assert _history(conn) == []
        assert not _exists(conn, "public.t1")  # 앞 파일도 적용하지 않음
        assert not _exists(conn, "public.t2")


def test_comment_mentioning_commit_is_allowed(db_url: str, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "001_a.sql",
        "-- 이 파일에는 commit을 쓰지 않는다; commit 금지\ncreate table public.t1 (a int);",
    )
    with _connect(db_url) as conn:
        assert apply_mod.apply(conn, tmp_path) == ["001_a.sql"]


def test_missing_applied_file_stops(db_url: str, tmp_path: Path) -> None:
    _write(tmp_path, "001_a.sql", "create table public.t1 (a int);")
    with _connect(db_url) as conn:
        apply_mod.apply(conn, tmp_path)
        (tmp_path / "001_a.sql").rename(tmp_path / "001_renamed.sql")
        with pytest.raises(MigrationError, match="폴더에 없는 파일: 001_a.sql"):
            apply_mod.apply(conn, tmp_path)


def test_db_made_before_history_needs_adopt(db_url: str, tmp_path: Path) -> None:
    _write(tmp_path, "001_a.sql", "create table if not exists raw.x (a int);")
    _write(tmp_path, "002_b.sql", "create table public.t2 (a int);")
    with _connect(db_url) as conn:
        conn.execute(
            "create schema raw; create table raw.x (a int)"
        )  # 이전 apply.py로 만든 DB
        with pytest.raises(MigrationError, match="이력 표"):
            apply_mod.apply(conn, tmp_path)
        with pytest.raises(MigrationError, match="폴더에 없는 파일 이름: 009_z.sql"):
            apply_mod.apply(conn, tmp_path, adopt_through="009_z.sql")
        assert not _exists(conn, "public.schema_migrations")
        # 001까지만 실행 없이 등록하고 002는 실제로 적용
        assert apply_mod.apply(conn, tmp_path, adopt_through="001_a.sql") == [
            "002_b.sql"
        ]
        assert _history(conn) == ["001_a.sql", "002_b.sql"]
        assert _exists(conn, "public.t2")
        with pytest.raises(MigrationError, match="이미 있어"):
            apply_mod.apply(conn, tmp_path, adopt_through="001_a.sql")


def test_adopt_on_empty_db_stops(db_url: str, tmp_path: Path) -> None:
    _write(tmp_path, "001_a.sql", "create table public.t1 (a int);")
    with _connect(db_url) as conn:
        with pytest.raises(MigrationError, match="등록할 표가 없다"):
            apply_mod.apply(conn, tmp_path, adopt_through="001_a.sql")
        assert not _exists(conn, "public.schema_migrations")


def test_main_adopt_existing(
    db_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    _write(tmp_path, "001_a.sql", "create table if not exists raw.x (a int);")
    _write(tmp_path, "002_b.sql", "create table public.t2 (a int);")
    with _connect(db_url) as conn:
        conn.execute("create schema raw; create table raw.x (a int)")
    monkeypatch.setenv("DATABASE_URL", db_url)
    apply_mod.main(["--adopt-existing", "001_a.sql", "--migrations-dir", str(tmp_path)])
    out = capsys.readouterr().out.splitlines()
    assert out == ["adopted 001_a.sql (실행 없음)", "applied 002_b.sql"]


def test_non_owner_stops_with_privilege_hint(
    db_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """public CREATE만 받은 계정은 CREATE SCHEMA에서 DB 권한이 없어 멈춘다(DB 소유자여야 함)."""
    _write(tmp_path, "001_a.sql", "create schema if not exists raw;")
    role = f"apply_test_{uuid.uuid4().hex[:8]}"
    password = uuid.uuid4().hex
    dbname = conninfo_to_dict(db_url)["dbname"]
    with _connect(db_url) as admin:
        admin.execute(
            sql.SQL("create role {} login password {}").format(
                sql.Identifier(role), sql.Literal(password)
            )
        )
        admin.execute(
            sql.SQL("grant create on schema public to {}").format(sql.Identifier(role))
        )
    try:
        params = conninfo_to_dict(db_url)
        params.update(user=role, password=password)
        monkeypatch.setenv("DATABASE_URL", make_conninfo(**params))
        with pytest.raises(SystemExit) as exc:
            apply_mod.main(["--migrations-dir", str(tmp_path)])
        message = str(exc.value)
        assert f"permission denied for database {dbname}" in message
        assert apply_mod.PRIVILEGE_HINT in message
    finally:
        with _connect(db_url) as admin:
            admin.execute(sql.SQL("drop owned by {}").format(sql.Identifier(role)))
            admin.execute(sql.SQL("drop role {}").format(sql.Identifier(role)))


def test_lock_held_elsewhere_stops(db_url: str, tmp_path: Path) -> None:
    _write(tmp_path, "001_a.sql", "create table public.t1 (a int);")
    with _connect(db_url) as other, _connect(db_url) as conn:
        other.execute("select pg_advisory_lock(%s)", (apply_mod.LOCK_KEY,))
        with pytest.raises(MigrationError, match="실행 중"):
            apply_mod.apply(conn, tmp_path)
        other.execute("select pg_advisory_unlock(%s)", (apply_mod.LOCK_KEY,))
        assert apply_mod.apply(conn, tmp_path) == ["001_a.sql"]


def test_needs_autocommit(db_url: str, tmp_path: Path) -> None:
    with (
        psycopg.connect(db_url) as conn,
        pytest.raises(MigrationError, match="autocommit"),
    ):
        apply_mod.apply(conn, tmp_path)


def test_main_prints_status(
    db_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    _write(tmp_path, "001_a.sql", "create table public.t1 (a int);")
    monkeypatch.setenv("DATABASE_URL", db_url)
    apply_mod.main(["--migrations-dir", str(tmp_path)])
    assert "applied 001_a.sql" in capsys.readouterr().out
    apply_mod.main(["--migrations-dir", str(tmp_path)])
    assert "적용할 파일 없음" in capsys.readouterr().out
    apply_mod.main(["--status", "--migrations-dir", str(tmp_path)])
    assert capsys.readouterr().out.startswith("applied      001_a.sql")
