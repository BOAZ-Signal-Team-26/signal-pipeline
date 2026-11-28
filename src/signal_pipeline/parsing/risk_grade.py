"""투자설명서 표지(DART cover_html)의 투자위험등급(1~6)을 읽어 문서 단위 CSV로 낸다(이슈 #93).

- 표기: 「2등급[높은 위험]」, 「1등급(매우 위험)」. 공백·&nbsp; 변형 허용. 1등급이 가장 위험
- 표지에 서로 다른 등급이 둘 이상이면 고르지 않고 MULTIPLE_GRADES(docs/data-model.md 「충돌 시 임의 선택 금지」)
- 외국 엄브렐러 펀드의 「하위펀드별 위험등급 참조」는 UMBRELLA_SUBFUND_GRADES(비교 집단 제외 규칙 대상)
- fund_group.representative_risk_grade 적재는 매칭 단계(fund_key)가 생긴 뒤. 지금은 문서 단위 파일만 냄(11월 24일 PM 결정)

사용: DATABASE_URL=... uv run python -m signal_pipeline.parsing.risk_grade ../signal-data
출력: {data_root}/exports/risk_grade/prospectus_cover__{YYYYMMDD}.csv (UTF-8 BOM, 새 파일만 씀)
"""

from __future__ import annotations

import argparse
import csv
import html
import io
import os
import re
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import psycopg

from signal_pipeline.common.storage import write_new

KST = timezone(timedelta(hours=9))
GRADE = re.compile(r"(?<!\d)([1-6])\s*등급\s*[\[(（]")
TAG = re.compile(r"<[^>]+>")
UMBRELLA = re.compile(r"하위\s*펀드\s*별\s*위험\s*등급")
COLUMNS = ("document_id", "접수번호", "위험등급", "결측사유", "근거원본")

DOCS_SQL = """
SELECT d.document_id, d.rcept_no, r.storage_path
FROM raw.document d
LEFT JOIN LATERAL (
  SELECT storage_path FROM raw.raw_object
  WHERE document_id = d.document_id AND file_role = 'cover_html' AND collect_status = 'success'
  ORDER BY version_seq DESC LIMIT 1
) r ON true
WHERE d.document_type = '투자설명서'
ORDER BY d.document_id
"""


def cover_grade(page: str) -> tuple[int | None, str | None]:
    """(등급, None) 또는 (None, 결측 사유)."""
    text = html.unescape(TAG.sub(" ", page))
    # 하위펀드별 등급 안내가 있으면 특정 하위펀드의 등급을 문서 등급으로 쓰지 않음
    if UMBRELLA.search(text):
        return None, "UMBRELLA_SUBFUND_GRADES"
    grades = set(GRADE.findall(text))
    if len(grades) == 1:
        return int(grades.pop()), None
    if grades:
        return None, "MULTIPLE_GRADES"
    return None, "NO_GRADE_TEXT"


def build_rows(conn, data_root: Path) -> list[tuple]:
    rows = []
    for document_id, rcept_no, path in conn.execute(DOCS_SQL).fetchall():
        if path is None:
            rows.append((document_id, rcept_no, "", "NO_COVER", ""))
            continue
        page = (data_root / path).read_text(encoding="utf-8", errors="replace")
        grade, reason = cover_grade(page)
        rows.append((document_id, rcept_no, grade or "", reason or "", path))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("data_root", type=Path)
    args = ap.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL 환경 변수가 필요하다", file=sys.stderr)
        return 2
    with psycopg.connect(url) as conn:
        rows = build_rows(conn, args.data_root)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(COLUMNS)
    writer.writerows(rows)
    today = datetime.now(UTC).astimezone(KST).date()
    rel = f"exports/risk_grade/prospectus_cover__{today:%Y%m%d}.csv"
    write_new(args.data_root / rel, buf.getvalue().encode("utf-8-sig"))
    graded = Counter(r[2] for r in rows if r[2] != "")
    missing = Counter(r[3] for r in rows if r[3])
    print(
        f"{rel}: 문서 {len(rows)}, 등급 있음 {sum(graded.values())} {dict(sorted(graded.items()))}"
    )
    print(f"결측 {sum(missing.values())} {dict(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
