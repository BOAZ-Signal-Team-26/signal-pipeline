"""축 4 「없음 비율」의 위험등급 통제 잔차(초안). 펀드 묶음(fund_key) 단위 OLS.

기준: docs/scoring-and-population.md 「저장 단위와 계산 단위」(관측 단위 = 고유 fund_key),
「위험 요약」(운용사 공통 교란 → 운용사 고정효과).

- 관측치: 펀드 묶음마다 대표 투자설명서 1건(가장 늦게 접수, 같으면 document_id가 큰 문서)
- 종속변수(초안 정의): 없음 ÷ (있음 + 없음). 판정 불가·적용 대상 아님은 분모에서 뺌.
  파트 A 요약 수치는 미결이라 이 값은 화면에 쓰지 않는 분석용 값
- 모형 A: 절편 + 위험등급 더미(기준 = 가장 낮은 등급) + ETF 여부
- 모형 B: 모형 A + 운용사 더미(고정효과). 펀드 묶음이 1개인 운용사는 잔차가 0이 됨
- 잔차 상위 목록의 기본은 모형 B, 모형 A는 운용사 간 양식 차이를 보려고 함께 냄(11월 28일 PM 결정).
  근거: 설계 문서의 운용사 고정효과 결정. 모형 A 잔차는 문서 양식이 나쁜 운용사에 몰림
- 제외: 대표 문서 동률(최신 접수일에 문서가 여럿), 대표 등급 없음(묶음 규칙의 MISSING·CONFLICT·
  FOREIGN_UMBRELLA), 판정값 없음, 있음+없음 0
- 한계: 기준일 인자가 없음(모든 문서가 실행일 전에 접수됐다고 봄). ETF는 보고서명 「상장지수」로만 판정
  (로컬 DB에 KRX 확인 매칭 표가 비어 있음. 축 4의 4.2 판정과 같은 상황)

묶음은 signal_pipeline.matching.fund_key 규칙으로 메모리에서 다시 계산한다(DB에 쓰지 않음).

사용: DATABASE_URL=postgresql://... uv run python -m signal_pipeline.scoring.residual ../signal-data \\
        --judgments-csv ../signal-data/exports/runs/<score run>/axis4_judgments.csv \\
        --grades-csv ../signal-data/exports/risk_grade/prospectus_cover__20261124.csv
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg

from signal_pipeline.common.storage import write_new
from signal_pipeline.matching.fund_group import load_docs, read_grades
from signal_pipeline.matching.fund_key import (
    OK,
    CoverGrade,
    Doc,
    Group,
    build_groups,
    pick_grade,
)
from signal_pipeline.scoring.axis4_rules import ITEMS

KST = timezone(timedelta(hours=9))
VERSION = "axis4-residual-draft-1"
PIVOT_TOL = 1e-9
ITEM_COUNT = len(ITEMS)
MET, UNMET = "있음", "없음"
STATUSES = (MET, UNMET, "판정 불가", "적용 대상 아님")


@dataclass(frozen=True)
class FundRow:
    corp_code: str
    corp_name: str
    group_key: str
    rcept_no: str
    grade: int | None
    is_etf: bool
    counts: dict[str, int]
    excluded: str | None = None  # 제외 사유. None이면 회귀에 들어감

    @property
    def none_ratio(self) -> float | None:
        judged = self.counts.get(MET, 0) + self.counts.get(UNMET, 0)
        return self.counts.get(UNMET, 0) / judged if judged else None


@dataclass(frozen=True)
class Fit:
    names: tuple[str, ...]
    coef: dict[str, float | None]  # None = 다른 열과 선형종속이라 뺀 열
    fitted: tuple[float, ...]
    residual: tuple[float, ...]
    r2: float


def _solve(xtx: list[list[float]], xty: list[float]) -> tuple[list[float], list[int]]:
    """가우스-조르단 소거. 피벗이 0에 가까운 열은 건너뛰고 계수 0으로 둔다. 반환: (계수, 쓴 열)."""
    k = len(xty)
    a = [row[:] + [b] for row, b in zip(xtx, xty)]
    used: list[int] = []
    for col in range(k):
        row = len(used)
        piv = max(range(row, k), key=lambda r: abs(a[r][col]), default=None)
        if piv is None or abs(a[piv][col]) < PIVOT_TOL:
            continue
        a[row], a[piv] = a[piv], a[row]
        a[row] = [v / a[row][col] for v in a[row]]
        for r in range(k):
            if r != row and a[r][col]:
                f = a[r][col]
                a[r] = [v - f * w for v, w in zip(a[r], a[row])]
        used.append(col)
    beta = [0.0] * k
    for r, col in enumerate(used):
        beta[col] = a[r][k]
    return beta, used


def ols(names: list[str], x: list[list[float]], y: list[float]) -> Fit:
    """정규방정식 OLS. 선형종속 열의 계수는 None.

    ponytail: 더미 변수 수십 개·관측 수백 개 규모용 순수 파이썬. 연속 변수가 많아지면 QR(numpy)로 바꿈
    """
    k = len(names)
    xtx = [[sum(r[i] * r[j] for r in x) for j in range(k)] for i in range(k)]
    xty = [sum(r[i] * v for r, v in zip(x, y)) for i in range(k)]
    beta, used = _solve(xtx, xty)
    fitted = [sum(b * v for b, v in zip(beta, r)) for r in x]
    resid = [v - f for v, f in zip(y, fitted)]
    mean = sum(y) / len(y)
    sst = sum((v - mean) ** 2 for v in y)
    r2 = 1 - sum(e * e for e in resid) / sst if sst else 0.0
    coef = {n: (beta[i] if i in used else None) for i, n in enumerate(names)}
    return Fit(tuple(names), coef, tuple(fitted), tuple(resid), r2)


def representative(group: Group) -> tuple[Doc, bool]:
    """가장 늦게 접수된 문서와, 그 접수일에 문서가 여럿인지(동률).

    동률이면 ID 순서로 고르지 않고 제외한다(docs/scoring-and-population.md 「기준일과 대표본 선택」 4번,
    AMBIGUOUS_DOCUMENT). 반환 문서는 출력 CSV에서 묶음을 찾아가는 용도로만 씀
    """
    latest = max(d.received_date for d in group.docs)
    tied = [d for d in group.docs if d.received_date == latest]
    return max(tied, key=lambda d: d.document_id), len(tied) > 1


def read_judgments(path: Path) -> dict[str, Counter[str]]:
    """축 4 판정 CSV → 접수번호별 판정값 개수. 모르는 판정값은 중단."""
    out: dict[str, Counter[str]] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if r["판정값"] not in STATUSES:
                raise ValueError(f"모르는 판정값: {r['접수번호']} {r['판정값']!r}")
            out.setdefault(r["접수번호"], Counter())[r["판정값"]] += 1
    return out


def check_coverage(docs: list[Doc], judgments: dict[str, Counter[str]]) -> None:
    """판정 CSV가 DB 투자설명서와 같은 문서 집합이고 문서마다 판정이 10항목인지. 아니면 중단."""
    have = {d.rcept_no for d in docs}
    if extra := sorted(set(judgments) - have):
        raise ValueError(f"판정 CSV에 DB에 없는 접수번호: {extra[:5]}")
    if lost := sorted(have - set(judgments)):
        raise ValueError(f"판정 CSV에 빠진 접수번호: {lost[:5]}")
    if short := sorted(
        r for r, c in judgments.items() if sum(c.values()) != ITEM_COUNT
    ):
        raise ValueError(f"판정 항목 수가 {ITEM_COUNT}이 아닌 접수번호: {short[:5]}")


def _exclusion(status: str, row: FundRow, tied: bool) -> str | None:
    if tied:
        return "대표 문서 동률(AMBIGUOUS_DOCUMENT)"
    if status != OK:
        return f"등급 없음({status})"
    if not row.counts:
        return "판정값 없음"
    if row.none_ratio is None:
        return "있음+없음 0"
    return None


def build_rows(
    groups: list[Group],
    grades: dict[int, CoverGrade],
    judgments: dict[str, Counter[str]],
) -> list[FundRow]:
    rows = []
    for g in groups:
        rep, tied = representative(g)
        pick = pick_grade(g, grades)
        row = FundRow(
            corp_code=g.corp_code,
            corp_name=rep.corp_name,
            group_key=g.key,
            rcept_no=rep.rcept_no,
            grade=pick.grade,
            is_etf="상장지수" in rep.report_name,
            counts=dict(judgments.get(rep.rcept_no, {})),
        )
        rows.append(replace(row, excluded=_exclusion(pick.status, row, tied)))
    return rows


def design(
    rows: list[FundRow], manager_fe: bool
) -> tuple[list[str], list[list[float]]]:
    grades = sorted({r.grade for r in rows})
    managers = sorted({r.corp_code for r in rows})
    names = ["절편"] + [f"등급{g}" for g in grades[1:]] + ["ETF"]
    if manager_fe:
        names += [f"운용사:{m}" for m in managers[1:]]
    x = []
    for r in rows:
        v = [1.0] + [float(r.grade == g) for g in grades[1:]] + [float(r.is_etf)]
        if manager_fe:
            v += [float(r.corp_code == m) for m in managers[1:]]
        x.append(v)
    return names, x


def fit_both(rows: list[FundRow]) -> tuple[list[FundRow], Fit, Fit]:
    used = [r for r in rows if r.excluded is None]
    if not used:
        raise ValueError("회귀에 들어갈 펀드 묶음이 없음")
    y = [r.none_ratio for r in used]
    return used, ols(*design(used, False), y), ols(*design(used, True), y)


CSV_COLUMNS = (
    "운용사코드", "운용사", "묶음키", "대표접수번호", "위험등급", "ETF", "운용사_묶음수",
    "있음", "없음", "판정불가", "적용대상아님", "없음비율",
    "적합값_A", "잔차_A", "적합값_B", "잔차_B", "제외사유",
)  # fmt: skip


def _fmt(v: float | None) -> str:
    return "" if v is None else f"{v:.6f}"


def to_csv(rows: list[FundRow], used: list[FundRow], a: Fit, b: Fit) -> bytes:
    idx = {r.rcept_no: i for i, r in enumerate(used)}
    per_mgr = Counter(r.corp_code for r in used)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_COLUMNS)
    for r in rows:
        i = idx.get(r.rcept_no) if r.excluded is None else None
        fit = ["", "", "", ""] if i is None else [
            _fmt(a.fitted[i]), _fmt(a.residual[i]), _fmt(b.fitted[i]), _fmt(b.residual[i])
        ]  # fmt: skip
        w.writerow(
            [r.corp_code, r.corp_name, r.group_key, r.rcept_no, r.grade or "",
             int(r.is_etf), per_mgr.get(r.corp_code, 0)]
            + [r.counts.get(s, 0) for s in STATUSES]
            + [_fmt(r.none_ratio)] + fit + [r.excluded or ""]
        )  # fmt: skip
    return ("﻿" + buf.getvalue()).encode("utf-8")


def _main_coef(fit: Fit) -> dict[str, float | None]:
    return {
        n: (None if c is None else round(c, 6))
        for n, c in fit.coef.items()
        if not n.startswith("운용사:")
    }


def summarize(rows: list[FundRow], used: list[FundRow], a: Fit, b: Fit) -> dict:
    per_mgr = Counter(r.corp_code for r in used)
    return {
        "version": VERSION,
        "groups": len(rows),
        "used": len(used),
        "excluded": dict(Counter(r.excluded for r in rows if r.excluded)),
        "grade_counts": dict(sorted(Counter(r.grade for r in used).items())),
        # 등급 계수는 이 등급과의 차이. 포함된 묶음에 1등급이 없으면 1이 아닌 값이 됨
        "base_grade": min(r.grade for r in used),
        "coef_note": "등급N 계수는 다른 설명변수가 같을 때 base_grade 등급 대비 없음 비율의 차이. "
        "ETF 계수는 ETF가 아닌 펀드 대비 차이. 모형 B는 운용사 고정효과를 통제한 값",
        "etf_used": sum(r.is_etf for r in used),
        "none_ratio_zero": sum(r.none_ratio == 0 for r in used),
        "model_a": {"r2": round(a.r2, 4), "coef": _main_coef(a)},
        "model_b": {
            "r2": round(b.r2, 4),
            "coef": _main_coef(b),
            "managers": len(per_mgr),
            "single_group_managers": sum(1 for n in per_mgr.values() if n == 1),
            "dropped_collinear": [n for n, c in b.coef.items() if c is None],
        },
    }


def save(stem: Path, csv_bytes: bytes, json_bytes: bytes) -> None:
    """CSV·JSON을 새 파일로 쓴다. JSON 쓰기가 실패하면 이번 실행에서 만든 파일만 지워 다시 실행할 수 있게 함.

    JSON이 실행 전부터 있으면(FileExistsError) 그 파일은 건드리지 않고 CSV만 지움.
    JSON을 만든 뒤 쓰다가 실패하면 반쯤 쓴 JSON도 지움.
    """
    csv_path, json_path = stem.with_suffix(".csv"), stem.with_suffix(".json")
    write_new(csv_path, csv_bytes)
    try:
        write_new(json_path, json_bytes)
    except FileExistsError:
        csv_path.unlink()
        raise
    except BaseException:
        csv_path.unlink()
        json_path.unlink(missing_ok=True)
        raise


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("data_root", type=Path, help="signal-data 루트")
    ap.add_argument("--judgments-csv", type=Path, required=True)
    ap.add_argument("--grades-csv", type=Path, required=True)
    args = ap.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL 환경 변수가 필요하다", file=sys.stderr)
        return 2
    try:
        with psycopg.connect(url) as conn:
            docs = load_docs(conn)
        groups, unparsed = build_groups(docs)
        grades = read_grades(args.grades_csv, docs)
        judgments = read_judgments(args.judgments_csv)
        check_coverage(docs, judgments)
        rows = build_rows(groups, grades, judgments)
        used, a, b = fit_both(rows)
    except ValueError as error:
        print(f"입력 오류: {error}", file=sys.stderr)
        return 2
    summary = summarize(rows, used, a, b) | {
        "unparsed_documents": len(unparsed),
        "inputs": {
            name: {"path": str(p), "sha256": _sha(p)}
            for name, p in (("judgments_csv", args.judgments_csv), ("grades_csv", args.grades_csv))
        },
    }  # fmt: skip
    day = f"{datetime.now(KST):%Y%m%d}"
    stem = args.data_root / "exports" / "residual" / f"axis4_residual__{day}"
    text = json.dumps(summary, ensure_ascii=False, indent=1)
    save(stem, to_csv(rows, used, a, b), text.encode("utf-8"))
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
