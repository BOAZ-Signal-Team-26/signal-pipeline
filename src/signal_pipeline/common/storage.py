"""원본 파일 저장. docs/storage-and-failure-rules.md 「원본 보관」을 그대로 구현한다.

경로: {RAW_ROOT}/raw/{source}/{collected_date}/{object_key_hash}/{file_role}__v{version_seq}.{ext}
      + 같은 이름 뒤에 .meta.json

- object_key_hash: source_object_key(원천 구성 필드)를 정렬된 UTF-8 JSON으로 만든 SHA-256
- 같은 source·source_object_key의 최신 판과 바이트 SHA-256이 같으면 새 판을 만들지 않고 기존 판을 돌려준다
- 원본은 고치지 않는다. 내용이 바뀌었을 때만 version_seq를 1 올린 새 파일을 쓴다
- 반환하는 storage_path는 RAW_ROOT 기준 상대경로
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


def object_key_hash(source_object_key: dict[str, str]) -> str:
    text = json.dumps(
        source_object_key, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def is_pdf(content: bytes) -> bool:
    return content.startswith(b"%PDF-")


def is_zip(content: bytes) -> bool:
    return content.startswith(b"PK\x03\x04")


@dataclass
class StoredObject:
    storage_path: str
    sha256: str
    version_seq: int
    size: int
    reused: bool


class RawStore:
    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)

    def _versions(
        self, source: str, key_hash: str, file_role: str, ext: str
    ) -> list[tuple[int, Path]]:
        pattern = re.compile(rf"^{re.escape(file_role)}__v(\d+)\.{re.escape(ext)}$")
        found = []
        for path in (self.root / "raw" / source).glob(
            f"*/{key_hash}/{file_role}__v*.{ext}"
        ):
            match = pattern.match(path.name)
            if match:
                found.append((int(match.group(1)), path))
        return sorted(found)

    def latest(
        self, source: str, source_object_key: dict[str, str], file_role: str, ext: str
    ) -> Path | None:
        """같은 source·키·역할의 최신 판 파일. 없으면 None. 이미 받은 원본을 건너뛸 때 쓴다."""
        versions = self._versions(
            source, object_key_hash(source_object_key), file_role, ext
        )
        return versions[-1][1] if versions else None

    def save(
        self,
        source: str,
        source_object_key: dict[str, str],
        file_role: str,
        ext: str,
        content: bytes,
        meta: dict[str, object],
    ) -> StoredObject:
        key_hash = object_key_hash(source_object_key)
        digest = sha256_hex(content)
        versions = self._versions(source, key_hash, file_role, ext)

        if versions:
            latest_seq, latest_path = versions[-1]
            if sha256_hex(latest_path.read_bytes()) == digest:
                return StoredObject(
                    str(latest_path.relative_to(self.root)),
                    digest,
                    latest_seq,
                    len(content),
                    reused=True,
                )
        version_seq = versions[-1][0] + 1 if versions else 1

        collected_at = datetime.now(UTC)
        folder = self.root / "raw" / source / collected_at.date().isoformat() / key_hash
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{file_role}__v{version_seq}.{ext}"
        _write_atomic(path, content)

        record = {
            "source": source,
            "source_object_key": source_object_key,
            "file_role": file_role,
            "version_seq": version_seq,
            "sha256": digest,
            "size": len(content),
            "collected_at": collected_at.isoformat(timespec="seconds"),
            **meta,
        }
        meta_path = path.with_name(path.name + ".meta.json")
        _write_atomic(
            meta_path, json.dumps(record, ensure_ascii=False, indent=1).encode()
        )
        return StoredObject(
            str(path.relative_to(self.root)),
            digest,
            version_seq,
            len(content),
            reused=False,
        )


def _write_atomic(path: Path, data: bytes) -> None:
    """임시 파일에 다 쓴 뒤 이름을 바꾼다. 중간에 끊겨도 반쪽 파일이 남지 않는다."""
    temp = path.with_name(path.name + ".part")
    temp.write_bytes(data)
    os.replace(temp, path)
