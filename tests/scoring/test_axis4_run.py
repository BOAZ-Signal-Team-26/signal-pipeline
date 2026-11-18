"""축 4 판정 실행 통합 테스트. TEST_DATABASE_URL이 없으면 건너뛴다. 키워드 자산은 테스트용으로 바꿔 끼운다.

TEST_DATABASE_URL은 지워도 되는 빈 DB(예: signal_test)를 가리켜야 한다. 각 테스트는 트랜잭션 안에서 돌고 끝나면 롤백한다.
"""

import csv
import hashlib
import json
import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from signal_pipeline.loading.local_load import SEARCH_PATH
from signal_pipeline.scoring import axis4_run
from signal_pipeline.scoring import axis4_store as store
from signal_pipeline.scoring.axis4_export import COLUMNS, export_csv
from signal_pipeline.scoring.axis4_rules import ITEMS, Judgment
from signal_pipeline.scoring.axis4_run import dry_run, run_axis4

URL = os.environ.get("TEST_DATABASE_URL")
MIGRATIONS = Path(__file__).resolve().parents[2] / "db" / "migrations"
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL 없음")

ASSET = {
    "asset": "axis4",
    "version": "v0",
    "status": "DRAFT",
    "provenance": "test",
    "items": {
        "3.1": {"any": [{"id": "vol", "re": r"수익률\s*변동성"}]},
        "3.2": {"any": [{"id": "result", "re": r"\d+%\s*로\s*\d\s*등급"}]},
        "3.3": {
            "meaning": [{"id": "scale", "re": r"1\s*등급\s*매우\s*높은\s*위험"}],
            "caution": [{"id": "change", "re": r"등급은\s*변경될\s*수\s*있"}],
        },
        "3.4": {"any": [{"id": "grade", "re": r"위험등급\s*:?\s*\d\s*등급"}]},
        "11.2": {"any": [{"id": "deposit", "re": r"예금자\s*보호"}]},
        "body": {
            "pointer": [{"id": "ref", "re": "참고|참조"}],
            "pointer_same_doc": [{"id": "attach", "re": "붙임"}],
            "pointer_other_doc": [{"id": "other", "re": "집합투자규약"}],
        },
        "toc": {"any": [{"id": "toc", "re": r"목\s*차"}]},
    },
}
ASSET_BYTES = json.dumps(ASSET, ensure_ascii=False).encode("utf-8")
# (section_seq, kind, part_seq, 절 번호, 제목, 텍스트)
SECTIONS = [
    (1, "other", None, None, None, "표지 예금자 보호 대상이 아닙니다. 위험등급: 2등급"),
    (2, "body", 1, "1", "모집", "모집 본문"),
    (3, "body", 2, "7", "투자목적", "투자목적\n국내 주식에 투자합니다."),
    (4, "body", 2, "8", "투자대상", "투자대상\n주식 60% 이하"),
    (5, "body", 2, "9", "투자전략", "투자전략\n성장주 중심"),
    (
        6,
        "body",
        2,
        "10",
        "위험등급",
        "수익률 변동성 기준. 변동성 12%로 2등급. 1등급 매우 높은 위험. 등급은 변경될 수 있습니다.",
    ),
    (7, "body", 2, "11", "환매", "환매 본문"),
    (8, "body", 2, "13", "보수", "보수 본문"),
    (9, "body", 5, "2", "신탁의 해지", "신탁의 해지\n수익자 동의 시 해지합니다."),
]


def envelope(status, evidence=(), checked=(), value=None, reason=None) -> dict:
    return {
        "contract_version": 1,
        "status": status,
        "value": value,
        "evidence": [
            {"section_id": s, "char_start": a, "char_end": b, "quote": "q"}
            for s, a, b in evidence
        ],
        "checked_section_ids": list(checked),
        "reason_code": reason,
    }


