"""fund_key 묶음 규칙과 대표 위험등급 선택(순수 함수, DB 없음).

규칙(docs/matching-rules.md 「fund_key 묶음은 클래스 표기만 제거하고 호수·모자 구분은 제거하지 않음」,
docs/data-model.md 「상품과 법인」 risk_grade·fund_key)
- 묶음 키 = (운용사 corp_code, 정규화한 펀드명). 코드로 묶지 않고, 운용사가 다르면 이름이 같아도 따로 묶음
- 정규화: 접수 제목 껍데기·정정 접두 제거 → NFKC → 공백 제거 → 이름 끝의 클래스 표기 제거 → 「제N호」를 「N호」로 통일
- 지키는 것: 호수 숫자, 모/자 표기, 유형 괄호([주식], (채권혼합)), 환헤지 표기((H), (UH)). 모두 이름 안에 그대로 남음
- 등급: 문서 표지 등급이 모두 같을 때만 대표 등급. 서로 다르면 고르지 않음(CONFLICT).
  하위펀드별 등급 안내가 있는 외국 엄브렐러는 제외(FOREIGN_UMBRELLA)
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

RULE_VERSION = "fund-key-v1"

# 「[기재정정]투자설명서(집합투자증권)(펀드명)」. 접두 대괄호는 [기재정정], [첨부정정] 등 어떤 것이든 허용
TITLE = re.compile(r"^(?:\[[^\]]*\])?투자설명서\(집합투자증권\)\((.+)\)$")
# 이름 끝의 클래스 표기만 뗀다. 앞이 영숫자이면 뗀 것이 이름 일부(ETF형 등)일 수 있어 건드리지 않음
# ponytail: 이름 중간 표기와 대문자+소문자만의 약칭(Ce 등)은 안 뗌. 실측에 클래스 표기가 없어 필요해지면 추가
CLASS_TAIL = (
    re.compile(
        r"\(?(?:종류|[Cc]lass|클래스)-?[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*(?:\([^)]*\))?\)?$"
    ),
    re.compile(r"\(?(?<![A-Za-z0-9])[A-Z](?:-[A-Za-z0-9]{1,3})?형\)?$"),
)
HO = re.compile(r"제(\d+)호")

CONFLICT = "CONFLICT"
FOREIGN_UMBRELLA = "FOREIGN_UMBRELLA"
MISSING = "MISSING"
OK = "OK"


def fund_name(report_name: str) -> str | None:
    """접수 제목에서 펀드명을 뽑는다. 형식이 다르면 None."""
    m = TITLE.match(unicodedata.normalize("NFKC", report_name).strip())
    return m.group(1).strip() if m else None


def strip_class(name: str) -> str:
    """이름 끝의 클래스 표기를 뗀다(여러 겹이면 반복)."""
    prev = None
    while prev != name:
        prev = name
        for pattern in CLASS_TAIL:
            name = pattern.sub("", name.rstrip())
    return name.rstrip()


def group_key(name: str) -> str:
    """같은 펀드의 클래스는 같은 값이 되고, 호수·모자·유형이 다르면 다른 값이 되는 문자열."""
    text = unicodedata.normalize("NFKC", name)
    text = re.sub(r"\s+", "", text)
    return HO.sub(r"\1호", strip_class(text))


@dataclass(frozen=True)
class Doc:
    document_id: int
    rcept_no: str
    report_name: str
    corp_code: str
    corp_name: str
    received_date: date


@dataclass(frozen=True)
class CoverGrade:
    grade: int | None
    reason: str | None  # 등급이 없을 때 표지 파서의 결측 사유


@dataclass(frozen=True)
class Group:
    corp_code: str
    key: str
    canonical_name: str
    docs: tuple[Doc, ...]  # document_id 순


@dataclass(frozen=True)
class GradePick:
    status: str  # OK / CONFLICT / FOREIGN_UMBRELLA / MISSING
    grade: int | None
    source_document_id: int | None
    detail: dict


def build_groups(docs: list[Doc]) -> tuple[list[Group], list[Doc]]:
    """문서를 묶음으로 나눈다. 반환: (묶음 목록(첫 문서 순), 펀드명을 못 뽑은 문서)."""
    buckets: dict[tuple[str, str], list[Doc]] = {}
    unparsed: list[Doc] = []
    for doc in sorted(docs, key=lambda d: d.document_id):
        name = fund_name(doc.report_name)
        if name is None:
            unparsed.append(doc)
            continue
        buckets.setdefault((doc.corp_code, group_key(name)), []).append(doc)
    groups = []
    for (corp, key), members in buckets.items():
        first = fund_name(members[0].report_name) or ""
        groups.append(Group(corp, key, strip_class(first), tuple(members)))
    return groups, unparsed


def pick_grade(group: Group, grades: dict[int, CoverGrade]) -> GradePick:
    """묶음의 대표 등급. 문서 표지 등급이 하나로 모일 때만 값을 낸다."""
    covers = {d.document_id: grades[d.document_id] for d in group.docs}
    if any(c.reason == "UMBRELLA_SUBFUND_GRADES" for c in covers.values()):
        return GradePick(
            FOREIGN_UMBRELLA, None, None, {"reason_code": "UMBRELLA_SUBFUND_GRADES"}
        )
    graded = {i: c.grade for i, c in covers.items() if c.grade is not None}
    values = set(graded.values())
    multi = [i for i, c in covers.items() if c.reason == "MULTIPLE_GRADES"]
    if len(values) > 1 or multi:
        return GradePick(
            CONFLICT,
            None,
            None,
            {"grades_by_document": graded, "multiple_grades_documents": multi},
        )
    if not values:
        reasons = sorted({c.reason or "UNKNOWN" for c in covers.values()})
        return GradePick(MISSING, None, None, {"reasons": reasons})
    # 같은 등급이 여러 문서에 있으면 가장 늦게 접수된(같으면 document_id가 큰) 문서를 근거로 씀
    by_id = {d.document_id: d for d in group.docs}
    source = max(graded, key=lambda i: (by_id[i].received_date, i))
    return GradePick(OK, values.pop(), source, {"documents": sorted(graded)})
