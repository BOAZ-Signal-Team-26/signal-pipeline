#!/usr/bin/env python3
"""OPEN DART 목록 API · 원문 API 1회 확인 (설계 문서의 「미호출」 미결 2건을 닫기 위한 조사 스크립트).

설계 근거는 docs/data-sources.md 「OPEN DART API」. 그 절은 2026-09-30까지 「미호출」이었다.
키는 .env 의 OPENDART_API_KEY 에서 읽고, 화면에는 절대 찍지 않는다.

확인할 것 둘
- 목록 API `list.json` 의 응답 필드 이름 — ERD `document` 표 칼럼(접수번호·접수일·법인코드·공시 세부유형)과 대조
- 원문 API `document.xml` 의 zip 안에 무엇이 들어 있는지 — XML 만인지, PDF 첨부까지인지

용례:
    python3 research/scripts/probe_opendart.py                  # 최근 7일 펀드공시(G) 목록 + 원문 1건
    python3 research/scripts/probe_opendart.py --days 30 --no-doc

출력은 필드 이름·건수·zip 파일 목록만이다. 응답 원본은 저장하지 않는다(--save-dir 지정 시에만 그 폴더에 둠).

실호출로 확인한 것 (2026-09-30, 결과는 docs/data-sources.md 「OPEN DART API」에 정리)
- 목록 항목 필드 9개: corp_cls, corp_code(8자), corp_name, flr_nm, rcept_dt(YYYYMMDD), rcept_no(14자),
  report_nm, rm, stock_code(펀드는 빈 문자열). 최근 7일 펀드공시(G) 147건
- **`pblntf_detail_ty`는 응답에 없고 요청 필터로도 효과가 없다.** G001·G002·G003 모두 147건으로 동일.
  문서 종류는 report_nm 으로만 가른다
- document.xml 의 zip 안에는 `{접수번호}.xml` 1개만 있다. PDF 첨부 없음. 내용은 표지·정정 안내이며 본문 없음
- Homebrew python3.14 는 인증서 경로가 없어 SSL 검증에 실패한다. 저장소의 `.venv/bin/python`(3.12)으로 실행한다
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import sys
import urllib.parse
import urllib.request
import zipfile

LIST_URL = "https://opendart.fss.or.kr/api/list.json"
DOC_URL = "https://opendart.fss.or.kr/api/document.xml"
UA = "BOAZ-Signal research probe (github.com/BOAZ-Signal-Team-26/signal-pipeline)"


def load_env(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                name, _, value = line.partition("=")
                os.environ.setdefault(name.strip(), value.strip())


def get(url: str, params: dict) -> tuple[int, bytes, str]:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status, response.read(), response.headers.get("Content-Type", "")


def probe_list(key: str, days: int, detail: str | None) -> list[dict]:
    end = dt.date.today()
    begin = end - dt.timedelta(days=days)
    params = {
        "crtfc_key": key,
        "bgn_de": begin.strftime("%Y%m%d"),
        "end_de": end.strftime("%Y%m%d"),
        "pblntf_ty": "G",
        "page_no": 1,
        "page_count": 100,
    }
    if detail:
        params["pblntf_detail_ty"] = detail
    status, body, ctype = get(LIST_URL, params)
    data = json.loads(body.decode("utf-8"))
    label = "list.json pblntf_ty=G" + (f" pblntf_detail_ty={detail}" if detail else "")
    print(f"[{label}] HTTP {status} · {ctype}")
    print(f"  status={data.get('status')} message={data.get('message')}")
    print(f"  최상위 키: {sorted(k for k in data if k != 'list')}")
    print(f"  total_count={data.get('total_count')} total_page={data.get('total_page')} "
          f"이번 페이지={len(data.get('list', []))}건")
    items = data.get("list", [])
    if items:
        fields: set[str] = set()
        for item in items:
            fields.update(item.keys())
        print(f"  목록 항목 필드({len(fields)}): {sorted(fields)}")
        sample = items[0]
        print("  첫 항목 값 길이: " + ", ".join(
            f"{k}={len(str(v))}자" for k, v in sorted(sample.items())))
        names: dict[str, int] = {}
        for item in items:
            name = item.get("report_nm", "")
            head = name.split("(")[0].replace("[기재정정]", "").strip()
            names[head] = names.get(head, 0) + 1
        print(f"  report_nm 앞머리 분포(이번 페이지): {dict(sorted(names.items(), key=lambda x: -x[1]))}")
        detail_values = sorted({str(item.get("pblntf_detail_ty", "")) for item in items})
        print(f"  응답 안 pblntf_detail_ty 값: {detail_values if 'pblntf_detail_ty' in fields else '(필드 없음)'}")
    return items


def probe_document(key: str, rcept_no: str, save_dir: str | None) -> None:
    status, body, ctype = get(DOC_URL, {"crtfc_key": key, "rcept_no": rcept_no})
    print(f"[document.xml rcept_no={rcept_no}] HTTP {status} · {ctype} · {len(body):,}바이트")
    if not zipfile.is_zipfile(io.BytesIO(body)):
        print("  zip 이 아니다. 앞 200바이트:", body[:200])
        return
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        for info in archive.infolist():
            ext = os.path.splitext(info.filename)[1].lower()
            print(f"  - {info.filename} ({ext or '확장자 없음'}) {info.file_size:,}바이트")
            if ext == ".xml":
                text = archive.read(info).decode("utf-8", errors="replace")
                tags: list[str] = []
                for chunk in text.split("<")[1:60]:
                    tag = chunk.split(">")[0].split()[0] if chunk.strip() else ""
                    if tag and not tag.startswith(("/", "?", "!")) and tag not in tags:
                        tags.append(tag)
                print(f"    앞부분 태그 순서: {tags[:15]}")
        if save_dir:
            os.makedirs(save_dir, exist_ok=True)
            path = os.path.join(save_dir, f"opendart_{rcept_no}.zip")
            with open(path, "wb") as handle:
                handle.write(body)
            print(f"  저장: {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--no-doc", action="store_true", help="document.xml 호출 생략")
    parser.add_argument("--save-dir", default=None, help="응답 zip 을 저장할 폴더(저장소 밖 권장)")
    args = parser.parse_args()

    load_env()
    key = os.environ.get("OPENDART_API_KEY", "").strip()
    if not key:
        sys.exit(".env 에 OPENDART_API_KEY 가 비어 있다. 값은 Notion 「API 키 보관」 페이지에서 받는다.")

    items = probe_list(key, args.days, None)
    for detail in ("G001", "G002", "G003"):
        probe_list(key, args.days, detail)

    if args.no_doc or not items:
        return
    target = next((i for i in items if "투자설명서" in i.get("report_nm", "")), items[0])
    probe_document(key, target["rcept_no"], args.save_dir)


if __name__ == "__main__":
    main()