@pytest.fixture
def db(tmp_path: Path, monkeypatch) -> Iterator[tuple[psycopg.Connection, Path, dict]]:
    assert URL
    monkeypatch.setattr(store, "read_asset", lambda: ASSET_BYTES)
    with psycopg.connect(URL, options=f"-c search_path={SEARCH_PATH}") as conn:
        for path in sorted(MIGRATIONS.glob("*.sql")):
            conn.execute(path.read_text(encoding="utf-8"))
        conn.execute(
            "insert into pipeline_run (run_id, run_kind, baseline_date, status, config_manifest, config_sha256, started_at)"
            " values ('parse-1', 'EXTRACT', '2026-11-18', 'SUCCEEDED', '{}', repeat('0', 64), now())"
        )
        docs: dict[int, dict[str, tuple[int, int, int]]] = {}
        for n in (1, 2):
            rcept = f"2026111800000{n}"
            doc = conn.execute(
                "insert into document (source, source_doc_key, source_key_payload, rcept_no, document_type,"
                " report_name, received_date) values ('dart', %s, '{}', %s, '투자설명서', 'OO증권투자신탁', '2026-11-18')"
                " returning document_id",
                (rcept, rcept),
            ).fetchone()[0]
            raw = conn.execute(
                "insert into raw_object (document_id, source, source_object_key, version_seq, body_format, file_role,"
                " sha256, storage_path, file_name, collected_at, request_params, collect_status)"
                " values (%s, 'dart', %s, 1, 'pdf', 'body_pdf', repeat('a', 64), 'x', 'a.pdf', now(), '{}', 'success')"
                " returning raw_object_id",
                (doc, rcept),
            ).fetchone()[0]
            conn.execute(
                "insert into file_extraction (raw_object_id, parser_version, created_run_id, extract_status,"
                " canonical_text_path, canonical_text_sha256, structure_status, text_length, extracted_at)"
                " values (%s, 'p1', 'parse-1', 'EXTRACT_OK', 'x', repeat('b', 64), 'NOT_REQUESTED', 9999, now())",
                (raw,),
            )
            start, ids = 0, {}
            for seq, kind, part, no, title, text in SECTIONS:
                sid = conn.execute(
                    "insert into section (document_id, raw_object_id, parser_version, section_seq, part_seq,"
                    " source_section_no, section_kind, section_title, char_start, char_end, section_text, extract_status)"
                    " values (%s, %s, 'p1', %s, %s, %s, %s, %s, %s, %s, %s, 'EXTRACT_OK') returning section_id",
                    (
                        doc,
                        raw,
                        seq,
                        part,
                        no,
                        kind,
                        title,
                        start,
                        start + len(text),
                        text,
                    ),
                ).fetchone()[0]
                ids[f"{part}/{no}"] = (sid, start, start + len(text))
                start += len(text) + 10
            docs[doc] = ids
        conn.execute(
            "insert into pipeline_run (run_id, run_kind, baseline_date, status, config_manifest, config_sha256, started_at)"
            " values ('llm-1', 'EXTRACT', '2026-11-18', 'SUCCEEDED', '{\"parser_version\": \"p1\"}', repeat('0', 64), now())"
        )
        for doc, ids in docs.items():
            s10, s13, s11 = ids["2/10"], ids["2/13"], ids["2/11"]
            fields = {
                "principal_loss_notice": envelope(
                    "FOUND", [(s10[0], s10[1], s10[1] + 5)], value="x"
                ),
                "key_risk_phrases": envelope(
                    "FOUND", [(s10[0], s10[1] + 6, s10[1] + 9)], value=["y"]
                ),
                "fee_structure": envelope(
                    "FOUND", [(s13[0], s13[1], s13[1] + 2)], value={}
                ),
                "redemption_terms": envelope(
                    "NOT_FOUND", checked=[s11[0]], reason="NOT_IN_DOCUMENT"
                ),
            }
            for field, env in fields.items():
                conn.execute(
                    "insert into llm_field_extraction (run_id, document_id, field_name, attempt_no, model_name,"
                    " prompt_sha256, input_sha256, result_status, value_json, is_selected, extracted_at)"
                    " values ('llm-1', %s, %s, 1, 'm', repeat('c', 64), repeat('d', 64), 'OK', %s, true, now())",
                    (doc, field, json.dumps(env)),
                )
        etf_doc = sorted(docs)[1]
        product = conn.execute(
            "insert into product (product_name, product_category, is_etf, etf_confidence)"
            " values ('OO ETF', 'ETF', true, 'KRX_CONFIRMED') returning product_id"
        ).fetchone()[0]
        conn.execute(
            "insert into document_product (document_id, product_id, match_method, matched_at) values (%s, %s, 'code', now())",
            (etf_doc, product),
        )
        yield conn, tmp_path, docs
        conn.rollback()


