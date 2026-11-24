"""근거 quote 대체 정렬. 정확·공백 무시 일치가 실패했을 때만 쓴다(11월 7일 PM 결정).

- anchors: quote의 8글자 조각이 절에 나오는 곳마다 quote 시작 위치를 추정해 표를 모은다(가장 긴 공통 구간 하나만 믿지 않음)
- fuzzy: 기준점 주변에서 quote와 가장 비슷한 구간(SequenceMatcher.ratio)
- chain: 원문에 끼어든 표 라벨·쪽 머리글을 건너뛰도록 4글자 이상 공통 구간을 이어 붙임. 덮은 비율·구간 길이로 거름
- same_numbers: 근사·연쇄 일치는 quote와 원문 구간의 숫자 값 묶음이 같을 때만 받는다(1.00 = 1.0 = 1, 쉼표 무시)
- token_window: fee_structure의 짧은 표 셀을 200자 안에서 어절별로 찾음. 다른 클래스 행이 끼면 버림. 원문 위치를 돌려준다
- fragments: fee_structure만. 위가 모두 실패했을 때 줄바꿈·다른 열 숫자로 갈라진 quote를 조각으로 찾음(이슈 #80). 원문 위치를 돌려준다
fuzzy·chain은 공백을 뺀 텍스트 위치를 돌려준다.
"""

from __future__ import annotations

import re
import unicodedata
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


NEG = re.compile(r"않|없|아니|못")


def same_negation(a: str, b: str) -> bool:
    """부정 표현(않·없·아니·못) 수가 같은지. 「발생할 수 있습니다」와 「없습니다」를 같은 근거로 받지 않음."""
    return Counter(NEG.findall(a)) == Counter(NEG.findall(b))


def class_ok(quote: str, span: str, other_classes: tuple[str, ...] = ()) -> bool:
    """구간에 인용에 없는 클래스 이름이 있거나 클래스 표시가 인용보다 많으면 False."""
    span = re.sub(r"\s", "", span)
    if len(CLASS_MARK.findall(span)) > len(CLASS_MARK.findall(quote)):
        return False
    return not any(re.sub(r"\s", "", c) in span for c in other_classes if c)


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


# 수수료·보수 항목 이름(「선취판매수수료」, 「운용보수」 등)
FEE_ITEM = re.compile(r"[^\s\d]*(?:수수료|보수)[^\s\d]*")


def _other_fee_item(quote: str, gap: str) -> bool:
    """인용 어절 사이에 인용에 없는 다른 수수료·보수 항목 이름이 끼었는지.

    「후취판매수수료 1% 선취판매수수료 없음」에서 「후취판매수수료 없음」 인용이
    두 항목의 셀을 이어 붙여 일치하지 않게 한다.
    PDF가 항목 이름 안에 공백을 넣는 경우(「운용 보수」)가 있어 공백을 지우고 글자만 남겨 비교한다.
    """
    q = re.sub(r"\s", "", quote)
    items = (
        re.sub(r"[^가-힣A-Za-z]", "", item)
        for item in FEE_ITEM.findall(re.sub(r"\s", "", gap))
    )
    return any(item and item not in q for item in items)


def token_window(
    text: str, quote: str, other_classes: tuple[str, ...] = ()
) -> tuple[tuple[int, int] | None, int]:
    """((첫 토큰 시작, 마지막 토큰 끝) 첫 일치, 일치 수). 원문 위치.

    구간 안에 다른 클래스 이름이 있거나 클래스 표시가 quote보다 많으면 버린다
    (A클래스 인용이 C클래스 행 값을 잡지 않게). 인용 어절 사이에 인용에 없는
    다른 수수료·보수 항목 이름이 끼어도 버린다(다른 항목 셀을 잇지 않게).
    """
    pats = [_token_pattern(t) for t in TOK.findall(quote)]
    if not pats:
        return None, 0
    hits = []
    for m0 in pats[0].finditer(text):
        end, gaps = m0.end(), []
        for p in pats[1:]:
            m = p.search(text, end, m0.start() + TOKEN_WINDOW)
            if not m:
                break
            gaps.append(text[end : m.start()])
            end = m.end()
        else:
            if class_ok(quote, text[m0.start() : end], other_classes) and not any(
                _other_fee_item(quote, g) for g in gaps
            ):
                hits.append((m0.start(), end))
    return (hits[0] if hits else None), len(hits)


# 조각 일치(이슈 #80): PDF 표에서 줄바꿈·다른 열 숫자가 끼어 quote가 여러 조각으로 갈라진 경우.
# quote의 모든 글자가 순서대로 원문에 있어야 하고(유사도 없음), 조각 사이 건너뛴 글자만 허용한다
FRAG_MIN = 3  # 조각 최소 글자 수(끝에 남은 숫자·「%」·「이내」는 예외)
FRAG_GAP = 160  # 조각 사이 건너뛸 수 있는 글자 수(공백 제외)
FRAG_SPAN = 500  # 원문 구간 최대 길이
FRAG_TAIL = ("%", "이내")
SENTINEL = (
    "\x00"  # 공백으로 떨어진 두 숫자 사이에 넣어 「1 0.5%」가 「10.5%」로 붙지 않게 함
)
DASHES = dict.fromkeys(map(ord, "‐‑‒–—−－―"), "-")
INVISIBLE = "\u200b\ufeff\u00a0"


def _nfkc(ch: str) -> str:
    return unicodedata.normalize("NFKC", ch).translate(DASHES)


