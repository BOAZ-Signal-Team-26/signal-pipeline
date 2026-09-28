#!/usr/bin/env python3
"""DART 투자설명서 본문 PDF를 부·절 단위로 쪼갠다.

용례:
    python3 scripts/dart_sections.py 20260911000067            # 구조만 출력
    python3 scripts/dart_sections.py 20260911000067 --dump out/  # 절별 파일로 저장

근거와 실측은 gate-a/17. 인증키가 필요 없다 — DART 공개 뷰어를 쓴다.

**`pdftotext`(poppler)가 필요하다.** 유일한 외부 의존성이다.

수집 경로 (gate-a/15 4절)
    dsaf001/main.do?rcpNo=   → 문서 트리에서 「[ 본 문 ]」 노드
    report/viewer.do?...     → 그 노드는 PDF 링크 한 줄이다
    report/download.do?...   → 본문 PDF

**표제를 eleId 번호로 찾으면 안 된다** (01 결정). 원본은 표지가 eleId=1이고
[기재정정]은 정정신고 노드가 앞에 붙어 2다. 노드 텍스트로 찾는다.

**트리 JS는 `var node1 = {}`을 노드마다 재사용한다.** 변수명으로 정규식을 걸면
마지막 노드 하나만 잡힌다. 블록으로 끊어 읽어야 한다.
"""
from __future__ import annotations

import argparse
import html
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse

BASE = "https://dart.fss.or.kr"
# 「제N부」로 시작하고 그 줄에 표제만 있는 행. 들여쓰기는 조건에 넣지 않는다.
PART = re.compile(r"^제([1-5])부\.?\s+(\S.*)$")
TOC_SEC = re.compile(r"^\s*(\d{1,2})\.\s*(.+?)\s*$")
MAX_HEAD = 60


def get(url: str, referer: str | None = None, binary: bool = False):
    command = ["curl", "-sS", "--max-time", "120", "-A", "Mozilla/5.0"]
    if referer:
        command += ["-e", referer]
    result = subprocess.run(command + [url], capture_output=True)
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError("조회 실패 %s: %s"
                           % (url.split("?")[0],
                              result.stderr.decode("utf-8", "replace").strip()))
    return result.stdout if binary else result.stdout.decode("utf-8", "replace")


def tree(rcept_no: str) -> list[dict[str, str]]:
    page = get("%s/dsaf001/main.do?rcpNo=%s" % (BASE, rcept_no))
    nodes = []
    for block in re.split(r"var node\d+ = \{\};", page)[1:]:
        nodes.append(dict(re.findall(r"node\d+\['(\w+)'\]\s*=\s*\"([^\"]*)\"", block)))
    return [n for n in nodes if n.get("eleId")]


def body_pdf(rcept_no: str) -> bytes:
    nodes = tree(rcept_no)
    target = next((n for n in nodes if "본" in n.get("text", "") and "문" in n["text"]), None)
    if target is None:
        raise RuntimeError("「[ 본 문 ]」 노드가 없다: %s"
                           % [n.get("text") for n in nodes])
    viewer = ("%s/report/viewer.do?rcpNo=%s&dcmNo=%s&eleId=%s&offset=%s&length=%s&dtd=%s"
              % (BASE, rcept_no, target["dcmNo"], target["eleId"],
                 target["offset"], target["length"], target.get("dtd", "dart4.xsd")))
    element = get(viewer, referer="%s/dsaf001/main.do?rcpNo=%s" % (BASE, rcept_no))
    links = re.findall(r"download\.do\?[^\"'>\s]+", element)
    if not links:
        raise RuntimeError("본문 요소에 PDF 링크가 없다 (%d바이트)" % len(element))
    return get("%s/report/%s" % (BASE, html.unescape(links[0])),
               referer=viewer, binary=True)


def to_text(pdf: bytes) -> list[str]:
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "body.pdf")
        with open(path, "wb") as handle:
            handle.write(pdf)
        out = os.path.join(folder, "body.txt")
        result = subprocess.run(["pdftotext", "-layout", path, out], capture_output=True)
        if result.returncode != 0:
            raise RuntimeError("pdftotext 실패: %s"
                               % result.stderr.decode("utf-8", "replace")[:200])
        return io_read(out).split("\n")


def io_read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


def part_runs(lines: list[str]) -> list[list[tuple[int, int, str]]]:
    """「제N부」 표제 행을 찾아 오름차순 묶음으로 나눈다.

    **들여쓰기로 목차와 본문을 가를 수 없다 (gate-a/17 실측).** 문서마다
    제각각이다 — 목차가 0칸인 것도 4칸인 것도 있고, 본문 표제가 2칸인 것도
    25칸인 것도 있다. 대신 **순서는 일정하다**: 제1~5부가 오름차순으로 한 번
    나오면 목차, 다시 한 번 나오면 본문이다. 그래서 묶음으로 끊는다.
    """
    marks = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        match = PART.match(stripped)
        if match and len(stripped) < MAX_HEAD:
            marks.append((index, int(match.group(1)), stripped))
    runs: list[list[tuple[int, int, str]]] = []
    for mark in marks:
        if runs and mark[1] > runs[-1][-1][1]:
            runs[-1].append(mark)
        else:
            runs.append([mark])
    return runs


