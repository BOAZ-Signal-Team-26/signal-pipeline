import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_ddl_tables_match_dbml() -> None:
    dbml = (ROOT / "docs/schema.dbml").read_text(encoding="utf-8")
    sql = (ROOT / "db/migrations/001_erd_v2_2.sql").read_text(encoding="utf-8")
    dbml_tables = set(re.findall(r"^Table (\w+) \{", dbml, re.MULTILINE))
    sql_tables = set(
        re.findall(r"^create table if not exists (\w+) \(", sql, re.MULTILINE)
    )
    assert len(dbml_tables) == 17
    assert sql_tables == dbml_tables
