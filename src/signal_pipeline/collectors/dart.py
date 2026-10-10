"""DART 펀드공시 크롤러 1차 (이슈 #45).

수집 경로와 규칙은 docs/data-sources.md 「DART」, 원본 보관은 docs/storage-and-failure-rules.md.

처리 흐름 (접수일 하루씩, 오름차순)
1. list_stream: OPEN DART list.json(pblntf_ty=G)을 100건씩 받아 report_nm으로 분류
2. 투자설명서(정정본 포함)만 받는다: 표지 XML(document.xml) + 뷰어 트리(main.do) + 표지 HTML(viewer.do)
   + 본문 PDF(download.do)
   증권신고서·일괄신고서는 건수만 세고 요청하지 않는다. 목록 응답(api_response)에는 남는다.
   현재 설계에서 점수 계산에 쓰이지 않고, 첫 실행에서 요청의 약 절반을 차지했음(10월 5일 결정)
3. 그날 문서를 빠짐없이 처리하면 워터마크를 그날로 전진. 실패가 남은 날 이후로는 전진하지 않음

실행
    uv run --env-file .env python -m signal_pipeline.collectors.dart --from 2026-08-25 --max-pdf 500
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from zoneinfo import ZoneInfo

from signal_pipeline.common.http import FetchResult, HttpClient, Outcome
from signal_pipeline.common.runlog import RunLog
from signal_pipeline.common.state import Watermark
from signal_pipeline.common.storage import RawStore, encode_source_key, is_pdf, is_zip

SOURCE = "dart"
CRAWLER_VERSION = "dart-crawler 0.2"
USER_AGENT = (
    "BOAZ-Signal-crawler/0.1 (+https://github.com/BOAZ-Signal-Team-26/signal-pipeline)"
)
KST = ZoneInfo("Asia/Seoul")

LIST_URL = "https://opendart.fss.or.kr/api/list.json"
DOC_URL = "https://opendart.fss.or.kr/api/document.xml"
VIEWER_BASE = "https://dart.fss.or.kr"
PAGE_COUNT = 100  # OPEN DART 페이지당 최대 건수
LIST_FOLDER = "_list"  # 목록 응답 폴더. 14자리 접수번호 폴더와 섞이지 않게 `_`로 시작

# OPEN DART 응답 status (개발가이드 「공시검색」 메시지 설명, 10월 5일 확인)
STATUS_OUTCOME = {
    "000": Outcome.SUCCESS,
    "013": Outcome.EMPTY,  # 조회된 데이타가 없습니다
    "014": Outcome.PERMANENT_FAILED,  # 파일이 존재하지 않습니다 (재시도해도 같음)
    "010": Outcome.CONFIG_ERROR,  # 등록되지 않은 키
    "011": Outcome.CONFIG_ERROR,  # 사용할 수 없는 키
    "012": Outcome.CONFIG_ERROR,  # 접근할 수 없는 IP
    "901": Outcome.CONFIG_ERROR,  # 계정 개인정보 보유기간 만료
    "020": Outcome.RATE_LIMITED,  # 요청 제한 초과
    "800": Outcome.RETRYABLE_FAILED,  # 시스템 점검
    "900": Outcome.RETRYABLE_FAILED,  # 정의되지 않은 오류
}
STOP_OUTCOMES = {Outcome.CONFIG_ERROR, Outcome.RATE_LIMITED}


class Kind(StrEnum):
    PROSPECTUS = "투자설명서"
    REGISTRATION = "증권신고서"
    SHELF = "일괄신고서"
    OTHER = "대상 아님"


TARGET_KINDS = {Kind.PROSPECTUS}
# 뷰어 트리에서 표지를 찾을 노드 이름(공백 제거 후 비교). 번호(eleId)로 찾지 않음(docs/data-sources.md)
COVER_NODE = "투자설명서"
BODY_NODE = "[본문]"
REQUIRED_ROLES = ["cover_xml", "viewer_tree", "cover_html", "body_pdf"]
EXT = {
    "cover_xml": "zip",
    "viewer_tree": "html",
    "cover_html": "html",
    "body_pdf": "pdf",
}


def classify_report(report_nm: str) -> tuple[Kind, bool]:
    """report_nm → (문서 종류, 정정본 여부). 예: 「[기재정정]투자설명서(집합투자증권)(…)」."""
    correction = report_nm.startswith("[")
    base = re.sub(r"^(\[[^\]]*\])+", "", report_nm).strip()
    for kind in (Kind.PROSPECTUS, Kind.REGISTRATION, Kind.SHELF):
        if base.startswith(kind.value):
            return kind, correction
    return Kind.OTHER, correction


def parse_tree(page: str) -> list[dict[str, str]]:
    """main.do의 문서 트리 노드. 트리 JS가 `var nodeN = {}`를 노드마다 재사용하므로 블록 단위로 끊어 읽는다."""
    nodes = []
    for block in re.split(r"var\s+node\d+\s*=\s*\{\}\s*;", page)[1:]:
        fields = dict(re.findall(r"node\d+\['(\w+)'\]\s*=\s*\"([^\"]*)\"", block))
        if fields.get("eleId"):
            nodes.append(fields)
    return nodes


def find_node(nodes: list[dict[str, str]], name: str) -> dict[str, str] | None:
    return next(
        (n for n in nodes if re.sub(r"\s", "", n.get("text", "")) == name), None
    )


def find_pdf_link(viewer_page: str) -> str | None:
    match = re.search(r"download\.do\?[^\"'>\s]+", viewer_page)
    return html.unescape(match.group(0)) if match else None


@dataclass
class DocResult:
    complete: bool = True  # 재시도로 고칠 수 있는 실패가 없으면 True
    new_pdf: bool = False
    new_any: bool = False
    skipped: bool = False
    stop: Outcome | None = None


@dataclass
class Summary:
    days_done: list[str] = field(default_factory=list)
    kinds: Counter[str] = field(default_factory=Counter)
    documents_skipped: int = 0
    documents_new: int = 0
    body_pdf_new: int = 0
    cover_xml_014: list[str] = field(default_factory=list)
    permanent_failures: list[str] = field(default_factory=list)
    list_failures: list[str] = field(default_factory=list)
    lookback_new: list[str] = field(default_factory=list)
    stopped_by: str | None = None


class DartCrawler:
    def __init__(
        self,
        client: HttpClient,
        store: RawStore,
        log: RunLog,
        api_key: str,
        max_pdf: int,
    ) -> None:
        self.client, self.store, self.log = client, store, log
        self.api_key = api_key
        self.max_pdf = max_pdf
        self.summary = Summary()

    # ---- 요청·저장 공통 ----

    def _save(self, rcept_no: str, role: str, content: bytes, meta: dict) -> str:
        stored = self.store.save(
            SOURCE,
            encode_source_key([rcept_no]),
            role,
            EXT[role],
            content,
            {"source_fields": {"rcept_no": rcept_no}, **meta},
        )
        self.log.log_object(
            stored, source=SOURCE, file_role=role, document_key=rcept_no
        )
        return stored.storage_path

    def _latest(self, rcept_no: str, role: str) -> Path | None:
        return self.store.latest(SOURCE, encode_source_key([rcept_no]), role, EXT[role])

    # ---- list_stream ----

    def list_stream(self, day: date) -> tuple[list[dict], Outcome]:
        items: list[dict] = []
        page = 1
        while True:
            ymd = day.strftime("%Y%m%d")
            params = {
                "crtfc_key": self.api_key,
                "bgn_de": ymd,
                "end_de": ymd,
                "pblntf_ty": "G",
                "page_no": str(page),
                "page_count": str(PAGE_COUNT),
            }
            result = self.client.fetch(LIST_URL, params=params)
            request_key = f"list.json:G:{ymd}:p{page}"
            if result.outcome is not Outcome.SUCCESS:
                return items, self.log.log_fetch(
                    result, source=SOURCE, request_key=request_key
                )
            data = json.loads(result.content or b"{}")
            status = str(data.get("status", ""))
            outcome = STATUS_OUTCOME.get(status, Outcome.PERMANENT_FAILED)
            rows = data.get("list", []) if outcome is Outcome.SUCCESS else []
            path = None
            if outcome is Outcome.SUCCESS:
                # 목록 페이지: raw/dart/_list/{접수일}/page-NNNN__v{n}.json
                # PR #43에 DART 목록 예시가 없어 스냅숏형 소스(data_go_fund) 모양을 따른 제안
                stored = self.store.save(
                    SOURCE,
                    f"{LIST_FOLDER}/{day.isoformat()}",
                    "api_response",
                    "json",
                    result.content or b"",
                    {
                        "endpoint": result.endpoint,
                        "run_id": self.log.run_id,
                        "source_fields": {
                            "pblntf_ty": "G",
                            "rcept_dt": ymd,
                            "page": page,
                        },
                    },
                    name=f"page-{page:04d}",
                )
                self.log.log_object(
                    stored, source=SOURCE, file_role="api_response", document_key=None
                )
                path = stored.storage_path
            self.log.log_fetch(
                result,
                source=SOURCE,
                request_key=request_key,
                storage_path=path,
                source_result_code=status,
                result_count=len(rows),
                final_outcome=outcome,
                final_error=None if outcome is Outcome.SUCCESS else data.get("message"),
            )
            if outcome is Outcome.EMPTY:
                return items, Outcome.SUCCESS
            if outcome is not Outcome.SUCCESS:
                return items, outcome
            items += rows
            if page >= int(data.get("total_page", 1)):
                return items, Outcome.SUCCESS
            page += 1

    # ---- 문서 단위 ----

    def cover_xml(self, rcept_no: str) -> Outcome:
        params = {"crtfc_key": self.api_key, "rcept_no": rcept_no}
        result = self.client.fetch(DOC_URL, params=params)
        request_key = f"document.xml:{rcept_no}"
        if result.outcome is not Outcome.SUCCESS:
            return self.log.log_fetch(
                result, source=SOURCE, request_key=request_key, document_key=rcept_no
            )
        content = result.content or b""
        if is_zip(content):
            path = self._save(
                rcept_no, "cover_xml", content, {"endpoint": result.endpoint}
            )
            return self.log.log_fetch(
                result,
                source=SOURCE,
                request_key=request_key,
                document_key=rcept_no,
                storage_path=path,
            )
        # zip이 아니면 오류 XML. 예: <status>014</status> 파일이 존재하지 않습니다
        status = re.search(rb"<status>(\d+)</status>", content)
        code = status.group(1).decode() if status else None
        outcome = STATUS_OUTCOME.get(code or "", Outcome.PERMANENT_FAILED)
        if code == "014":
            self.summary.cover_xml_014.append(rcept_no)
        return self.log.log_fetch(
            result,
            source=SOURCE,
            request_key=request_key,
            document_key=rcept_no,
            source_result_code=code,
            final_outcome=outcome,
            final_error=f"document.xml status {code}" if code else "zip 아님",
        )

    def viewer_tree(self, rcept_no: str) -> tuple[list[dict[str, str]], Outcome]:
        stored = self._latest(rcept_no, "viewer_tree")
        if stored is not None:  # 이미 받은 트리는 다시 호출하지 않고 읽음
            return parse_tree(stored.read_text("utf-8", "replace")), Outcome.SUCCESS
        url = f"{VIEWER_BASE}/dsaf001/main.do"
        result = self.client.fetch(url, params={"rcpNo": rcept_no})
        request_key = f"main.do:{rcept_no}"
        if result.outcome is not Outcome.SUCCESS:
            outcome = self.log.log_fetch(
                result, source=SOURCE, request_key=request_key, document_key=rcept_no
            )
            return [], outcome
        content = result.content or b""
        nodes = parse_tree(content.decode("utf-8", "replace"))
        if not nodes:
            outcome = self.log.log_fetch(
                result,
                source=SOURCE,
                request_key=request_key,
                document_key=rcept_no,
                final_outcome=Outcome.PERMANENT_FAILED,
                final_error="트리 노드 없음",
            )
            return [], outcome
        path = self._save(
            rcept_no, "viewer_tree", content, {"endpoint": result.endpoint}
        )
        self.log.log_fetch(
            result,
            source=SOURCE,
            request_key=request_key,
            document_key=rcept_no,
            storage_path=path,
            result_count=len(nodes),
        )
        return nodes, Outcome.SUCCESS

    def _viewer(self, rcept_no: str, node: dict[str, str]) -> FetchResult:
        params = {
            "rcpNo": rcept_no,
            "dcmNo": node.get("dcmNo", ""),
            "eleId": node.get("eleId", ""),
            "offset": node.get("offset", ""),
            "length": node.get("length", ""),
            "dtd": node.get("dtd", "dart4.xsd"),
        }
        referer = f"{VIEWER_BASE}/dsaf001/main.do?rcpNo={rcept_no}"
        return self.client.fetch(
            f"{VIEWER_BASE}/report/viewer.do",
            params=params,
            headers={"Referer": referer},
        )

    def cover_html(self, rcept_no: str, nodes: list[dict]) -> Outcome:
        node = find_node(nodes, COVER_NODE)
        request_key = f"viewer.do:cover:{rcept_no}"
        if node is None:
            self.summary.permanent_failures.append(f"{rcept_no} 표지 노드 없음")
            return Outcome.PERMANENT_FAILED
        result = self._viewer(rcept_no, node)
        if result.outcome is not Outcome.SUCCESS:
            return self.log.log_fetch(
                result, source=SOURCE, request_key=request_key, document_key=rcept_no
            )
        path = self._save(
            rcept_no,
            "cover_html",
            result.content or b"",
            {"endpoint": result.endpoint, "node_text": node.get("text")},
        )
        return self.log.log_fetch(
            result,
            source=SOURCE,
            request_key=request_key,
            document_key=rcept_no,
            storage_path=path,
        )

    def body_pdf(self, rcept_no: str, nodes: list[dict]) -> Outcome:
        node = find_node(nodes, BODY_NODE)
        if node is None:
            self.summary.permanent_failures.append(f"{rcept_no} 본문 노드 없음")
            return Outcome.PERMANENT_FAILED
        result = self._viewer(rcept_no, node)
        request_key = f"viewer.do:body:{rcept_no}"
        if result.outcome is not Outcome.SUCCESS:
            return self.log.log_fetch(
                result, source=SOURCE, request_key=request_key, document_key=rcept_no
            )
        link = find_pdf_link((result.content or b"").decode("utf-8", "replace"))
        if link is None:
            self.summary.permanent_failures.append(f"{rcept_no} PDF 링크 없음")
            return self.log.log_fetch(
                result,
                source=SOURCE,
                request_key=request_key,
                document_key=rcept_no,
                final_outcome=Outcome.PERMANENT_FAILED,
                final_error="PDF 링크 없음",
            )
        self.log.log_fetch(
            result, source=SOURCE, request_key=request_key, document_key=rcept_no
        )
        pdf = self.client.fetch(
            f"{VIEWER_BASE}/report/{link}",
            headers={"Referer": f"{VIEWER_BASE}/report/viewer.do"},
        )
        request_key = f"download.do:{rcept_no}"
        if pdf.outcome is not Outcome.SUCCESS:
            return self.log.log_fetch(
                pdf, source=SOURCE, request_key=request_key, document_key=rcept_no
            )
        content = pdf.content or b""
        if not is_pdf(content):  # 오류 HTML을 PDF로 저장하지 않음
            self.summary.permanent_failures.append(f"{rcept_no} PDF 아님")
            return self.log.log_fetch(
                pdf,
                source=SOURCE,
                request_key=request_key,
                document_key=rcept_no,
                final_outcome=Outcome.PERMANENT_FAILED,
                final_error=f"PDF 아님 ({pdf.content_type})",
            )
        path = self._save(
            rcept_no,
            "body_pdf",
            content,
            {"endpoint": pdf.endpoint, "file_name": link.split("flNm=")[-1]},
        )
        return self.log.log_fetch(
            pdf,
            source=SOURCE,
            request_key=request_key,
            document_key=rcept_no,
            storage_path=path,
        )

    def document(self, item: dict) -> DocResult:
        rcept_no = item["rcept_no"]
        missing = [r for r in REQUIRED_ROLES if self._latest(rcept_no, r) is None]
        if not missing:
            return DocResult(skipped=True)

        doc = DocResult()
        outcomes: dict[str, Outcome] = {}
        if "cover_xml" in missing:
            outcomes["cover_xml"] = self.cover_xml(rcept_no)
        if {"viewer_tree", "cover_html", "body_pdf"} & set(missing):
            nodes, outcomes["viewer_tree"] = self.viewer_tree(rcept_no)
            if nodes:
                if "cover_html" in missing:
                    outcomes["cover_html"] = self.cover_html(rcept_no, nodes)
                if "body_pdf" in missing:
                    outcomes["body_pdf"] = self.body_pdf(rcept_no, nodes)
                    doc.new_pdf = outcomes["body_pdf"] is Outcome.SUCCESS

        for outcome in outcomes.values():
            if outcome in STOP_OUTCOMES:
                doc.stop = outcome
            # 영구 실패(014, 노드 없음, PDF 아님)는 다시 해도 같으므로 그날 완료를 막지 않음
            if outcome in (Outcome.RETRYABLE_FAILED, *STOP_OUTCOMES):
                doc.complete = False
        doc.new_any = any(o is Outcome.SUCCESS for o in outcomes.values())
        return doc

    # ---- 하루·전체 ----

    def day(self, day: date, previous_mark: date | None) -> tuple[bool, bool]:
        """(그날 완료 여부, 실행을 멈춰야 하는지)."""
        items, outcome = self.list_stream(day)
        if outcome is not Outcome.SUCCESS:
            # 목록을 못 받은 날은 미완료. 실행을 FAILED로 끝내도록 기록(워터마크는 그날 앞에서 멈춤)
            self.summary.list_failures.append(f"{day.isoformat()} {outcome}")
            return False, outcome in STOP_OUTCOMES
        complete = True
        for item in items:
            kind, _ = classify_report(item.get("report_nm", ""))
            self.summary.kinds[kind.value] += 1
            if kind not in TARGET_KINDS:  # 신고서·대상 아님은 건수만
                continue
            if self.summary.body_pdf_new >= self.max_pdf:
                self.summary.stopped_by = f"max_pdf {self.max_pdf}"
                return False, True
            doc = self.document(item)
            if doc.skipped:
                self.summary.documents_skipped += 1
                continue
            self.summary.documents_new += int(doc.new_any)
            self.summary.body_pdf_new += int(doc.new_pdf)
            if doc.new_any and previous_mark and day <= previous_mark:
                self.summary.lookback_new.append(item["rcept_no"])
            if doc.stop:
                self.summary.stopped_by = str(doc.stop)
                return False, True
            complete = complete and doc.complete
        return complete, False

    def run(self, start: date, end: date, mark: Watermark) -> bool:
        previous_mark = mark.load()
        advancing = True
        current = start
        while current <= end:
            complete, stop = self.day(current, previous_mark)
            print(
                f"{current} 완료={complete} 본문PDF 신규 누적={self.summary.body_pdf_new}",
                file=sys.stderr,
            )
            if complete:
                self.summary.days_done.append(current.isoformat())
            advancing = advancing and complete
            if advancing:
                mark.advance(current, self.log.run_id, first_day=start)
            if stop:
                break
            current += timedelta(days=1)
        stopped = self.summary.stopped_by in {str(o) for o in STOP_OUTCOMES}
        return not stopped and not self.summary.list_failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DART 펀드공시 크롤러 1차")
    parser.add_argument(
        "--from",
        dest="start",
        type=date.fromisoformat,
        help="시작 접수일. 워터마크가 있으면 생략(워터마크 − 룩백)",
    )
    parser.add_argument(
        "--to",
        dest="end",
        type=date.fromisoformat,
        help="끝 접수일. 기본은 어제(한국 시각, 오늘 목록은 아직 늘어나는 중)",
    )
    parser.add_argument("--max-pdf", type=int, default=500)
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=3,
        help="잠정값 3일(docs/storage-and-failure-rules.md 「미결」)",
    )
    parser.add_argument("--min-interval", type=float, default=1.0)
    args = parser.parse_args(argv)

    raw_root = os.environ.get("RAW_ROOT", "").strip()
    api_key = os.environ.get("OPENDART_API_KEY", "").strip()
    if not raw_root or not api_key:
        parser.error(
            ".env에 RAW_ROOT와 OPENDART_API_KEY가 필요합니다 (--env-file .env)"
        )

    mark = Watermark(raw_root, SOURCE)
    # 워터마크가 있으면 워터마크 − 룩백부터. --from은 첫 실행에만 쓰임
    start = mark.start_date(args.lookback_days) or args.start
    if start is None:
        parser.error("첫 실행에는 --from이 필요합니다")
    end = args.end or datetime.now(KST).date() - timedelta(days=1)

    config = {
        "crawler": CRAWLER_VERSION,
        "source": SOURCE,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "max_pdf": args.max_pdf,
        "lookback_days": args.lookback_days,
        "lookback_days_status": "잠정",
        "min_interval": args.min_interval,
        "user_agent": USER_AGENT,
    }
    log = RunLog(raw_root, baseline_date=end.isoformat(), config=config)
    print(f"run_id={log.run_id} {start}~{end}", file=sys.stderr)
    with HttpClient(USER_AGENT, min_interval=args.min_interval) as client:
        crawler = DartCrawler(client, RawStore(raw_root), log, api_key, args.max_pdf)
        try:
            ok = crawler.run(start, end, mark)
        except BaseException:
            log.finish("FAILED", {"stopped_by": "exception"})
            raise
    summary = crawler.summary
    log.finish(
        "SUCCEEDED" if ok else "FAILED",
        {
            "days_done": summary.days_done,
            "kinds": dict(summary.kinds),
            "documents_new": summary.documents_new,
            "documents_skipped": summary.documents_skipped,
            "body_pdf_new": summary.body_pdf_new,
            "cover_xml_014": summary.cover_xml_014,
            "permanent_failures": summary.permanent_failures,
            "list_failures": summary.list_failures,
            "lookback_new": summary.lookback_new,
            "watermark": str(mark.load()),
            "stopped_by": summary.stopped_by,
        },
    )
    print(json.dumps(log.run["summary"], ensure_ascii=False, indent=1), file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
