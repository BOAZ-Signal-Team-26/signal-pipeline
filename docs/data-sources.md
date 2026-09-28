# 데이터 소스 수집 명세

## 상태

| 항목 | 내용 |
|---|---|
| 상태 | 현행 명세. 소스가 바뀌면 실측일을 덧붙이지 않고 이 문서를 고침 |
| 기준일 | 2026-09-22 (최초 작성 09-20, 금감원 실호출 09-21~22 반영) |
| 담당 | 대현 |
| 승인 | 팀 승인 전 |
| 범위 | 「어떻게 호출해서 받아오는가」만 다룸. 받은 뒤의 보관·실패 판정은 [원본 보관과 수집·파싱 실패 처리 규칙](storage-and-failure-rules.md), 조인과 칼럼은 [데이터 테이블·ERD 설계](data-model.md) |

- 모든 파라미터는 실측 또는 공식 스펙 페이지 판독으로 확인한 값
- 확인하지 못한 값은 본문에 「미확인」으로 표시하고 「미결」 절에 모음
- 스키마·키·실행 계약이 이 문서와 어긋나면 [데이터 테이블·ERD 설계](data-model.md)가 우선

## 결정 요약

| 결정 | 근거 |
|---|---|
| 금투협은 `curl`로 받고, 응답이 `</root>`로 끝나는지 확인한 뒤에만 사용 | `urllib`로 받으면 1,499행 중 43행만 도착. [금투협 중복 행·ETF 이름 규칙 검증](records/phase1-erd/kofia-rows-and-etf-rule.md) 「검증 1: 금투협 중복 행」 |
| 금투협 공시 목록은 한 요청 1년 미만 창, 실무상 1개월 단위로 분할 | 정확히 1년부터 오류 없이 0행. 11개월 창 186MB |
| 금투협 판매사별 펀드 목록으로 판매관계를 코드로 채움 | 판매사코드와 표준코드를 직접 줌. [조인 키 확인 기록](records/phase1-erd/join-key-checks.md) 「판매회사 명단 소스」 |
| 공공데이터포털 증분은 `beginBasDt` 사용, `setpDt`는 워터마크로 쓰지 않음 | `beginBasDt`는 그 날짜 이후 전체, `basDt`는 그 하루. `setpDt`는 과거 설정일 |
| KRX ETF 일별 스냅숏은 과거 일자로 몰아 받을 수 있음 | 2016-09-02 조회 성공. 최소 10년 소급 |
| DART 표지는 노드 텍스트 「투 자 설 명 서」로 찾고 `eleId` 번호로 찾지 않음 | 원본은 `eleId=1`, 정정본은 `eleId=2`가 표지 |
| DART 본문은 PDF 하나를 받아 부·절로 나눔 | 부 45/45, 절 292/294. [DART 본문 PDF 부·절 분할 실현성 검증](records/phase1-erd/dart-section-split.md) |
| 금감원 OPEN API는 개인 키 기준 1개월(28일) 창, `euc-kr` 디코드, JSON 루트 키 `reponse` | 09-21 실호출 |
| 금감원 제재 증분은 `inputDate` 기준 | 09-22 표본 8건 중 1건에서 확인. 재검증 필요(「미결」) |
| 분쟁조정결정례는 HWP 5.0만 추출, HWP 3.0은 추출 대상 외 | HWP 3.0은 OLE가 아닌 자체 바이너리 |

## 소스 한눈에 보기

| 소스 | 인증 | 호출 상태 | 공식 명세 | 호출 스크립트 |
|---|---|---|---|---|
| 금투협 전자공시 | 불필요 | 실호출 확인 | 없음. 화면 JS 역공학 | [`fetch_kofia_ann.py`](../research/scripts/fetch_kofia_ann.py) · [`fetch_kofia_sales.py`](../research/scripts/fetch_kofia_sales.py) · [`kofia_attachments.py`](../research/scripts/kofia_attachments.py) |
| 공공데이터포털 펀드상품기본정보 | 키 | 실호출 확인 (183,649건) | 있으나 미열람 (활용가이드 docx·Swagger) | [`verify_etf_rule.py`](../research/scripts/verify_etf_rule.py) |
| KRX ETF 일별매매정보 | 키 + 서비스별 승인 | 실호출 확인 (1,167건) | 공식 명세 없음. 응답 구조 실측 완료(09-20) | [`verify_etf_rule.py`](../research/scripts/verify_etf_rule.py) |
| DART 공개 뷰어 | 불필요 | 실호출 확인 | 없음. HTML 판독 | [`dart_sections.py`](../research/scripts/dart_sections.py) |
| OPEN DART API | 키 | 미호출 | 가이드 페이지 판독 | 없음 |
| 금감원 검사결과제재 / 경영유의사항 | 키 | 실호출 확인 (09-21 개인 키, 제재 8건) | 있음. 결과변수 표와 샘플 공개 | [`fetch_fss_sanctions.py`](../research/scripts/fetch_fss_sanctions.py) |
| 금감원 분쟁조정결정례 | 불필요 | 실호출 확인 | 없음. HTML 판독 (경로 09-20 복구) | [`fetch_fss_dispute.py`](../research/scripts/fetch_fss_dispute.py) + [`hwp_text.py`](../research/scripts/hwp_text.py) |
| 국가법령정보 | 키(`OC`) | 미호출 | 미확인 | 없음 |
| finlife | 키 | 펀드·ETF·ELS 없음. 소스 존치 미결 | 개요 페이지만 | 없음 |

