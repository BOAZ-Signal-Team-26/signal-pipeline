from pdfplumber.utils import chars_to_textmap

from signal_pipeline.parsing.pdf_layout import (
    is_invisible,
    is_white,
    layout_textmap,
    table_char_ranges,
    trim_page,
)


def char(x0: float, top: float, text: str = "가") -> dict:
    return {"text": text, "x0": x0, "x1": x0 + 10, "top": top, "bottom": top + 10}


def test_is_white_by_color_space() -> None:
    assert is_white(1) and is_white((1,)) and is_white((1.0, 1.0, 1.0))
    assert is_white((0, 0, 0, 0))  # CMYK
    assert not is_white((0.867, 0.867, 0.863)) and not is_white((0, 0, 0, 1))
    assert not is_white(None) and not is_white(()) and not is_white("Pattern")
    assert not is_white((1, "P1"))  # 패턴 색은 보이는 것


def test_invisible_rect_and_line() -> None:
    white = {"object_type": "rect", "fill": True, "stroke": False}
    assert is_invisible({**white, "non_stroking_color": (1, 1, 1)})
    assert not is_invisible({**white, "non_stroking_color": (0.5,)})
    assert not is_invisible({**white, "non_stroking_color": 1, "stroke": True})
    assert not is_invisible({**white, "non_stroking_color": 1, "fill": False})
    line = {"object_type": "line", "stroking_color": (1,)}
    assert is_invisible(line) and not is_invisible({**line, "stroking_color": (0,)})
    assert not is_invisible({"object_type": "char"})


def test_trim_page_keeps_origin_per_char_and_strips_padding() -> None:
    a, b = char(0, 0, "A"), char(10, 0, "B")
    tuples = [(" ", None)] * 3 + [("\n", None)] + [
        ("A", a), (" ", None), ("B", b), (" ", None), (" ", None), ("\n", None),
        (" ", None), ("\n", None),
    ]  # fmt: skip
    text, origins = trim_page(tuples)
    assert text == "A B\n" and origins == [a, None, b, None]


def test_trim_page_replaces_nul_and_empty_page_is_empty() -> None:
    text, _ = trim_page([("a", char(0, 0)), ("\x00", None), ("b", char(0, 0))])
    assert text == "a b\n"
    assert trim_page([(" ", None), ("\n", None)]) == ("", [])


def test_trim_page_replaces_form_feed_and_cr() -> None:
    text, origins = trim_page(
        [("a", char(0, 0)), ("\x0c", None), ("\r", None), ("b", char(0, 0))]
    )
    assert text == "a  b\n" and len(origins) == 5


def test_table_char_ranges_uses_char_centers() -> None:
    origins = [char(0, 0), char(10, 0), None, char(100, 0), char(110, 50)]
    # 표 bbox는 앞 두 글자와 사이 공백만 덮음
    assert table_char_ranges(origins, [(0, 0, 30, 20)]) == [(0, 2)]
    # 글자 없는 표는 뺌, 여러 표는 시작 순
    got = table_char_ranges(
        origins, [(100, 40, 130, 60), (0, 0, 30, 20), (500, 500, 600, 600)]
    )
    assert got == [(0, 2), (4, 5)]


class FakePage:
    width, height, bbox = 200.0, 100.0, (0, 0, 200.0, 100.0)

    def __init__(self, chars: list[dict]) -> None:
        self.chars = chars


def fake_char(text: str, x0: float, top: float) -> dict:
    return {
        "text": text, "x0": x0, "x1": x0 + 6, "top": top, "bottom": top + 10,
        "upright": True, "size": 10.0, "doctop": top, "fontname": "f", "matrix": (1, 0, 0, 1, x0, 0),
    }  # fmt: skip


def test_layout_textmap_orders_lines_top_down_across_upright_groups() -> None:
    # 내용 순서가 본문(upright) → 회전 글자 → 머리글(upright)이면 pdfplumber 기본 layout은
    # 머리글을 글자 묶음 순서대로 쪽 끝에 둔다. 위에서 아래로 다시 정렬해야 한다
    body = [fake_char(c, 10 + 6 * i, 40) for i, c in enumerate("본문")]
    turned = [{**fake_char("회", 150, 20), "upright": False}]
    head = [fake_char(c, 10 + 6 * i, 5) for i, c in enumerate("제3부")]
    chars = body + turned + head
    text, _ = trim_page(layout_textmap(FakePage(chars)).tuples)
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    assert lines.index("제3부") < lines.index("본문")
    default = chars_to_textmap(
        chars,
        layout=True,
        layout_width=200,
        layout_height=100,
        layout_bbox=FakePage.bbox,
    )
    default_lines = [
        x.strip() for x in trim_page(default.tuples)[0].split("\n") if x.strip()
    ]
    assert default_lines.index("제3부") > default_lines.index(
        "본문"
    )  # 기본 동작이 틀린 것을 고정
