#!/usr/bin/env python3
"""금투협 수시공시 첨부 조회·다운로드, 그리고 묶음 내 동일성 비교.

용례:
    # 한 공고 묶음의 행들이 같은 파일을 가리키는지 확인
    python3 scripts/kofia_attachments.py A01048 20260814 2OF0401 2 \
        K55301B27762 K55301B27788 K55301B27796

근거와 파라미터 설명은 gate-a/12 6절.
전송에 curl을 쓰는 이유는 fetch_kofia_ann.py 주석 참고.
"""
import hashlib
import re
import subprocess
import sys
import urllib.parse

SERVICE_URL = "https://dis.kofia.or.kr/proframeWeb/XMLSERVICES/"
DOWNLOAD_URL = "https://disdown.kofia.or.kr/COMFSFileDownload.jsp"

DETAIL_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<message>
  <proframeHeader>
    <pfmAppName>FS-DIS2</pfmAppName>
    <pfmSvcName>DISFtimeDetSO</pfmSvcName>
    <pfmFnName>select</pfmFnName>
  </proframeHeader>
  <systemHeader></systemHeader>
  <DISFtimeDetOutputListDTO>
    <companyCd>{company}</companyCd>
    <standardDt>{date}</standardDt>
    <standardCd>{code}</standardCd>
    <txCd>{tx}</txCd>
    <txVsn>{version}</txVsn>
    <uGb>F</uGb>
    <seq>{seq}</seq>
  </DISFtimeDetOutputListDTO>
</message>"""


def _tag(block, name):
    match = re.search(r"<%s>(.*?)</%s>" % (name, name), block, re.S)
    return match.group(1).strip() if match else ""


def attachments(company, date, code, tx, version, seq="1"):
    """(fileNm, serverPath, originalFileNm) 목록. txVsn을 0으로 주면 SQL 예외가 난다."""
    body = DETAIL_TEMPLATE.format(
        company=company, date=date, code=code, tx=tx, version=version, seq=seq
    )
    result = subprocess.run(
        ["curl", "-sS", "--max-time", "90", "-X", "POST", SERVICE_URL,
         "-H", "Content-Type: text/xml; charset=UTF-8",
         "-H", "Referer: https://dis.kofia.or.kr/websquare/index.jsp",
         "-A", "Mozilla/5.0", "--data-binary", "@-"],
        input=body.encode("utf-8"), capture_output=True,
    )
    xml = result.stdout.decode("utf-8", "replace")
    # 목록 조회와 같은 서버·같은 함정이다. 잘린 XML은 첨부를 조용히 적게 센다.
    if result.returncode != 0 or not xml.rstrip().endswith("</root>"):
        raise RuntimeError(
            "첨부 목록 조회 실패 (%s %s %s): 응답이 </root>로 끝나지 않음 (%d바이트)"
            % (company, date, code, len(xml))
        )
    start = xml.find("<file>")
    if start < 0:
        return []
    found = []
    for match in re.finditer(r"<list>(.*?)</list>", xml[start:], re.S):
        block = match.group(1)
        name = _tag(block, "fileNm")
        if name:
            found.append((name, _tag(block, "serverPath"), _tag(block, "originalFileNm")))
    return found


def download(file_name, server_path, original_name):
    url = "%s?serverPath=%s&serverFileNm=%s&filename=%s" % (
        DOWNLOAD_URL,
        urllib.parse.quote(server_path, safe=""),
        urllib.parse.quote(file_name, safe=""),
        urllib.parse.quote(original_name, safe=""),
    )
    result = subprocess.run(
        ["curl", "-sS", "-L", "--max-time", "120", "-A", "Mozilla/5.0",
         "-H", "Referer: https://dis.kofia.or.kr/", url],
        capture_output=True,
    )
    return result.stdout


if __name__ == "__main__":
    if len(sys.argv) < 6:
        sys.exit("usage: kofia_attachments.py <companyCd> <standardDt> <txCd> <txVsn> <standardCd>...")
    company, date, tx, version = sys.argv[1:5]
    codes = sys.argv[5:]

    # 같은 파일을 여러 행이 가리키므로 fileNm 기준으로 한 번만 받는다 (gate-a/12 6절).
    digests = {}
    per_row = {}
    for code in codes:
        found = attachments(company, date, code, tx, version)
        per_row[code] = tuple(sorted(name for name, _, _ in found))
        for name, path, original in found:
            if name not in digests:
                digests[name] = (hashlib.sha256(download(name, path, original)).hexdigest(), original)
        print("%-14s 첨부 %d건" % (code, len(found)))

    distinct = set(per_row.values())
    print("\n행별 첨부 파일명 집합: %d종" % len(distinct))
    if len(distinct) == 1:
        print("→ 모든 행이 같은 파일을 가리킨다. 이 묶음은 문서 1건이다.")
        for name in sorted(next(iter(distinct))):
            digest, original = digests[name]
            print("   %s  %s" % (digest[:16], original))
    else:
        print("→ 행마다 파일이 다르다. 묶으면 안 된다.")
        for code, names in per_row.items():
            print("   %-14s %s" % (code, [digests[n][1] for n in names]))
