#!/usr/bin/env python3
"""금투협 전자공시 펀드공시검색 조회 (인증키 불필요).

용례:
    python3 scripts/fetch_kofia_ann.py 20260813 20260815 > out.xml

엔드포인트와 파라미터는 2026-09-19 실측으로 확인했다. 근거는 gate-a/12.
화면 JS(`/wq/fundann/inc/DISFundAnnSrch.xml`)의 goSearch()가 만드는 DTO와 같다.

전송에 curl을 쓴다. urllib는 이 서버의 응답을 절반쯤에서 끊어 받는다(응답
1,500행 중 43행만 도착하는 식). 잘린 XML은 파서가 행을 조용히 적게 세므로
`</root>`로 끝나는지 확인한 뒤에만 결과를 돌려준다.
"""
import subprocess
import sys
import time

URL = "https://dis.kofia.or.kr/proframeWeb/XMLSERVICES/"

# uGb=1 전체(정기+수시). 2·3은 0건을 돌려주므로 쓰지 않는다.
# uRptAllYN=1 은 보고서 유형 미지정(전체)을 뜻한다. 0으로 두면 0건이 나온다.
# gbOption=S 는 펀드 선택 방식이며 uCdList를 비우면 전체가 대상이다.
TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<message>
  <proframeHeader>
    <pfmAppName>FS-DIS2</pfmAppName>
    <pfmSvcName>DISFundFTimeAnnSO</pfmSvcName>
    <pfmFnName>selectAnn</pfmFnName>
  </proframeHeader>
  <systemHeader></systemHeader>
  <DISFTimeAnnInsDTO>
    <uGb>1</uGb>
    <vStrtDt>{start}</vStrtDt>
    <vEndDt>{end}</vEndDt>
    <uCdList>{fund}</uCdList>
    <gbOption>{gb_option}</gbOption>
    <uRptList></uRptList>
    <tsCd></tsCd>
    <uRptAllYN>1</uRptAllYN>
    <companyCd>{company}</companyCd>
  </DISFTimeAnnInsDTO>
</message>"""


def fetch(start, end, fund="", company="", gb_option="S", timeout=120, attempts=3):
    """조회기간은 1년 이내여야 한다(화면의 검증 규칙과 같다)."""
    body = TEMPLATE.format(
        start=start, end=end, fund=fund, company=company, gb_option=gb_option
    )
    command = [
        "curl", "-sS", "--max-time", str(timeout),
        "-X", "POST", URL,
        "-H", "Content-Type: text/xml; charset=UTF-8",
        "-H", "Referer: https://dis.kofia.or.kr/websquare/index.jsp",
        "-A", "Mozilla/5.0",
        "--data-binary", "@-",
    ]
    last_error = None
    for attempt in range(attempts):
        result = subprocess.run(
            command, input=body.encode("utf-8"), capture_output=True
        )
        text = result.stdout.decode("utf-8", "replace")
        if result.returncode != 0:
            last_error = result.stderr.decode("utf-8", "replace").strip()
        elif not text.rstrip().endswith("</root>"):
            last_error = "응답이 </root>로 끝나지 않음 — 잘린 응답 (%d바이트)" % len(text)
        else:
            return text
        if attempt < attempts - 1:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("금투협 조회 실패 (%d회 시도): %s" % (attempts, last_error))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("usage: fetch_kofia_ann.py <YYYYMMDD> <YYYYMMDD> [fundName] [companyCd]")
    sys.stdout.write(fetch(*sys.argv[1:5]))
