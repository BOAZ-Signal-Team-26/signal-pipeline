#!/usr/bin/env python3
"""금감원 분쟁조정결정례 게시판 수집 (인증키 불필요).

용례:
    python3 scripts/fetch_fss_dispute.py --list                  # 최근 목록
    python3 scripts/fetch_fss_dispute.py --detail 219340         # 첨부 목록
    python3 scripts/fetch_fss_dispute.py --fetch 219340 --out /tmp/d
    python3 scripts/fetch_fss_dispute.py --fetch 219340 --out /tmp/d --text

09-20에 `nttId` 8건에서 역추적해 복구한 경로다. 근거는 gate-a/15 6절.

**`menuNo`는 페이지 껍데기만 정한다.** 내용을 정하는 것은 `bbsId`(B0000390)와 `nttId`다.
`menuNo`를 다른 메뉴 값으로 넣어도 같은 글과 같은 `atchFileId`가 나오고 제목만 딴
게시판으로 바뀐다. 역추적 과정에서 실제로 겪었다 — 「개선권고사항」 제목이 달린 채
분쟁조정 글이 내려왔다. **제목만 보고 게시판을 판정하면 안 된다.**

`bbsId=`는 빈 값으로 둔다. 다운로드 URL이 원래 그렇게 생겼다.
"""
from __future__ import annotations

import argparse
import html
import os
import re
import subprocess
import sys
import time
import urllib.parse

BASE = "https://www.fss.or.kr"
BBS_ID = "B0000390"
MENU_NO = "201193"

LIST_URL = "%s/fss/bbs/%s/list.do?menuNo=%s" % (BASE, BBS_ID, MENU_NO)
VIEW_URL = "%s/fss/bbs/%s/view.do?nttId=%%s&menuNo=%s" % (BASE, BBS_ID, MENU_NO)
DOWN_URL = ("%s/fss/cmmn/file/fileDown.do?menuNo=%s"
            "&atchFileId=%%s&fileSn=%%s&bbsId=" % (BASE, MENU_NO))

CALL_INTERVAL = 1.0     # 방어적 수집 원칙. 값의 근거는 gate-a/15 9절.


def get(url: str, referer: str | None = None, binary: bool = False,
        timeout: int = 60, attempts: int = 3) -> bytes:
    command = ["curl", "-sS", "--max-time", str(timeout), "-A", "Mozilla/5.0"]
    if referer:
        command += ["-e", referer]
    command.append(url)
    last = ""
    for attempt in range(attempts):
        result = subprocess.run(command, capture_output=True)
        if result.returncode == 0 and result.stdout:
            return result.stdout
        last = result.stderr.decode("utf-8", "replace").strip() or "빈 응답"
        if attempt < attempts - 1:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("조회 실패 %s: %s" % (url.split("?")[0], last))


def listing() -> list[tuple[str, str]]:
    """(nttId, 제목). 목록 페이지 한 장 분량이다."""
    page = get(LIST_URL).decode("utf-8", "replace")
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for match in re.finditer(r'nttId=(\d+)[^>]*>(?:\s*<[^>]+>)*([^<]{4,})', page):
        ntt, title = match.group(1), html.unescape(match.group(2)).strip()
        if ntt not in seen:
            seen.add(ntt)
            found.append((ntt, title))
    return found


def attachments(ntt_id: str) -> list[tuple[str, str, str]]:
    """(atchFileId, fileSn, 파일명). 한 글에 첨부가 여럿일 수 있다."""
    page = get(VIEW_URL % ntt_id).decode("utf-8", "replace")
    pairs = re.findall(
        r"fileDown\.do\?menuNo=\d+&(?:amp;)?atchFileId=([0-9a-f]+)&(?:amp;)?fileSn=(\d+)",
        page)
    names = [urllib.parse.unquote(html.unescape(n))
             for n in re.findall(r"fileName=([^\"&]+)", page)]
    out = []
    for index, (file_id, seq) in enumerate(dict.fromkeys(pairs)):
        out.append((file_id, seq, names[index] if index < len(names) else ""))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true", help="최근 목록")
    parser.add_argument("--detail", metavar="nttId", help="첨부 목록만 출력")
    parser.add_argument("--fetch", metavar="nttId", help="첨부를 내려받는다")
    parser.add_argument("--out", default=".", help="--fetch 저장 폴더")
    parser.add_argument("--text", action="store_true",
                        help="내려받은 뒤 hwp_text.py로 본문 앞부분을 출력")
    args = parser.parse_args()

    if args.list:
        for ntt, title in listing():
            print("%s\t%s" % (ntt, title))
        return

    ntt_id = args.detail or args.fetch
    if not ntt_id:
        parser.error("--list / --detail / --fetch 중 하나를 지정하세요")

    files = attachments(ntt_id)
    if not files:
        print("첨부 없음 (nttId=%s)" % ntt_id, file=sys.stderr)
        return
    for file_id, seq, name in files:
        print("%s  fileSn=%s  %s" % (file_id, seq, name))

    if not args.fetch:
        return

    os.makedirs(args.out, exist_ok=True)
    referer = VIEW_URL % ntt_id
    for file_id, seq, name in files:
        time.sleep(CALL_INTERVAL)
        blob = get(DOWN_URL % (file_id, seq), referer=referer, binary=True)
        path = os.path.join(args.out, name or "%s_%s.bin" % (ntt_id, seq))
        with open(path, "wb") as handle:
            handle.write(blob)
        # HWP 5.0은 OLE 복합문서다. 시그니처가 없으면 3.0이거나 다른 형식이다.
        kind = "HWP 5.0" if blob[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" else "HWP 5.0 아님"
        print("  저장 %s (%d바이트, %s)" % (path, len(blob), kind), file=sys.stderr)
        if args.text:
            here = os.path.dirname(os.path.abspath(__file__))
            result = subprocess.run(
                [sys.executable, os.path.join(here, "hwp_text.py"), path],
                capture_output=True)
            print(result.stdout.decode("utf-8", "replace")[:600])


if __name__ == "__main__":
    main()
