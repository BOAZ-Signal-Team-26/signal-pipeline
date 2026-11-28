"""13절 수수료·보수 표 정규화 시험. DB·PDF 없이 pdfplumber extract() 모양의 행을 직접 만든다."""

from signal_pipeline.parsing.fee_table import fund_name, normalize_document
from signal_pipeline.parsing.fee_table_rows import merge_labels, normalize_table

N = None

# 접수번호 20260901000010 32쪽 아래 보수 표(22열) 앞 7행과 33쪽 위 이어지는 표(13열) 앞 6행.
# dump.py 출력에서 그대로 옮겨 적음
P32_BOSU = [
    ["명칭\n(클래스)", N, N, "", "지급비율(연간, %)", *[N] * 16, ""],
    [N, N, N, "집합투\n자업자", N, "판매\n회사", "신탁\n업자", "", "사무", "", "총보수", "기타\n비용",
     "총보수\nㆍ비용", "", "합성", "", "", "동종", "", "", "증권", ""],
    [N, N, N, N, N, N, N, N, "관리", N, N, N, N, N, "총보수", N, N, "유형", N, N, "거래", N],
    [N, N, N, N, N, N, N, N, "회사", N, N, N, N, N, "ᆞ비용", N, N, "총보수", N, N, "비용", N],
    ["", "수수료선취-", "", "0.6000", N, "0.6500", "0.0300", "0.0170", N, N, "1.2970", "0.0000",
     "1.2970", "1.2970", N, N, "1.3300", N, N, "0.4321", N, N],
    [N, "오프라인 (A)", *[N] * 20],
    ["", "수수료미징구-", "", "0.6000", N, "1.3000", "0.0300", "0.0170", N, N, "1.9470", "0.0008",
     "1.9478", "1.9478", N, N, "1.6000", N, N, "0.4453", N, N],
]  # fmt: skip
P33_CONT = [
    ["", "오프라인-", *[""] * 11],
    [N, "보수체감 (C1)", *[N] * 11],
    ["", "수수료미징구-", "", "0.6000", "1.2000", "0.0300", "0.0170", "1.8470", "0.0008",
     "1.8478", "1.8478", "-", "0.4453"],
    [N, "오프라인-", *[N] * 11],
    [N, "보수체감 (C2)", *[N] * 11],
    ["지급시기", N, N, "매3개월 후급", N, N, N, "-", "사유발생\n시", "-", "-", "-", "사유\n발생시"],
]  # fmt: skip
P32_FRAGMENT = [["집합투"], ["자업자"]]  # 표 안 머리글 칸이 따로 잡힌 작은 표
VALUATION = [
    ["구 분", "내 용"],
    ["상장증권", "평가기준일에 증권시장에서 거래된 최종시가"],
]


def test_real_example_split_header_label_and_page_continuation() -> None:
    raw = [
        (31, [(0.3, VALUATION)]),
        (32, [(0.78, P32_BOSU), (0.81, P32_FRAGMENT)]),
        (33, [(0.07, P33_CONT)]),
    ]
    status, tables = normalize_document(raw, "어떤펀드")
    assert status == "OK"
    assert len(tables) == 1
    table = tables[0]
    assert table["pages"] == [32, 33]
    assert table["orientation"] == "ROWS"
    assert table["columns"] == [
        "집합투자업자",
        "판매회사",
        "신탁업자",
        "사무관리회사",
        "총보수",
        "기타비용",
        "총보수ㆍ비용",
        "합성총보수ᆞ비용",
        "동종유형총보수",
        "증권거래비용",
    ]
    labels = [r["label"] for r in table["rows"]]
    assert labels == [
        "수수료선취-오프라인(A)",
        "수수료미징구-오프라인-보수체감(C1)",
        "수수료미징구-오프라인-보수체감(C2)",
    ]
    a, c1, c2 = (r["cells"] for r in table["rows"])
    assert a[4] == "1.2970" and a[0] == "0.6000" and a[-1] == "0.4321"
    assert c1[1] == "1.3000" and c2[1] == "1.2000"
    assert all(len(r["cells"]) == len(table["columns"]) for r in table["rows"])


def test_empty_columns_dropped_and_cell_text_kept() -> None:
    raw = [
        ["구분", "", "선취판매수수료", N, "환매수수료", ""],
        ["수수료선취(A)", N, "납입금액의\n1% 이내", N, "-", ""],
    ]
    [table] = normalize_table(raw, page=1, top=0.5)
    assert table.columns == ("선취판매수수료", "환매수수료")
    assert table.entries[0].cells == ("납입금액의1% 이내", "-")


