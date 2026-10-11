# 데이터 처리 요구 명세

데이터 엔지니어링·인프라(주영)가 만들어 넘기는 것과 데이터 사이언스(다빈)가 받아 쓰는 것의 모양. 칼럼·enum·경로의 정본은 [데이터 테이블·ERD 설계](data-model.md), [스키마 명세](schema-catalog.md), [DBML](schema.dbml), [원본 보관과 수집·파싱 실패 처리 규칙](storage-and-failure-rules.md)이며 이 문서는 그중 넘김에 쓰는 부분만 모으고 새로 정하는 것을 적는다.

## 상태

| 항목 | 내용 |
|---|---|
| 상태 | 초안. PM(대현) 승인(10월 7일), 데이터 사이언스(다빈) 리뷰 의견 반영 후 승인 대기(10월 10일 의견) |
| 작성일 | 10월 7일 |
| 담당 | 정 데이터 사이언스(다빈) / 부 데이터 엔지니어링·인프라(주영). 초안은 주영, 승인은 다빈 |
| 근거 | Notion 티켓 「데이터 사이언스가 사용할 데이터 포맷 결정 (데이터 처리 요구 명세)」(10월 4일 변경 포함), 이슈 #48 |
| 기준 판 | ERD v2.2(PR #43, 10월 6일 갱신분). PR #43이 병합되기 전이라 링크한 문서의 현재 dev 판과 다른 곳이 있음. 8절은 PR #43 10월 9일 갱신분과 대조함(10월 11일) |
| 범위 밖 | 채점 결과를 받는 쪽 계약(두 파트 출력)은 [3단계 입출력 Schema 설계 입력](io-schema.md) 「CDI 출력 요구」와 [데이터 테이블·ERD 설계](data-model.md) 「두 파트 출력의 저장 계약」 |

## 1. 범위

- 상품: 펀드(1순위)·ETF(2순위). ELS는 제외(9차 미팅 9월 30일). 상품을 늘리면 이 문서를 별도로 개정
- 문서: DART 투자설명서(정정본 포함) 본문 PDF. 증권신고서·일괄신고서는 본문 PDF가 없어 받지 않음(10월 5일 범위 변경, 이슈 #45)
- 간이투자설명서: 10월에는 DART 투자설명서 안의 「요약정보」 구간을 간이 대표로 씀(3절). 금투협 별도 간이 PDF는 펀드별로 받는 수집 경로가 없어 검증용으로만 둠
- 점수 단위: 문서 1건당 1개. 절은 고칠 곳 위치 표시와 작성기준 항목 점검(부·절 제목·순서)에 씀(10월 4일 변경)

## 2. 넘기는 파일

데이터 사이언스(다빈)는 DB를 직접 조회하지 않고 채점 실행마다 만들어지는 파일 두 개를 읽는다. 데이터 소스 간 조인은 데이터 엔지니어링·인프라(주영)가 끝내서 넘긴다(5차 미팅 9월 9일 「데이터소스 간 Join을 해서 DS에게 제공」).

| 파일 | 한 행 | 담는 것 |
|---|---|---|
| `runs/{score_run_id}/documents.parquet` | fund_key × 역할(투자설명서 / 간이) | 채점에 쓸 대표 문서의 텍스트·구조·위험등급·작성기준일 |
| `runs/{score_run_id}/excluded.parquet` | 제외된 펀드 또는 상품 1개 | 비교 집단에서 뺀 대상과 사유(6절) |

- 경로는 RAW_ROOT 기준 상대경로. `runs/{run_id}/`는 실행 완료 뒤 불변(저장 규칙 「실행 폴더 불변」)
- 입력 파일(`inputs.json`, `selection.json`, `documents.parquet`, `excluded.parquet`)은 실행 시작 때 한 번 쓰고 이후 바꾸지 않음. 실패한 채점 실행을 다시 돌릴 때는 새 `score_run_id`를 발급(PR #43 저장 규칙 「실행 폴더 불변」과 같은 규칙)
- `documents.parquet`·`excluded.parquet`는 채점 입력이라 `runs/{score_run_id}/`에 둠. `exports/`에는 사본을 두지 않음(10월 7일 PM(대현) 리뷰. PR #43 저장 규칙 「`exports/`」와 같음)
- 두 파일 모두 SCORE 실행의 입력 manifest(`runs/{score_run_id}/inputs.json`)에 경로와 sha256을 기록
- 더 자세한 원자료가 필요하면 각 행의 `canonical_text_path`, `structure_manifest_path`로 파생 파일(`derived/{원본 sha256}/{파서 버전}/text.txt`, `structure.json`)을 직접 읽을 수 있음

### documents.parquet 칼럼

| 칼럼 | 자료형 | 예시 값 | 출처·설명 |
|---|---|---|---|
| score_run_id | string | `score-20261014T010000Z-a1b2` | pipeline_run.run_id(SCORE). 형식은 크롤러의 `extract-…`와 같은 규칙 제안 |
| baseline_date | date | `2026-10-14` | pipeline_run.baseline_date. 대표 문서는 이 날짜 이하의 문서에서 고름 |
| fund_key | string | (발급 규칙 확정 전) | fund_group.fund_key. 회귀·층내 백분위의 관측 단위(7차 미팅 결정 ②) |
| fund_name | string | `NH-Amundi성장주도코리아50증권투자신탁[채권혼합]` | fund_group.canonical_name |
| product_category | string | `펀드` | product.product_category(`펀드`/`ETF`). 펀드에 속한 클래스가 서로 다르면 제외(6절) |
| role | string | `PROSPECTUS` | `PROSPECTUS`(투자설명서 대표) / `SIMPLE`(간이 대표). selection manifest의 역할 |
| document_id | int64 | `1024` | document.document_id |
| rcept_no | string | `20260916000065` | document.rcept_no(DART 접수번호 14자리) |
| report_name | string | `[기재정정]투자설명서(집합투자증권)(베어링독일성장펀드)` | document.report_name |
| is_correction | bool | `true` | document.is_correction |
| report_base_date | date | `2026-08-24` | document.report_base_date(문서 작성기준일). 못 읽으면 NULL |
| report_base_date_status | string | `OK` | `OK` / `UNREADABLE`(5절). 이 문서에서 추가, 10월 10일 데이터 사이언스(다빈) 확정 |
| standard_version | string | (작성기준 판 목록 확정 전) | 작성기준일 이전에 시행된 가장 최근 작성기준 판의 자산 파일 이름(4-4) |
| raw_object_id | int64 | `5001` | raw_object.raw_object_id(본문 PDF) |
| raw_sha256 | string | 64자 16진수 | raw_object.sha256 |
| parser_version | string | `pdfplumber-0.11_prep-4` | file_extraction.parser_version. 형식 `{도구}-{주.부}_prep-{n}`(PR #43 원본 보관 규칙) |
| text | string | (문서 전체 텍스트) | `text.txt` 전체. canonical text, UTF-8/LF |
| text_length | int64 | `168659` | file_extraction.text_length(Unicode code point 수) |
| scope_char_start, scope_char_end | int64 | `0`, `168659` | 이 역할이 쓰는 구간. `PROSPECTUS`는 문서 전체, `SIMPLE`은 요약정보 구간 |
| sections | list<struct> | 아래 「sections 원소」 | section 행. 4-2 |
| headings_status | string | `OK` | `OK` / `PARTIAL` / `NOT_FOUND`(5절) |
| table_regions | list<struct{char_start, char_end, has_sentences}> | `[{12034, 13310, true}]` | 표 영역. `has_sentences`는 칸 안에 문장이 있는 표인지. 4-3. `structure.json` 블록에서 옮김(4-6) |
| table_split_status | string | `OK` | `OK` / `FAILED` / `NOT_ATTEMPTED`(5절) |
| page_furniture_regions | list<struct{char_start, char_end}> | `[{0, 18}]` | 쪽 머리글·쪽 번호 구간. 지표 계산에서 뺌(4-2 ④). `structure.json` 블록에서 옮김(4-6) |
| representative_risk_grade | int8 | `2` | fund_group.representative_risk_grade(1~6, 1이 가장 높은 위험). 층 배정 기준 |
| risk_grade_source_kind | string | `SIMPLE_PROSPECTUS_TITLE` | fund_group.risk_grade_source_kind |
| class_grade_mismatch | bool | `false` | 펀드 안 클래스의 위험등급이 대표 등급과 다른지. 제외가 아니라 확인 대상(6절) |
| canonical_text_path | string | `derived/3f…/pdfplumber-0.11_prep-4/text.txt` | file_extraction.canonical_text_path |
| structure_manifest_path | string | `derived/3f…/pdfplumber-0.11_prep-4/structure.json` | file_extraction.structure_manifest_path |

- 행에는 `extract_status`가 `EXTRACT_OK`인 문서만 들어감(7차 미팅 결정 ①). `EXTRACT_OK`가 아닌 투자설명서 대표는 펀드 전체를 `excluded.parquet`로 보냄(6절)
- 간이 대표가 없는 펀드는 `SIMPLE` 행이 없음. 이것은 제외가 아니며 간이 지표만 `SUMMARY_NOT_FOUND`로 판정 불가(5절)
- 위치는 모두 `text`의 0부터 세는 Unicode code point 반열린 구간 `[char_start, char_end)`. UTF-8 바이트나 UTF-16 코드 유닛과 섞지 않음([데이터 테이블·ERD 설계](data-model.md) 「절」)

### sections 원소

| 필드 | 자료형 | 예시 값 | 설명 |
|---|---|---|---|
| section_id | int64 | `88001` | section.section_id. 축 4 근거 위치(B11 안 1, 절 번호 + 글자 범위)가 가리키는 값 |
| section_seq | int32 | `12` | 문서 안 전역 순번 |
| section_kind | string | `body` | `body` / `summary` / `other`(4-2 ⑤) |
| part_seq | int32 | `1` | 원문 부 번호(「제1부」 → 1). 부 체계 밖이면 NULL |
| source_section_no | string | `"2"` | 부 안의 절 번호 원문(「2.」 → `"2"`). 부마다 다시 1부터 시작. 비숫자 번호도 보존(PR #43 ERD varchar) |
| title | string | `2. 집합투자기구의 종류 및 형태` | 원문 제목 그대로 |
| title_char_start, title_char_end | int64 | `20511`, `20530` | 제목 줄 범위. 지표에서 제목을 뺄 때 씀 |
| char_start, char_end | int64 | `20511`, `24890` | 절 범위(제목 포함) |
| extract_status | string | `EXTRACT_OK` | 경계를 못 찾은 절은 `SECTION_BOUNDARY_NOT_FOUND`이고 범위는 NULL |

## 3. 펀드당 대표 문서 두 역할

- 같은 fund_key에서 투자설명서 대표 1건과 간이 대표 0~1건을 따로 고름(10월 4일 PM 확정). 고르는 순서는 [점수 저장과 비교 모집단](scoring-and-population.md) 「기준일과 대표본 선택」 그대로
- 선택 결과·선택 이유·사용한 (raw_object_id, parser_version)은 `runs/{score_run_id}/selection.json`에 기록하고 `documents.parquet`는 그 결과를 펼친 것
- 파트 B·층내 백분위·통계 관측치는 `PROSPECTUS` 행으로만 셈. `SIMPLE` 행은 간이 3-1 점검에만 씀
- 정함(이 문서 제안, 미결 표 「역할 안의 소스 우선순위」「간이 3-1 입력 경로」의 10월 7일 답)
  - 역할 안 소스 우선순위: 10월은 DART만 수집하므로 DART 하나. 금투협 투자설명서·간이 PDF 수집이 생기면 이 표를 다시 정함
  - 간이 입력 경로: DART 투자설명서 안 「요약정보」 구간(`section_kind = summary`). `SIMPLE` 행은 `PROSPECTUS` 행과 같은 문서이고 `scope_char_start/end`로 요약정보 구간만 가리킴. 요약정보 구간을 못 찾으면 `SIMPLE` 행 없음
- 대표본을 고를 수 없으면(날짜 동률, 계보 충돌) 펀드를 `AMBIGUOUS_DOCUMENT`로 제외

## 4. 추출 결과의 모양

### 4-1. 텍스트와 위치

- 텍스트는 파일 전체를 보존한 canonical text(UTF-8, LF). 표·머리글을 지우지 않음. 지표별 제외는 구간 목록으로 함([원본 보관과 수집·파싱 실패 처리 규칙](storage-and-failure-rules.md) 「파생 텍스트·실행 스냅숏 경로」)
- 쪽 위치·글꼴은 `structure.json`에 있고 `documents.parquet`에는 넣지 않음. 쪽 번호가 필요하면 글자 위치로 `structure.json`의 쪽 시작 위치에서 찾음(4-6)

### 4-2. 부·절 제목과 범위

10월 7일 PDF 500건 확인 결과(데이터 엔지니어링·인프라(주영))를 기준으로 정함.

| 확인 | 결과 |
|---|---|
| PDF 책갈피(목차)가 있는 문서 | 500건 중 150건(30%). 생성 도구에 따라 갈림(oz는 모두 있음, MS Word로 만든 문서는 대부분 없음) |
| 책갈피 제목을 본문에서 찾아 글자 범위를 붙인 비율 | 11,945개 중 11,799개(98.8%). 못 찾은 것은 본문에 없는 이름표 「표지」 42개와 문장 조각으로 된 책갈피 |
| 책갈피 없이 제목 규칙으로 찾은 비율(책갈피 150건을 정답으로 채점) | 부 제목 재현율 95.9~100%, 절 제목 재현율 95.8~100%. 정밀도는 부 64~65%, 절 43~77%(굵기 조건 유무에 따라) |
| 책갈피 없는 표본 7건(문서 앞 목차 페이지와 대조) | 7건 모두 「제1부」~「제5부」를 찾음. 목차 페이지가 있는 6건의 절 제목을 굵기 조건 없이 모두 찾음 |

- 제목 찾는 방법: 분할은 모든 문서에서 제목 규칙으로 하고, 책갈피는 검증에만 씀(10월 10일 PM(대현) 결정)
  1. 「제N부」, 부 안의 「N.」로 시작하는 줄을 제목 후보로 뽑음. 번호만 있는 줄은 다음 줄과 이어 붙임. 문서 앞 목차 페이지는 후보에서 뺌
  2. 책갈피가 있는 문서는 규칙으로 찾은 부·절을 책갈피와 대조해 분할 결과를 검증함
  3. 정밀도 보완(쪽 머리글의 「제1부」 반복, 본문 번호 목록 걸러내기)은 절 분할 작업(10월 1일~14일)에서 정하고 실패율과 함께 보고
- 결정 근거(PR #51, 502건): 책갈피가 있는 문서는 149건(30%)뿐임. 규칙 결과가 책갈피와 부 정밀도 96.0%, 절 정밀도 90.3%로 맞음. 위 표의 정밀도(부 64~65%, 절 43~77%)는 10월 7일 측정값
- 절 경계 기준
  - ① 제목 줄은 절 범위에 넣음. 범위는 제목 줄 시작부터 다음 같은 수준 이상 제목 직전까지. 제목만의 범위는 `title_char_start/end`로 따로 둠
  - ② section 행은 부 안의 「N.」 절까지 만듦. 「가.」「(1)」 같은 하위 제목은 `structure.json`의 `subheading` 블록에 제목과 범위만 둠(4-6)
  - ③ 표·각주·별표는 텍스트 순서상 놓인 절에 속함. 여러 쪽에 걸친 표는 시작 위치의 절. 표 범위는 `table_regions`로 따로 표시
  - ④ 쪽 머리글·쪽 번호는 텍스트에서 지우지 않고 `page_furniture_regions`로 표시. 지표 계산에서 뺌
  - ⑤ 부·절 체계 밖 구간: 요약정보는 `summary`, 표지·목차·투자결정시 유의사항은 `other`, 맨 뒤 용어 목록은 제5부 안의 `body`
- `records/phase1-erd/dart-section-split.md`(9월 20일, 9건 표본)의 「PDF에 북마크 없음」은 표본이 작아 생긴 차이. 500건 기준으로는 30%에 책갈피가 있음

### 4-3. 표 영역과 본문 구분

- 쓰는 곳: 전문용어 밀도(2-1)·설명 안 한 비율(2-2)은 표를 포함한 텍스트(`text`)
- 문장 길이(ASL)는 받는 쪽이 `text`에서 아래 구간을 빼고 계산함. 표를 지운 텍스트를 따로 넘기지 않음(10월 7일 PM(대현) 리뷰: 표를 지운 문자열은 글자 위치가 밀려 머리글·제목·절 범위를 함께 뺄 수 없음)
  - `table_regions` 중 `has_sentences = false`인 표. 비교용 ASL은 `table_regions` 전부
  - `page_furniture_regions`
  - `sections`의 `title_char_start`~`title_char_end`
  - 절별 ASL은 위 구간을 뺀 뒤 절 범위(`char_start`~`char_end`)로 자름
- 구간 합치기: 모든 구간은 `text` 기준 반열린 구간 `[char_start, char_end)`. 종류와 관계없이 시작 위치 순으로 정렬하고, 겹치거나 맞닿은 구간을 하나로 합친 뒤 뺌
- 방법(10월 7일 확인): 페이지에서 눈에 보이지 않는 그림 요소를 뺀 뒤 PDF 도구의 표 찾기를 씀(pdfplumber `find_tables`, 기본 설정)
  - 빼는 요소: 흰색으로 채우고 외곽선이 없는 사각형, 흰색 선. 패턴 등 숫자가 아닌 색은 보이는 것으로 봄
  - 찾은 표의 페이지 영역을 그 안에 있는 글자의 범위로 바꿔 `table_regions`에 넣음
  - 생성 도구별 설정은 두지 않음. 변수표의 「숫자 아닌 글자 10% 미만 줄」 규칙은 PDF 구조를 읽지 못한 문서(`structure_status`가 `AVAILABLE`이 아님)용 예비 규칙으로만 남김
- 이 방법을 고른 근거(표본 12건, 생성 도구 6종)
  - 기본 설정 그대로는 iText·oz로 만든 문서에서 본문 문장 영역까지 표로 잡힘(표 안 글자 비율 87~99%). 원인은 문단마다 깔린 흰색 배경 사각형의 가장자리를 표 테두리로 읽은 것
  - 보이지 않는 요소를 빼면 iText 43~57%, oz 60%로 내려가고 다른 생성 도구는 거의 그대로(22~50%)
  - 선만 엄격하게 보는 설정은 MS Word·Adobe 문서의 실제 표를 놓침(표 안 글자 비율 0~4%)이라 쓰지 않음
  - 문장과 표가 섞인 페이지 12쪽(생성 도구마다 1쪽 이상)을 눈으로 대조: 12쪽 모두 표는 표 영역, 본문 문장과 절 제목은 밖. 테두리 있는 안내 상자(「집합투자기구 공시 정보 안내」) 1개가 표로 잡힘
  - 선·사각형이 없는 문장 위주 페이지 30쪽에서 잘못 잡힌 표 0개
  - 500건 전체 실행(10월 7일): 오류 0건, 표가 하나도 없는 문서 0건. 표 안 글자 비율 중앙값은 생성 도구별 40~53%(MS Word 46%, iText 44%, oz 53%, Adobe 40%, Gaaiho 53%, ezPDF 49%), 그 밖의 도구 13건은 16%
  - 비율이 튀는 문서 2종을 눈으로 확인: 98%(MS Word 2건)는 5쪽짜리 문서로 페이지 전체가 항목 이름 칸·내용 칸의 요약표 배치라 실제로 표. 5%(Foxit)는 표 없이 문장만 있는 문서
  - 처리 시간: pdfplumber로 문서 1건(평균 70.6쪽)에 평균 4.1초(4개 프로세스 동시 실행, 개인 PC). DART 6,500건이면 한 프로세스로 약 7시간이라 병렬 처리나 추출 1회 재사용(v2.2 추출 키 = 원본 파일 × 파서 버전)이 필요
- 칸 안에 문장이 있는 표: 투자설명서에는 「구분 | 투자위험의 주요내용」처럼 칸마다 문단이 들어간 표가 많음. 표 안 텍스트에 「다.」로 끝나는 문장이 있으면 `has_sentences = true`로 표시해 넘김. 이런 표는 ASL에 넣음. 표를 모두 뺀 ASL도 비교용으로 함께 계산해 결과 차이를 확인함(10월 10일 데이터 사이언스(다빈) 결정)
  - 판정 기준은 「다.」로 끝나는 문장만. 개조식 종결(「함.」「음.」「임.」「됨.」)을 넣을지는 PR #51 표본으로 실측한 뒤 정함(「미결」)
- 표의 페이지 영역을 글자 범위로 바꾸려면 표를 찾은 도구와 canonical text를 만든 도구가 같아야 함. 텍스트와 표 모두 pdfplumber로 추출해 이 조건을 맞춤(10월 10일 PM(대현) 요청, PR #51)
- 표 분리 실패는 파일럿 전 파트 B에 영향을 주는 유일한 추출 실패([점수 저장과 비교 모집단](scoring-and-population.md) 「결과 상태와 결측」)

### 4-4. 문서 작성기준일과 작성기준 판

- 작성기준일: 간이투자설명서 표제의 「(작성기준일 : 2026.08.24)」 형식 또는 투자설명서 표지에서 읽음 → `report_base_date`
- 작성기준 판: 기업공시서식 작성기준은 2026년에만 8회 개정됨. 작성기준일 이전에 시행된 가장 최근 판을 `standard_version`에 기록. 판 파일은 `assets/standards/`(불변, 이름·버전·해시)
- 판 목록과 시행일은 아직 자산 파일로 만들어지지 않음(「미결」)
- 작성기준 판은 `structure.json`에 넣지 않음. 이유는 4-6 「넣지 않는 것」

### 4-5. 글꼴 굵기·색

- 10월 7일 확인(표본 12건): 추출 가능. 굵기는 생성 도구에 따라 굵은 글꼴(MS Word·Adobe) 또는 보통 글꼴에 외곽선 덧그리기(iText·oz 등) 두 방식이라 둘 다 봐야 함. 빨간 글씨는 위험 경고 문구에 몰림(12건 중 11건)
- 3-4 중요 문구 강조는 보류 상태이므로 `documents.parquet`에는 넣지 않음. 추출할 때 `structure.json`의 `emphasis` 블록에 글꼴·강조 정보를 남겨 3-4 재개 때 다시 추출하지 않게 함(4-6)

### 4-6. `structure.json` 필드

- `structure.json`은 원본 파일 × 파서 버전마다 하나인 추출 기록. 그 PDF에서 읽은 구조를 담음
- `documents.parquet`의 텍스트·구조 칼럼은 이 파일에서 옮겨 만듦. 값이 이상하면 이 파일로 다시 확인함(10월 7일 PM(대현) 리뷰)
- 채점에 쓰지 않는 추출 검증 값은 이 파일에만 둠
- 필드 이름은 PR #51 리뷰에서 PR #43 설계 이름과 맞춰 확정. 아래 표는 뜻과 위치만 정함. 괄호 안은 PR #51 현재 이름, 「제안」은 PR #51에 없는 필드
- 위치는 모두 `text.txt` 기준 0부터 세는 Unicode code point 반열린 구간 `[char_start, char_end)`
- 표 분리 실패: 표 찾기만 실패하면 파일 전체를 실패로 두지 않음
  - 표 안 글자는 `text.txt`에 그대로 남음. 표 위치만 모름
  - 영향은 ASL 하나(`TABLE_SPLIT_FAILED`, 5절). 2-1·2-2와 절은 그대로 씀
  - `structure_status`는 `PARTIAL`. 이미 추출된 결과로 보지 않고 다음 실행에서 다시 추출함
  - 같은 PDF에서 계속 실패하면 실행 기록에 같은 사유가 반복됨. 코드·라이브러리를 고치면 파서 버전을 올려 다시 추출

#### 최상위 필드 (문서 전체 속성)

| 항목 | 담는 것 | `documents.parquet` |
|---|---|---|
| 형식 버전 (`schema_version`) | 이 파일 형식의 버전 | 옮기지 않음 |
| 원본·파서 (`raw_sha256`, `parser_version`) | 추출 키. `derived/` 경로와 같음 | `raw_sha256`, `parser_version` |
| 텍스트 대응 (`text_sha256`, `text_length`) | 짝이 되는 `text.txt`의 해시와 길이 | `text_length` |
| 구조 상태 (`structure_status`) | 부·절 구조를 만들었는지. 표 분리만 실패하면 `PARTIAL` | `headings_status`의 근거 |
| 쪽 시작 위치 (`page_starts`) | 쪽마다 시작 글자 위치. 쪽 번호는 1부터 | 옮기지 않음 |
| 부 (`parts`) | 부 번호, 제목, 범위 | 옮기지 않음 |
| 절 (`sections`) | 2절 「sections 원소」와 같은 필드. `section_id`(DB 값)만 없음 | `sections` |
| 표 분리 상태 (제안 `table_split_status`) | `OK` / `FAILED` / `NOT_ATTEMPTED`. `FAILED`·`NOT_ATTEMPTED`이면 표 블록 없음. `FAILED`여도 텍스트·절은 씀(아래) | `table_split_status` |
| 책갈피 대조 (`bookmark_check`) | 아래 「책갈피 대조」. 책갈피가 없는 문서는 null | 옮기지 않음 |
| 블록 (`blocks`) | 아래 「blocks 원소」 | 아래 표 |

#### blocks 원소

- 한 원소 = 텍스트 안의 구간 하나. 시작 위치 순으로 정렬
- 공통 필드: 종류(`kind`), `char_start`, `char_end`
- 블록 ID는 두지 않음. 근거 위치는 절 번호 + 글자 범위로 가리킴(PR #43 io-schema B11 안 1)

| 종류 | 종류별 필드 | 쓰는 곳 | `documents.parquet` |
|---|---|---|---|
| `table` | `has_sentences`(칸 안에 「다.」로 끝나는 문장이 있는지, 4-3) | ASL 구간 빼기(4-3) | `table_regions` |
| `page_furniture` | 없음 | 쪽 머리글·쪽 번호. 지표에서 뺌(4-2 ④) | `page_furniture_regions` |
| `subheading` | `title`, `level`(1 = 「가.」, 2 = 「(1)」), `section_seq`(속한 절), `title_char_start`, `title_char_end` | 하위 제목 위치(4-2 ②). section 행은 만들지 않음 | 옮기지 않음 |
| `summary_label` | `text`(항목 이름 원문) | 요약정보 표 왼쪽 칸 항목 이름(「투자목적」 등). 10월 10일 데이터 사이언스(다빈) 요청 | 옮기지 않음 |
| `emphasis` | `bold`(굵게 보이는지), `bold_method`(`font` 굵은 글꼴 / `stroke` 외곽선 덧그리기), `color`(`#RRGGBB`, 검정이면 null) | 3-4 중요 문구 강조 재개 대비(4-5) | 옮기지 않음 |

- `subheading` 범위는 제목 줄 시작부터 다음 같은 수준 이상 제목 직전까지(4-2 ① 규칙과 같음)
- `summary_label`은 요약정보 구간(`section_kind = summary`) 안 표의 첫 열 칸만 대상

#### 책갈피 대조

- 분할은 규칙으로만 하고 책갈피는 검증에만 씀(10월 10일 PM(대현) 결정, 4-2)
- 책갈피가 있는 문서만 값이 있음. 없으면 필드 전체가 null(「책갈피 없음」과 「하나도 안 맞음」을 구분하기 위함)
- 부는 부 번호, 절은 (부 번호, 절 번호)가 같으면 일치로 셈

| 필드 | 뜻 |
|---|---|
| 책갈피 부 수, 책갈피 절 수 | 책갈피의 「제N부」·「N.」 제목 수 |
| 규칙 부 수, 규칙 절 수 | 규칙으로 찾은 부 수, 범위를 찾은 본문 절 수 |
| 일치 부 수, 일치 절 수 | 둘 다에 있는 부·절 수 |

- 실행 전체의 재현율·정밀도는 실행 요약(`runs/{run_id}/run.json`)에 냄

#### 넣지 않는 것

- 작성기준 판: `documents.parquet`의 `standard_version`에만 둠(4-4)
  - 이유: 이 파일은 원본 파일 × 파서 버전마다 한 번 만들고 다시 쓰지 않음. 판 선택은 판 목록 자산 파일에 따라 바뀜. 이 파일에 넣으면 판 목록을 고칠 때마다 PDF를 다시 추출해야 함
- 제목 출처(`headings_source`): 10월 10일 결정 뒤 모든 문서가 규칙 분할이라 구분할 값이 없음. 책갈피 유무는 책갈피 대조가 null인지로 알 수 있음

## 5. 결측·실패 표기

- 값이 없을 때 NULL만 두지 않음. 이유를 같은 행의 상태 칼럼이나 사유 코드로 함께 넘김
- 세 가지를 구분

| 구분 | 뜻 | 표기 |
|---|---|---|
| 해당 없음 | 원천에 원래 없음을 확인함(간이 없음, 용어 목록 없음) | 행 없음 또는 상태 `ABSENT` 계열 사유 코드 |
| 미확인 | 아직 확인하지 못함(수집 전, 방법 미정) | 상태 `NOT_ATTEMPTED` |
| 추출 실패 | 시도했으나 읽지 못함 | 상태 `FAILED`·`NOT_FOUND` 또는 `*_FAILED`·`*_UNREADABLE` 사유 코드 |

- 칼럼별 표기와 채점 쪽 결과([점수 저장과 비교 모집단](scoring-and-population.md) 「결과 상태와 결측」의 사유 코드와 같은 이름)

| 경우 | documents.parquet 표기 | 영향받는 지표 | 채점 쪽 result_status / reason_code |
|---|---|---|---|
| 본문 추출 실패 | 행 없음, `excluded.parquet`에 `PROSPECTUS_EXTRACT_FAILED` | 펀드 전체 | 비교 제외 |
| 표 영역을 나누지 못함 | `table_split_status = FAILED` 또는 `NOT_ATTEMPTED`, `table_regions = NULL` | ASL | UNDETERMINED / TABLE_SPLIT_FAILED |
| 부·절 제목을 찾지 못함 | `headings_status = NOT_FOUND`, `sections` 빈 목록 | 3-1a, 3-1b-① | UNDETERMINED / HEADINGS_NOT_FOUND |
| 일부 절 경계를 못 찾음 | `headings_status = PARTIAL`, 해당 원소 `SECTION_BOUNDARY_NOT_FOUND` | 그 절을 쓰는 점검 | 지표 정의에 따름 |
| 간이 대표 없음 | `SIMPLE` 행 없음 | 간이 3-1a·3-1b | UNDETERMINED / SUMMARY_NOT_FOUND |
| 맨 뒤 용어 목록 없음 | 용어 목록 절 없음(제5부 `body` 중 해당 제목 없음) | 3-2 | UNDETERMINED / GLOSSARY_ABSENT |
| 작성기준일을 읽지 못함 | `report_base_date = NULL`, `report_base_date_status = UNREADABLE`, `standard_version = NULL` | 3-1a, 3-1b-①, 간이 3-1 | UNDETERMINED / STANDARD_DATE_UNREADABLE |

- 대체값을 넣지 않음. 표를 빼지 못한 텍스트로 ASL을 계산해 OK로 내지 않음

## 6. 조인에서 빠진 상품 표시

`excluded.parquet` 한 행 = 제외된 대상 하나. 층 자체를 정할 수 없는 대상은 가짜 위험등급 층을 만들지 않고 이 파일(실행 전체 제외 목록)에 둠.

| 칼럼 | 자료형 | 예시 값 | 설명 |
|---|---|---|---|
| fund_key | string | NULL | 묶음이 정해진 경우만 값 |
| product_id | int64 | `3301` | fund_key가 없을 때 상품 클래스 |
| reason_code | string | `FOREIGN_UMBRELLA` | 아래 표 |
| detail | string(JSON) | `{"sub_fund_grades": [2, 3, 4]}` | 사유별 근거 |

| reason_code | 뜻 | 근거 |
|---|---|---|
| ETF_UNCONFIRMED | KRX 연결이 `NAME_ONLY`·`PENDING`이라 ETF 여부 미정 | [상품·법인 매칭 규칙](matching-rules.md) 「KRX 매칭 실패 처리」 |
| RISK_GRADE_UNKNOWN | 대표 위험등급을 읽지 못함 | [점수 저장과 비교 모집단](scoring-and-population.md) 「층화와 결측」 |
| FUND_KEY_UNRESOLVED | 상품이 펀드 묶음에 연결되지 않음 | 같은 문서 「층화와 결측」 |
| SALE_STATUS_UNKNOWN | 판매 중 여부 미확인 | 같은 문서 「판매 중 확인」(v2.2에서 판매 칼럼 제거, 판단 근거 미결) |
| AMBIGUOUS_DOCUMENT | 대표 문서를 고를 수 없음 | 같은 문서 「기준일과 대표본 선택」 4번 |
| FOREIGN_UMBRELLA | 외국 엄브렐러 펀드(하위 펀드마다 등급이 따로 있음) | 10월 4일 PM 결정 |
| NO_PROSPECTUS | 기준일 이하에 투자설명서 대표가 없음 | 이 문서 |
| PROSPECTUS_EXTRACT_FAILED | 투자설명서 대표의 추출 상태가 `EXTRACT_OK`가 아님 | 7차 미팅 결정 ① |
| CATEGORY_MIXED | 한 펀드의 클래스들이 펀드와 ETF로 갈림 | 이 문서 |

- 클래스 간 위험등급 불일치는 제외가 아님. `documents.parquet`의 `class_grade_mismatch = true`로 표시하고, 상세(클래스 product_id·대표 등급·클래스 등급)는 match_failure `CLASS_GRADE_MISMATCH`의 상세 JSON에 있음(v2.2 결정 대기 기본값)
- 클래스 간 등급이 다른 건수는 데이터 사이언스(다빈)가 10월 8일까지 확인(티켓 할 일)
- `reason_code` 9개는 10월 10일 데이터 사이언스(다빈) 리뷰로 확정

## 7. 사전에 없는 단어 기록

- 2-1(전문용어 밀도 = 사전에 있는 고유 전문용어 수 ÷ 전체 고유단어 수)에서 사전에 없는 단어는 분모에 넣고 분자에서 뺌(9월 30일 데이터 사이언스(다빈) 계산 계획)
- 기록 위치: 2-1·2-2 score 행의 `score_payload`에 미분류 단어 종류 수·목록·사전 버전([데이터 테이블·ERD 설계](data-model.md) 「10-02 변수표가 ERD에 주는 영향」). 채점 쪽에서 남기는 것이므로 `documents.parquet`에는 칼럼이 없음
- 형태소 분석기 버전이 텍스트 처리에 영향을 주면 파서 버전을 올림(저장 규칙). 형태소 분석기 확정(Kiwi / Okt)은 데이터 사이언스(다빈) 10월 14일

## 8. 소스별 룩백 재조회와 워터마크 검증

PR #43 미결 「룩백 재조회 방식과 소스별 워터마크 검증 방법」(데이터 엔지니어링·인프라(주영), 필요 시점 이 명세)의 답. PR #43은 10월 9일 이 절을 [원본 보관과 수집·파싱 실패 처리 규칙](storage-and-failure-rules.md) 「재시도와 워터마크」에 반영함. 워터마크는 v2.2 `source_watermark`(키 = 소스 × 조회 범위, 값 = covered_from ~ covered_through)에 기록.

- 공통 규칙
  - 구간의 모든 페이지를 받고 아래 검증을 통과했을 때만 전진. 앞선 날로 되돌리지 않음
  - `covered_from`은 누적 구간의 시작(첫 실행 시작일). 룩백은 `covered_from`보다 앞으로 가지 않음. 받은 적 없는 날을 룩백으로 처음 받으면 「룩백 구간 신규 발견 수」가 부풀어 룩백 일수 판단 근거로 쓸 수 없기 때문(10월 5일 크롤러 실측)
  - 룩백 재조회: 다음 실행은 `covered_through − 룩백 일수`부터 목록을 다시 받음. 이미 원본이 있는 문서는 원문을 다시 요청하지 않고, 새로 나타난 문서만 받음. 실행마다 룩백 구간 신규 발견 수를 기록해 룩백 일수 확정 근거로 씀
  - 검증에 실패한 구간이 있으면 그 앞에서 워터마크를 멈추고 실행을 `FAILED`로 끝냄(PR #47 리뷰 반영)

| 소스 | 증분 축 | 룩백 | 구간 완전성 검증 | 상태 |
|---|---|---|---|---|
| DART | 접수일 `rcept_dt`, 하루 단위 | 3일(잠정) | `total_page`까지 모든 페이지 수신, 페이지마다 status `000`(정상) 또는 `013`(자료 없음). 추가 제안: 응답 `total_count`와 받은 행 수 대조 | 구현(크롤러 1차, 이슈 #45·PR #47, dev 미병합). 건수 대조는 미구현 |
| 공공데이터포털 펀드 | 기준일 `basDt`, 전건 스냅숏 | 없음(매번 전건) | `response.body.totalCount`와 누적 행 수 대조 | 크롤러 2차(10월 14일) |
| KRX ETF | 기준일 `basDd`, 일별 전건 | 없음(일별 파일) | 응답에 `respCode` 키가 없고 `OutBlock_1`이 배열이며 행의 `BAS_DD`가 요청 기준일과 같음. 0행은 거래소 영업일 정보로 휴장일임을 확인한 경우에만 정상 0건(EMPTY)으로 기록하고 전진. 확인 방법이 정해지기 전에는 0행이면 전진하지 않음 | 크롤러 2차. 휴장일 응답 미확인 |
| 금투협 공시 | `standardDt` | 7일(잠정) | 응답이 `</root>`로 끝나고 `dbio_total_count_`와 `<list>` 행 수가 같음 | 수집기 미정 |
| 금감원 제재 | 입력일 `inputDate` | 미정 | `resultCode` `1`·`900`만 정상 | 게시판 크롤러 보류(10월 7일 10차 미팅). 재개 여부는 PM(대현) 검토(10월 14일) 결과에 따름. API 정기 수집도 보류 대상인지는 PR #43 리뷰에서 확인 요청(10월 11일) |

- 이 절은 위 5종만 다룸. 금투협 판매관계·분쟁조정·국가법령의 구간 완전성 검증은 해당 수집기 구현 전에 정함. finlife는 CDI 범위 제외라 대상 아님

## 9. 7차 미팅 결정 3건 반영 확인

| 결정(9월 20일) | 반영 위치 |
|---|---|
| ① 텍스트 추출이 성공한 것(EXTRACT_OK)만 넘김 | 2절 「행에는 `EXTRACT_OK`인 문서만」, 6절 `PROSPECTUS_EXTRACT_FAILED`. v2.2부터 점수 단위가 문서라 판단 기준이 절이 아니라 문서 |
| ② 회귀 관측 단위 = fund_key(같은 펀드의 클래스는 한 건) | 2절 `documents.parquet` 한 행 = fund_key × 역할, 파트 B·통계는 `PROSPECTUS` 행만(3절) |
| ③ 점수 출력이 비교 집단 스냅숏(population_snapshot) 번호를 가리킴 | 채점 쪽 계약. 비교 집단은 `documents.parquet`의 `PROSPECTUS` 행에서 `product_category × representative_risk_grade`로 만들고 `runs/{score_run_id}/populations/`에 기록([점수 저장과 비교 모집단](scoring-and-population.md) 「population_snapshot」) |

## 10. 리뷰 승인 기록

| 항목 | 기록 |
|---|---|
| 데이터 엔지니어링·인프라(주영): 이 명세로 만들 수 있음 확인 | 10월 7일 확인. 작성기준 판(4-4)은 판 목록 자산 파일이 생긴 뒤 |
| PM(대현) 리뷰·승인 | 10월 7일 승인. 수정 요청(입력 불변 문장, `text_excl_tables` 제거, `structure.json` 필드 정의, 「하나」 문구, PR #51 요청 3건) 반영 |
| 데이터 사이언스(다빈) 리뷰·승인 | 10월 10일 의견(표 안 문장은 ASL에 넣음, 사유 코드·`report_base_date_status` 확정, 요약정보 항목 이름 요청) 반영. 승인 대기 |

## 미결

| 질문 | 결정 필요 주체 | 필요 시점 |
|---|---|---|
| 제목 추출 정밀도 보완 규칙(머리글 반복 「제1부」, 본문 번호 목록) | 데이터 엔지니어링·인프라(주영) | 절 분할 실패율 산출(10월 14일) |
| 작성기준 판 목록·시행일 자산 파일 작성 | [확인 필요: 담당] | 작성기준 항목 점검 구현 전 |
| DART 목록 건수 대조(`total_count`) 추가 | 데이터 엔지니어링·인프라(주영) | 크롤러 2차(10월 14일) |
| KRX 휴장일 확인 방법(거래소 영업일 정보의 출처, 휴장일 응답 형태) | 데이터 엔지니어링·인프라(주영) | 크롤러 2차(10월 14일) |
| 룩백 일수 확정(DART 3일, 금투협 7일 잠정) | 데이터 엔지니어링·인프라(주영) | 룩백 구간 신규 발견 수가 2주 이상 쌓인 뒤 |
| `has_sentences` 판정에 개조식 종결(「함.」「음.」「임.」「됨.」)을 넣을지. 넣으면 해당 표가 ASL에 들어감 | 데이터 엔지니어링·인프라(주영) | PR #51 표본 40건 실측 뒤, 10월 14일 전 |

## 참고

- 10월 7일 PDF 구조 확인 원자료: 표본 목록·측정 스크립트는 저장소 밖 실험 폴더에 있음. 수치는 이 문서 4-2·4-3·4-5에 옮김
- [데이터 테이블·ERD 설계](data-model.md) 「v2.2」「절」「두 파트 출력의 저장 계약」
- [원본 보관과 수집·파싱 실패 처리 규칙](storage-and-failure-rules.md) 「파생 텍스트·실행 스냅숏 경로」「재시도와 워터마크」「추출 실패와 절 품질」
- [점수 저장과 비교 모집단](scoring-and-population.md) 「결과 상태와 결측」「층화와 결측」「기준일과 대표본 선택」
- [데이터 소스 수집 명세](data-sources.md) 「응답 완전성 검증」