- 「공식 명세」가 없는 소스(금투협·KRX·DART 공개 뷰어)는 판독한 내용이 전부이며, 서버가 예고 없이 바뀌면 알 수 없음
- 금감원 제재·경영유의는 09-20 명세 판독 시점에는 미호출이었고 09-21 개인 키 발급 후 실호출함

## 먼저 알아야 할 호출 주의점

| 주의점 | 내용 |
|---|---|
| 금투협은 `urllib`로 받을 수 없음 | 응답이 중간에서 잘림(1,499행 중 43행). `curl` 사용 |
| 파라미터 누락이 오류가 아니라 빈 결과로 나타남 | 금투협 `uRptAllYN=0`이면 HTTP 200 + 정상 XML + 0행. 0건을 정상으로 넘기지 않음 |
| 금감원 JSON 루트 키가 `reponse` | `response`가 아님. 공식 스펙의 오타이며 그대로 따라야 함 |

## 금투협 전자공시

- 화면: WebSquare. 뒤에 proframe이라는 XML-RPC 계열 서버가 있음
- 공식 API 문서 없음. 화면 JS 판독과 실호출로 확인한 내용
- 근거 실측: [금투협 중복 행·ETF 이름 규칙 검증](records/phase1-erd/kofia-rows-and-etf-rule.md) 「검증 1: 금투협 중복 행」

### 공통 호출 형식

```
POST https://dis.kofia.or.kr/proframeWeb/XMLSERVICES/
Content-Type: text/xml; charset=UTF-8
Referer: https://dis.kofia.or.kr/websquare/index.jsp
```

```xml
<message>
  <proframeHeader>
    <pfmAppName>FS-DIS2</pfmAppName>
    <pfmSvcName>{서비스명}</pfmSvcName>
    <pfmFnName>{함수명}</pfmFnName>
  </proframeHeader>
  <systemHeader></systemHeader>
  <{DTO명}> ... </{DTO명}>
</message>
```

- `pfmAppName`은 네 서비스 모두 `FS-DIS2`
- 서비스마다 바뀌는 것은 `pfmSvcName`·`pfmFnName`·DTO뿐

### 공시 목록 — `DISFundFTimeAnnSO.selectAnn`

DTO: `DISFTimeAnnInsDTO`

| 파라미터 | 값 | 설명 |
|---|---|---|
| `uGb` | `1` | 전체(정기+수시). `2`·`3`은 0건 반환 |
| `vStrtDt` / `vEndDt` | `YYYYMMDD` | 한 번에 1년 미만. 서버가 강제하며, 넘기면 오류가 아니라 0행 |
| `uCdList` | 빈 값 | 펀드 지정. 비우면 전체 |
| `gbOption` | `S` | `S`=펀드선택 / `N`·`F`=펀드명 |
| `uRptList` / `tsCd` | 빈 값 | 보고서 유형 |
| `uRptAllYN` | `1` | `tsCd`가 비면 반드시 `1`. `0`이면 오류 없이 0건 |
| `companyCd` | 빈 값 | 운용사 지정. 비우면 전체 |

- 응답 행 요소: `<list>`. 그리드 칼럼 20개
- 사용 필드: `standardDt` `uFundNm` `koreanNm` `standardCd` `companyCd` `tsCd` `txCd` `txVsn` `announceTtl` `seq` `tmpV1` `uRptGb` `Status_GB`
- 페이징 없음. 3일치 조회에 `dbio_total_count_` 1,499와 `<list>` 1,499행이 일치
- 수시/정기 판별: `uRptGb`가 `O`(수시) / `R`(정기). `tsCd` 접두 `2OF` / `2RF`와 100% 일치. 응답만 보고 수시를 거르는 유일한 수단
- 클래스 행: `uFundNm`이 `└▶`로 시작
- `tmpV1`: 수시공시에서는 모펀드 코드, 정기공시에서는 자기 코드. `ZZZZZZ…`는 결측이 아니라 수시 모펀드 행 표시자
- 문서 자연키 `(companyCd, standardDt, announceTtl, tmpV1)`와 수시공시 한정 규칙은 [데이터 테이블·ERD 설계](data-model.md) 「문서와 소스별 키」
- 증분 축: `standardDt`. 룩백 일수는 [원본 보관과 수집·파싱 실패 처리 규칙](storage-and-failure-rules.md) 「재시도와 워터마크」

### 조회 창 실측 (09-20)

호출 7회로 확인.

| 요청 기간 | 결과 |
|---|---|
| 1개월 `20260815~20260915` | 6,845행 (5.7MB) |
| 6개월 `20260315~20260915` | 125,069행 (104MB) |
| 11개월 `20251015~20260915` | 225,177행 (186MB) |
| 정확히 1년 `20250915~20260915` | 0행 (657바이트) |
| 1년+1일 / 1년+1개월 | 0행 |
| 2년 전 3일치 `20240813~20240815` | 2,044행 |

