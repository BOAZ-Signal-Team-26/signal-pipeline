import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_ddl_tables_match_dbml() -> None:
    dbml = (ROOT / "docs/schema.dbml").read_text(encoding="utf-8")
    sql = (ROOT / "db/migrations/001_erd_v2_2.sql").read_text(encoding="utf-8")
    dbml_tables = set(re.findall(r"^Table (\w+) \{", dbml, re.MULTILINE))
    placed = re.findall(
        r"^create table if not exists (raw|staging|mart)\.(\w+) \(", sql, re.MULTILINE
    )
    assert len(dbml_tables) == 17
    assert {table for _, table in placed} == dbml_tables
    counts = {
        schema: sum(s == schema for s, _ in placed)
        for schema in ("raw", "staging", "mart")
    }
    assert counts == {"raw": 5, "staging": 9, "mart": 3}
    assert not re.search(r"^create table if not exists \w+ \(", sql, re.MULTILINE)
