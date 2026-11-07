"""LLM 추출 실행을 가짜 Bedrock 응답으로 끝까지 돌리는 테스트. TEST_DATABASE_URL이 없으면 건너뛴다.

TEST_DATABASE_URL은 지워도 되는 빈 DB(예: signal_test)를 가리켜야 한다. 각 테스트는 트랜잭션 안에서 돌고 끝나면 롤백한다.
"""

import json
import os
from collections.abc import Iterator
from pathlib import Path

import httpx
import psycopg
import pytest

from signal_pipeline.extraction.bedrock import MODELS, TOKEN_ENV, BedrockClient
from signal_pipeline.extraction.run import run_extraction
from signal_pipeline.extraction.store import check_selected, verify_run, write_new
from signal_pipeline.loading.local_load import SEARCH_PATH

URL = os.environ.get("TEST_DATABASE_URL")
MIGRATIONS = Path(__file__).resolve().parents[2] / "db" / "migrations"
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL 없음")
FAKE = "FAKE-BEDROCK-TOKEN-9f8e7d"

LOSS = "투자원금의 손실이 발생할 수 있습니다."
RISK1 = "주가 변동에 따라 손실이 날 수 있습니다."
RISK2 = "환율 변동에 따라 손실이 날 수 있습니다."
FEE_TEXT = "A클래스 판매수수료 납입금액의 1.00% 이내"
NO_FEE = "이 투자신탁은 환매수수료를 부과하지 않습니다."
# (section_seq, kind, part_seq, 절 번호, 텍스트)
SECTIONS = [
    (
        1,
        "other",
        None,
        None,
        "표지. 원금 보장 없음",
    ),  # 원금손실 문장은 10절에서 찾아 key_risk_phrases와 겹치게 함
    (2, "summary", None, None, FEE_TEXT),
    (3, "body", 2, "10", f"{LOSS} {RISK1} {RISK2}"),
    (4, "body", 2, "11", NO_FEE),
    (5, "body", 2, "13", "보수 본문"),
]
LOAD = {
    "rate": {"amount": 1.0, "unit": "%"},
    "basis": "납입금액",
    "condition": None,
    "text": "1.00% 이내",
}
FEE = {
    "classes": [
        {
            "class_name": "A",
            "front_load": LOAD,
            "back_load": None,
            "total_fee": None,
            "peer_total_fee": None,
        }
    ]
}


def answer(status="FOUND", value=None, quotes=(), reason_code=None) -> str:
    return json.dumps(
        {
            "status": status,
            "value": value,
            "evidence": [{"quote": q} for q in quotes],
            "reason_code": reason_code,
            "notes": None,
        },
        ensure_ascii=False,
    )


GOOD = {
    "principal_loss_notice": answer(value=LOSS, quotes=[LOSS]),
    "key_risk_phrases": answer(
        value=[LOSS, RISK1, RISK2], quotes=[LOSS, RISK1, RISK2]
    ),  # LOSS는 중복 제거 대상
    "fee_structure": answer(value=FEE, quotes=[FEE_TEXT]),
    "redemption_terms": answer(value={"tiers": []}, quotes=[NO_FEE]),
}


def body(text: str) -> bytes:
    return json.dumps(
        {
            "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
            "usage": {"inputTokens": 1000, "outputTokens": 100, "totalTokens": 1100},
        },
        ensure_ascii=False,
    ).encode()


class Fake:
    """필드별 응답 목록을 차례로 돌려준다. 목록이 끝나면 GOOD."""

    def __init__(self, script: dict[str, list] | None = None) -> None:
        self.script = {k: list(v) for k, v in (script or {}).items()}
        self.calls: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {FAKE}"
        system = json.loads(request.content)["system"][0]["text"]
        field = next(f for f in GOOD if f"({f})" in system.splitlines()[0])
        self.calls.append(field)
        queue = self.script.get(field) or []
        item = queue.pop(0) if queue else GOOD[field]
        if isinstance(item, int):
            return httpx.Response(
                item, content=f'{{"message":"error {FAKE}"}}'.encode()
            )
        return httpx.Response(200, content=body(item))