def norm_map(text: str) -> tuple[str, list[int]]:
    """공백을 지우고 NFKC로 정규화한 텍스트와 글자마다의 원문 위치."""
    out: list[str] = []
    pos: list[int] = []
    gap_at = None
    for i, ch in enumerate(text):
        if ch.isspace() or ch in INVISIBLE:
            if gap_at is None and out:
                gap_at = i
            continue
        for c in _nfkc(ch):
            if gap_at is not None and out[-1] in NUM_CHARS | {"%"} and c in NUM_CHARS:
                out.append(SENTINEL)
                pos.append(gap_at)
            gap_at = None
            out.append(c)
            pos.append(i)
    return "".join(out), pos


def _norm_quote(q: str) -> str:
    return "".join(c for ch in q if not ch.isspace() for c in _nfkc(ch))


def _edge_ok(t: str, a: int, b: int, q: str, qi: int, qj: int) -> bool:
    """조각 t[a:b] == q[qi:qj]의 양 끝이 숫자 중간을 자르지 않는지."""
    if q[qi] in NUM_CHARS and qi > 0 and q[qi - 1] in NUM_CHARS:
        return False
    if q[qj - 1] in NUM_CHARS and qj < len(q) and q[qj] in NUM_CHARS:
        return False
    if q[qi].isdigit() and (qi == 0 or q[qi - 1] not in NUM_CHARS):
        p = t[a - 1] if a else ""
        if p.isdigit() or (p in ".," and a >= 2 and t[a - 2].isdigit()):
            return False
    if q[qj - 1].isdigit() and (qj == len(q) or q[qj] not in NUM_CHARS):
        n = t[b] if b < len(t) else ""
        if n.isdigit() or (n in ".," and b + 1 < len(t) and t[b + 1].isdigit()):
            return False
    return True


def _chain_frags(t: str, q: str, i: int, k0: int) -> list[tuple[int, int]] | None:
    """t[i:i+k0] == q[:k0]에서 시작해 남은 quote를 가장 긴 조각부터 앞으로 찾아 잇는다."""
    frags, qi, p = [(i, i + k0)], k0, i + k0
    while qi < len(q):
        rest = len(q) - qi
        win = t[p : p + FRAG_GAP + rest]
        hit = None
        for size in range(rest, 0, -1):
            if size < FRAG_MIN and not (
                size == rest and (q[qi:].isdigit() or q[qi:] in FRAG_TAIL)
            ):
                break
            sub = q[qi : qi + size]
            j = win.find(sub)
            while 0 <= j <= FRAG_GAP:
                if _edge_ok(t, p + j, p + j + size, q, qi, qi + size):
                    hit = (p + j, p + j + size)
                    break
                j = win.find(sub, j + 1)
            if hit:
                break
        if not hit:
            return None
        frags.append(hit)
        qi += hit[1] - hit[0]
        p = hit[1]
    return frags


# 조각 사이에 낀 클래스 표시: 「C클래스」, 「(C-e)」
GAP_CLASS = re.compile(r"[A-Za-z0-9-]*클래스|\([A-Za-z][A-Za-z0-9-]{0,5}\)")


def _frags_ok(
    t: str, frags: list, q: str, classes: tuple[str, ...], others: tuple[str, ...]
) -> bool:
    """다른 클래스 행·다른 수수료 항목 셀을 잇지 않았는지.

    - 구간에 인용에 없는 다른 클래스 이름이 통째로 있으면 거부
    - 조각 사이에 낀 클래스 표시가 모델이 답한 클래스 이름의 일부가 아니면 거부
    - 조각 사이에 인용에 없는 다른 수수료·보수 항목 이름이 끼면 거부
    """
    inside = t[frags[0][0] : frags[-1][1]]
    if any((c := _norm_quote(o)) and c not in q and c in inside for o in others):
        return False
    names = [_norm_quote(c) for c in classes if c]
    for (_, b), (a, _) in pairwise(frags):
        gap = t[b:a].replace(SENTINEL, "")
        if any(not any(m in n for n in names) for m in GAP_CLASS.findall(gap)):
            return False
        if _other_fee_item(q, gap):
            return False
    return True


def fragments(
    text: str,
    quote: str,
    classes: tuple[str, ...] = (),
    others: tuple[str, ...] = (),
) -> tuple[tuple[int, int] | None, int, int]:
    """((원문 시작, 끝), 후보 수, 건너뛴 글자 수). 건너뛴 글자가 가장 적은 후보, 같으면 앞의 것.

    classes = 모델이 답한 클래스 이름 전부, others = 그중 인용에 없는 것.
    """
    q = _norm_quote(quote)
    if len(q) < 4:
        return None, 0, 0
    t, pos = norm_map(text)
    head = q[:FRAG_MIN]
    best, seen = None, set()
    i = t.find(head)
    while i >= 0:
        k = FRAG_MIN
        while k < len(q) and t.startswith(q[: k + 1], i):
            k += 1
        while k > 0 and not _edge_ok(t, i, i + k, q, 0, k):
            k -= 1
        frags = _chain_frags(t, q, i, k) if k >= FRAG_MIN else None
        if frags and _frags_ok(t, frags, q, classes, others):
            s, e = pos[frags[0][0]], pos[frags[-1][1] - 1] + 1
            if e - s <= FRAG_SPAN and (s, e) not in seen:
                seen.add((s, e))
                gap = (frags[-1][1] - frags[0][0]) - len(q)
                if best is None or gap < best[2]:
                    best = (s, e, gap)
        i = t.find(head, i + 1)
    if best is None:
        return None, 0, 0
    s, e, gap = best
    return (s, e), len(seen), gap