- 제약은 한 번에 조회하는 기간 폭이며 소급 한계가 아님. 2년 전 구간도 그대로 반환
- 백필은 언제든 가능. 1년 미만 창으로 나누면 됨. 경계는 1년 미만이고 정확히 1년부터 0행
- 초과 요청은 오류 없이 실패함: HTTP 200, `</root>` 정상, 657~754바이트 빈 응답, 오류 메시지 없음
- `uRptAllYN` 사례와 같은 형태. 넓은 창으로 돌면 「그 기간엔 공시가 없었다」로 잘못 읽힘 → 창 폭 검증을 코드에 넣어야 함
- 응답 크기(6개월 104MB, 11개월 186MB) 때문에 1개월 단위 분할 권고

### 첨부 목록 — `DISFtimeDetSO.select`

- DTO: `DISFtimeDetOutputListDTO`
- 파라미터: 공시 목록 응답 행의 `companyCd` `standardDt` `standardCd` `txCd` `txVsn` `seq`를 그대로 사용. `uGb`는 `F` 고정
- 응답: `<file>` 노드 안에 `<list>` 행. 필드는 `fileNm`(서버 저장명) · `serverPath` · `originalFileNm`(사람이 보는 한글 파일명)
- 주의: `txVsn=0`으로 보내면 서버가 SQL 예외 반환. 목록 응답의 값을 그대로 사용

다운로드:

```
GET https://disdown.kofia.or.kr/COMFSFileDownload.jsp
    ?serverPath={serverPath}&serverFileNm={fileNm}&filename={originalFileNm}
Referer: https://dis.kofia.or.kr/
```

- 쿼리값 셋을 각각 URL 인코딩(`quote(safe="")`). `originalFileNm`이 한글이라 인코딩 없이 붙이면 실패
- `fileNm`은 서버 저장명이라 내려받기 전에 같은 파일을 가릴 수 있음. 중복 판정 규칙은 [원본 보관과 수집·파싱 실패 처리 규칙](storage-and-failure-rules.md) 「금투협 클래스 행 중복 제거」

### 판매회사 마스터 — `DISMngCompInqSO.select`

- DTO: `DISMngCompInqListDTO`. `option=S2`, `standardDt={YYYYMM}`
- 응답 행 요소: `<list>`. 사용 필드 `saleCompCd`·`koreanNm`
- 약 200곳 (표본 200행, `saleCompCd` 200종, 전부 6자리)

### 판매사별 펀드 — `DISSalesCompFeeCmsSO.select`

- DTO: `DISCondFuncDTO`. `tmpV11`=판매사코드, `tmpV30`=기준일(`YYYYMMDD`), 나머지(`tmpV12`·`tmpV3`·`tmpV5`·`tmpV4`)는 빈 값
- 응답 행 요소가 `<list>`가 아니라 `<selectMeta>`. 금투협의 다른 서비스와 다름
- 필드: `tmpV17`=표준코드, `tmpV18`=운용사코드, `tmpV2`=펀드명, `tmpV4`=설정일, `tmpV16`=기준일
- ETF 행: 은행 채널(신한은행·국민은행)에서는 「상장지수」 0건, 증권사 채널(삼성증권)에서는 4,437건 중 6건 (09-22 정정). [조인 키 확인 기록](records/phase1-erd/join-key-checks.md) 「판매회사 명단 소스」
- 전체 순회: 200곳 × 평균 3,000건 ≈ 60만 행. 호출 간격 1초(「공통 수집 규칙」)

## 공공데이터포털 펀드상품기본정보

```
GET https://apis.data.go.kr/1160100/service/GetFundProductInfoService/getStandardCodeInfo
    ?serviceKey={키}&numOfRows=1000&pageNo={n}&resultType=json
```

| 항목 | 내용 |
|---|---|
| 인증 | `DATA_GO_KR_API_KEY`. 디코딩된 원문 키를 쿼리 인코더로 한 번만 URL 인코딩. 이미 인코딩된 키를 다시 인코딩하지 않음 |
| 페이징 | `numOfRows` 최대 1,000. `response.body.totalCount`까지 `pageNo` 증가. 184페이지 |
| 응답 | `response.body.items.item`. 1건일 때 배열이 아니라 객체로 옴 → 리스트로 감싸야 함 |
| 사용 필드 | `srtnCd`(단축코드 5자리) `asoStdCd`(표준코드) `fndNm` `setpDt` `fndTp` `prdClsfCd`(상품 표 `product_class_code`) |
| 실측 | 183,649건(2026-09-19). 펀드 1개당 1행, 클래스와 사모 포함 |
| `srtnCd` 성질 | 형식 `[A-Z0-9]{5}` 전건 일치. `srtnCd == asoStdCd[6:11]` 성립. 전역 유일이 아님(겹침 규모는 [조인 키 확인 기록](records/phase1-erd/join-key-checks.md) 「srtnCd 비유일」, 재측정하면 달라짐) |
| `setpDt` 주의점 | 결측 0.00%. `11111111` 더미 5건, 연도 범위 1111~2026. 설정일이며 판매개시일이 아님 |

