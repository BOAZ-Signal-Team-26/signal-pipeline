"""db/migrations/*.sql을 파일 이름 순서로 DATABASE_URL의 DB에 적용한다.

사용: DATABASE_URL=postgresql://user:pw@host:port/db uv run python db/apply.py
각 파일은 다시 실행해도 변화가 없도록 작성하므로(IF NOT EXISTS) 적용 이력 표를 두지 않는다.
"""

import os
import sys
from pathlib import Path

import psycopg

MIGRATIONS = Path(__file__).parent / "migrations"


def main() -> None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL 환경 변수가 필요하다")
    with psycopg.connect(url) as conn:  # 블록이 정상 종료되면 커밋, 예외면 롤백
        for path in sorted(MIGRATIONS.glob("*.sql")):
            conn.execute(path.read_text(encoding="utf-8"))
            print(f"applied {path.name}")


if __name__ == "__main__":
    main()
