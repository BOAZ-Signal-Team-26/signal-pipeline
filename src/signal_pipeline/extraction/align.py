"""근거 quote 대체 정렬. 정확·공백 무시 일치가 실패했을 때만 쓴다(11월 7일 PM 결정).

- anchors: quote의 8글자 조각이 절에 나오는 곳마다 quote 시작 위치를 추정해 표를 모은다(가장 긴 공통 구간 하나만 믿지 않음)
- fuzzy: 기준점 주변에서 quote와 가장 비슷한 구간(SequenceMatcher.ratio)
- chain: 원문에 끼어든 표 라벨·쪽 머리글을 건너뛰도록 4글자 이상 공통 구간을 이어 붙임. 덮은 비율·구간 길이로 거름
- same_numbers: 근사·연쇄 일치는 quote와 원문 구간의 숫자 값 묶음이 같을 때만 받는다(1.00 = 1.0 = 1, 쉼표 무시)
fuzzy·chain은 공백을 뺀 텍스트 위치를 돌려준다.
토큰 근접 일치(짧은 표 셀을 200자 안에서 토큰별로 찾음)는 다른 클래스 행의 값을 이어 붙일 수 있어 뺐다(11월 7일).
"""

from __future__ import annotations

import re
from collections import Counter
from decimal import Decimal
from difflib import SequenceMatcher
from itertools import pairwise

SHINGLE = 8  # 기준점 후보가 될 최소 공통 글자 수
TOP_ANCHORS = 3  # 표가 많은 기준점 몇 개까지 볼지
CHAIN_BLOCK = 4  # 연쇄 정렬에 쓰는 공통 구간 최소 글자 수
CHAIN_MIN = 0.9  # quote 글자 중 순서대로 맞은 비율 하한
SPAN_MAX = 1.5  # 원문 구간 길이 상한(quote 길이 배수)

NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
NUM_CHARS = set("0123456789.,")


def same_numbers(a: str, b: str) -> bool:
    """두 텍스트의 숫자 값 묶음(중복 포함)이 같은지. 1.00 = 1.0 = 1, 쉼표는 지운다."""

    def values(t: str) -> Counter:
        return Counter(Decimal(m.replace(",", "")) for m in NUM.findall(t))

    return values(a) == values(b)


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


def chain(q: str, norm: str, g: int) -> tuple[float, int, int, str] | None:
    """기준점 g부터 quote 2배 길이 창에서 공통 구간을 이어 붙임. (덮은 비율, 시작, 끝, 숫자 비교용 원문), 기준 미달이면 None.

    숫자 비교용 원문은 원문에만 끼어든 구간(쪽 머리글 등)을 뺀 것. 단 끼어든 구간 양옆이 숫자면 숫자가 바뀐 것일 수 있어 남긴다.
    """
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
    if cov < CHAIN_MIN or e - s > len(q) * SPAN_MAX:
        return None
    kept = win[blocks[0].b : blocks[0].b + blocks[0].size]
    for p, b in pairwise(blocks):
        inserted = p.a + p.size == b.a
        if not (inserted and NUM_CHARS.isdisjoint(win[p.b + p.size - 1] + win[b.b])):
            kept += win[p.b + p.size : b.b]
        kept += win[b.b : b.b + b.size]
    return cov, s, e, kept


TOKEN_WINDOW = 200
TOKEN_MAX = 4  # 토큰 근접 일치를 쓰는 quote 최대 어절 수
TOK = re.compile(r"\d+(?:\.\d+)?%?|[^\s\d]+")
TOK_NUM = re.compile(r"(\d+)(?:\.(\d+))?(%?)")
# 클래스 표시: 「A클래스」의 「클래스」, 「(A)」「(C-e)」 같은 괄호 코드
CLASS_MARK = re.compile(r"클래스|\([A-Za-z][A-Za-z0-9-]{0,5}\)")


def _token_pattern(tok: str) -> re.Pattern:
    m = TOK_NUM.fullmatch(tok)
    if not m:
        return re.compile(re.escape(tok))
    whole, frac, pct = m.group(1), (m.group(2) or "").rstrip("0"), m.group(3)
    body = whole + (rf"\.{frac}0*" if frac else r"(?:\.0*)?")
    return re.compile(rf"(?<![\d.]){body}(?!\.?\d)" + (r"\s*%" if pct else ""))


def token_window(
    text: str, quote: str, other_classes: tuple[str, ...] = ()
) -> tuple[tuple[int, int] | None, int]:
    """((첫 토큰 시작, 마지막 토큰 끝) 첫 일치, 일치 수). 원문 위치.

    구간 안에 다른 클래스 이름이 있거나 클래스 표시가 quote보다 많으면 버린다
    (A클래스 인용이 C클래스 행 값을 잡지 않게).
    """
    pats = [_token_pattern(t) for t in TOK.findall(quote)]
    if not pats:
        return None, 0
    others = [re.sub(r"\s", "", c) for c in other_classes if c]
    hits = []
    for m0 in pats[0].finditer(text):
        end = m0.end()
        for p in pats[1:]:
            m = p.search(text, end, m0.start() + TOKEN_WINDOW)
            if not m:
                break
            end = m.end()
        else:
            span = re.sub(r"\s", "", text[m0.start() : end])
            marks = len(CLASS_MARK.findall(span)) > len(CLASS_MARK.findall(quote))
            if not marks and not any(o in span for o in others):
                hits.append((m0.start(), end))
    return (hits[0] if hits else None), len(hits)