증분 (09-20 실측): `beginBasDt`와 `basDt`가 둘 다 동작하며 의미가 다름.

| 요청 | `totalCount` |
|---|---|
| 파라미터 없음 (전건) | 183,649 |
| `beginBasDt=20260901` | 2,354 (그 날짜 이후 전체) |
| `basDt=20260901` | 376 (그 하루) |

- 증분 수집에는 `beginBasDt` 사용
- `setpDt`는 과거 날짜라 워터마크로 쓰지 않음

## KRX

```
GET https://data-dbg.krx.co.kr/svc/apis/etp/etf_bydd_trd?basDd={YYYYMMDD}
Header: AUTH_KEY: {키}
```

- 인증: `KRX_API_KEY`. 발급과 승인이 별개. 키를 받아도 서비스별 이용 승인을 따로 받아야 함 (`etf_bydd_trd` 승인 09-19)

| 응답 | 뜻 |
|---|---|
| `{"respMsg":"Unauthorized Key"}` | 키가 없거나 틀림 |
| `{"respMsg":"Unauthorized API Call"}` | 키는 맞으나 해당 서비스 승인이 없음 |

- 두 메시지를 구분해야 키 문제인지 승인 문제인지 알 수 있음
- 응답 구조 (09-20 실측): 루트 키 `OutBlock_1` 하나, 값이 행 배열
- 행 필드 19개: `BAS_DD` `ISU_CD` `ISU_NM` `TDD_CLSPRC` `CMPPREVDD_PRC` `FLUC_RT` `NAV` `TDD_OPNPRC` `TDD_HGPRC` `TDD_LWPRC` `ACC_TRDVOL` `ACC_TRDVAL` `MKTCAP` `INVSTASST_NETASST_TOTAMT` `LIST_SHRS` `IDX_IND_NM` `OBJ_STKPRC_IDX` `CMPPREVDD_IDX` `FLUC_RT_IDX`
- 사용 필드: `ISU_CD`·`ISU_NM`. `NAV`·`MKTCAP`·`LIST_SHRS`는 규모 지표로 사용 가능
- `ISU_NM`은 정식 펀드명이 아니라 상장 약명 (`1Q 200액티브` vs `하나1Q200액티브증권상장지수투자신탁[주식]`). 공공데이터포털과 완전일치율 0.0%, 포함매칭 최대치 80.4% ([금투협 중복 행·ETF 이름 규칙 검증](records/phase1-erd/kofia-rows-and-etf-rule.md) 「이름 공간 차이」)
- 실측: 1,167건(2026-09-04 기준일)
- 증분 축: `basDd` 일자 단위 조회. 매일 전건 스냅숏
- 우회로 없음: `data.krx.co.kr`의 비공식 `getJsonData.cmd`는 세션을 요구해 `LOGOUT`만 반환

소급 범위 (09-20 실측): 최소 10년.

| 기준일 | ETF 종목 수 |
|---|---|
| 2016-09-02 | 226 |
| 2021-09-02 | 502 |
| 2024-09-02 | 881 |
| 2025-12-01 | 1,048 |
| 2026-06-01 | 1,130 |
| 2026-09-04 | 1,167 |

- 과거 일자를 그대로 주므로 일별 스냅숏은 나중에 몰아 받아도 됨
- 상장폐지 후보 차집합도 과거 구간에서 생성 가능. 확정에는 거래일·응답 완전성·공식 상장폐지 근거 확인 필요
- 적재 주기·보관 범위 결정을 서두를 이유 없음

## DART

### 공개 뷰어 (인증 불필요, 실호출 확인)

```
GET https://dart.fss.or.kr/dsaf001/main.do?rcpNo={접수번호}
```

- 좌측 문서 트리를 만드는 인라인 `<script>` 안에 노드 배열이 서버 렌더링됨. AJAX 아님
- `node1['dcmNo'] = "…"` 형태로 한 줄에 하나씩 들어 있어 정규식으로 추출. 필요한 값은 `dcmNo`·`eleId`·`offset`·`length`·`dtd`
- 트리 JS가 `var node1 = {}`을 노드마다 재사용 → 변수명으로 정규식을 걸면 마지막 노드 하나만 잡힘. 블록 단위로 끊어 읽어야 함
- 추출 절차 원문과 10건 실측: [09-14 초기 소스 확인](records/phase1-erd/initial-source-checks.md) 「DART 표지 10건 실측」

```
GET https://dart.fss.or.kr/report/viewer.do
    ?rcpNo=&dcmNo=&eleId=&offset=&length=&dtd=dart4.xsd
```