def toc(lines: list[str], run: list[tuple[int, int, str]],
        stop: int) -> dict[int, list[tuple[int, str]]]:
    """목차 묶음에서 부별 절 목록을 읽는다.

    **`*` 로 시작하는 줄에서 멈춘다.** 목차 끝의 「* 용어정리」 다음에
    「요약 정보(간이투자설명서)」가 이어지는데, 거기에도 `1. 투자목적` 같은
    번호 항목이 있어 계속 읽으면 절이 과잉 집계된다(gate-a/17 3절).
    """
    found: dict[int, list[tuple[int, str]]] = {}
    edges = [m[0] for m in run] + [stop]
    for index, (_, part, _) in enumerate(run):
        found[part] = []
        for line in lines[edges[index] + 1:edges[index + 1]]:
            if line.strip().startswith("*"):
                break
            section = TOC_SEC.match(line)
            if not section:
                continue
            number = int(section.group(1))
            # 절 번호는 부 안에서 단조 증가한다. 되돌아가면 목차가 끝난 것이다.
            # 마지막 부 뒤에 「투자자 유의사항」 같은 번호 목록이 이어지는 문서가
            # 있어, 이 검사가 없으면 제5부 절이 6개에서 24개로 부푼다(gate-a/17).
            if found[part] and number <= found[part][-1][0]:
                break
            found[part].append((number, section.group(2).strip()))
    return found


def normalize(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", text)


def split(lines: list[str]):
    """(부 번호, 표제, 시작행, 끝행, [(절 번호, 절 제목, 시작행)]) 목록."""
    runs = [r for r in part_runs(lines) if len(r) >= 3]
    if not runs:
        raise RuntimeError("「제N부」 표제를 찾지 못했다")
    if len(runs) == 1:
        # 목차가 없는 문서. 그 묶음을 본문으로 본다.
        contents, body = {}, runs[0]
    else:
        contents = toc(lines, runs[0], runs[1][0][0])
        body = runs[1]
    heads = [(i, part, text) for i, part, text in body]
    bounds = [h[0] for h in heads] + [len(lines)]
    out = []
    for index, (start, part, title) in enumerate(heads):
        end = bounds[index + 1]
        body = [(i, normalize(lines[i])) for i in range(start + 1, end)]
        sections = []
        for number, name in contents.get(part, []):
            key = normalize(name)
            head = normalize("%d." % number) + key[:12]
            spot = next((i for i, text in body if text.startswith(head)), None)
            if spot is None:
                spot = next((i for i, text in body
                             if key[:14] and key[:14] in text
                             and len(text) < len(key) + 30), None)
            sections.append((number, name, spot))
        out.append((part, title, start, end, sections))
    return out, contents


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("rcept_no", help="DART 접수번호 14자리")
    parser.add_argument("--dump", metavar="DIR", help="절별 텍스트를 파일로 저장")
    args = parser.parse_args()

    lines = to_text(body_pdf(args.rcept_no))
    parts, contents = split(lines)
    expected = sum(len(v) for v in contents.values())
    hit = sum(1 for _, _, _, _, s in parts for _, _, spot in s if spot is not None)

    print("본문 %d행, 부 %d개, 목차 절 %d개" % (len(lines), len(parts), expected))
    for part, title, start, end, sections in parts:
        found = [s for s in sections if s[2] is not None]
        print("\n  %s  (%d행)  절 %d/%d"
              % (title[:40], end - start, len(found), len(sections)))
        for number, name, spot in sections:
            print("     %2d. %-34s %s" % (number, name[:34],
                                          spot if spot is not None else "못 찾음"))
    print("\n절 적중 %d/%d" % (hit, expected))

    if args.dump:
        os.makedirs(args.dump, exist_ok=True)
        count = 0
        for part, _, start, end, sections in parts:
            spots = [(n, t, s) for n, t, s in sections if s is not None]
            for index, (number, name, spot) in enumerate(spots):
                stop = spots[index + 1][2] if index + 1 < len(spots) else end
                safe = re.sub(r"[^0-9A-Za-z가-힣]", "_", name)[:40]
                path = os.path.join(args.dump, "p%d_%02d_%s.txt" % (part, number, safe))
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("\n".join(lines[spot:stop]))
                count += 1
        print("절 %d개를 %s 에 저장" % (count, args.dump))


if __name__ == "__main__":
    main()