@pytest.fixture
def db(tmp_path: Path, monkeypatch) -> Iterator[tuple[psycopg.Connection, Path]]:
    assert URL
    monkeypatch.setenv(TOKEN_ENV, FAKE)
    with psycopg.connect(URL, options=f"-c search_path={SEARCH_PATH}") as conn:
        for path in sorted(MIGRATIONS.glob("*.sql")):
            conn.execute(path.read_text(encoding="utf-8"))
        conn.execute(
            "insert into pipeline_run (run_id, run_kind, baseline_date, status, config_manifest, config_sha256, started_at)"
            " values ('parse-1', 'EXTRACT', '2026-11-07', 'SUCCEEDED', '{}', repeat('0', 64), now())"
        )
        for n in (1, 2):
            rcept = f"2026110700000{n}"
            doc = conn.execute(
                "insert into document (source, source_doc_key, source_key_payload, rcept_no, document_type,"
                " report_name, received_date) values ('dart', %s, '{}', %s, '투자설명서', 'OO증권투자신탁', '2026-11-07')"
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
            start = 0
            for seq, kind, part, no, text in SECTIONS:
                conn.execute(
                    "insert into section (document_id, raw_object_id, parser_version, section_seq, part_seq,"
                    " source_section_no, section_kind, char_start, char_end, section_text, extract_status)"
                    " values (%s, %s, 'p1', %s, %s, %s, %s, %s, %s, %s, 'EXTRACT_OK')",
                    (doc, raw, seq, part, no, kind, start, start + len(text), text),
                )
                start += len(text) + 10
        yield conn, tmp_path
        conn.rollback()


def run(db, fake: Fake, **kw) -> dict:
    conn, root = db
    client = BedrockClient(
        MODELS["lite"],
        backoff_base=0,
        max_retries=1,
        transport=httpx.MockTransport(fake),
    )
    return run_extraction(conn, root, client, workers=kw.pop("workers", 2), **kw)


def rows(conn, run_id: str) -> list[tuple]:
    return conn.execute(
        "select document_id, field_name, attempt_no, result_status, is_selected, input_tokens, raw_response_path,"
        " value_json, error_reason from llm_field_extraction where run_id = %s order by 1, 2, 3",
        (run_id,),
    ).fetchall()


def test_end_to_end_then_reuse_skips_calls(db) -> None:
    conn, root = db
    fake = Fake()
    first = run(db, fake)
    assert (
        first["status"] == "SUCCEEDED" and first["calls"] == 8 and first["reused"] == 0
    )
    r1 = rows(conn, first["run_id"])
    assert len(r1) == 8 and all(r[3] == "OK" and r[4] for r in r1)
    krp = next(r for r in r1 if r[1] == "key_risk_phrases")
    assert krp[7]["value"] == [RISK1, RISK2]  # 문서 단위 중복 제거 반영
    assert verify_run(conn, root, first["run_id"]) == []
    assert conn.execute(
        "select status, completed_at is not null from pipeline_run where run_id = %s",
        (first["run_id"],),
    ).fetchone() == ("SUCCEEDED", True)
    assert (root / "runs" / first["run_id"] / "llm" / "excluded_etf.json").exists()

    second = run(db, fake)
    assert second["calls"] == 0 and second["reused"] == 8 and len(fake.calls) == 8
    r2 = rows(conn, second["run_id"])
    assert all(r[3] == "OK" and r[4] and r[5] is None for r in r2)  # 토큰 NULL
    assert sorted(r[6] for r in r2) == sorted(
        r[6] for r in r1
    )  # 원래 response.json을 가리킴
    assert not list((root / "runs" / second["run_id"]).rglob("response.json"))
    req = json.loads(
        next((root / "runs" / second["run_id"]).rglob("request.json")).read_text(
            encoding="utf-8"
        )
    )
    assert req["reused_from"]["run_id"] == first["run_id"]
    assert verify_run(conn, root, second["run_id"]) == []


def test_failed_is_recalled_with_attempt_2(db) -> None:
    conn, root = db
    fake = Fake({"redemption_terms": ["not json", 500, 500]})
    result = run(db, fake, workers=1)
    got = [
        (r[0], r[2], r[3], r[4], r[8])
        for r in rows(conn, result["run_id"])
        if r[1] == "redemption_terms"
    ]
    doc1, doc2 = sorted({g[0] for g in got})
    # 문서 1: PARSE_FAILED → 재호출(HTTP 500 두 번) CALL_FAILED. 문서 2: 남은 응답 없어 GOOD
    assert [g[1:] for g in got if g[0] == doc1] == [
        (1, "FAILED", False, "PARSE_FAILED"),
        (2, "FAILED", True, "CALL_FAILED"),
    ]
    assert [g[1:] for g in got if g[0] == doc2] == [(1, "OK", True, None)]
    assert verify_run(conn, root, result["run_id"]) == []

    # 다음 실행: 이전 FAILED는 재사용하지 않고 다시 호출
    again = run(db, Fake())
    assert again["calls"] == 1 and again["reused"] == 7


def test_evidence_not_located_reconverts_stored_response(db) -> None:
    conn, _ = db
    first = run(db, Fake())
    # 예전 변환기가 근거를 못 찾았던 상황을 흉내 낸다
    conn.execute(
        "update llm_field_extraction set result_status = 'FAILED', error_reason = 'EVIDENCE_NOT_LOCATED',"
        " value_json = jsonb_set(value_json, '{reason_code}', '\"EVIDENCE_NOT_LOCATED\"')"
        " where run_id = %s and field_name = 'fee_structure'",
        (first["run_id"],),
    )
    fake = Fake()
    second = run(db, fake)
    assert fake.calls == [] and second["reused"] == 8
    fee = [r for r in rows(conn, second["run_id"]) if r[1] == "fee_structure"]
    assert all(r[3] == "OK" and r[2] == 1 for r in fee)


def test_evidence_not_located_in_run_calls_once_more(db) -> None:
    conn, _ = db
    bad = answer(value=FEE, quotes=["없는 문장"])
    fake = Fake({"fee_structure": [bad, bad, bad, bad]})
    result = run(db, fake, workers=1)
    fee = [r for r in rows(conn, result["run_id"]) if r[1] == "fee_structure"]
    assert [(r[2], r[8], r[4]) for r in fee] == [
        (1, "EVIDENCE_NOT_LOCATED", False),
        (2, "EVIDENCE_NOT_LOCATED", True),
    ] * 2
    assert fake.calls.count("fee_structure") == 4  # 문서당 최대 2회


def test_is_selected_unique_and_check_query(db) -> None:
    conn, _ = db
    result = run(db, Fake({"principal_loss_notice": ["x"]}))
    assert check_selected(conn, result["run_id"]) == []
    conn.execute(
        "update llm_field_extraction set is_selected = true where run_id = %s and attempt_no = 1",
        (result["run_id"],),
    )
    bad = check_selected(conn, result["run_id"])
    assert (
        len(bad) == 1
        and bad[0]["field_name"] == "principal_loss_notice"
        and bad[0]["selected"] == 2
    )


def test_budget_stops_new_calls(db) -> None:
    conn, _ = db
    fake = Fake()
    # 호출 1회 = 1000*0.30/1e6 + 100*2.50/1e6 = 0.00055달러
    result = run(db, fake, workers=1, budget_usd=0.001)
    assert result["status"] == "FAILED" and "budget" in result["reason"]
    assert result["calls"] == 2 and len(fake.calls) == 2
    assert conn.execute(
        "select status from pipeline_run where run_id = %s", (result["run_id"],)
    ).fetchone() == ("FAILED",)


def test_no_key_in_written_files(db) -> None:
    conn, root = db
    result = run(db, Fake({"principal_loss_notice": [400]}))
    files = [p for p in root.rglob("*") if p.is_file()]
    assert files and not [p for p in files if FAKE.encode() in p.read_bytes()]
    dump = json.dumps(
        [list(map(str, r)) for r in rows(conn, result["run_id"])], ensure_ascii=False
    )
    assert FAKE not in dump


def test_write_new_refuses_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "a" / "response.json"
    write_new(path, b"first")
    with pytest.raises(FileExistsError):
        write_new(path, b"second")
    assert path.read_bytes() == b"first"