- 표지 노드를 `eleId` 번호로 찾지 않음. 원본은 `eleId=1`, [기재정정]은 정정신고 노드가 앞에 붙어 `eleId=2`가 표지. 고정 번호로 읽으면 원본과 정정본 중 하나는 반드시 틀림 → 노드 텍스트 「투 자 설 명 서」로 찾음
- 위험등급은 표지 노드 안 `「n등급[문구]」` 표기. 띄어쓰기 변형 있음
- ETF 여부는 표지 「집합투자기구 명칭」의 「상장지수」로 후보 선별 가능(표본 ETF 3건 전부). 판정은 KRX 대조가 1차([상품·법인 매칭 규칙](matching-rules.md) 「ETF 판정」)
- 판매회사 명단은 표지에 없음(10/10). 판매사는 금투협 판매사별 펀드에서 받음
- `viewer.do` 호출에는 `Referer`로 `main.do?rcpNo=...` URL을 붙여 보냄. Referer 없이 호출해 비교한 적은 없음 → 필요 여부 미확인(「미결」)

### 본문 PDF

- 「[ 본 문 ]」 요소는 PDF 링크 한 줄(10건 전부). 실제 본문은 별도 다운로드

```
GET https://dart.fss.or.kr/report/download.do?dcmNo={dcmNo}&flNm={파일명}
```

- 실측: HTTP 200 · `application/pdf` · 718,944바이트
- 수집 성공 판정은 MIME과 실제 형식을 함께 확인. 오류 HTML을 PDF로 저장하지 않음([원본 보관과 수집·파싱 실패 처리 규칙](storage-and-failure-rules.md) 「수집 실패」)
- DART가 절(`eleId`) 단위로 주는 것은 표지와 변경요약뿐이며 본문은 PDF 파일 하나
- 부·절 분할 방법(요약): `pdftotext -layout`으로 텍스트 추출 → 문서 앞 목차에서 부별 절 제목을 읽음 → 본문에서 그 제목을 찾아 경계로 사용. 제1~5부가 오름차순으로 한 번 나오면 목차, 다시 나오면 본문
- 외부 의존성: `pdftotext`(poppler). 인증키 불필요
- 분할 실측과 주의할 점: [DART 본문 PDF 부·절 분할 실현성 검증](records/phase1-erd/dart-section-split.md)
- 간이투자설명서는 별도 문서가 아니라 투자설명서 PDF 안의 「요약 정보」 절로 들어 있음

### 목록

- 목록 진입점 `https://dart.fss.or.kr/dsac001/mainF.do`는 서버 렌더링 HTML 표라 바로 파싱됨
- 목록을 API로 받는 경로(`pblntf_detail_ty` G001~G003 필터)의 엔드포인트·파라미터는 저장소에 없음. 필터 값만 기록됨(「미결」)

### OPEN DART API (미호출)

```
GET https://opendart.fss.or.kr/api/document.xml?crtfc_key={키}&rcept_no={접수번호}
```

- 인자 둘, 응답은 zip
- 가이드 페이지만 인증키 없이 읽었고 실제 호출은 하지 않음
- zip 안에 XML만 있는지, PDF 등 첨부까지 들어 있는지 가이드에 명시 없음. 추정으로 설계하지 않음(「미결」)
- 증분 축: `rcept_dt`. 룩백 일수와 그 이유(정정본)는 [원본 보관과 수집·파싱 실패 처리 규칙](storage-and-failure-rules.md) 「재시도와 워터마크」

## 금감원 검사결과제재·경영유의사항

- 두 API는 공개 명세의 요청 변수·결과 필드가 같음
- 공개 샘플의 `examMgmtNo`도 같지만 내부 저장 테이블이나 레코드 동일성은 확인되지 않음 → 소스 이름공간과 원천 키를 각각 보존

```
GET https://www.fss.or.kr/fss/kr/openApi/api/openInfo.jsp        # 검사결과제재
GET https://www.fss.or.kr/fss/kr/openApi/api/openInfoImpr.jsp    # 경영유의사항 등
    ?apiType={xml|json}&startDate=YYYY-MM-DD&endDate=YYYY-MM-DD&authKey={32자리}
```

- 요청 변수는 넷뿐. 금융회사·업종·페이지 변수 없음
- 결과 필드 13개: `emOpenNo`(제재정보번호) `examMgmtNo`(검사관리번호) `transCode` `emOpenSeq` `actGbn` `finInstName`(금융회사) `actReqDate`(제재조치일) `actOrganCon` `actOfficerCon` `actEmpCon` `actObjContent`(제재대상사실) `inputDate` `inputMan`
- 필드별 뜻과 샘플 대조: [조인 키 확인 기록](records/phase1-erd/join-key-checks.md) 「제재공시」

