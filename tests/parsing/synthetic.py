"""합성 DART 본문 텍스트 생성기(시험용)."""

PARTS = [
    "제1부 모집 또는 매출에 관한 사항",
    "제2부 발행인에 관한 사항",
    "제3부 투자위험요소",
]
SECS = {1: ["투자대상", "투자전략"], 2: ["회사의 개요"], 3: ["위험요인", "기타사항"]}


def toc_block(indent: str = "") -> list[str]:
    lines = []
    for n, title in enumerate(PARTS, 1):
        lines.append(indent + title)
        lines += [f"   {i}. {name}" for i, name in enumerate(SECS[n], 1)]
    return lines


def body_block() -> list[str]:
    lines = []
    for n, title in enumerate(PARTS, 1):
        lines.append("   " + title)
        for i, name in enumerate(SECS[n], 1):
            lines += [f"{i}. {name}", "본문 내용 " * 5]
    return lines


def make(*blocks: list[str]) -> str:
    return "\n".join(["표지", *[x for b in blocks for x in b]])
