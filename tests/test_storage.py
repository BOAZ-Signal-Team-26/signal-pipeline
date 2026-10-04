import json
from pathlib import Path

from signal_pipeline.common.storage import RawStore, is_pdf, is_zip, object_key_hash

KEY = {"rcept_no": "20261002000026", "file_role": "body_pdf"}


def test_object_key_hash_ignores_key_order() -> None:
    assert object_key_hash({"a": "1", "b": "2"}) == object_key_hash(
        {"b": "2", "a": "1"}
    )
    assert object_key_hash({"a": "1"}) != object_key_hash({"a": "2"})


def test_path_follows_storage_rule(tmp_path: Path) -> None:
    stored = RawStore(tmp_path).save("dart", KEY, "body_pdf", "pdf", b"%PDF-1 a", {})
    parts = Path(stored.storage_path).parts
    # raw/{source}/{collected_date}/{object_key_hash}/{file_role}__v{n}.{ext}
    assert parts[0] == "raw" and parts[1] == "dart"
    assert parts[3] == object_key_hash(KEY)
    assert parts[4] == "body_pdf__v1.pdf"
    meta = json.loads((tmp_path / (stored.storage_path + ".meta.json")).read_text())
    assert meta["sha256"] == stored.sha256 and meta["version_seq"] == 1


def test_same_bytes_are_not_saved_again(tmp_path: Path) -> None:
    store = RawStore(tmp_path)
    first = store.save("dart", KEY, "body_pdf", "pdf", b"%PDF-1 a", {})
    second = store.save("dart", KEY, "body_pdf", "pdf", b"%PDF-1 a", {})
    assert second.reused and second.storage_path == first.storage_path
    assert len(list(tmp_path.rglob("*.pdf"))) == 1


def test_changed_bytes_make_next_version(tmp_path: Path) -> None:
    store = RawStore(tmp_path)
    store.save("dart", KEY, "body_pdf", "pdf", b"%PDF-1 a", {})
    changed = store.save("dart", KEY, "body_pdf", "pdf", b"%PDF-1 b", {})
    assert not changed.reused and changed.version_seq == 2


def test_no_partial_files_left(tmp_path: Path) -> None:
    RawStore(tmp_path).save("dart", KEY, "body_pdf", "pdf", b"%PDF-1 a", {})
    assert not list(tmp_path.rglob("*.part"))


def test_format_checks() -> None:
    assert is_pdf(b"%PDF-1.7 ...") and not is_pdf(b"<html>error</html>")
    assert is_zip(b"PK\x03\x04...") and not is_zip(b"<?xml version")