| 주의점 | 내용 |
|---|---|
| JSON 루트 키가 `reponse` | `response`로 짜면 전건 0으로 오류 없이 실패. 실호출로 확정(09-21) |
| 페이징 없음 | 5,700여 건 백필은 기간 분할로만 가능 |
| `emOpenSeq`는 워터마크가 아님 | 검사 1건 안의 순번이며 요청 변수에도 없음. 증분은 날짜로만 |
| 날짜 형식 | 요청 `YYYY-MM-DD` / `actReqDate` `2026.9.17.`(월·일 앞자리 0 생략, 끝에 점) / `inputDate` `2026-09-17 13:30:31.0` |
| `result` 단건 시 객체 가능성 | 공공데이터포털과 같은 형태를 예상해 스크립트가 방어함. 실제 단건 응답으로는 미검증(받은 것은 0건과 8건뿐) |
| 기간 분할 폭 | 개인 키는 한 호출 최대 1개월. 넘기면 `resultCode=030`(「최대 조회기간 초과(개인 : 1개월)」). 스크립트는 `CHUNK_DAYS=28`. 옛 값 90일은 틀림(09-21 정정). 법인 키 상한 미확인 |
| 응답 인코딩 `euc-kr` | `Content-Type: text/html;charset=euc-kr`. `utf-8`로 디코드하면 `resultMsg`·`finInstName`·`actObjContent` 등 한글 필드가 치환문자로 깨짐. 스크립트 수정 완료 |
| `resultCode` 네 갈래 | `1`=정상(0건 포함 가능) / `900`=그 구간 자료 없음(정상) / `030`=조회기간 상한 초과 / `033`=일일 조회 건수 초과. `1` 외 전부 예외로 던지던 스크립트 수정 완료 |
| 일일 조회 건수 30회 | `resultCode=033`, 메시지 「하루 조회 건수를 초과하였습니다. 하루 조회 건수는 30회 입니다.」. `sanction`·`impr` 두 엔드포인트가 같은 키의 한도를 공유(양쪽에서 실측). 초기화 시점 미확인(달력일 자정 추정) |
| 상품 칸 없음 | 13개 필드에 상품 식별자가 없고, 본문 `actObjContent`도 `㉮펀드`·`甲`·`A지점`으로 마스킹. 상품 매칭을 시도하지 않음([상품·법인 매칭 규칙](matching-rules.md) 「제재공시 법인 매칭」) |

인증키:

- 32자리. 개인 신청과 법인 신청의 경로가 다름
- 법인 키에만 요청 IP 등록이 붙음 → 수집 서버 IP가 정해지기 전에 법인 키를 신청하면 재신청 필요
- 09-21 개인 키 발급. 1개월 상한은 개인 키 등급의 값이며 법인 키를 받으면 재확인 필요

실호출 기록:

| 날짜 | 호출 | 결과 |
|---|---|---|
| 09-21 | 최근 24개월 월 단위 조회 | 2026-09만 `resultCnt=8`, 그 외 월은 `900`. 탐색 호출이 일일 한도 30회를 다 써 2024-10 이전 구간은 `033`으로 중단. 그 달들에 자료가 없다는 뜻이 아님 |
| 09-22 | `--from 2026-09-01 --to 2026-09-30` 1회(내부 28일 + 2일 두 구간) | 8건 전량 수신. 표본 [`fss_sanctions_sample.csv`](../research/samples/fss_sanctions_sample.csv). 값 표기·결측·이상값은 [소스별 데이터 현황표](records/phase1-erd/source-profile.md) |

날짜 필터 대상 (09-22 확인):

- `startDate`/`endDate`는 `inputDate`(공시 입력일시)에 걸리며 `actReqDate`(제재조치일)가 아님
- 근거: 09월 조회 8건 중 1건(토스뱅크)의 `actReqDate`가 2026.8.25(구간 밖), `inputDate`가 2026-09-03(구간 안)
- 표본 1건 근거이므로 다른 달 표본으로 재검증 필요(「미결」)

## 금감원 분쟁조정결정례

- API 없음. 게시판 `B0000390`
- 게시글 본문이 비어 있고 HWP 첨부만 제공. 한 글에 첨부 1~3건(사건 814 / 첨부 845)
- HWP 5.0 추출: OLE 복합문서에서 `BodyText/Section0`을 zlib raw deflate(`-15`)로 풀고 `HWPTAG_PARA_TEXT`(태그 67) 레코드에서 UTF-16LE 텍스트 추출
- [`hwp_text.py`](../research/scripts/hwp_text.py) + [`_ole.py`](../research/scripts/_ole.py)가 외부 의존성 없이 처리
- 버전 판별: OLE 시그니처 `D0CF11E0…`. 없으면 HWP 5.0이 아님
- `PrvText`: 압축 없는 UTF-16LE 평문. 본문을 읽지 못할 때의 대체 경로

| 한계 | 내용 |
|---|---|
| HWP 3.0 추출 불가 | OLE가 아닌 자체 바이너리. 첨부 213단위 중 94건(1999~2004년) |
| 「상위 버전 배포용 문서」 | `BodyText`가 안내문뿐. `--preview`로 `PrvText`(약 1,000자)를 얻는 것이 최선 |

- 조인 불가: 상품명·판매사명·운용사명 모두 마스킹(`●●증권`, `▣▣자산운용`). 업종만 남음([조인 키 확인 기록](records/phase1-erd/join-key-checks.md) 「분쟁조정 마스킹」)
- 재현 확인(09-20): `nttId=219340` 첨부에서 `【 ○○○ : ●●증권 】` 마스킹까지 재현
- 증분 축: 게시판 ID + 게시글 번호

## 국가법령정보