def run(db, **kw) -> dict:
    conn, root, _ = db
    return run_axis4(conn, root, "llm-1", parser_version="p1", **kw)


def test_end_to_end_and_rerun(db) -> None:
    conn, root, docs = db
    first = run(db)
    assert first["status"] == "SUCCEEDED" and first["violations"] == 0
    assert first["documents"] == 2 and first["rows"] == 20
    rid = first["run_id"]
    assert store.verify_run(conn, rid, 2) == []
    assert conn.execute(
        "select count(*) from score where run_id = %s and result_status = 'PENDING'",
        (rid,),
    ).fetchone() == (0,)
    assert conn.execute(
        "select count(*) from metric_definition where metric_key like 'disclosure_item_%'"
    ).fetchone() == (10,)
    run_row = conn.execute(
        "select status, run_kind, upstream_run_id, completed_at is not null, input_manifest_path, selection_manifest_path,"
        " config_manifest->>'purpose' from pipeline_run where run_id = %s",
        (rid,),
    ).fetchone()
    assert run_row[:4] == ("SUCCEEDED", "SCORE", "llm-1", True)
    assert run_row[4].endswith("axis4/input_manifest.jsonl") and run_row[5].endswith(
        "axis4/selection.json"
    )
    assert run_row[6] == "development"
    assert (root / run_row[5]).exists()
    assert json.loads((root / "runs" / rid / "run.json").read_text(encoding="utf-8"))[
        "selection_manifest_sha256"
    ]

    etf_doc = sorted(docs)[1]
    rows = {
        (d, p["item"]): (st, rs, raw)
        for d, p, st, rs, raw in conn.execute(
            "select document_id, score_payload, result_status, reason_code, raw_score from score where run_id = %s",
            (rid,),
        )
    }
    assert rows[(etf_doc, "4.2")] == ("NOT_APPLICABLE", "ETF_KRX_CONFIRMED", None)
    first_doc = min(docs)
    assert (
        rows[(first_doc, "4.2")][0] == "OK" and rows[(first_doc, "4.2")][2] == 0
    )  # 환매수수료 NOT_FOUND → 없음
    for item in ("나1", "나2", "3.1", "3.2", "3.3", "3.4", "4.1", "4.3", "11.2"):
        assert rows[(first_doc, item)] == ("OK", None, 1), item

    path = root / first["csv"]
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    table = list(csv.reader(path.read_text(encoding="utf-8-sig").splitlines()))
    assert (
        tuple(table[0]) == COLUMNS
        and len(table) == 21
        and all(len(r) == 6 for r in table)
    )
    assert [r[2] for r in table[1:11]] == list(ITEMS)
    assert {r[3] for r in table[1:]} <= {"있음", "없음", "판정 불가", "적용 대상 아님"}

    second = run(db)  # 같은 자산·정의 → 정의 행은 늘지 않고 새 실행이 성공
    assert second["status"] == "SUCCEEDED" and second["run_id"] != rid
    assert conn.execute(
        "select count(*) from metric_definition where metric_key like 'disclosure_item_%'"
    ).fetchone() == (10,)


