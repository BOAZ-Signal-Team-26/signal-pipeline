"""근거 quote 대체 정렬. 정확·공백 무시 일치가 실패했을 때만 쓴다(11월 7일 PM 결정).

- anchors: quote의 8글자 조각이 절에 나오는 곳마다 quote 시작 위치를 추정해 표를 모은다(가장 긴 공통 구간 하나만 믿지 않음)
- fuzzy: 기준점 주변에서 quote와 가장 비슷한 구간(SequenceMatcher.ratio)
- chain: 원문에 끼어든 표 라벨·쪽 머리글을 건너뛰도록 4글자 이상 공통 구간을 이어 붙임. 덮은 비율·구간 길이로 거름
- token_window: 짧은 표 셀 인용. 토큰이 순서대로 200자 안에 나오면 일치. 숫자는 값으로 비교(1.00% = 1.0% = 1%)
fuzzy·chain은 공백을 뺀 텍스트 위치를, token_window는 원문 위치를 돌려준다.
"""

from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher

SHINGLE = 8  # 기준점 후보가 될 최소 공통 글자 수
TOP_ANCHORS = 3  # 표가 많은 기준점 몇 개까지 볼지
CHAIN_BLOCK = 4  # 연쇄 정렬에 쓰는 공통 구간 최소 글자 수
CHAIN_MIN = 0.9  # quote 글자 중 순서대로 맞은 비율 하한
SPAN_MAX = 1.5  # 원문 구간 길이 상한(quote 길이 배수)
TOKEN_WINDOW = 200
TOKEN_MAX = 4  # 토큰 근접 일치를 쓰는 quote 최대 토큰 수(공백 기준)

TOK = re.compile(r"\d+(?:\.\d+)?%?|[^\s\d]+")
NUM = re.compile(r"(\d+)(?:\.(\d+))?(%?)")


def anchors(q: str, norm: str) -> list[int]:
    """quote 시작 위치 후보. 표가 많은 순, ±10자 안의 후보는 하나로."""
    votes: Counter[int] = Counter()
    for k in range(len(q) - SHINGLE + 1):
        shingle = q[k : k + SHINGLE]
        i = norm.find(shingle)
        while i >= 0:
            votes[i - k] += 1
            i = norm.find(shingle, i + 1)
    picked: list[int] = []
    for g, _ in votes.most_common():
        if all(abs(g - p) > 10 for p in picked):
            picked.append(g)
            if len(picked) == TOP_ANCHORS:
                break
    return picked


def _scan(q: str, norm: str, starts, lengths, best):
    sm = SequenceMatcher(None, autojunk=False)
    for start in starts:
        for length in lengths:
            cand = norm[start : start + length]
            if not cand:
                continue
            sm.set_seqs(q, cand)
            # quick_ratio는 ratio의 상한이라 결과는 같고 계산만 줄어든다
            if sm.real_quick_ratio() <= best[0] or sm.quick_ratio() <= best[0]:
                continue
            r = sm.ratio()
            if r > best[0]:
                best = (r, start, start + len(cand))
    return best


def fuzzy(q: str, norm: str, g: int) -> tuple[float, int, int]:
    """기준점 g 주변 ±10자·길이 ±20%에서 가장 비슷한 구간. (유사도, 시작, 끝).

    길이는 quote 길이의 1/40 간격으로 훑은 뒤 가장 나은 구간 주변만 한 글자씩 다시 본다.
    """
    lo, hi = int(len(q) * 0.8), int(len(q) * 1.2)
    step = max(1, len(q) // 40)
    starts = range(max(0, g - 10), min(len(norm), g + 11))
    best = _scan(q, norm, starts, range(lo, hi + 1, step), (0.0, 0, 0))
    r, s, e = best
    if step > 1 and r:
        starts = range(max(0, s - step), min(len(norm), s + step + 1))
        lengths = range(max(lo, e - s - step), min(hi, e - s + step) + 1)
        best = _scan(q, norm, starts, lengths, best)
    return best


def chain(q: str, norm: str, g: int) -> tuple[float, int, int] | None:
    """기준점 g부터 quote 2배 길이 창에서 공통 구간을 이어 붙임. (덮은 비율, 시작, 끝), 기준 미달이면 None."""
    a = max(0, g - len(q) // 4)
    win = norm[a : a + 2 * len(q)]
    blocks = [
        b
        for b in SequenceMatcher(None, q, win, autojunk=False).get_matching_blocks()
        if b.size >= CHAIN_BLOCK
    ]
    if not blocks:
        return None
    cov = sum(b.size for b in blocks) / len(q)
    s, e = a + blocks[0].b, a + blocks[-1].b + blocks[-1].size
    return (cov, s, e) if cov >= CHAIN_MIN and e - s <= len(q) * SPAN_MAX else None


def _token_pattern(tok: str) -> re.Pattern:
    m = NUM.fullmatch(tok)
    if not m:
        return re.compile(re.escape(tok))
    whole, frac, pct = m.group(1), (m.group(2) or "").rstrip("0"), m.group(3)
    body = whole + (rf"\.{frac}0*" if frac else r"(?:\.0*)?")
    return re.compile(rf"(?<![\d.]){body}(?!\.?\d)" + (r"\s*%" if pct else ""))


def token_window(text: str, quote: str) -> tuple[tuple[int, int] | None, int]:
    """((첫 토큰 시작, 마지막 토큰 끝) 첫 일치, 일치 수). 원문 위치."""
    pats = [_token_pattern(t) for t in TOK.findall(quote)]
    if not pats:
        return None, 0
    hits = []
    for m0 in pats[0].finditer(text):
        end = m0.end()
        for p in pats[1:]:
            m = p.search(text, end, m0.start() + TOKEN_WINDOW)
            if not m:
                break
            end = m.end()
        else:
            hits.append((m0.start(), end))
    return (hits[0] if hits else None), len(hits)
