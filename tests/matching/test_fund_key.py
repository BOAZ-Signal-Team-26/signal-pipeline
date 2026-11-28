"""fund_key 묶음 규칙과 대표 등급 선택 테스트(DB 없음)."""

from datetime import date

from signal_pipeline.matching.fund_key import (
    CONFLICT,
    FOREIGN_UMBRELLA,
    MISSING,
    OK,
    CoverGrade,
    Doc,
    build_groups,
    fund_name,
    group_key,
    pick_grade,
)


def _doc(
    i: int, name: str, corp: str = "001", received: date = date(2026, 9, 1)
) -> Doc:
    title = f"[기재정정]투자설명서(집합투자증권)({name})"
    return Doc(i, f"2026090100{i:04d}", title, corp, "가나자산운용", received)


def _key(name: str) -> str:
    return group_key(name)


def test_class_suffix_removed() -> None:
    base = "가나코리아증권자투자신탁(주식)"
    for suffix in ("종류A", "(종류C-e)", " Class A", "(A형)", "C-e형"):
        assert _key(base + suffix) == _key(base)


def test_type_and_hedge_marks_kept() -> None:
    assert _key("가나증권투자신탁(H)[주식]") != _key("가나증권투자신탁(UH)[주식]")
    assert _key("가나증권투자신탁[주식]") != _key("가나증권투자신탁[채권]")
    assert _key("가나ETF형증권투자신탁") == _key("가나ETF형증권투자신탁")


def test_ho_number_kept() -> None:
    assert _key("가나증권투자신탁1호") != _key("가나증권투자신탁2호")
    assert _key("가나증권투자신탁제1호") == _key("가나증권투자신탁1호")
    assert _key("가나증권투자신탁(제1호)[채권]") != _key(
        "가나증권투자신탁(제11호)[채권]"
    )


def test_mother_child_kept() -> None:
    assert _key("가나코리아증권모투자신탁") != _key("가나코리아증권자투자신탁")


def test_title_parsing() -> None:
    assert fund_name("[기재정정]투자설명서(집합투자증권)(X(Y)Z)") == "X(Y)Z"
    assert fund_name("투자설명서(집합투자증권)(X)") == "X"
    assert fund_name("일괄신고서(X)") is None


def test_groups_split_by_manager_and_merge_corrections() -> None:
    docs = [
        _doc(1, "가나증권자투자신탁(주식)"),
        _doc(2, "가나 증권자투자신탁(주식)종류A"),  # 같은 펀드의 정정본
        _doc(3, "가나증권자투자신탁(주식)", corp="002"),  # 운용사 다름
        _doc(4, "가나증권모투자신탁(주식)"),  # 모펀드는 따로
    ]
    groups, unparsed = build_groups(docs)
    assert unparsed == []
    sizes = sorted(len(g.docs) for g in groups)
    assert sizes == [1, 1, 2]
    merged = next(g for g in groups if len(g.docs) == 2)
    assert [d.document_id for d in merged.docs] == [1, 2]


def test_unparsable_title_reported() -> None:
    bad = Doc(9, "20260901009999", "이상한제목", "001", "가나", date(2026, 9, 1))
    groups, unparsed = build_groups([bad])
    assert groups == [] and unparsed == [bad]


def test_pick_grade_agreement_uses_latest_document() -> None:
    docs = [
        _doc(1, "가나증권투자신탁"),
        _doc(2, "가나증권투자신탁", received=date(2026, 9, 5)),
    ]
    (group,), _ = build_groups(docs)
    pick = pick_grade(group, {1: CoverGrade(3, None), 2: CoverGrade(3, None)})
    assert (pick.status, pick.grade, pick.source_document_id) == (OK, 3, 2)


def test_pick_grade_conflict_picks_nothing() -> None:
    docs = [_doc(1, "가나증권투자신탁"), _doc(2, "가나증권투자신탁")]
    (group,), _ = build_groups(docs)
    pick = pick_grade(group, {1: CoverGrade(3, None), 2: CoverGrade(4, None)})
    assert (pick.status, pick.grade, pick.source_document_id) == (CONFLICT, None, None)
    multi = pick_grade(
        group, {1: CoverGrade(3, None), 2: CoverGrade(None, "MULTIPLE_GRADES")}
    )
    assert multi.status == CONFLICT


def test_pick_grade_umbrella_and_missing() -> None:
    (group,), _ = build_groups([_doc(1, "해외엄브렐러펀드")])
    assert (
        pick_grade(group, {1: CoverGrade(None, "UMBRELLA_SUBFUND_GRADES")}).status
        == FOREIGN_UMBRELLA
    )
    assert pick_grade(group, {1: CoverGrade(None, "NO_COVER")}).status == MISSING