def test_definition_hash_mismatch_rejects_run(db) -> None:
    conn, root, _ = db
    store.register_metrics(conn, store.install_keywords(root))
    conn.execute(
        "update metric_definition set definition_sha256 = repeat('0', 64) where metric_key = %s",
        (store.metric_key("3.1", "v0"),),
    )
    with pytest.raises(ValueError, match="해시 불일치"):
        run(db)
    assert conn.execute(
        "select count(*) from pipeline_run where run_kind = 'SCORE'"
    ).fetchone() == (0,)


def test_asset_hash_mismatch(db) -> None:
    _, root, _ = db
    sha = hashlib.sha256(ASSET_BYTES).hexdigest()
    target = root / f"assets/keywords/axis4__v0__{sha[:12]}.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"{}")
    with pytest.raises(ValueError, match="자산 해시 불일치"):
        run(db)


def test_upstream_must_be_succeeded_extract(db) -> None:
    conn, _, _ = db
    conn.execute("update pipeline_run set status = 'FAILED' where run_id = 'llm-1'")
    with pytest.raises(ValueError, match="EXTRACT/SUCCEEDED"):
        run(db)


def test_exception_closes_run_as_failed(db, monkeypatch) -> None:
    conn, _, _ = db

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(store, "update_judgments", boom)
    with pytest.raises(RuntimeError):
        run(db)
    assert conn.execute(
        "select status from pipeline_run where run_kind = 'SCORE'"
    ).fetchone() == ("FAILED",)


def test_verify_run_detects_violations(db) -> None:
    conn, _, docs = db
    rid = run(db)["run_id"]
    conn.execute(
        "update score set score_payload = jsonb_set(score_payload, '{evidence}',"
        " '[{\"section_id\": 1, \"char_start\": 0, \"char_end\": 999999}]') where run_id = %s and score_payload->>'item' = '3.1'"
        " and document_id = %s",
        (rid, min(docs)),
    )
    conn.execute(
        "update score set score_payload = jsonb_set(score_payload, '{checked_section_ids}', '[]')"
        " where run_id = %s and score_payload->>'item' = '4.2' and document_id = %s",
        (rid, min(docs)),
    )
    errors = store.verify_run(conn, rid, 2)
    assert any("범위 밖" in e for e in errors) and any(
        "검사한 절이 없음" in e for e in errors
    )
    assert store.verify_run(conn, rid, 3)[0].startswith("행 수")


def test_dry_run_writes_nothing(db) -> None:
    conn, root, _ = db
    result = dry_run(conn, "llm-1", "p1", None, None)
    assert result["documents"] == 2 and result["status_counts"]["3.4:MET"] == 2
    assert result["status_counts"]["4.2:NOT_APPLICABLE"] == 1
    assert conn.execute("select count(*) from score").fetchone() == (0,)
    assert conn.execute("select count(*) from metric_definition").fetchone() == (0,)
    assert not list(root.rglob("*"))


def test_parser_version_defaults_to_llm_run_and_rejects_mismatch(db) -> None:
    conn, root, _ = db
    assert (
        run_axis4(conn, root, "llm-1")["status"] == "SUCCEEDED"
    )  # 기본값 = LLM 실행의 p1
    with pytest.raises(ValueError, match="다름"):
        run_axis4(conn, root, "llm-1", parser_version="p2")
    conn.execute(
        "update pipeline_run set config_manifest = '{}' where run_id = 'llm-1'"
    )
    with pytest.raises(ValueError, match="parser_version 기록이 없음"):
        run_axis4(conn, root, "llm-1")


