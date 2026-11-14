"""db/migrations/*.sql 중 아직 적용하지 않은 파일만 파일 이름 순서로 DATABASE_URL의 DB에 적용한다.

사용:
  DATABASE_URL=postgresql://user:pw@host:port/db uv run python db/apply.py           # 적용
  DATABASE_URL=... uv run python db/apply.py --status                                # 파일별 상태만 출력
  DATABASE_URL=... uv run python db/apply.py --adopt-existing                        # 이력 표 이전 방식으로 만든 DB 등록

규칙
- 적용한 파일은 이력 표 public.schema_migrations(filename, sha256, applied_at)에 남긴다
- 파일 하나를 한 트랜잭션으로 적용하고 같은 트랜잭션에서 이력을 남긴다. 실패하면 그 파일의 변경과 이력이
  함께 롤백되고 뒤 파일은 적용하지 않는다. 그래서 파일 안에 BEGIN·COMMIT이나 CREATE INDEX CONCURRENTLY처럼
  트랜잭션 밖에서만 도는 문장을 쓰지 않는다
- 적용한 파일은 고치지 않는다. 바꿀 내용은 새 번호 파일로 추가한다. 적용한 파일의 sha256이 이력과 다르거나,
  이력에 있는 파일이 폴더에 없거나, 새 파일 이름이 마지막으로 적용한 파일보다 앞서면 아무것도 적용하지 않고 멈춘다
- 이력 표가 없는데 raw·staging·mart 스키마에 표가 있으면(이력 표 이전의 apply.py로 만든 DB) 멈춘다.
  IF NOT EXISTS는 이미 있는 표의 정의를 바꾸지 않으므로, 다시 적용해도 지금 파일과 같은 정의라는 보장이 없다.
  DB를 새로 만들어 적용하거나, 지금 파일로 만든 DB가 확실할 때만 --adopt-existing으로 지금 파일 전체를
  실행 없이 이력에 등록한다
- 두 곳에서 동시에 실행하지 않도록 세션 수준 advisory lock을 잡는다. 이미 잡혀 있으면 기다리지 않고 멈춘다
- 실행 계정은 public 스키마에 표를 만들 수 있어야 한다(PostgreSQL 15부터 public의 CREATE 권한은 DB 소유자에게만 있음)
"""

import argparse
import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg

MIGRATIONS = Path(__file__).parent / "migrations"
HISTORY = "public.schema_migrations"
SCHEMAS = ("raw", "staging", "mart")
LOCK_KEY = 2026111301  # 이 스크립트 전용 advisory lock 번호


class MigrationError(Exception):
    pass


@dataclass(frozen=True)
class Migration:
    name: str
    sha256: str
    sql: str


@dataclass(frozen=True)
class Status:
    name: str
    state: str  # applied / pending / changed / missing
    applied_at: str | None = None


def load_files(migrations_dir: Path) -> list[Migration]:
    files = []
    for path in sorted(migrations_dir.glob("*.sql")):
        data = path.read_bytes()
        files.append(
            Migration(path.name, hashlib.sha256(data).hexdigest(), data.decode("utf-8"))
        )
    return files


def _history_exists(conn: psycopg.Connection) -> bool:
    return conn.execute("select to_regclass(%s)", (HISTORY,)).fetchone()[0] is not None


def _existing_tables(conn: psycopg.Connection) -> int:
    return conn.execute(
        "select count(*) from pg_tables where schemaname = any(%s)", (list(SCHEMAS),)
    ).fetchone()[0]


def _create_history(conn: psycopg.Connection) -> None:
    conn.execute(
        f"create table if not exists {HISTORY} ("
        " filename text primary key,"
        " sha256 char(64) not null,"
        " applied_at timestamptz not null default now())"
    )


def _applied(conn: psycopg.Connection) -> dict[str, tuple[str, str]]:
    rows = conn.execute(
        f"select filename, sha256, applied_at::text from {HISTORY} order by filename"
    ).fetchall()
    return {name: (sha, at) for name, sha, at in rows}


def status(conn: psycopg.Connection, migrations_dir: Path = MIGRATIONS) -> list[Status]:
    """파일과 이력을 대조한 상태 목록. 이력 표가 없으면 모든 파일이 pending."""
    applied = _applied(conn) if _history_exists(conn) else {}
    files = load_files(migrations_dir)
    out = []
    for m in files:
        if m.name not in applied:
            out.append(Status(m.name, "pending"))
        elif applied[m.name][0] != m.sha256:
            out.append(Status(m.name, "changed", applied[m.name][1]))
        else:
            out.append(Status(m.name, "applied", applied[m.name][1]))
    names = {m.name for m in files}
    out += [
        Status(n, "missing", at) for n, (_, at) in applied.items() if n not in names
    ]
    return sorted(out, key=lambda s: s.name)