- `LAW_API_OC` 비어 있음. 미호출
- 무인증 호출이 `{"result":{"err_cd":"010","err_msg":"미등록 인증키","total_count":"0"}}`를 반환한다는 기록 있음
- 기록의 출처는 팀 Notion 조사(「[Study] 데이터 소스 6종」)이며 이 저장소의 실측이 아님. 엔드포인트도 남아 있지 않아 현재 재현 불가
- 연결 방식은 키를 받아도 정해지지 않음. 먼저 정할 것 둘
  - 금소법 19조의 「설명서」와 수집 대상 「투자설명서」는 같은 서류가 아님. 대응 관계 미정의
  - 09-23 사전 안건은 고지 충실도를 점수로 추진. 배점·분모·적용 상품군·근거 절은 미결([점수 저장과 비교 모집단](scoring-and-population.md) 「CDI와 고지 충실도」)
- 증분 축: `MST` 변경 여부 미확인이라 조문 내용 해시 후보. 원천 계약 확인 전 미정

## finlife

- 오픈 API 8종: 금융회사개요·정기예금·적금·연금저축·주택담보대출·전세자금대출·개인신용대출·개인사업자대출
- 펀드·ETF·ELS 없음. 화면의 「펀드」 메뉴는 금투협 전자공시로 리다이렉트
- 펀드 조인 키로 성립하지 않음. 소스 존치 여부 미결
- `fin_prdt_cd`가 8종 공통 응답 필드라는 것은 공식 원문으로 확인하지 못함. 예제 응답에서는 `fin_co_no`(금융회사코드)만 확인
- 근거: [09-14 초기 소스 확인](records/phase1-erd/initial-source-checks.md) 「finlife 범위와 펀드코드 체계」

## 공통 수집 규칙

### 방어적 수집

- 호출 간격 1초 이상, 동시 요청 1개
- 전체 순회가 60만 행 규모인 금투협 판매사별 펀드에 특히 적용

### 조사 스크립트 재시도

- 스크립트 공통: 3회, 대기 2초·4초. 네트워크 오류와 파싱 오류를 함께 받음
- 생산 수집기의 재시도 계약(타임아웃·5xx 최대 5회)은 [원본 보관과 수집·파싱 실패 처리 규칙](storage-and-failure-rules.md) 「재시도와 워터마크」. 3회는 조사 스크립트 값

### 응답 완전성 검증

| 소스 | 검증 수단 |
|---|---|
| 금투협 | 응답이 `</root>`로 끝나는지. 끝나지 않으면 절단 |
| 공공데이터포털 | `totalCount`와 누적 건수 대조 |
| 금감원 OPEN API | `1`·`900`은 정상. `030`(기간 상한 초과)·`033`(일일 30회 초과)은 재시도해도 풀리지 않으므로 즉시 중단하고 `resultMsg` 기록 |
| KRX | `respCode` 키가 있으면 오류 응답 |

- 절단을 잡지 못하면 파서가 행을 오류 없이 적게 셈. 발견이 가장 늦은 실패

### 인증키

- `.env`에만 둠. 커밋 금지(`.gitignore`). `.env.example`에는 이름만

| 이름 | 소스 | 상태 |
|---|---|---|
| `DATA_GO_KR_API_KEY` | 공공데이터포털 | 있음 |
| `KRX_API_KEY` | KRX | 있음 (서비스 승인 완료) |
| `OPENDART_API_KEY` | OPEN DART | 비어 있음(09-20 확인). 데이터 테이블·ERD 설계 확정 점검 「접근 권한 4종 중 3종」의 3종째 |
| `FINLIFE_API_KEY` | finlife | 소스 존치 미결 |
| `LAW_API_OC` | 국가법령정보 | 비어 있음 |
| `FSS_API_KEY` | 금감원 제재·경영유의 | 발급됨(09-21, 개인용). 일일 조회 30회 한도로 하루 계획 호출 수 관리 필요 |

## 값 표기와 이상값

상세 실측은 [소스별 데이터 현황표](records/phase1-erd/source-profile.md). 수집·파싱 구현에 바로 걸리는 것만 요약.

| 소스 | 값 표기 | 이상값·주의 |
|---|---|---|
| DART | 위험등급 `2등급[높은 위험]` / `2등급[ 높은 위험 ]` / `2등급[높은 위험 ]` 공백 변형 3종(10건 안). 1~6등급, 1등급이 최고위험. 정규식은 `(\d)등급`까지만 보고 뒤를 버림 | 「[ 본 문 ]」이 PDF 링크 한 줄(10/10). 원래 구조이며 누락 아님 |
| 금투협 수시공시 | `standardCd` 접두 3종 `K55` 887 / `KR5` 603 / `KRM` 9. 한 칸에 두 코드 체계 혼재 → 접두 3자로 분기. PDF 본문 위험등급은 `투자 위험등급 N등급[명칭]`. 상품명은 `…자투자신탁 1(채권혼합)`처럼 공백 + 숫자 호수 | `tmpV1`의 `ZZZZZZ…` 33건은 모펀드 행 표시자. `urllib` 수신 시 1,499행 → 43행 절단 |
| 금감원 제재 | `actReqDate` `YYYY.M.D.`, `inputDate` `YYYY-MM-DD HH:MM:SS.f`. `finInstName`은 법인격 없는 약칭(`교통은행`) 또는 전치·후치 혼재(`㈜비엔케이투자증권`·`다올투자증권㈜`) | 본문에 `u2018`·`u2019` 35회, `u2027` 3회, `u2020` 4회, `u203B` 1회가 문자가 아닌 글자 그대로 들어 있음. 줄바꿈 자리에 글자 `n` 202회. 치환 규칙 필요. `㉮`는 펀드 전용이 아닌 범용 상품 마스킹 기호(`㉮보험`) |
| 분쟁조정 | 서술형. 정형 값 없음. 마스킹 기호 4종 `●` `○` `▣` `▤` | HWP 3.0 94건, 배포용 7건, BMP 내장 4건(`PrvText`로 약 1,022자 부분 복구) |
| KRX | `ISU_NM` 상장 약명. 브랜드 개명(ACE ← 구 KINDEX), `(합성)`·`(합성 H)` 표기 차이 | 공공데이터포털 정식명과 완전일치 0.0% |
| 공공데이터포털 | `srtnCd` `[A-Z0-9]{5}` | `setpDt` 더미 `11111111` 5건 |

