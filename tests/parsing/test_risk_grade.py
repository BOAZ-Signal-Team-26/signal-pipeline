from signal_pipeline.parsing.risk_grade import cover_grade


def wrap(body: str) -> str:
    return f"<html><body><table><tr><td>{body}</td></tr></table></body></html>"


def test_bracket_notation() -> None:
    assert cover_grade(wrap("투자위험등급 <b>2등급[ 높은 위험 ]</b>")) == (2, None)


def test_paren_notation_and_entities() -> None:
    assert cover_grade(wrap("투자&nbsp;위험&nbsp;등급 1등급(매우&nbsp;위험)")) == (
        1,
        None,
    )


def test_same_grade_twice_is_one_grade() -> None:
    assert cover_grade(wrap("3등급[다소 높은 위험] … 3등급[다소 높은 위험]")) == (
        3,
        None,
    )


def test_umbrella_subfund_grades() -> None:
    html = wrap("투자위험등급: 하위펀드별 위험등급 참조")
    assert cover_grade(html) == (None, "UMBRELLA_SUBFUND_GRADES")


def test_two_grades() -> None:
    html = wrap("A클래스 2등급[높은 위험] B클래스 3등급[다소 높은 위험]")
    assert cover_grade(html) == (None, "MULTIPLE_GRADES")


def test_no_grade_text() -> None:
    assert cover_grade(wrap("집합투자증권 투자설명서")) == (None, "NO_GRADE_TEXT")


def test_grade_number_out_of_range_is_ignored() -> None:
    assert cover_grade(wrap("7등급[없는 등급]")) == (None, "NO_GRADE_TEXT")


def test_two_digit_number_is_not_read_as_last_digit() -> None:
    assert cover_grade(wrap("12등급[범위 밖 등급]")) == (None, "NO_GRADE_TEXT")
    assert cover_grade(wrap("12등급[범위 밖] 2등급[높은 위험]")) == (2, None)


def test_umbrella_notice_wins_over_one_subfund_grade() -> None:
    html = wrap("하위펀드별 위험등급 참조. A하위펀드 2등급[높은 위험]")
    assert cover_grade(html) == (None, "UMBRELLA_SUBFUND_GRADES")
