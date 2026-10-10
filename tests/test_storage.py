import json
from pathlib import Path

from signal_pipeline.common.storage import (
    MAX_KEY_BYTES,
    RawStore,
    encode_source_key,
    is_pdf,
    is_zip,
)

KEY = encode_source_key(["20261002000026"])


def test_encode_source_key_keeps_korean_and_escapes_only_reserved() -> None:
    assert encode_source_key(["20261002000026"]) == "20261002000026"
    assert encode_source_key(["A01020", "20260814", "투자설명서/정정"]) == (
        "A01020~20260814~투자설명서%2F정정"
    )
    assert encode_source_key(["a~b", "50%", "x\ny"]) == "a%7Eb~50%25~x%0Ay"


def test_encode_source_key_long_value_gets_hash_suffix() -> None:
    long_key = encode_source_key(["가" * 200])
    assert len(long_key.encode("utf-8")) <= MAX_KEY_BYTES
    assert long_key.startswith("가") and "-h" in long_key
    assert encode_source_key(["가" * 200]) == long_key  # 같은 입력이면 같은 결과
    assert encode_source_key(["가" * 199 + "나"]) != long_key


def test_path_follows_storage_rule(tmp_path: Path) -> None:
    stored = RawStore(tmp_path).save("dart", KEY, "body_pdf", "pdf", b"%PDF-1 a", {})
    # raw/{source}/{원천 키}/{file_role}__v{n}.{ext}
    assert stored.storage_path == "raw/dart/20261002000026/body_pdf__v1.pdf"
    meta = json.loads((tmp_path / (stored.storage_path + ".meta.json")).read_text())
    assert meta["sha256"] == stored.sha256 and meta["version_seq"] == 1
    assert meta["source_key"] == KEY and meta["file_role"] == "body_pdf"


def test_roles_and_versions_share_one_folder(tmp_path: Path) -> None:
    store = RawStore(tmp_path)
    store.save("dart", KEY, "cover_html", "html", b"<html>", {})
    store.save("dart", KEY, "body_pdf", "pdf", b"%PDF-1 a", {})
    changed = store.save("dart", KEY, "body_pdf", "pdf", b"%PDF-1 b", {})
    assert changed.storage_path == "raw/dart/20261002000026/body_pdf__v2.pdf"
    names = sorted(p.name for p in (tmp_path / "raw/dart/20261002000026").iterdir())
    assert names == [
        "body_pdf__v1.pdf",
        "body_pdf__v1.pdf.meta.json",
        "body_pdf__v2.pdf",
        "body_pdf__v2.pdf.meta.json",
        "cover_html__v1.html",
        "cover_html__v1.html.meta.json",
    ]


def test_same_bytes_are_not_saved_again(tmp_path: Path) -> None:
    store = RawStore(tmp_path)
    first = store.save("dart", KEY, "body_pdf", "pdf", b"%PDF-1 a", {})
    second = store.save("dart", KEY, "body_pdf", "pdf", b"%PDF-1 a", {})
    assert second.reused and second.storage_path == first.storage_path
    assert len(list(tmp_path.rglob("*.pdf"))) == 1


def test_custom_name_for_pages(tmp_path: Path) -> None:
    stored = RawStore(tmp_path).save(
        "dart", "_list/2026-09-01", "api_response", "json", b"{}", {}, name="page-0001"
    )
    assert stored.storage_path == "raw/dart/_list/2026-09-01/page-0001__v1.json"


def test_latest_finds_newest_version(tmp_path: Path) -> None:
    store = RawStore(tmp_path)
    assert store.latest("dart", KEY, "body_pdf", "pdf") is None
    store.save("dart", KEY, "body_pdf", "pdf", b"%PDF-1 a", {})
    store.save("dart", KEY, "body_pdf", "pdf", b"%PDF-1 b", {})
    assert store.latest("dart", KEY, "body_pdf", "pdf").name == "body_pdf__v2.pdf"


def test_no_partial_files_left(tmp_path: Path) -> None:
    RawStore(tmp_path).save("dart", KEY, "body_pdf", "pdf", b"%PDF-1 a", {})
    assert not list(tmp_path.rglob("*.part"))


def test_format_checks() -> None:
    assert is_pdf(b"%PDF-1.7 ...") and not is_pdf(b"<html>error</html>")
    assert is_zip(b"PK\x03\x04...") and not is_zip(b"<?xml version")