def test_other_metric_rows_in_same_run_are_ignored(db) -> None:
    conn, root, docs = db
    rid = run(db)["run_id"]
    conn.execute(
        "insert into metric_definition (metric_key, metric_id, version, target_type, level, direction,"
        " definition_status, definition_manifest, definition_sha256)"
        " values ('other_metric:v1', 'other_metric', 'v1', 'DOCUMENT', 'ATOMIC', 'HIGHER_IS_BETTER', 'DRAFT', '{}', repeat('0', 64))"
    )
    conn.execute(
        "insert into score (run_id, target_type, target_key, document_id, metric_key, assessor_key, result_status,"
        " reason_code, normalization_status, score_payload, scored_at)"
        " values (%s, 'DOCUMENT', repeat('1', 64), %s, 'other_metric:v1', 'x', 'PENDING', 'PLANNED', 'NOT_REQUESTED',"
        " '{}', now())",
        (rid, min(docs)),
    )
    assert store.verify_run(conn, rid, 2) == []
    assert sum(store.status_counts(conn, rid).values()) == 20
    (
        root / "exports" / "runs" / rid / "axis4_judgments.csv"
    ).unlink()  # 이미 쓴 CSV를 지우고 다시 내보낸다
    path = export_csv(conn, root, rid)
    assert len(path.read_text(encoding="utf-8-sig").splitlines()) == 21


def test_close_failure_keeps_original_exception_and_hides_message(
    db, monkeypatch, capsys
) -> None:
    def boom(*a, **k):
        raise RuntimeError("postgresql://user@secret-host/db")

    monkeypatch.setattr(store, "update_judgments", boom)
    monkeypatch.setattr(axis4_run, "_close", boom)
    with pytest.raises(RuntimeError, match="secret-host"):
        run(db)
    err = capsys.readouterr().err
    assert "RuntimeError" in err and "secret-host" not in err


def test_stopped_by_records_type_and_sqlstate_only(db, monkeypatch) -> None:
    _, root, _ = db

    def boom(*a, **k):
        raise psycopg.errors.UniqueViolation("Key (host)=(secret-host)")

    monkeypatch.setattr(store, "update_judgments", boom)
    with pytest.raises(psycopg.errors.UniqueViolation):
        run(db)
    (run_json,) = (root / "runs").glob("*/run.json")
    text = run_json.read_text(encoding="utf-8")
    assert "UniqueViolation SQLSTATE 23505" in text and "secret-host" not in text


def test_judgment_count_mismatch_raises(db) -> None:
    conn, _, docs = db
    rid = run(db)["run_id"]  # PENDING이 이미 없으므로 UPDATE가 0행
    with pytest.raises(ValueError, match="불일치"):
        store.update_judgments(
            conn, rid, min(docs), [Judgment("3.1", "UNDETERMINED", "X")], "v0"
        )


def test_changed_asset_with_same_version_is_rejected(db, monkeypatch) -> None:
    assert run(db)["status"] == "SUCCEEDED"
    changed = json.dumps(
        {**ASSET, "provenance": "changed"}, ensure_ascii=False
    ).encode()
    monkeypatch.setattr(store, "read_asset", lambda: changed)
    with pytest.raises(ValueError, match="새 지표 버전"):
        run(db)


def test_new_asset_version_makes_new_metric_keys(db, monkeypatch) -> None:
    conn, _, _ = db
    assert run(db)["status"] == "SUCCEEDED"
    v1 = json.dumps({**ASSET, "version": "v1"}, ensure_ascii=False).encode()
    monkeypatch.setattr(store, "read_asset", lambda: v1)
    second = run(db)
    assert second["status"] == "SUCCEEDED"
    assert conn.execute(
        "select count(*) from metric_definition where metric_key like 'disclosure_item_%'"
    ).fetchone() == (20,)
    assert conn.execute(
        "select count(distinct metric_key) from score where run_id = %s and metric_key like '%%:v1'",
        (second["run_id"],),
    ).fetchone() == (10,)


def test_etf_by_report_name_is_not_applicable(db) -> None:
    conn, _, docs = db
    conn.execute(
        "update document set report_name = 'OO 상장지수투자신탁' where document_id = %s",
        (min(docs),),
    )
    rid = run(db)["run_id"]
    assert conn.execute(
        "select result_status, reason_code from score where run_id = %s and document_id = %s"
        " and score_payload->>'item' = '4.2'",
        (rid, min(docs)),
    ).fetchone() == ("NOT_APPLICABLE", "ETF_REPORT_NAME")