def _check(conn: psycopg.Connection, files: list[Migration]) -> list[Migration]:
    """멈출 조건을 모두 확인하고 적용할 파일 목록을 돌려준다."""
    applied = _applied(conn)
    problems = []
    for m in files:
        if m.name in applied and applied[m.name][0] != m.sha256:
            problems.append(f"적용한 뒤 내용이 바뀐 파일: {m.name}")
    names = {m.name for m in files}
    problems += [
        f"이력에는 있으나 폴더에 없는 파일: {n}" for n in applied if n not in names
    ]
    pending = [m for m in files if m.name not in applied]
    last = max(applied, default=None)
    if last is not None:
        problems += [
            f"마지막으로 적용한 {last}보다 이름이 앞서는 새 파일: {m.name}"
            for m in pending
            if m.name < last
        ]
    if problems:
        raise MigrationError("적용하지 않고 멈춤\n- " + "\n- ".join(problems))
    return pending


def apply(
    conn: psycopg.Connection,
    migrations_dir: Path = MIGRATIONS,
    *,
    adopt_existing: bool = False,
) -> list[str]:
    """적용하지 않은 파일을 적용하고 적용한 파일 이름을 돌려준다. conn은 autocommit 연결이어야 한다."""
    if not conn.autocommit:
        raise MigrationError(
            "autocommit 연결이 필요하다(파일마다 트랜잭션을 따로 연다)"
        )
    files = load_files(migrations_dir)
    if not conn.execute("select pg_try_advisory_lock(%s)", (LOCK_KEY,)).fetchone()[0]:
        raise MigrationError(
            "다른 곳에서 apply.py를 실행 중이다. 끝난 뒤 다시 실행한다"
        )
    try:
        if not _history_exists(conn):
            if _existing_tables(conn):
                if not adopt_existing:
                    raise MigrationError(
                        f"이력 표({HISTORY}) 없이 {'·'.join(SCHEMAS)} 스키마에 표가 있다. "
                        "이력 표 이전 방식으로 만든 DB라 지금 파일과 정의가 같다는 보장이 없다. "
                        "DB를 새로 만들어 적용하거나, 지금 파일로 만든 DB가 확실하면 --adopt-existing으로 등록한다"
                    )
                with conn.transaction():
                    _create_history(conn)
                    for m in files:
                        conn.execute(
                            f"insert into {HISTORY} (filename, sha256) values (%s, %s)",
                            (m.name, m.sha256),
                        )
                return []
            if adopt_existing:
                raise MigrationError(
                    "등록할 표가 없다. 빈 DB는 --adopt-existing 없이 실행해 적용한다"
                )
            with conn.transaction():
                _create_history(conn)
        elif adopt_existing:
            raise MigrationError("이력 표가 이미 있어 --adopt-existing을 쓸 수 없다")
        done = []
        for m in _check(conn, files):
            try:
                with conn.transaction():
                    conn.execute(m.sql)
                    conn.execute(
                        f"insert into {HISTORY} (filename, sha256) values (%s, %s)",
                        (m.name, m.sha256),
                    )
            except psycopg.Error as e:
                applied = f" 앞서 적용한 파일: {', '.join(done)}." if done else ""
                raise MigrationError(
                    f"{m.name} 적용 실패. 이 파일의 변경은 롤백했다.{applied}\n{e}"
                ) from e
            done.append(m.name)
        return done
    finally:
        conn.execute("select pg_advisory_unlock(%s)", (LOCK_KEY,))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--status", action="store_true", help="파일별 상태만 출력")
    group.add_argument(
        "--adopt-existing",
        action="store_true",
        help="이력 표 없이 만든 DB의 지금 파일 전체를 실행 없이 이력에 등록",
    )
    parser.add_argument("--migrations-dir", type=Path, default=MIGRATIONS)
    args = parser.parse_args(argv)
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL 환경 변수가 필요하다")
    with psycopg.connect(url, autocommit=True) as conn:
        if args.status:
            for s in status(conn, args.migrations_dir):
                print(
                    f"{s.state:8} {s.name}"
                    + (f"  ({s.applied_at})" if s.applied_at else "")
                )
            return
        try:
            done = apply(conn, args.migrations_dir, adopt_existing=args.adopt_existing)
        except MigrationError as e:
            sys.exit(str(e))
    if args.adopt_existing:
        print(
            f"이력 표에 등록함: {len(load_files(args.migrations_dir))}개 파일(실행 없음)"
        )
    for name in done:
        print(f"applied {name}")
    if not done and not args.adopt_existing:
        print("적용할 파일 없음")


if __name__ == "__main__":
    main()
