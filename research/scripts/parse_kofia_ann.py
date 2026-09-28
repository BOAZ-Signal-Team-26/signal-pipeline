#!/usr/bin/env python3
"""금투협 공시 응답 XML을 행으로 풀고 자연키 묶음 분포를 센다.

용례:
    python3 scripts/fetch_kofia_ann.py 20260813 20260815 | python3 scripts/parse_kofia_ann.py
"""
import collections
import csv
import re
import sys

# 응답의 행 요소는 <list>다. 그리드 출력 컬럼은 20개이며 아래가 의미 있는 것들이다.
FIELDS = [
    "standardDt", "uFundNm", "koreanNm", "standardCd", "companyCd",
    "tsCd", "txCd", "txVsn", "announceTtl", "seq", "tmpV1", "uRptGb", "Status_GB",
]

# 01의 source_doc_key 제안. tmpV1을 빼면 서로 다른 펀드가 한 묶음으로 뭉개진다(gate-a/12).
NATURAL_KEY = ("companyCd", "standardDt", "announceTtl", "tmpV1")


def parse(xml):
    rows = []
    for block in re.findall(r"<list>(.*?)</list>", xml, re.S):
        row = {}
        for field in FIELDS:
            match = re.search(r"<%s>(.*?)</%s>" % (field, field), block, re.S)
            row[field] = match.group(1).strip() if match else ""
        rows.append(row)
    return rows


def summarize(rows):
    groups = collections.defaultdict(list)
    for row in rows:
        groups[tuple(row[k] for k in NATURAL_KEY)].append(row)
    sizes = [len(v) for v in groups.values()]
    return groups, sizes


if __name__ == "__main__":
    rows = parse(sys.stdin.read())
    if not rows:
        sys.exit("행이 없습니다. uRptAllYN=1 과 uGb=1 을 확인하세요.")
    groups, sizes = summarize(rows)
    print(f"행 {len(rows)}  자연키 묶음 {len(groups)}  크기 max={max(sizes)} 평균={sum(sizes)/len(sizes):.2f}", file=sys.stderr)
    # 클래스 행은 uFundNm이 └▶로 시작한다.
    classes = sum(1 for r in rows if r["uFundNm"].startswith("└▶"))
    print(f"클래스 행 {classes} / 모·단독 행 {len(rows) - classes}", file=sys.stderr)
    writer = csv.DictWriter(sys.stdout, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(rows)