## 미결

| 질문 | 결정 필요 주체 | 필요 시점 |
|---|---|---|
| OPEN DART `document.xml` zip 안에 XML만 있는가, PDF 등 첨부까지 있는가 | 주영 (OPEN DART 키 발급 후 접수번호 1건 호출) | DART 수집기 구현 전 |
| DART 목록 API 엔드포인트·파라미터(`pblntf_detail_ty` G001~G003 필터) | [담당 미정] (OPEN DART 가이드에서 목록 API 확인) | DART 수집기 구현 전 |
| DART `viewer.do`에 Referer가 꼭 필요한가 (명세는 「필요」, 실측은 Referer 붙여서만 호출) | 주영 (Referer 없이 1회 호출) | DART 수집기 구현 전 |
| 금감원 제재 증분 필터가 `inputDate`라는 판정이 다른 달에도 성립하는가 (근거 1건) | 대현 (다른 달 표본으로 재확인) | 제재 수집기 구현 전 |
| 경영유의사항(`impr`) 본문의 실제 마스킹 수준 (공개 샘플이 제재와 같은 예시 텍스트) | 대현 (`--kind impr`로 2026-09 구간 호출) | 경영유의사항 API 채택 결정 전 |
| 경영유의사항 API를 소스로 채택하는가 (09-20 안건, 결과 기록 없음) | 팀 (09-20 회의록 확인) | 09-30 2단계 설계 확정 전 |
| `emOpenNo`가 제재·경영유의에 걸쳐 유일한가 (저장 표본에서는 8/8 공백) | 대현 (같은 기간을 양쪽에서 받아 교집합 확인) | 제재 문서 키 확정 전 |
| 금감원 `result` 단건 응답 형태와 한 응답의 건수 상한 | 대현 (다음 조회 가능일 실호출) | 제재 수집기 구현 전 |
| 금감원 법인 키의 1회 조회기간 상한과 일일 한도 초기화 시점 | [담당 미정] (법인 키 발급 후 확인) | 법인 키 신청 시 |
| 국가법령정보 연결 방식 (조인인가 텍스트 참조인가, 금소법 「설명서」와 투자설명서의 대응) | 팀 (미팅 안건. 키로 해결되지 않음) | 3단계 입출력 Schema 설계(10-14) 전 |
| finlife를 소스에서 빼는가, 금융회사 마스터(`fin_co_no`)·연금저축펀드 용도로 남기는가 (09-16 안건, 결과 기록 없음) | 팀 (09-16 회의록 확인) | 09-30 2단계 설계 확정 전 |
| finlife `fin_prdt_cd`가 8종 공통 필드인가 | [담당 미정] (존치로 결정되면 명세 확인) | finlife 존치 결정 후 |

## 참고

- 실측 근거: [09-14 초기 소스 확인](records/phase1-erd/initial-source-checks.md), [금투협 중복 행·ETF 이름 규칙 검증](records/phase1-erd/kofia-rows-and-etf-rule.md), [조인 키 확인 기록](records/phase1-erd/join-key-checks.md), [DART 본문 PDF 부·절 분할 실현성 검증](records/phase1-erd/dart-section-split.md), [소스별 데이터 현황표](records/phase1-erd/source-profile.md)
- 스크립트와 표본: [원천 데이터 검증 스크립트와 표본](../research/README.md)
- 사실 유형별 소유 문서: [설계 문서 안내](README.md) 「문서 소유 규칙」
- 대체된 판단: 「1년 지나면 금투협 공시를 영구히 받을 수 없음」 → 창 폭 제약(09-20), 「KRX는 오늘 안 받으면 재구성 불가」 → 최소 10년 소급(09-20), 「금감원 분할 90일」 → 1개월(09-21), 「판매사별 펀드에서 ETF 0건 = 구조적 불가」 → 은행 채널 한정(09-22), 「DART 수집 실패 판정 = `Content-Type != application/pdf`」 → MIME + 실제 형식 확인(09-22)
