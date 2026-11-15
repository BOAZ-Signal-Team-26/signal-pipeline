"""db/migrations/*.sql 중 아직 적용하지 않은 파일만 파일 이름 순서로 DATABASE_URL의 DB에 적용한다.

사용:
  DATABASE_URL=postgresql://user:pw@host:port/db uv run python db/apply.py           # 적용
  DATABASE_URL=... uv run python db/apply.py --status                                # 파일별 상태만 출력
  DATABASE_URL=... uv run python db/apply.py --adopt-existing 001_erd_v2_2.sql       # 이력 표 이전 방식으로 만든 DB 등록

규칙
- 적용한 파일은 이력 표 public.schema_migrations(filename, sha256, applied_at)에 남긴다
- 파일 하나를 한 트랜잭션으로 적용하고 같은 트랜잭션에서 이력을 남긴다. 실패하면 그 파일의 변경과 이력이
  함께 롤백되고 뒤 파일은 적용하지 않는다. 그래서 파일 안에 CREATE INDEX CONCURRENTLY처럼 트랜잭션 밖에서만
  도는 문장을 쓰지 않는다. 트랜잭션 제어 문장(BEGIN·COMMIT·ROLLBACK·SAVEPOINT 등)이 있으면 그 지점에서
  트랜잭션이 끝나 앞 문장만 남으므로, 적용할 파일에 이런 문장이 있으면 아무것도 적용하지 않고 멈춘다.
  검사는 줄 처음이나 `;` 뒤에 오는 키워드로 하므로, 여러 줄 CASE의 END나 PL/pgSQL 본문의 BEGIN·END가
  줄 처음에 오면 잘못 멈출 수 있다
- 적용한 파일은 고치지 않는다. 바꿀 내용은 새 번호 파일로 추가한다. 적용한 파일의 sha256이 이력과 다르거나,
  이력에 있는 파일이 폴더에 없거나, 새 파일 이름이 마지막으로 적용한 파일보다 앞서면 아무것도 적용하지 않고 멈춘다
- 이력 표가 없는데 raw·staging·mart 스키마에 표가 있으면(이력 표 이전의 apply.py로 만든 DB) 멈춘다.
  IF NOT EXISTS는 이미 있는 표의 정의를 바꾸지 않으므로, 다시 적용해도 지금 파일과 같은 정의라는 보장이 없다.
  DB를 새로 만들어 적용하거나, 지금 파일로 만든 DB가 확실할 때만 --adopt-existing <마지막 파일 이름>으로
  그 파일까지 실행 없이 이력에 등록한다. 그 뒤 파일은 이어서 실제로 적용한다. 스키마가 파일과 같은지는 확인하지 않는다
- 두 곳에서 동시에 실행하지 않도록 세션 수준 advisory lock을 잡는다. 이미 잡혀 있으면 기다리지 않고 멈춘다
- 실행 계정은 대상 DB의 소유자여야 한다. 001의 CREATE SCHEMA는 DB의 CREATE 권한이, 이력 표는 public 스키마의
  CREATE 권한이 필요하고, 둘 다 기본으로 DB 소유자에게만 있다(public은 PostgreSQL 15부터)
"""

import argparse
import contextlib
import hashlib
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg

MIGRATIONS = Path(__file__).parent / "migrations"
HISTORY = "public.schema_migrations"
SCHEMAS = ("raw", "staging", "mart")
LOCK_KEY = 2026111301  # 이 스크립트 전용 advisory lock 번호
# 줄 처음이나 `;` 뒤에 오는 트랜잭션 제어 키워드. 주석(--)은 지운 뒤 찾는다
TX_CONTROL = re.compile(
    r"(?:^|;)\s*(begin|start\s+transaction|commit|end|abort|rollback|savepoint|release)\b",
    re.IGNORECASE | re.MULTILINE,
)
PRIVILEGE_HINT = "실행 계정에 권한이 없다. 대상 DB의 소유자 계정(RDS에서는 signal_owner)으로 실행한다"


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
    state: str  # applied / pending / changed / missing / out_of_order
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
    """파일과 이력을 대조한 상태 목록. 이력 표가 없으면 모든 파일이 pending.

    out_of_order: 이력에 없지만 이름이 마지막 적용 파일보다 앞서서 apply가 멈추는 파일
    """
    applied = _applied(conn) if _history_exists(conn) else {}
    last = max(applied, default=None)
    files = load_files(migrations_dir)
    out = []
    for m in files:
        if m.name not in applied:
            late = last is not None and m.name < last
            out.append(Status(m.name, "out_of_order" if late else "pending"))
        elif applied[m.name][0] != m.sha256:
            out.append(Status(m.name, "changed", applied[m.name][1]))
        else:
            out.append(Status(m.name, "applied", applied[m.name][1]))
    names = {m.name for m in files}
    out += [
        Status(n, "missing", at) for n, (_, at) in applied.items() if n not in names
    ]
    return sorted(out, key=lambda s: s.name)


