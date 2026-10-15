"""원본 파일 저장. docs/storage-and-failure-rules.md 「파일 경로」「적재 순서」를 구현한다.

경로: {RAW_ROOT}/raw/{source}/{원천 키}/{이름}__v{n}.{ext}  + 같은 이름 뒤에 .meta.json
- 원천 키: 문서 하나를 가리키는 읽을 수 있는 키(DART는 접수번호). 같은 문서의 역할별 파일과
  모든 판(v1, v2 …)이 이 폴더 하나에 모인다. 만드는 규칙은 encode_source_key
- 이름: 기본은 file_role(body_pdf 등). 목록 페이지처럼 한 폴더에 같은 역할 파일이 여럿이면 따로 지정
- 같은 폴더·이름의 최신 판과 바이트 SHA-256이 같으면 새 판을 만들지 않고 기존 판을 돌려준다
- 원본은 고치지 않는다. 내용이 바뀌었을 때만 판 번호를 1 올린 새 파일을 쓴다
- .meta.json을 먼저, 원본을 나중에 쓴다(적재 순서 4번)
- 반환하는 storage_path는 RAW_ROOT 기준 상대경로

이 경로 규칙은 10월 4일 확정(signal-pipeline PR #43, signal-infra PR #28 3.2).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

MAX_KEY_BYTES = 200


def _encode_field(value: str) -> str:
    """`/`·`~`·`%`·제어 문자만 퍼센트 인코딩. 한글 등 나머지는 그대로 둔다."""
    out = []
    for char in value:
        code = ord(char)
        if char in "/~%" or code < 0x20 or code == 0x7F:
            out.append("".join(f"%{b:02X}" for b in char.encode("utf-8")))
        else:
            out.append(char)
    return "".join(out)


def encode_source_key(fields: list[str]) -> str:
    """원천 키 필드들 → 폴더 이름. 필드가 여럿이면 `~`로 연결.

    인코딩 뒤 200바이트를 넘으면 앞부분을 남기고 `-h` + 전체 키 SHA-256 앞 12자를 붙인다.
    원래 필드 값은 .meta.json의 source_fields에 보존한다.
    """
    key = "~".join(_encode_field(f) for f in fields)
    raw = key.encode("utf-8")
    if len(raw) <= MAX_KEY_BYTES:
        return key
    suffix = "-h" + hashlib.sha256(raw).hexdigest()[:12]
    head = raw[: MAX_KEY_BYTES - len(suffix)].decode("utf-8", "ignore")
    return head + suffix


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

    def folder(self, source: str, source_key: str) -> Path:
        return self.root / "raw" / source / source_key

    def _versions(
        self, source: str, source_key: str, name: str, ext: str
    ) -> list[tuple[int, Path]]:
        pattern = re.compile(rf"^{re.escape(name)}__v(\d+)\.{re.escape(ext)}$")
        found = []
        for path in self.folder(source, source_key).glob(f"{name}__v*.{ext}"):
            match = pattern.match(path.name)
            if match:
                found.append((int(match.group(1)), path))
        return sorted(found)

    def latest(self, source: str, source_key: str, name: str, ext: str) -> Path | None:
        """같은 원천 키 폴더·이름의 최신 판 파일. 없으면 None. 이미 받은 원본을 건너뛸 때 쓴다."""
        versions = self._versions(source, source_key, name, ext)
        return versions[-1][1] if versions else None

    def save(
        self,
        source: str,
        source_key: str,
        file_role: str,
        ext: str,
        content: bytes,
        meta: dict[str, object],
        name: str | None = None,
    ) -> StoredObject:
        name = name or file_role
        digest = sha256_hex(content)
        versions = self._versions(source, source_key, name, ext)

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

        folder = self.folder(source, source_key)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{name}__v{version_seq}.{ext}"
        record = {
            "source": source,
            "source_key": source_key,
            "file_role": file_role,
            "version_seq": version_seq,
            "sha256": digest,
            "size": len(content),
            "collected_at": datetime.now(UTC).isoformat(timespec="seconds"),
            **meta,
        }
        meta_path = path.with_name(path.name + ".meta.json")
        write_atomic(
            meta_path, json.dumps(record, ensure_ascii=False, indent=1).encode()
        )
        write_atomic(path, content)
        return StoredObject(
            str(path.relative_to(self.root)),
            digest,
            version_seq,
            len(content),
            reused=False,
        )


def write_atomic(path: Path, data: bytes) -> None:
    """임시 파일에 다 쓴 뒤 이름을 바꾼다. 중간에 끊겨도 반쪽 파일이 남지 않는다."""
    temp = path.with_name(path.name + ".part")
    temp.write_bytes(data)
    os.replace(temp, path)
