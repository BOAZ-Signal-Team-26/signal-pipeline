# 스키마 명세 — 2026-10-04 v2.2

- 범위: [DBML](schema.dbml)을 파싱해 정리한 17개 테이블(관계 42개, enum 26개)의 전체 칼럼·키·관계·상태값
- 상태: v2.2(이슈 #42) = 연기한 표 4개 제거, analysis_target을 score에 병합(결정 대기 A), 추출 키를 원본 파일 × 파서 버전으로 변경, 표 2개 추가(llm_field_extraction, source_watermark), 채울 수 없는 칼럼 제거, 코드 체계별 두 칼럼(결정 대기 E). 변경표와 반대 결정 시 범위는 [데이터 테이블·ERD 설계](data-model.md) 「v2.2」. 연기한 표의 정의 요지는 같은 문서 「예약 계약(승인 뒤 추가)」. 이전 판 v2.1 = [ERD 설계 변천과 검토 기록](records/phase1-erd/design-review-history.md) 「v2 6관점 검토」의 즉시 반영 조치(실행 분리·공식 run 마커·모집단 유일키·enum 통일·지표 방향·공개 ID 규칙) 반영
- 논리 검토안. 물리 DB 구축이나 팀 승인 아님
- NULL 허용은 구조적 허용. 조건부 필수 규칙은 [데이터 테이블·ERD 설계](data-model.md) 「절과 점수 대상」·「적재 검증 규칙」, 점수·결측 상태 조합은 [점수 저장과 비교 모집단](scoring-and-population.md) 「결과 상태와 결측」
- 복합 FK는 하나의 관계로 셈
- 옛 번호 표기 해석: [설계 문서 안내](README.md) 「옛 문서 번호 대응」. DBML에서 이 명세를 다시 생성할 때는 DBML 주석(2026-09-29 새 문서 이름으로 교정)을 그대로 옮기고 이 머리말을 유지

## product

| 칼럼 | 논리 타입 | NULL | 키 | 설명 |
|---|---|---|---|---|
| product_id | int | 불가 | PK | 내부 발급 서러게이트 키. 구체 자료형(int/bigint 등)·생성 방식은 2단계 데이터 파이프라인 Flow 설계 사안 |
| short_code | varchar(5) | 허용 |  | 단축코드 5자리 영숫자([A-Z0-9]{5}). DART 표지 펀드코드 = 공공데이터포털 srtnCd(두 소스 코드 조인, [조인 키 확인 기록](records/phase1-erd/join-key-checks.md) 「조인 키 확인 현황」). 펀드·ETF 1차 조인 키. 전역 유일 아님(전체 165,118종 중 4,899종=3.0% 중복) — 2015년 이후 설정분·상장지수 1,435건 범위에서는 안전. 겹치면 (asoStdCd 앞 6자리, short_code) 조합으로 확장([조인 키 확인 기록](records/phase1-erd/join-key-checks.md) 「srtnCd 비유일」) |
| kofia_fund_code | varchar(12) | 허용 |  | K55 체계 코드 12자리 = K55+운용사3+단축5+검증1. 결정 대기 E(기본값: 체계별 두 칼럼, 10월 4일). 채우는 소스 두 곳: 금투협 수시공시 코드와 공공데이터포털 asoStdCd 중 K55로 시작하는 값(ETF 대조 표본 1,373건 중 1,195건). 접두 3자로 분기([매칭 규칙](matching-rules.md) 「코드 체계 분기」). 반대 결정(한 칸 병합 등) 시 이 칼럼과 standard_code 두 칼럼만 바뀜 |
| standard_code | varchar(12) | 허용 |  | KR5/KRM 체계 협회표준코드 12자리. 공공데이터포털 asoStdCd 중 KR5·KRM으로 시작하는 값(같은 표본 178건)과 금투협 standardCd의 KR5·KRM 값. kofia_fund_code와 체계가 다름. 결정 대기 E |
| isu_cd | varchar | 허용 |  | 거래소 종목코드. ETF에만 값 존재(그 외 NULL). short_code와 잇는 코드성 수단이 없어 이름으로만 연결되고 완전일치 0.0%/포함매칭 80.4%([금투협 중복 행과 ETF 이름 규칙 검증](records/phase1-erd/kofia-rows-and-etf-rule.md) 「검증 2: ETF 이름 규칙」. ISU_CD와 srtnCd를 잇는 대응 소스 없음). 길이·형식은 문서에 근거 없어 미정 |
| product_name | text | 불가 |  | 포털 fndNm 원문. DART 표지 명칭은 매칭 근거에 별도 보존 |
| product_name_normalized | text | 허용 |  | [매칭 규칙](matching-rules.md) 「상품명 정규화」 4단계(NFKC→공백 제거→(주)/주식회사 제거→유형괄호·호수·클래스 분리) 결과 |
| product_category | product_category_enum | 허용 |  | 분류 미확정이면 NULL. 펀드/ETF로 강제 배정하지 않음 |
| is_etf | boolean | 허용 |  | KRX_CONFIRMED=true, NOT_ETF=false, NAME_ONLY/PENDING=NULL |
| etf_confidence | etf_confidence_enum | 불가 |  | [금투협 중복 행과 ETF 이름 규칙 검증](records/phase1-erd/kofia-rows-and-etf-rule.md) 「검증 2: ETF 이름 규칙」 반영, 신설 |
| fund_key | varchar | 허용 | FK | 고정 식별자(09-20 결정). 묶음 미확정이면 NULL, 통계에서 사유와 함께 제외 |
| risk_grade | int | 허용 |  | 이 상품(클래스)에 대해 공시된 값을 그대로 보존. 펀드 대표 등급은 이 칼럼이 아니라 `fund_group.representative_risk_grade`에 있고, 대표 등급을 각 클래스에 복사하지 않음(클래스 간 불일치를 보존하기 위함). 1~6, 1이 최고위험. DART 투자설명서 표지 "N등급[문구]"에서 정규식(\\d)등급으로 추출. corp_code 조인이 아니라 문서→상품 경로로 채움. 위험등급 원천이 DART 하나만은 아닐 수 있음(금투협 첨부 PDF 본문에도 표기 확인, [소스별 데이터 현황표](records/phase1-erd/source-profile.md) 「값 표기」) — [점수 저장과 비교 모집단](scoring-and-population.md) 「알려진 분석 위험」의 위험등급 결측 논증 전제이므로 재검토 대상. 공시된 펀드 위험등급(1~6등급)을 그대로 쓰고 사람이 다시 매기지 않음(9차 미팅). 펀드 등급 규칙(10-04 확정): 출처는 간이투자설명서 표제, 간이가 없으면 투자설명서 표지. 기준은 문서 작성기준일 시점의 공시 등급. 클래스끼리 다르면 확인 대상으로 기록([데이터 테이블·ERD 설계](data-model.md) 「상품과 법인」) |
| manager_id | int | 허용 | FK | 운용사/겸업 법인. 포털에 운용사 필드가 없어 매핑 전 NULL 허용 |
| inception_date | date | 허용 |  | 포털 setpDt 설정일. 유효 달력일만 변환; 더미는 NULL과 원천 보존. 판매개시일과 다름. v2.2: 판매개시일·판매종료일 칼럼은 채울 수 없어 제거 |
| fund_type | varchar | 허용 |  | 공공데이터포털 fndTp. [점수 저장과 비교 모집단](scoring-and-population.md) 「알려진 분석 위험」에서 위험등급의 보조 층화축 후보로만 확보. 코드 형식·길이 미정. 값 형식은 데이터 엔지니어링·인프라(주영) API 조회로 확인대기(9차 미팅) |
| product_class_code | varchar | 허용 |  | 공공데이터포털 prdClsfCd. 코드 형식·길이 미정. 값 형식은 데이터 엔지니어링·인프라(주영) API 조회로 확인대기(9차 미팅) |
| source_raw_object_id | int | 허용 | FK | 현재 상품 값을 공급한 포털 응답 파일. basDt와 원천 행 키로 역추적 |
| source_baseline_date | date | 허용 |  | 원천 basDt. 설정일/수집일과 구분 |
| risk_grade_raw_object_id | int | 허용 | FK | 현재 위험등급의 DART 표지 또는 금투협 첨부 근거. 과거 값은 실행 입력 manifest에 고정 |
| valid_from | date | 허용 |  | SCD2 예비 칸(09-14 티켓 메모 반영, 신설). 물리화 여부는 2단계 데이터 파이프라인 Flow 설계 사안 — 지금은 이력을 두지 않으면 변경 이력이 영구 소실된다는 문제만 인지된 상태 |
| valid_to | date | 허용 |  | SCD2 예비 칸. valid_from과 동일 사유 |

- FK: (fund_key) → fund_group(fund_key)
- FK: (manager_id) → distributor(distributor_id)
- FK: (source_raw_object_id) → raw_object(raw_object_id)
- FK: (risk_grade_raw_object_id) → raw_object(raw_object_id)

## distributor

| 칼럼 | 논리 타입 | NULL | 키 | 설명 |
|---|---|---|---|---|
| distributor_id | int | 불가 | PK | 내부 발급 서러게이트 키 |
| kofia_sales_code | varchar(6) | 허용 | UK | 판매회사 마스터 saleCompCd. 200건 전부 6자리/유일. 운용사 코드와 별개 |
| corp_code | varchar | 허용 |  | DART 법인 고유번호(공시 제출 법인=운용사). 원래 상품 표에 있던 것을 이관(문서→상품 경로로 위험등급을 채우기 위한 결정과 연동). document.corp_code와 값 체계가 같아 보이나 이 문서 어디에도 FK로 명시돼 있지 않아 관계선을 긋지 않았다([데이터 테이블·ERD 설계](data-model.md) 「ERD」의 그림에 넣지 않은 관계 1번). 8자리(09-30 목록 API 실측으로 확인, [데이터 소스 명세](data-sources.md) 「OPEN DART API」) |
| kofia_disclosure_company_code | varchar(6) | 허용 | UK | 금투협 전자공시 공시 목록의 운용사 코드 companyCd(예: A01021=한화자산운용, A01048=미래에셋자산운용). 현재 운용사 기준이라 합병·상호 변경을 반영. 공시 행을 적재할 때 채움. 표준코드 안 3자리 코드(kofia_mgmt_code)와 체계가 다름. 운용사 연결 1순위 키([매칭 규칙](matching-rules.md) 「운용사 연결 순서」). 10월 4일 추가 |
| kofia_mgmt_code | varchar(3) | 허용 |  | 금투협 운용사 코드 3자리 영숫자(예: 105=삼성자산운용, 301=미래에셋자산운용). 대응표 536건 = [research/samples/kofia_mgmt_codes.csv](../research/samples/kofia_mgmt_codes.csv) |
| distributor_name | text | 불가 |  | 원문명 |
| distributor_name_normalized | text | 허용 |  | [매칭 규칙](matching-rules.md) 「법인명 정규화」 5단계(NFKC→구상호 치환→법인격 표기 제거→공백 제거→지점 표기 제거) 결과. 상품명 정규화 규칙을 쓰지 않는다 — 법인명에는 클래스 표기가 없고 대신 상호 변경이 있다 |
| distributor_type | distributor_type_enum | 불가 |  |  |


## product_distributor

| 칼럼 | 논리 타입 | NULL | 키 | 설명 |
|---|---|---|---|---|
| product_id | int | 불가 | PK, FK |  |
| distributor_id | int | 불가 | PK, FK |  |
| snapshot_month | varchar(6) | 불가 | PK | YYYYMM. 09-20 신설. 이 칸 없이 (product_id, distributor_id)로 upsert하면 매달 과거 판매 관계를 경고 없이 덮어쓴다 |
| source_raw_object_id | int | 불가 | FK | 판매사별 펀드 API 응답. source_document_id가 NULL이어도 출처 보존 |
| observed_date | date | 불가 |  | 실제 조회 기준일 tmpV30/tmpV16. snapshot_month의 대표일 정책은 [데이터 테이블·ERD 설계](data-model.md) 「적재 검증 규칙」 참조 |
| source_document_id | int | 허용 | FK | 이 연결을 알려준 문서. 확정된 현재 경로(금투협 전자공시 "판매사별 펀드보수비용" 코드 조회)에서는 명단이 문서가 아니라 별도 API 조회에서 오므로 항상 NULL이다([조인 키 확인 기록](records/phase1-erd/join-key-checks.md) 「판매회사 명단 소스」). 문서 경로가 추가되면 NULL 허용 여부를 재검토 |

- PK: (product_id, distributor_id, snapshot_month)
- FK: (product_id) → product(product_id)
- FK: (distributor_id) → distributor(distributor_id)
- FK: (source_raw_object_id) → raw_object(raw_object_id)
- FK: (source_document_id) → document(document_id)

## document

| 칼럼 | 논리 타입 | NULL | 키 | 설명 |
|---|---|---|---|---|
| document_id | int | 불가 | PK | 내부 발급 서러게이트 키 |
| source | varchar | 불가 |  | 소스/엔드포인트 이름공간. 7개: dart, kofia_disclosure, fss_sanction, fss_improvement, fss_dispute, data_go_fund(공공데이터포털 펀드상품기본정보), krx_etf_daily(KRX ETF 일별 매매정보). 뒤 두 소스는 API 스냅숏이라 document 행 없이 raw_object(document_id NULL)와 source_watermark에만 나온다 |
| source_doc_key | varchar | 불가 |  | source 안에서 유일한 원천 식별자. DART rcept_no, 금투협 4필드 해시. 제재공시는 emOpenNo가 아니라 후보 복합키, [데이터 테이블·ERD 설계](data-model.md) 「문서와 소스별 키」 참조 |
| source_key_payload | text | 불가 |  | 키 생성 전 원천 필드 JSON. 제재 API 후보는 examMgmtNo/emOpenSeq/transCode/actGbn. 빈 키/충돌은 격리 |
| source_record_payload | text | 허용 |  | 제재 13필드 등 원천 레코드 JSON. API 응답 파일의 원문도 별도 보존 |
| action_date | date | 허용 |  | 제재 actReqDate. 공시 입력/접수 날짜와 다름 |
| source_input_at | timestamp | 허용 |  | 제재 inputDate. 원문 문자열과 시간대 해석은 payload에 보존 |
| rcept_no | varchar(14) | 허용 |  | DART 접수번호. DART 전용 칸(09-14 티켓 메모 반영) — 그 외 소스는 NULL. 14자리 숫자(09-30 목록 API 실측으로 확인, [데이터 소스 명세](data-sources.md) 「OPEN DART API」) |
| dcm_no | varchar | 허용 |  | DART 문서번호. download.do?dcmNo=로 본문 PDF를 받을 때 필요. DART 전용 칸. 길이 미정 |
| corp_code | varchar | 허용 |  | DART 법인코드(제출 법인=운용사). distributor.corp_code와 값 체계가 같아 보이나 FK로 명시된 바 없어 관계선을 긋지 않았다([데이터 테이블·ERD 설계](data-model.md) 「ERD」의 그림에 넣지 않은 관계 1번). 8자리(09-30 목록 API 실측으로 확인) |
| document_type | document_type_enum | 불가 |  |  |
| report_name | text | 허용 |  | DART 보고서명 원문(예: "[기재정정] 투자설명서"). document_type은 이 값에서 파생 |
| distributor_id | int | 허용 | FK | 상품 연결이 없는 문서(분쟁조정·제재공시 등)를 판매사 축에 붙이기 위한 칼럼. nullable. 분쟁조정은 판매사명도 마스킹이라 이 값조차 못 채운다 — "문서 표에만 존재하는 미연결 레코드"가 정상 상태다([조인 키 확인 기록](records/phase1-erd/join-key-checks.md) 「분쟁조정 마스킹」) |
| is_correction | boolean | 허용 |  | DART 구조로 판정. 미판정/금투협 연결 규칙 미확정은 NULL, false로 만들지 않음 |
| lineage_id | int | 허용 | FK | 같은 사건 최초 문서. 확인된 원본만 self; 원본 미도착/계보 미확정은 NULL |
| version_no | int | 허용 |  | 파생 칼럼(09-14 티켓 메모 반영, 신설). lineage 안에서 received_date 순번 |
| is_current | boolean | 허용 |  | 파생 칼럼(09-14 티켓 메모 반영, 신설). 물리 칼럼으로 둘지는 2단계 데이터 파이프라인 Flow 설계의 이력 설계에서 결정 |
| initial_submit_date | date | 허용 |  | 정정본이면 정정신고 요소에 적힌 최초제출일. 원본이면 received_date와 같다 |
| report_base_date | date | 허용 |  | v2.2 결정 대기(10월 4일 판단 항목). 문서 작성기준일. 작성기준 항목 점검이 이 시점의 작성기준 판과 비교한다. 비교한 작성기준 판과 표 영역 구분은 칼럼 없이 파일(구조 manifest, 작성기준 판 버전 파일). 반대 결정 시 칼럼 제거 후 manifest로 이동 |
| received_date | date | 불가 |  | 접수일자. 분쟁조정은 게시일로 채움. 금소법 시행(2021년) 이후 자료만 거르는 기준이라 필수 유지(9차 미팅). 현재 조사 스크립트 `research/scripts/fetch_fss_dispute.py`의 `listing()`은 게시일을 파싱하지 않음(수집기 미구현). 분석·리서치(민석) 확인대기, 2026-10-04 |

- UNIQUE: (source, source_doc_key)
- FK: (distributor_id) → distributor(distributor_id)
- FK: (lineage_id) → document(document_id)

## document_product

| 칼럼 | 논리 타입 | NULL | 키 | 설명 |
|---|---|---|---|---|
| document_id | int | 불가 | PK, FK |  |
| product_id | int | 불가 | PK, FK |  |
| match_method | match_method_enum | 불가 |  | [매칭 규칙](matching-rules.md) 「매칭 경로」의 3단 계단식(1차 코드 → 2차 정규화 펀드명 → 3차 운용사명+설정일) 중 어느 단에서 붙었는지 |
| match_score | decimal | 허용 |  | 매칭 점수. 코드 매칭이면 1.0, 문자열 매칭이면 유사도. precision/scale은 문서에 근거 없어 미정 |
| matched_at | timestamp | 불가 |  |  |

- PK: (document_id, product_id)
- FK: (document_id) → document(document_id)
- FK: (product_id) → product(product_id)

## section

| 칼럼 | 논리 타입 | NULL | 키 | 설명 |
|---|---|---|---|---|
| section_id | int | 불가 | PK | 내부 발급 서러게이트 키. v2.2: 키가 추출 실행이 아니라 원본 파일 x 파서 버전이므로 같은 파서로 다시 추출하지 않는 한 값이 유지된다. 공개 ID로 쓸 때 run_id 동반이 필요 없다(schema-catalog.md 「공개 식별자 규칙」) |
| document_id | int | 불가 | FK |  |
| raw_object_id | int | 불가 | FK |  |
| parser_version | varchar | 불가 | FK | v2.2. 이 절을 만든 파서 버전. file_extraction과 같은 값. 같은 파일을 같은 파서 버전으로 추출한 결과가 이미 있으면 다시 추출하지 않는다 |
| section_seq | int | 불가 |  | 한 파일/파서 버전 안의 전역 순번. 부 안의 절 번호와 다름 |
| part_seq | int | 허용 |  | 원문 부 번호. 요약 등 부 체계 밖 구간은 NULL |
| source_section_no | varchar | 허용 |  | 원문 절 번호. 부마다 반복되며 비숫자 번호도 보존 |
| canonical_section_code | varchar | 허용 |  | v2.2 신설. 문서 간 같은 절을 묶는 정규 절 분류. 제4부 절 구성이 문서마다 다름(표본 9문서 중 7건 3절, 2건 6절, records/phase1-erd/dart-section-split.md). 값 규칙은 결정 대기 F(칼럼만 두고 값 규칙 미정). 분류 못 하면 NULL |
| section_kind | section_kind_enum | 불가 |  | summary도 실제 원문 구간, 가짜 집계 절 생성 금지 |
| char_start | int | 허용 |  | file_extraction의 canonical text 기준 0-based Unicode code point(글자 위치) 시작. 줄 번호가 아니다. SECTION_BOUNDARY_NOT_FOUND이면 NULL |
| char_end | int | 허용 |  | 같은 텍스트 기준 exclusive 끝. 성공한 절은 0 <= start < end <= text_length. SECTION_BOUNDARY_NOT_FOUND이면 NULL |
| quality_flags | text | 허용 |  | JSON 배열. SHORT_TEXT 등 계산 적합성 표시; 추출 실패와 구분 |
| section_title | text | 허용 |  |  |
| section_text | text | 허용 |  | canonical text의 [char_start,char_end) 구간. 실패 시 복구된 텍스트 또는 NULL. 지표용 전처리는 별도 버전으로 추적 |
| extract_status | raw_extract_status_enum | 불가 |  | 추출 성패. 짧다는 이유만으로 실패 처리하지 않는다(storage-and-failure-rules.md 「추출 실패와 절 품질」). 본문 경계를 못 찾은 절은 SECTION_BOUNDARY_NOT_FOUND |

- UNIQUE: (raw_object_id, parser_version, section_seq)
- FK: (document_id) → document(document_id)
- FK: (raw_object_id, parser_version) → file_extraction(raw_object_id, parser_version)
- FK: (raw_object_id, document_id) → raw_object(raw_object_id, document_id)

## score

| 칼럼 | 논리 타입 | NULL | 키 | 설명 |
|---|---|---|---|---|
| score_id | int | 불가 | PK | 내부 발급 서러게이트 키 |
| run_id | varchar | 불가 | FK | SCORE run |
| target_type | target_type_enum | 불가 | FK | target_type별로 대상 칼럼(section_id, document_id, fund_key) 중 정확히 하나만 채워짐(CHECK num_nonnulls(section_id, document_id, fund_key) = 1. DOCUMENT_PAIR는 Phase 2이며 현재 저장 불가. 적재 검증). v2.2 결정 대기 A(analysis_target 병합, 기본값). 계산 단위. 결정 대기 B10 채택: metric_definition.target_type과 같아야 함(아래 복합 FK로 강제) |
| target_key | varchar(64) | 불가 |  | v2.2 병합. target_key 계약(data-model.md 「절과 점수 대상」 6번, 계약 버전 3): 종류/앵커/대표본 정책 버전의 정규 JSON SHA-256(data-model.md 「절과 점수 대상」 6번). run 안의 재시도 멱등성 키이며 run 간 동일 대상 탐지 키가 아님. 공개 ID로 쓰지 않음 |
| section_id | int | 허용 | FK | SECTION만 필수, 다른 유형은 NULL. 그 절의 파서 버전은 section.parser_version이며 run의 input_manifest가 고정한 파서 버전과 일치해야 함(적재 검증) |
| document_id | int | 허용 | FK | DOCUMENT만 필수. 다른 유형은 NULL |
| fund_key | varchar | 허용 | FK | FUND만 필수. 다른 유형은 NULL; 통계 연결은 실행 입력/모집단 manifest |
| metric_key | varchar | 불가 | FK | 불변 지표 버전. ASL/축값/CDI/백분위도 서로 다른 지표로 명시 가능. (metric_key, target_type) 복합 FK |
| assessor_key | varchar | 불가 |  | deterministic 또는 config_manifest 안의 평가자/모델 설정 키. 재시도는 같은 키, 별도 평가자는 다른 키 |
| result_status | result_status_enum | 불가 |  |  |
| reason_code | varchar | 허용 |  | OK 이외에는 필수. ZERO_DENOMINATOR/SHORT_TEXT/UNAPPROVED_DEFINITION/INPUT_FAILED 등 |
| raw_score | decimal | 허용 |  | OK일 때만 NOT NULL. 계산 불가를 0으로 대체하지 않는다 |
| numerator | decimal | 허용 |  |  |
| denominator | decimal | 허용 |  | 비율 지표 OK이면 양수. 분모 의미는 metric_definition에 고정 |
| normalized_score | decimal | 허용 |  | 정규화 OK일 때만 값. 범위/방향은 지표 계약에 명시 |
| normalization_status | normalization_status_enum | 불가 |  | 원점수 성공과 별도 상태 |
| normalization_reason | varchar | 허용 |  |  |
| population_snapshot_id | int | 허용 | FK | 같은 실행/지표의 모집단. 시도했으나 표본 미달인 경우도 연결 가능 |
| score_payload | text | 불가 |  | score_payload 계약 v2.2(target_key 계약과 별개): 항목별 충족/미충족/해당없음/판정불가, 적용수/평가완료수, 근거 위치 (section_id, char_start, char_end)(결정 B11 안 1; member_id·block_id 의존 제거), 「없음」 판정은 검사한 절 목록, 실제 가중치(파트 B 합산, 연기한 score_dependency 대신), 전처리/단위/커버리지. 파트 A는 항목 하나당 metric_key 하나, 파트 B는 축 1·2 합산 metric_key 하나(축 3은 파일럿 뒤 새 버전), 작성기준 항목 점검 4종은 파트 A 옆 별도 행(비교한 작성기준 판 기록). scoring-and-population.md 「고지 항목 판정」 참조 |
| scored_at | timestamp | 불가 |  |  |

- UNIQUE: (run_id, target_key, metric_key, assessor_key) — v2.2: 대상이 score에 병합되어 target_id 대신 target_key. 대상 칼럼이 NULL을 허용해 유일키에 앵커 칼럼을 직접 넣지 않았다
- FK: (run_id) → pipeline_run(run_id)
- FK: (section_id) → section(section_id)
- FK: (document_id) → document(document_id)
- FK: (fund_key) → fund_group(fund_key)
- FK: (population_snapshot_id, run_id, metric_key) → population_snapshot(population_snapshot_id, run_id, metric_key)
- FK: (metric_key, target_type) → metric_definition(metric_key, target_type)

## match_failure

| 칼럼 | 논리 타입 | NULL | 키 | 설명 |
|---|---|---|---|---|
| failure_id | int | 불가 | PK | 내부 발급 서러게이트 키 |
| run_id | varchar | 불가 | FK | EXTRACT run(매칭은 추출 실행 소속) |
| target_type | match_target_enum | 불가 |  | 매칭 대상 종류. analysis_target의 target_type_enum과 다른 개념 |
| top1_candidate_distributor_id | int | 허용 | FK |  |
| resolved_at | timestamp | 허용 |  |  |
| resolution_note | text | 허용 |  |  |
| source | varchar | 불가 |  | 실패가 발생한 소스 |
| attempted_key_value | text | 불가 |  | 매칭을 시도한 키값. 코드 매칭 실패 시 코드, 문자열 매칭 실패 시 원문 상품명 |
| normalized_value | text | 허용 |  | [매칭 규칙](matching-rules.md) 「상품명 정규화」 4단계를 거친 문자열. 코드 매칭이면 NULL |
| top1_candidate_product_id | int | 허용 | FK | 유사도가 가장 높았던 상품. 없으면 NULL. 후보일 뿐 실제 매칭이 아니다 |
| top1_similarity | decimal | 허용 |  | 그 후보의 유사도 점수. precision/scale 미정 |
| failure_reason_code | failure_reason_enum | 불가 |  | v2.2 결정 대기: CLASS_GRADE_MISMATCH(클래스 위험등급 불일치) 추가. 클래스 product_id·대표 등급·클래스 등급·값 출처(운용사 공시/판매사/API)는 상세 JSON(resolution_note 안)에 기록(칼럼 추가 없음). 별도 표 분리 여부는 결정 대기 |
| attempted_at | timestamp | 불가 |  |  |
| status | match_failure_status_enum | 불가 |  |  |
| related_document_id | int | 허용 | FK | 있으면 연결. nullable |

- FK: (run_id) → pipeline_run(run_id)
- FK: (top1_candidate_distributor_id) → distributor(distributor_id)
- FK: (top1_candidate_product_id) → product(product_id)
- FK: (related_document_id) → document(document_id)

## raw_object

| 칼럼 | 논리 타입 | NULL | 키 | 설명 |
|---|---|---|---|---|
| raw_object_id | int | 불가 | PK | 저장한 바이트 1개 버전의 내부 키 |
| document_id | int | 허용 | FK | 문서 첨부만 연결. API 목록/상품/KRX 스냅숏은 NULL |
| source | varchar | 불가 |  |  |
| source_object_key | varchar | 불가 |  | source 안의 파일 식별자. 문서키+역할+첨부ID 또는 API서비스+기준일+페이지/필터 |
| version_seq | int | 불가 |  | 같은 source/source_object_key의 바이트 버전. 공시 정정 version_no와 별개 |
| body_format | body_format_enum | 불가 |  |  |
| original_file_name | text | 허용 |  |  |
| server_path | text | 허용 |  |  |
| download_url | text | 허용 |  | 인증값 제거 URL |
| source_baseline_date | date | 허용 |  |  |
| file_role | file_role_enum | 불가 |  | CDI 채점 대상을 가리는 유일한 칸 — 금투협은 문서 1건(공고)에 첨부가 2~3종이고 document_type이 "금투협 수시공시" 한 값이므로, 이 칸이 없으면 어느 파일을 채점할지 정할 자리가 없다 |
| sha256 | varchar(64) | 불가 |  | 파일 콘텐츠 해시(hex 다이제스트, 64자). [원본 보관과 수집·파싱 실패 처리 규칙](storage-and-failure-rules.md) 「버전·중복·재추출」의 재수집 시 버전 증가 여부·중복 저장 판정 키. 동일 바이트 검출에 사용한다. 해시가 다르더라도 요약/본문의 내용 중복은 가능하므로 대표 문서 선택을 대체하지 않는다 |
| storage_path | text | 불가 |  | [원본 보관과 수집·파싱 실패 처리 규칙](storage-and-failure-rules.md) 「파일 경로」의 raw/{source}/{원천 키}/{file_role}__v{n}.{ext} 규칙(스냅숏형 API는 원천 키 자리에 기준일). 원천 키는 source_object_key를 만드는 같은 인코딩 함수의 결과. RAW_ROOT 기준 상대경로만 저장, 절대경로 금지(09-22) |
| blob_path | text | 허용 |  | 2단계 데이터 파이프라인 Flow 설계 후보 칸(09-16 아키텍트 반영). CAS(blobs/{sha256 앞 2자}/{sha256}) 채택이 2단계로 미뤄져 현재는 쓰지 않는다 |
| file_name | text | 불가 |  | 원본 파일명(서버 저장명 포함) |
| content_type | varchar | 허용 |  | MIME 타입. 길이 미정 |
| collected_at | timestamp | 불가 |  | 원본 바이트 저장 완료 시각. 요청 시각은 collection_attempt |
| request_params | text | 불가 |  | 인증값 제거 JSON. 키 원문 대신 credential_ref만; collection_attempt와 같은 규약 |
| response_code | varchar | 허용 |  | 레거시 원문 응답 코드 보존. 판정에는 collection_attempt.http_status와 source_result_code를 각각 사용 |
| collect_status | collect_status_enum | 불가 |  | 실제 저장된 바이트 상태. 바이트 없는 요청 실패는 collection_attempt에만 기록 |

- UNIQUE: (source, source_object_key, version_seq)
- UNIQUE: (raw_object_id, document_id)
- FK: (document_id) → document(document_id)

## fund_group

| 칼럼 | 논리 타입 | NULL | 키 | 설명 |
|---|---|---|---|---|
| fund_key | varchar | 불가 | PK | 09-20 고정 서러게이트. 이름 변경에도 유지; 상품 행을 재해싱하지 않음 |
| canonical_name | text | 불가 |  |  |
| manager_id | int | 불가 | FK |  |
| created_run_id | varchar | 불가 | FK | 최초 발급한 EXTRACT run |
| grouping_evidence | text | 불가 |  | JSON. 모자/호수/유형을 보존한 매칭 근거와 최초 원천키 |
| representative_risk_grade | int | 허용 |  | 1~6(CHECK). 등급이 있으면 근거 문서·구분 필수(적재 검증). 작성기준일은 근거 문서의 document.report_base_date를 씀(중복 칼럼 없음). v2.2 결정 대기(10월 4일 판단 항목). 펀드 대표 위험등급 1~6. 규칙은 [데이터 테이블·ERD 설계](data-model.md) 「상품과 법인」(종류형 펀드는 등급 하나). 출처가 없으면 NULL이며 통계에서 사유와 함께 제외. 반대 결정 시 이 칼럼 3개를 제거하고 product.risk_grade로 층 배정 |
| risk_grade_source_document_id | int | 허용 | FK | 대표 등급을 읽은 문서. representative_risk_grade가 있으면 필수 |
| risk_grade_source_kind | risk_grade_source_enum | 허용 |  | 간이투자설명서 표제인지 투자설명서 표지인지. 간이가 있으면 간이 우선(PM 결정) |

- FK: (manager_id) → distributor(distributor_id)
- FK: (created_run_id) → pipeline_run(run_id)
- FK: (risk_grade_source_document_id) → document(document_id)

## pipeline_run

| 칼럼 | 논리 타입 | NULL | 키 | 설명 |
|---|---|---|---|---|
| run_id | varchar | 불가 | PK | 실행 식별자. 같은 실행 안의 요청 재시도에는 유지하고, 실패한 채점 실행을 다시 돌릴 때는 새 run_id 발급. run_kind로 추출 실행과 채점 실행을 구분([데이터 테이블·ERD 설계](data-model.md) 「실행과 비교 모집단」) |
| run_kind | run_kind_enum | 불가 |  | EXTRACT: 수집·추출·절·매칭·fund_group. SCORE: 대상·점수·모집단. 전체 처리 1회 = EXTRACT 1개 + 그것을 참조하는 SCORE 1개 |
| upstream_run_id | varchar | 허용 | FK | SCORE는 필수(참조하는 EXTRACT run). EXTRACT는 NULL. 대상은 SUCCEEDED인 EXTRACT run이고 baseline_date가 같아야 함(적재 검증) |
| is_official | boolean | 불가 |  | 기본 false. 대시보드/API가 서빙하는 공식 채점 실행. SCORE run만 true 가능, 동시에 true는 최대 1개(적재 검증). SUCCEEDED에서만 허용. 기준일별 과거 스냅숏 서빙은 서빙 계약 결정(검토 번호 B5, [데이터 테이블·ERD 설계](data-model.md) 「미결」)에서 확장 |
| published_at | timestamp | 허용 |  | 마지막으로 is_official을 true로 바꾼 시각. 공식 해제 시에도 지우지 않음. 전체 게시/해제 로그는 2단계 데이터 파이프라인 Flow 설계의 감사 로그 |
| baseline_date | date | 불가 |  | SCORE run은 upstream EXTRACT run과 같은 값(적재 검증). 기준일 변경은 새 EXTRACT + 새 SCORE |
| status | run_status_enum | 불가 |  | 실행 완료 이후 결과는 불변. 예외는 is_official/published_at 두 칼럼만 |
| config_manifest | text | 불가 |  | JSON: 파서/전처리/산식/매칭 버전, 용어 사전·고지 감점표·LLM 프롬프트 버전(09-22), 축간 정규화 가중치·임계값 설정, 소스 컷오프, 소스코드 버전. EXTRACT는 파서/매칭 부분, SCORE는 산식/평가자/모집단 부분이 유효 |
| config_sha256 | varchar(64) | 불가 |  |  |
| input_manifest_path | text | 허용 |  | SCORE run은 사용한 (raw_object_id, parser_version) 목록을 고정하며 upstream EXTRACT run이 만들지 않은 이전 실행의 추출 결과·절도 허용. 사용한 raw_object 목록과 상품/매칭/위험등급/판매관계 스냅숏. 완료 실행에 필수. SCORE run은 upstream EXTRACT의 manifest 해시를 함께 기록 |
| input_manifest_sha256 | varchar(64) | 허용 |  |  |
| selection_manifest_path | text | 허용 |  | path와 sha256은 함께 있거나 함께 비어야 하고 SCORE 완료 실행에는 필수(적재 검증). v2.2 병합 결과. SCORE run의 대상 선택 근거·대표본 정책 버전·펀드별 역할별 대표 문서(투자설명서 대표, 간이 대표)를 기록한 파일. RAW_ROOT 상대경로. 간이 대표 역할은 enum 없이 이 파일에 역할별로 기록(10월 4일 판단 항목, 결정 대기). EXTRACT run은 NULL |
| selection_manifest_sha256 | varchar(64) | 허용 |  |  |
| started_at | timestamp | 불가 |  |  |
| completed_at | timestamp | 허용 |  |  |

- FK: (upstream_run_id) → pipeline_run(run_id)
- 산식·가중치·평가자 설정만 바뀌면 새 SCORE run을 만들고 기존 EXTRACT run을 가리킨다. file_extraction·section을 다시 적재하지 않는다(v2.2: 같은 파일 x 파서 버전이면 새 EXTRACT run에서도 다시 추출하지 않는다). 파서·입력 스냅숏이 바뀌면 새 EXTRACT run과 새 SCORE run.
- is_official은 "지금 대시보드가 보여줄 점수"의 유일한 포인터다. MAX(completed_at) 추론을 쓰지 않는다.


## collection_attempt

| 칼럼 | 논리 타입 | NULL | 키 | 설명 |
|---|---|---|---|---|
| attempt_id | int | 불가 | PK |  |
| run_id | varchar | 불가 | FK | EXTRACT run |
| source | varchar | 불가 |  |  |
| request_key | varchar | 불가 |  | 비밀값 제외 서비스+조회조건의 정규화 키 |
| attempt_no | int | 불가 |  |  |
| endpoint | text | 불가 |  | 인증 쿼리/헤더 제거 |
| request_params | text | 불가 |  | JSON; 인증키 원문 저장 금지 |
| document_id | int | 허용 | FK |  |
| raw_object_id | int | 허용 | FK | 응답 바이트 저장 시 연결. 타임아웃은 NULL; 동일 바이트 재수집은 기존 파일 재사용 |
| http_status | int | 허용 |  | HTTP 응답이 없으면 NULL |
| source_result_code | varchar | 허용 |  | 900/030/033 등 선행 0 보존. HTTP 상태와 분리 |
| result_count | int | 허용 |  |  |
| outcome | attempt_outcome_enum | 불가 |  |  |
| error_reason | text | 허용 |  |  |
| attempted_at | timestamp | 불가 |  |  |

- UNIQUE: (run_id, request_key, attempt_no)
- FK: (run_id) → pipeline_run(run_id)
- FK: (document_id) → document(document_id)
- FK: (raw_object_id) → raw_object(raw_object_id)

## file_extraction

| 칼럼 | 논리 타입 | NULL | 키 | 설명 |
|---|---|---|---|---|
| raw_object_id | int | 불가 | PK, FK |  |
| parser_version | varchar | 불가 | PK | v2.2. 추출 키 = 원본 파일 x 파서 버전(추출 실행 번호에서 변경). EXTRACT_OK 행이 있으면 다시 추출하지 않는다. 형식: 소문자·숫자·.-_ 만 허용(파일 경로에 쓰임). 전처리 버전을 포함한 값이다(전처리가 바뀌면 새 파서 버전). 예 pdftotext-24.02_prep-3 |
| created_run_id | varchar | 불가 | FK | 이 행을 마지막으로 쓴 EXTRACT run(출처 기록용, 키 아님). EXTRACT_OK 행은 불변이며 갱신하지 않는다. FAILED/PARTIAL 행은 다음 실행이 같은 키로 덮어쓸 수 있고 이때 이 칼럼을 그 실행으로 갱신한다. SCORE 입력 판별에 쓰지 않는다(입력은 SCORE run의 input manifest가 고정) |
| extract_status | raw_extract_status_enum | 불가 |  |  |
| canonical_text_path | text | 허용 |  | 공통 RAW_ROOT 기준 상대경로(storage-and-failure-rules.md 「파생 텍스트·실행 스냅숏 경로」). UTF-8/LF 파일 전체 텍스트. 추출 실패 시 NULL 가능. 표/페이지 구조 보존 계약은 records/phase1-erd/design-review-history.md 「미결정 포함 재검토(09-23)」 |
| canonical_text_sha256 | varchar(64) | 허용 |  |  |
| structure_manifest_path | text | 허용 |  | RAW_ROOT 상대경로. 페이지/블록 종류/좌표/강조/텍스트 구간 대응 JSON |
| structure_manifest_sha256 | varchar(64) | 허용 |  |  |
| structure_status | structure_status_enum | 불가 |  | 텍스트 추출 성공과 독립. AVAILABLE/PARTIAL이면 manifest 경로·해시 필수, 그 외 NULL |
| text_length | int | 허용 |  | Unicode code point 수. 절 끝의 MAX로 전체 길이를 추정하지 않음 |
| error_reason | text | 허용 |  |  |
| extracted_at | timestamp | 불가 |  |  |

- PK: (raw_object_id, parser_version)
- FK: (raw_object_id) → raw_object(raw_object_id)
- FK: (created_run_id) → pipeline_run(run_id)

## population_snapshot

| 칼럼 | 논리 타입 | NULL | 키 | 설명 |
|---|---|---|---|---|
| population_snapshot_id | int | 불가 | PK |  |
| run_id | varchar | 불가 | FK | SCORE run |
| baseline_date | date | 불가 |  | SCORE run의 baseline_date와 같아야 함(적재 검증). 칼럼 존치 여부는 [데이터 테이블·ERD 설계](data-model.md) 「미결」 |
| population_key | varchar | 불가 |  | 실행 안의 층 식별자. 다른 실행에서 같은 문자열을 재사용해도 다른 스냅숏 |
| observation_unit | observation_unit_enum | 불가 |  | fund_section은 동일 의미 절당 펀드 하나; CDI 산식 담당 합의 전 생성 금지 |
| metric_key | varchar | 불가 | FK | 이 층이 어느 지표의 모집단인지. 산식·집계 범위·정규화 방식은 metric_definition.definition_manifest가 정본(v2.1에서 중복 JSON 칼럼 삭제) |
| product_category | product_category_enum | 불가 |  |  |
| risk_grade | int | 허용 |  |  |
| fund_type | varchar | 허용 |  |  |
| product_class_code | varchar | 허용 |  |  |
| stratification_definition | text | 불가 |  | 실제 사용한 축/조건 JSON. 후보 축을 모두 자동 적용하지 않음 |
| member_count | int | 불가 |  | 클래스/절 개수가 아닌 고유 fund_key 수 |
| minimum_member_count | int | 불가 |  | 최종 층내 백분위는 09-23 조회본 기준 30. 적용 기준은 실행 설정에 고정; [점수 저장과 비교 모집단](scoring-and-population.md) 「정규화와 층내 백분위」 참조 |
| excluded_count | int | 불가 |  |  |
| exclusion_counts | text | 불가 |  | JSON. PENDING/NAME_ONLY, 위험등급 결측, 판매상태 미상, 문서 충돌 등. 배정불가 상품을 임의 층에 넣지 않음 |
| membership_manifest_path | text | 불가 |  | 포함/제외 회원과 근거 파일. 정의는 [데이터 테이블·ERD 설계](data-model.md) 「적재 검증 규칙」; n/평균/분위수만으로 백분위 재현 불가 |
| membership_manifest_sha256 | varchar(64) | 불가 |  |  |
| computed_at | timestamp | 불가 |  |  |

- UNIQUE: (run_id, metric_key, population_key) — v2.1: 같은 실행에서 같은 층을 여러 지표가 쓸 수 있으므로 metric_key 포함
- UNIQUE: (population_snapshot_id, run_id, metric_key) — score 복합 FK 대상
- FK: (run_id) → pipeline_run(run_id) — SCORE run
- FK: (metric_key) → metric_definition(metric_key)

## metric_definition

| 칼럼 | 논리 타입 | NULL | 키 | 설명 |
|---|---|---|---|---|
| metric_key | varchar | 불가 | PK | 지표 ID+불변 버전. 예 asl:v1, cdi:v1. 이름 재사용으로 정의 덮어쓰기 금지 |
| metric_id | varchar | 불가 |  |  |
| version | varchar | 불가 |  |  |
| target_type | target_type_enum | 불가 |  | 버전 하나의 계산 단위는 하나. 단위 변경 시 새 버전 |
| level | metric_level_enum | 불가 |  |  |
| direction | metric_direction_enum | 불가 |  | v2.1: JSON에서 칼럼으로 승격. 축 합산·백분위 방향 변환을 SQL에서 검증 가능하게 함 |
| definition_status | definition_status_enum | 불가 |  | DRAFT 결과는 공식 통계·API에 노출 금지. 승인 이력 표는 만들지 않는다(B8 채택 안 함, v2.2 수정 9). 승인 상태 변경 이력은 definition_manifest 또는 이 칼럼의 변경 기록으로 남긴다 |
| definition_manifest | text | 불가 |  | JSON: 단위, 산식, 분모, 입력/구조 요구, 적용범위, 결측, 집계 순서, 정규화, 승인 근거, 자산 상대경로+sha256. 방향은 direction 칼럼이 정본 |
| definition_sha256 | varchar(64) | 불가 |  |  |

- UNIQUE: (metric_id, version)
- UNIQUE: (metric_key, target_type) — score 복합 FK 대상(결정 B10)

## llm_field_extraction

| 칼럼 | 논리 타입 | NULL | 키 | 설명 |
|---|---|---|---|---|
| extraction_id | int | 불가 | PK | 내부 발급 서러게이트 키 |
| run_id | varchar | 불가 | FK | EXTRACT run |
| document_id | int | 불가 | FK |  |
| raw_object_id | int | 허용 | FK | 파일 단위로 추출했으면 그 파일, 문서 단위면 NULL. 이번 버전은 문서 단위로 확정(raw_object_id는 참조용 NULL 허용). 파일 단위로 바꾸면 raw_object_id를 유일키에 넣는다(결정 대기, data-model.md 「v2.2」). 근거 절은 같은 문서 소속이어야 함(적재 검증) |
| field_name | varchar | 불가 |  | 6필드 이름은 분석·리서치(민석)·데이터 사이언스(다빈)가 10월 5일 확정 전이라 값으로 둔다. 필드가 바뀌어도 표 구조는 그대로 |
| attempt_no | int | 불가 |  | 같은 run·문서·필드의 재시도 순번, 1부터 |
| model_name | varchar | 불가 |  | 실제 호출한 모델 이름 |
| prompt_sha256 | varchar(64) | 불가 |  | 프롬프트 원문 해시. 원문은 config_manifest가 가리키는 파일 |
| input_tokens | int | 허용 |  |  |
| output_tokens | int | 허용 |  |  |
| result_status | result_status_enum | 불가 |  | OK이면 value_json 필수. 호출·파싱 실패는 FAILED. 문서에서 값을 찾지 못한 「없음」 결과는 기존 enum 값(UNDETERMINED는 판정 불가, NOT_APPLICABLE은 해당 없음)에 맞는 것이 없어 정의 보류(data-model.md 「미결」) |
| value_json | text | 허용 |  | 추출한 값 JSON. 값·단위·적용 클래스는 3단계 입출력 Schema 설계(io-schema.md)에서 정의 |
| evidence_section_id | int | 허용 | FK | 근거 위치. 결정 B11 안 1과 같은 형식 (section, char_start, char_end). 근거가 없는 필드는 NULL |
| evidence_char_start | int | 허용 |  | section과 같은 기준(canonical text의 Unicode code point 반열린 구간), 해당 절 범위 안 |
| evidence_char_end | int | 허용 |  |  |
| model_params | text | 허용 |  | 모델 파라미터 JSON(temperature 등) |
| raw_response_path | text | 허용 |  | 원응답 저장 경로. runs/{run_id}/llm/{document_id}/{field_name}/attempt-{n}/response.json. RAW_ROOT 상대경로 |
| response_sha256 | varchar(64) | 허용 |  | response.json 바이트의 sha256. 채점 실행 완료 전 재대조에 쓴다 |
| is_selected | boolean | 불가 |  | 같은 문서·필드의 시도 중 최종 채택한 행. 문서·필드당 true는 최대 1개(적재 검증) |
| error_reason | text | 허용 |  |  |
| extracted_at | timestamp | 불가 |  |  |

- UNIQUE: (run_id, document_id, field_name, attempt_no)
- FK: (run_id) → pipeline_run(run_id)
- FK: (document_id) → document(document_id)
- FK: (raw_object_id) → raw_object(raw_object_id)
- FK: (evidence_section_id) → section(section_id)

## source_watermark

| 칼럼 | 논리 타입 | NULL | 키 | 설명 |
|---|---|---|---|---|
| source | varchar | 불가 | PK | document.source와 같은 이름공간 또는 소스/엔드포인트 이름 |
| scope_key | varchar | 불가 | PK | 비밀값 제외 서비스+조회조건의 정규화 키(collection_attempt.request_key 규약). 소스당 증분 축이 여러 개면 구분 |
| covered_from | date | 불가 |  | 검증한 구간의 시작 기준일(포함). 구간 [covered_from, covered_through] 전체가 완전성 검증을 통과해야 한다 |
| covered_through | date | 불가 |  | 이 날짜(포함)까지 받았다고 검증된 기준일. 증분 축은 소스별(DART rcept_dt, 금투협 standardDt 등, data-sources.md) |
| verified_run_id | varchar | 불가 | FK | 구간 완전성을 검증한 EXTRACT run |
| verification_note | text | 허용 |  | 검증 방법과 결과. 구간 완전성 검증(건수 대조, 페이지 끝 확인 등) 뒤에만 전진한다. 검증 실패·부분 응답이면 갱신하지 않고 기존 값을 유지 |
| updated_at | timestamp | 불가 |  |  |

- PK: (source, scope_key)
- FK: (verified_run_id) → pipeline_run(run_id)

## Enum 상태값

### product_category_enum

`펀드`, `ETF`, `ELS`

- `ELS`는 Phase 1 범위 밖(9차 미팅, 1차 구현은 펀드·ETF만). 값은 유지하며 Phase 2 검토

### etf_confidence_enum

`KRX_CONFIRMED`, `NAME_ONLY`, `NOT_ETF`, `PENDING`

### distributor_type_enum

`운용사`, `판매사`, `겸업`, `미상`

### document_type_enum

`투자설명서`, `간이투자설명서`, `일괄신고서`, `효력발생안내`, `제재공시`, `분쟁조정결정문`, `금투협 수시공시`, `경영유의공시`

### body_format_enum

`html`, `json`, `xml`, `zip`, `unknown`, `pdf`, `hwp5`, `hwp3`, `hwp_dist`, `xml_only`

### risk_grade_source_enum (v2.2, 결정 대기)

`SIMPLE_PROSPECTUS_TITLE`, `PROSPECTUS_COVER`

### match_method_enum

`code`, `string`, `manual`

### failure_reason_enum

`PENDING_MASTER`, `AMBIGUOUS`, `NO_CANDIDATE`, `NO_CODE_IN_SOURCE`, `BELOW_THRESHOLD`, `NORMALIZE_FAILED`, `CLASS_GRADE_MISMATCH`(v2.2, 결정 대기)

### match_failure_status_enum

`미해결`, `수동확인중`, `보류`, `해결`, `대상외`

### file_role_enum

`cover_html`, `cover_xml`, `body_pdf`, `api_response`, `attachment`, `prospectus`, `prospectus_simple`, `change_summary`

### collect_status_enum

`success`, `failed`, `permanent_failed`

### raw_extract_status_enum

`EXTRACT_OK`, `EXTRACT_FAILED`, `EXTRACT_UNSUPPORTED_FORMAT`, `EXTRACT_PARTIAL`, `OCR_CANDIDATE`, `EXTRACT_NOT_APPLICABLE`, `SECTION_BOUNDARY_NOT_FOUND`(v2.2, section 전용)

### parse_status_enum

`PARSE_OK`, `PARSE_PENDING`, `PARSE_NOT_APPLICABLE`, `PARSE_PARTIAL`, `PARSE_FAILED`

### result_status_enum

`PENDING`, `OK`, `NOT_APPLICABLE`, `UNDETERMINED`, `FAILED`

### target_type_enum

`SECTION`, `DOCUMENT`, `DOCUMENT_PAIR`, `FUND`

### run_kind_enum (v2.1)

`EXTRACT`, `SCORE`

### run_status_enum (v2.1, pipeline_run)

`PLANNED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`

### attempt_outcome_enum (v2.1)

`SUCCESS`, `EMPTY`, `RETRYABLE_FAILED`, `PERMANENT_FAILED`, `CONFIG_ERROR`, `RATE_LIMITED`

### structure_status_enum (v2.1)

`AVAILABLE`, `PARTIAL`, `UNAVAILABLE`, `NOT_REQUESTED`

### section_kind_enum (v2.1)

`body`, `summary`, `other`

### match_target_enum (v2.1)

`product`, `distributor`

### observation_unit_enum (v2.1)

`fund_document`, `fund_section`

### normalization_status_enum (v2.1)

`OK`, `NOT_REQUESTED`, `UNAVAILABLE`

### metric_level_enum (v2.1)

`ATOMIC`, `AXIS`, `COMPOSITE`, `TRANSFORM`

### definition_status_enum (v2.1)

`DRAFT`, `APPROVED`, `RETIRED`

### metric_direction_enum (v2.1)

`HIGHER_IS_HARDER`, `HIGHER_IS_BETTER`, `NONE`

### enum 적용 범위

- v2.1에서 상태값 전부 enum으로 통일
- 남은 varchar 코드 칼럼: 값 집합이 지표 계약·프로토콜에 따라 열려 있는 것만

| 칼럼 | varchar 유지 이유 |
|---|---|
| `score.reason_code`, `score.normalization_reason`, `score.assessor_key` | 지표 계약에 따라 값 집합이 열림 |
| `llm_field_extraction.field_name` | 6필드 이름이 10월 5일 확정 전이라 값으로 둠 |

- 대소문자: 기존 값이 소문자였던 `section_kind`·`match_target`·`observation_unit`은 소문자 유지, 새 enum은 대문자
- 조건부 규칙: 해당 칼럼 설명과 [데이터 테이블·ERD 설계](data-model.md) 「적재 검증 규칙」
- PK/FK/UNIQUE만으로 대상 역할·상태 조합·의존관계 순환·manifest 내용까지 검증 불가

## 공개 식별자 규칙 (v2.2)

| 구분 | 칼럼 | 근거 |
|---|---|---|
| 공개 API 식별자로 사용 | `document.document_id`, `product.product_id`, `fund_group.fund_key`, `distributor.distributor_id`, `section.section_id` | 실행(run)과 무관하게 안정적. v2.2에서 `section_id`의 키가 추출 실행이 아니라 원본 파일 × 파서 버전이 되어 절 드릴다운 링크에 run_id를 동반하지 않아도 같은 절을 가리킨다. 파서 버전이 바뀌면 새 절이 만들어지므로 공식 점수가 참조하는 절은 그 점수 행의 `section_id`로 해석한다 |
| 공개 가능하되 run 파라미터를 항상 동반 | `pipeline_run.run_id`, `metric_definition.metric_key` | "어느 채점 실행·어느 지표 버전의 점수인가"를 명시할 때. 기본값은 is_official=true인 SCORE run |
| 내부 전용, 응답에 노출 금지 | `score.score_id`, `score.target_key`, `raw_object_id`, 파일 경로 | run마다 바뀌는 서러게이트이거나 내부 파일 구조를 드러냄. 근거 구간은 서버가 `section_id` + `char_start/char_end` + 인용 텍스트로 해석해 내려준다(결정 B11 안 1). char 범위는 그 절의 파서 버전이 만든 canonical text 기준이다 |

- 승인된 공식 점수만 걸러주는 조회 계층(`is_official=true` AND `definition_status='APPROVED'`를 한 곳에 모으는 뷰): 서빙 계약과 함께 결정 예정(검토 번호 B5, [데이터 테이블·ERD 설계](data-model.md) 「미결」)
- 결정 전까지 모든 조회가 두 조건을 직접 걸어야 함

## 미결

| 질문 | 결정 주체 | 필요 시점 |
|---|---|---|
| 칼럼별 미결(자료형 길이, precision/scale, 표 존치) | [데이터 테이블·ERD 설계](data-model.md) 「미결」에서 일괄 관리 | 2026-09-30 |