def _tx_control(sql_text: str) -> list[str]:
    """파일 안 트랜잭션 제어 키워드 목록(소문자, 나온 순서)."""
    no_comments = re.sub(r"--[^\n]*", "", sql_text)
    return [k.lower() for k in TX_CONTROL.findall(no_comments)]


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
    for m in pending:
        found = _tx_control(m.sql)
        if found:
            problems.append(
                f"트랜잭션 제어 문장이 있는 파일: {m.name} ({', '.join(dict.fromkeys(found))})"
            )
    if problems:
        raise MigrationError("적용하지 않고 멈춤\n- " + "\n- ".join(problems))
    return pending


def apply(
    conn: psycopg.Connection,
    migrations_dir: Path = MIGRATIONS,
    *,
    adopt_through: str | None = None,
) -> list[str]:
    """적용하지 않은 파일을 적용하고 적용한 파일 이름을 돌려준다. conn은 autocommit 연결이어야 한다.

    adopt_through: 이력 표 없이 만든 DB에서 이 이름까지의 파일을 실행 없이 이력에 등록한 뒤 나머지를 적용한다
    """
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
                if adopt_through is None:
                    raise MigrationError(
                        f"이력 표({HISTORY}) 없이 {'·'.join(SCHEMAS)} 스키마에 표가 있다. "
                        "이력 표 이전 방식으로 만든 DB라 지금 파일과 정의가 같다는 보장이 없다. "
                        "DB를 새로 만들어 적용하거나, 지금 파일로 만든 DB가 확실하면 "
                        "--adopt-existing <마지막 파일 이름>으로 등록한다"
                    )
                if adopt_through not in {m.name for m in files}:
                    raise MigrationError(f"폴더에 없는 파일 이름: {adopt_through}")
                with conn.transaction():
                    _create_history(conn)
                    for m in files:
                        if m.name <= adopt_through:
                            conn.execute(
                                f"insert into {HISTORY} (filename, sha256) values (%s, %s)",
                                (m.name, m.sha256),
                            )
            elif adopt_through is not None:
                raise MigrationError(
                    "등록할 표가 없다. 빈 DB는 --adopt-existing 없이 실행해 적용한다"
                )
            else:
                with conn.transaction():
                    _create_history(conn)
        elif adopt_through is not None:
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
                hint = (
                    f"\n{PRIVILEGE_HINT}"
                    if isinstance(e, psycopg.errors.InsufficientPrivilege)
                    else ""
                )
                raise MigrationError(
                    f"{m.name} 적용 실패. 이 파일의 변경은 롤백했다.{applied}\n{e}{hint}"
                ) from e
            done.append(m.name)
        return done
    finally:
        # 세션 락이라 연결이 끊기면 풀린다. 여기서 난 오류가 원래 실패 원인을 가리지 않게 한다
        with contextlib.suppress(psycopg.Error):
            conn.execute("select pg_advisory_unlock(%s)", (LOCK_KEY,))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--status", action="store_true", help="파일별 상태만 출력")
    group.add_argument(
        "--adopt-existing",
        metavar="LAST_FILE",
        help="이력 표 없이 만든 DB에서 이 파일까지 실행 없이 이력에 등록하고 뒤 파일은 적용",
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
                    f"{s.state:12} {s.name}"
                    + (f"  ({s.applied_at})" if s.applied_at else "")
                )
            return
        try:
            done = apply(conn, args.migrations_dir, adopt_through=args.adopt_existing)
        except MigrationError as e:
            sys.exit(str(e))
        except psycopg.errors.InsufficientPrivilege as e:
            sys.exit(f"{e}\n{PRIVILEGE_HINT}")
    if args.adopt_existing:
        for m in load_files(args.migrations_dir):
            if m.name <= args.adopt_existing:
                print(f"adopted {m.name} (실행 없음)")
    for name in done:
        print(f"applied {name}")
    if not done and not args.adopt_existing:
        print("적용할 파일 없음")


if __name__ == "__main__":
    main()
