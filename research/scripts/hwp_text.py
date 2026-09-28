#!/usr/bin/env python3
"""HWP 5.0 문서에서 본문 텍스트를 뽑는다. 외부 의존성 없음.

용례:
    python3 scripts/hwp_text.py 결정문.hwp
    python3 scripts/hwp_text.py --preview 결정문.hwp   # PrvText 만

분쟁조정결정례(J14) 확인에 쓴 도구다. 근거는 gate-a/14 5절.

한계
- **HWP 3.0은 읽지 못한다.** 자체 바이너리라 OLE가 아니다. 팀 실측에서
  분쟁조정 첨부 213단위 중 94건이 여기 해당한다(1999~2004년 문서).
- 「상위 버전 배포용 문서」는 BodyText 가 안내문뿐이다. 이때는 `--preview`로
  PrvText(약 1,000자)를 건지는 것이 최선이다.
"""
from __future__ import annotations

import argparse
import io
import struct
import sys
import zlib

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from _ole import Ole  # noqa: E402

PARA_TEXT = 67          # HWPTAG_PARA_TEXT


def preview(data: bytes) -> str:
    """PrvText 스트림. UTF-16LE 평문이라 압축 해제가 필요 없다."""
    raw = Ole(data).read("PrvText")
    return raw.decode("utf-16-le", "replace") if raw else ""


def body(data: bytes) -> str:
    """BodyText/SectionN 을 풀어 문단 텍스트만 잇는다."""
    ole = Ole(data)
    chunks: list[str] = []
    for name, _type, _size in ole.names():
        if not name.startswith("Section"):
            continue
        stream = ole.read(name)
        if not stream:
            continue
        try:
            # HWP 5.0 본문은 헤더 없는 deflate 다.
            decoded = zlib.decompress(stream, -15)
        except zlib.error:
            continue
        position = 0
        while position + 4 <= len(decoded):
            header = struct.unpack_from("<I", decoded, position)[0]
            position += 4
            tag = header & 0x3FF
            size = (header >> 20) & 0xFFF
            if size == 0xFFF:                 # 확장 길이
                size = struct.unpack_from("<I", decoded, position)[0]
                position += 4
            payload = decoded[position:position + size]
            position += size
            if tag != PARA_TEXT:
                continue
            text = payload.decode("utf-16-le", "replace")
            # 제어 문자(레코드 구분자)를 걷어낸다
            text = "".join(c for c in text if c == "\n" or ord(c) >= 32)
            if text.strip():
                chunks.append(text)
    return "\n".join(chunks)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--preview", action="store_true", help="PrvText 만 출력")
    args = parser.parse_args()

    data = io.open(args.path, "rb").read()
    if data[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        sys.exit("HWP 5.0(OLE)이 아니다. HWP 3.0이면 이 도구로는 읽을 수 없다.")
    text = preview(data) if args.preview else body(data)
    if not text.strip():
        sys.exit("텍스트가 없다. 배포용 문서일 수 있으니 --preview 를 써 보라.")
    sys.stdout.write(text)


if __name__ == "__main__":
    main()
