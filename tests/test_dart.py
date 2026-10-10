from datetime import date
from pathlib import Path

import httpx
import pytest

from signal_pipeline.collectors.dart import (
    BODY_NODE,
    COVER_NODE,
    TARGET_KINDS,
    DartCrawler,
    Kind,
    classify_report,
    find_node,
    find_pdf_link,
    parse_tree,
)
from signal_pipeline.common.http import HttpClient
from signal_pipeline.common.runlog import RunLog
from signal_pipeline.common.state import Watermark
from signal_pipeline.common.storage import RawStore

# DART 공개 뷰어 main.do의 트리 스크립트 형태(10월 5일 실제 응답 20261002000011에서 줄여 옮김).
# 정정본은 「정 정 신 고 (보고)」 노드가 앞에 붙어 표지가 eleId=2가 된다
TREE_PAGE = """
<script>
		var node1 = {};
		node1['text'] = "정 정 신 고 (보고)";
		node1['dcmNo'] = "11600615";
		node1['eleId'] = "1";
		node1['offset'] = "632";
		node1['length'] = "3720";
		node1['dtd'] = "dart4.xsd";
		treeData.push(node1);
		var node1 = {};
		node1['text'] = "투 자 설 명 서";
		node1['dcmNo'] = "11600615";
		node1['eleId'] = "2";
		node1['offset'] = "4382";
		node1['length'] = "7711";
		node1['dtd'] = "dart4.xsd";
		treeData.push(node1);
		var node1 = {};
		node1['text'] = "[ 본 문 ]";
		node1['dcmNo'] = "11600615";
		node1['eleId'] = "3";
		node1['offset'] = "12093";
		node1['length'] = "300";
		node1['dtd'] = "dart4.xsd";
		treeData.push(node1);
</script>
"""


@pytest.mark.parametrize(
    ("report_nm", "kind", "correction"),
    [
        (
            "투자설명서(집합투자증권)(NH-Amundi성장주도코리아50증권투자신탁[채권혼합])",
            Kind.PROSPECTUS,
            False,
        ),
        (
            "[기재정정]투자설명서(집합투자증권)(베어링독일성장펀드)",
            Kind.PROSPECTUS,
            True,
        ),
        (
            "[기재정정]일괄신고서(집합투자증권-회사형)(핌코펀드:글로벌인베스터즈시리즈피엘씨)",
            Kind.SHELF,
            True,
        ),
        (
            "[기재정정]증권신고서(집합투자증권-신탁형)(신한지수연계증권투자신탁SEK-70호)",
            Kind.REGISTRATION,
            True,
        ),
        ("증권발행실적보고서(집합투자증권)(어느펀드)", Kind.OTHER, False),
        ("[첨부정정]투자설명서(집합투자증권)(어느펀드)", Kind.PROSPECTUS, True),
    ],
)
def test_classify_report(report_nm: str, kind: Kind, correction: bool) -> None:
    assert classify_report(report_nm) == (kind, correction)


def test_parse_tree_reads_every_node_despite_reused_variable_name() -> None:
    nodes = parse_tree(TREE_PAGE)
    assert [n["eleId"] for n in nodes] == ["1", "2", "3"]
    assert nodes[1]["offset"] == "4382" and nodes[1]["dcmNo"] == "11600615"


def test_cover_is_found_by_text_not_by_ele_id() -> None:
    nodes = parse_tree(TREE_PAGE)
    cover = find_node(nodes, COVER_NODE)
    body = find_node(nodes, BODY_NODE)
    assert cover is not None and cover["eleId"] == "2"
    assert body is not None and body["eleId"] == "3"
    assert find_node(nodes, "일괄신고서") is None


def test_find_pdf_link_unescapes_html() -> None:
    page = '<a href="/report/download.do?dcmNo=11600646&amp;flNm=bpm91_abc.pdf">PDF</a>'
    assert find_pdf_link(page) == "download.do?dcmNo=11600646&flNm=bpm91_abc.pdf"
    assert find_pdf_link("<html>본문 없음</html>") is None


def test_only_prospectus_is_crawled() -> None:
    # 신고서는 분류해 건수만 세고 요청하지 않음(10월 5일 결정)
    assert TARGET_KINDS == {Kind.PROSPECTUS}


def test_list_failure_is_recorded_and_fails_run(tmp_path: Path) -> None:
    # 목록 조회가 404로 끝나는 날: 그날 미완료, 요약에 기록, 실행은 실패(PR #47 리뷰)
    client = HttpClient(
        "test",
        min_interval=0,
        backoff_base=0,
        transport=httpx.MockTransport(lambda request: httpx.Response(404)),
    )
    log = RunLog(tmp_path, baseline_date="2026-10-01", config={})
    crawler = DartCrawler(client, RawStore(tmp_path), log, api_key="K", max_pdf=1)
    mark = Watermark(tmp_path, "dart")
    day = date(2026, 10, 1)
    assert crawler.run(day, day, mark) is False
    assert crawler.summary.list_failures == ["2026-10-01 PERMANENT_FAILED"]
    assert crawler.summary.days_done == []
    assert mark.load() is None
