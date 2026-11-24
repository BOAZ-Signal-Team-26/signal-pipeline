"""등급 CSV 읽기 검증(DB 없음)."""

from datetime import date
from pathlib import Path

import pytest

from signal_pipeline.matching.fund_group import read_grades
from signal_pipeline.matching.fund_key import Doc

HEAD = "document_id,접수번호,위험등급,결측사유,근거원본\n"
DOCS = [
    Doc(1, "20260901000001", "t", "001", "가나", date(2026, 9, 1)),
    Doc(2, "20260901000002", "t", "001", "가나", date(2026, 9, 1)),
]


def _csv(tmp_path: Path, *lines: str) -> Path:
    p = tmp_path / "g.csv"
    p.write_text(HEAD + "".join(line + "\n" for line in lines), encoding="utf-8-sig")
    return p


OK1 = "1,20260901000001,3,,x"
OK2 = "2,20260901000002,,NO_COVER,"


def test_valid(tmp_path: Path) -> None:
    out = read_grades(_csv(tmp_path, OK1, OK2), DOCS)
    assert out[1].grade == 3 and out[2].reason == "NO_COVER"


@pytest.mark.parametrize(
    ("lines", "msg"),
    [
        ((OK1, OK1, OK2), "두 번"),
        ((OK1,), "빠진"),
        ((OK1, OK2, "3,20260901000003,2,,x"), "DB에 없는"),
        ((OK1, "2,20260901999999,,NO_COVER,"), "접수번호"),
        (("1,20260901000001,7,,x", OK2), "1~6"),
        (("1,20260901000001,0,,x", OK2), "1~6"),
        (("1,20260901000001,abc,,x", OK2), "1~6"),
    ],
)
def test_rejects(tmp_path: Path, lines: tuple[str, ...], msg: str) -> None:
    with pytest.raises(ValueError, match=msg):
        read_grades(_csv(tmp_path, *lines), DOCS)