def test_split_class_label_joins_previous_or_next_row() -> None:
    raw = [
        ["종류", "집합투자업자보수", "판매회사보수"],
        ["수수료선취-", "0.10", "0.50"],
        ["오프라인(A)", "", ""],
        ["수수료미징구-", "", ""],
        ["온라인(Ce)", "0.10", "0.20"],
    ]
    [table] = normalize_table(raw, page=1, top=0.1)
    rows = merge_labels(table.entries)
    assert [r.label for r in rows] == [
        "수수료선취-오프라인(A)",
        "수수료미징구-온라인(Ce)",
    ]
    assert rows[1].cells == ("0.10", "0.20")


def test_transposed_table_becomes_rows() -> None:
    raw = [
        ["", "지급비율 (연간, %)", N, "지급시기"],
        ["구 분", "A", "C", N],
        [N, "(수수료선취)", "(수수료미징구)", N],
        ["집합투자업자보수", "0.105", "0.105", "매3월 후급"],
        ["판매회사보수", "0.50", "0.80", N],
        ["총보수", "0.650", "0.950", "-"],
    ]
    status, tables = normalize_document([(30, [(0.3, raw)])], "")
    assert status == "OK"
    [table] = tables
    assert table["orientation"] == "TRANSPOSED"
    assert table["columns"] == ["집합투자업자보수", "판매회사보수", "총보수"]
    assert table["rows"] == [
        {"label": "A(수수료선취)", "cells": ["0.105", "0.50", "0.650"]},
        {"label": "C(수수료미징구)", "cells": ["0.105", "0.80", "0.950"]},
    ]


def test_vertical_single_class_uses_fund_name() -> None:
    raw = [
        ["구\x00분", "", "지급비율(연간,%)", "지급시기"],
        ["집합투자업자 보수", N, "0.045", "매 3개월"],
        ["신탁업자 보수", N, "0.005", N],
        ["총 보수", N, "0.060", "-"],
    ]
    status, tables = normalize_document([(31, [(0.2, raw)])], "어떤증권투자신탁(채권)")
    assert status == "OK"
    [table] = tables
    assert table["orientation"] == "VERTICAL_SINGLE"
    assert table["columns"] == ["집합투자업자보수", "신탁업자보수", "총보수"]
    assert table["rows"] == [
        {"label": "어떤증권투자신탁(채권)", "cells": ["0.045", "0.005", "0.060"]}
    ]


HEAD = ["구분", "집합투자업자보수", "판매회사보수", "총보수"]


def test_continuation_joined_only_near_top_of_next_page() -> None:
    first = [HEAD, ["수수료선취(A)", "0.1", "0.5", "0.6"]]
    cont = [["수수료미징구(C)", "0.1", "0.9", "1.0"]]
    _, tables = normalize_document([(10, [(0.7, first)]), (11, [(0.05, cont)])], "")
    assert tables[0]["pages"] == [10, 11]
    assert [r["label"] for r in tables[0]["rows"]] == [
        "수수료선취(A)",
        "수수료미징구(C)",
    ]
    _, tables = normalize_document([(10, [(0.7, first)]), (11, [(0.5, cont)])], "")
    assert tables[0]["pages"] == [10] and len(tables[0]["rows"]) == 1


def test_two_period_tables_stay_separate() -> None:
    year1 = [["1년 미만", "", ""], HEAD, ["수수료미징구(C)", "0.1", "0.9", "1.0"]]
    year2 = [HEAD, ["수수료미징구(C)", "0.1", "0.7", "0.8"]]
    _, tables = normalize_document([(20, [(0.2, year1), (0.6, year2)])], "")
    assert [t["rows"][0]["cells"][2] for t in tables] == ["1.0", "0.8"]


def test_non_fee_table_rejected() -> None:
    investment = [
        ["종류", "투자기간", "1년후", "3년후"],
        ["수수료선취(A)", "판매수수료 및 보수ㆍ비용", "232", "507"],
    ]
    status, tables = normalize_document(
        [(31, [(0.3, VALUATION), (0.6, investment)])], ""
    )
    assert (status, tables) == ("UNREADABLE", [])
    assert normalize_document([(31, [])], "") == ("NO_TABLE", [])


def test_fund_name_from_report_name() -> None:
    name = "[기재정정]투자설명서(집합투자증권)(마이다스머니마켓증권투자신탁(채권))"
    assert fund_name(name) == "마이다스머니마켓증권투자신탁(채권)"
