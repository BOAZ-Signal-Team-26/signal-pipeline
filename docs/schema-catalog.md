# 21. 스키마 명세 — 2026-09-23 v2.1

[DBML](schema.dbml)을 파싱해 정리한 20개 테이블의 전체 칼럼·키·관계·상태값이다. v2.1은 [22 검토](22_erd_v2_review.md)의 A 조치(실행 분리·공식 run 마커·모집단 유일키·enum 통일·지표 방향·공개 ID 규칙)를 반영한 상태이며 B 조치는 09-30 결정 전까지 미반영이다. 논리 검토안이며 물리 DB 구축이나 팀 승인을 뜻하지 않는다. NULL 허용은 구조적 허용이며 조건부 필수 규칙은 [20](20_erd_redesign.md)을 따른다. 복합 FK는 하나의 관계로 센다.

## product

| 칼럼 | 논리 타입 | NULL | 키 | 설명 |
|---|---|---|---|---|
| product_id | int | 불가 | PK | 내부 발급 서러게이트 키. 구체 자료형(int/bigint 등)·생성 방식은 관문 B 사안 |
| short_code | varchar(5) | 허용 |  | 단축코드 5자리 영숫자([A-Z0-9]{5}). DART 표지 펀드코드 = 공공데이터포털 srtnCd(J1,J2). 펀드·ETF 1차 조인 키. 전역 유일 아님(전체 165,118종 중 4,899종=3.0% 중복) — 2015년 이후 설정분·상장지수 1,435건 범위에서는 안전. 겹치면 (asoStdCd 앞 6자리, short_code) 조합으로 확장(14) |
| kofia_fund_code | varchar(12) | 허용 |  | 금투협 펀드코드 12자리 = K55+운용사3+단축5+검증1. 조인 키로는 J7(금투협 수시공시)에서만 쓰임 |
| standard_code | varchar(12) | 허용 |  | 협회표준코드(KR5.../KRM...). 공공데이터포털 asoStdCd. kofia_fund_code와 체계가 다름 |
| isu_cd | varchar | 허용 |  | 거래소 종목코드. ETF에만 값 존재(그 외 NULL). short_code와 잇는 코드성 수단이 없어 이름으로만 연결되고 완전일치 0.0%/포함매칭 80.4%(13, 미확인 2). 길이·형식은 문서에 근거 없어 미정 |
| fin_prdt_cd | varchar | 허용 |  | finlife 상품코드. J9로 확인됨 — finlife 오픈API 8종에 펀드·ETF·ELS 자체가 없어 조인 키로 성립하지 않는다. 소스 존치 여부 미정(09-16 안건). 길이·형식도 미정 |
| product_name | text | 불가 |  | 포털 fndNm 원문. DART 표지 명칭은 매칭 근거에 별도 보존 |
| product_name_normalized | text | 허용 |  | 05 1절 4단계 정규화(NFKC→공백 제거→(주)/주식회사 제거→유형괄호·호수·클래스 분리) 결과 |
| product_category | product_category_enum | 허용 |  | 분류 미확정이면 NULL. 펀드/ETF로 강제 배정하지 않음 |
| is_etf | boolean | 허용 |  | KRX_CONFIRMED=true, NOT_ETF=false, NAME_ONLY/PENDING=NULL |
| etf_confidence | etf_confidence_enum | 불가 |  | 13 반영, 신설 |
| fund_key | varchar | 허용 | FK | 고정 식별자(09-20 결정). 묶음 미확정이면 NULL, 통계에서 사유와 함께 제외 |
| risk_grade | int | 허용 |  | 1~6, 1이 최고위험. DART 투자설명서 표지 "N등급[문구]"에서 정규식(\\d)등급으로 추출. corp_code 조인이 아니라 문서→상품 경로로 채움. 위험등급 원천이 DART 하나만은 아닐 수 있음(금투협 첨부 PDF 본문에도 표기 확인, 16 3절, 미확인 22) — 04 3-2절 내생성 논증의 전제이므로 재검토 대상 |
| manager_id | int | 허용 | FK | 운용사/겸업 법인. 포털에 운용사 필드가 없어 매핑 전 NULL 허용 |
| inception_date | date | 허용 |  | 포털 setpDt 설정일. 유효 달력일만 변환; 더미는 NULL과 원천 보존. 판매개시일과 다름 |
| sale_start_date | date | 허용 |  | 확인된 판매개시일. 설정일을 사실값처럼 복사하지 않음 |
| sale_end_date | date | 허용 |  | 종료일 미상은 NULL. NULL 자체가 판매 중의 증거는 아님. 06의 후보/확인 범위 구분 |
| fund_type | varchar | 허용 |  | 공공데이터포털 fndTp. 04에서 위험등급의 보조 층화축 후보로만 확보. 코드 형식·길이 미정 |
| product_class_code | varchar | 허용 |  | 공공데이터포털 prdClsfCd. 코드 형식·길이 미정 |
| is_public_offering | boolean | 허용 |  | 공모/사모. 필터는 적재 단계에서 적용하고 원본은 구분 없이 전량 보관(00b A8) |
| source_raw_object_id | int | 허용 | FK | 현재 상품 값을 공급한 포털 응답 파일. basDt와 원천 행 키로 역추적 |
| source_baseline_date | date | 허용 |  | 원천 basDt. 설정일/수집일과 구분 |
| risk_grade_raw_object_id | int | 허용 | FK | 현재 위험등급의 DART 표지 또는 금투협 첨부 근거. 과거 값은 실행 입력 manifest에 고정 |
| valid_from | date | 허용 |  | SCD2 예비 칸(00b 반영, 신설). 물리화 여부는 관문 B 사안 — 지금은 이력을 두지 않으면 변경 이력이 영구 소실된다는 문제만 인지된 상태 |
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
| corp_code | varchar | 허용 |  | DART 법인 고유번호(공시 제출 법인=운용사). 원래 상품 표에 있던 것을 이관(문서→상품 경로로 위험등급을 채우기 위한 결정과 연동). document.corp_code와 값 체계가 같아 보이나 이 문서 어디에도 FK로 명시돼 있지 않아 관계선을 긋지 않았다(01 ERD "그림에 넣지 않은 것" #1). 길이 미정 |
| kofia_mgmt_code | varchar(3) | 허용 |  | 금투협 운용사 코드 3자리 영숫자(예: 105=삼성자산운용, 301=미래에셋자산운용). 대응표 536건 = reference/kofia_mgmt_codes.csv |
| distributor_name | text | 불가 |  | 원문명 |
| distributor_name_normalized | text | 허용 |  | 05 9절 5단계 법인명 정규화(NFKC→구상호 치환→법인격 표기 제거→공백 제거→지점 표기 제거) 결과. 상품명용 1절 규칙을 쓰지 않는다 — 법인명에는 클래스 표기가 없고 대신 상호 변경이 있다 |
| distributor_type | distributor_type_enum | 불가 |  |  |


## product_distributor

| 칼럼 | 논리 타입 | NULL | 키 | 설명 |
|---|---|---|---|---|
| product_id | int | 불가 | PK, FK |  |
| distributor_id | int | 불가 | PK, FK |  |
| snapshot_month | varchar(6) | 불가 | PK | YYYYMM. 09-20 신설. 이 칸 없이 (product_id, distributor_id)로 upsert하면 매달 과거 판매 관계를 소리 없이 덮어쓴다 |
| source_raw_object_id | int | 불가 | FK | 판매사별 펀드 API 응답. source_document_id가 NULL이어도 출처 보존 |
| observed_date | date | 불가 |  | 실제 조회 기준일 tmpV30/tmpV16. snapshot_month의 대표일 정책은 18 참조 |
| source_document_id | int | 허용 | FK | 이 연결을 알려준 문서. 확정된 현재 경로(금투협 전자공시 "판매사별 펀드보수비용" 코드 조회, J8)에서는 명단이 문서가 아니라 별도 API 조회에서 오므로 항상 NULL이다(14). 문서 경로가 추가되면 NULL 허용 여부를 재검토 |

- PK: (product_id, distributor_id, snapshot_month)
- FK: (product_id) → product(product_id)
- FK: (distributor_id) → distributor(distributor_id)
- FK: (source_raw_object_id) → raw_object(raw_object_id)
- FK: (source_document_id) → document(document_id)

## document

| 칼럼 | 논리 타입 | NULL | 키 | 설명 |
|---|---|---|---|---|
| document_id | int | 불가 | PK | 내부 발급 서러게이트 키 |
| source | varchar | 불가 |  | 소스/엔드포인트 이름공간. dart, kofia_disclosure, fss_sanction, fss_improvement, fss_dispute |
| source_doc_key | varchar | 불가 |  | source 안에서 유일한 원천 식별자. DART rcept_no, 금투협 4필드 해시. 제재공시는 emOpenNo가 아니라 후보 복합키, 18 참조 |
| source_key_payload | text | 불가 |  | 키 생성 전 원천 필드 JSON. 제재 API 후보는 examMgmtNo/emOpenSeq/transCode/actGbn. 빈 키/충돌은 격리 |
| source_record_payload | text | 허용 |  | 제재 13필드 등 원천 레코드 JSON. API 응답 파일의 원문도 별도 보존 |
| action_date | date | 허용 |  | 제재 actReqDate. 공시 입력/접수 날짜와 다름 |
| source_input_at | timestamp | 허용 |  | 제재 inputDate. 원문 문자열과 시간대 해석은 payload에 보존 |
| rcept_no | varchar | 허용 |  | DART 접수번호. DART 전용 칸(00b 반영) — 그 외 소스는 NULL. 자릿수는 문서에 근거 없어 미정 |
| dcm_no | varchar | 허용 |  | DART 문서번호. download.do?dcmNo=로 본문 PDF를 받을 때 필요. DART 전용 칸. 길이 미정 |
| corp_code | varchar | 허용 |  | DART 법인코드(제출 법인=운용사). distributor.corp_code와 값 체계가 같아 보이나 FK로 명시된 바 없어 관계선을 긋지 않았다(01 ERD "그림에 넣지 않은 것" #1). 길이 미정 |
| document_type | document_type_enum | 불가 |  |  |
| report_name | text | 허용 |  | DART 보고서명 원문(예: "[기재정정] 투자설명서"). document_type은 이 값에서 파생 |
| pblntf_detail_ty | varchar(4) | 허용 |  | DART 세부유형 코드 G001/G002/G003. 수집 필터는 이 코드로, 문서 종류 판별은 report_name으로 — 둘을 섞으면 누락 발생(A2) |
| distributor_id | int | 허용 | FK | 상품 연결이 없는 문서(분쟁조정·제재공시 등)를 판매사 축에 붙이기 위한 칼럼. nullable. 분쟁조정은 판매사명도 마스킹이라 이 값조차 못 채운다 — "문서 표에만 존재하는 미연결 레코드"가 정상 상태다(14, 미확인 4) |
| is_correction | boolean | 허용 |  | DART 구조로 판정. 미판정/금투협 연결 규칙 미확정은 NULL, false로 만들지 않음 |
| lineage_id | int | 허용 | FK | 같은 사건 최초 문서. 확인된 원본만 self; 원본 미도착/계보 미확정은 NULL |
| version_no | int | 허용 |  | 파생 칼럼(00b 반영, 신설). lineage 안에서 received_date 순번 |
| is_current | boolean | 허용 |  | 파생 칼럼(00b 반영, 신설). 물리 칼럼으로 둘지는 관문 B 이력 설계에서 결정 |
| initial_submit_date | date | 허용 |  | 정정본이면 정정신고 요소에 적힌 최초제출일. 원본이면 received_date와 같다 |
| received_date | date | 불가 |  | 접수일자 |

- UNIQUE: (source, source_doc_key)
- FK: (distributor_id) → distributor(distributor_id)
- FK: (lineage_id) → document(document_id)

## document_product

| 칼럼 | 논리 타입 | NULL | 키 | 설명 |
|---|---|---|---|---|
| document_id | int | 불가 | PK, FK |  |
| product_id | int | 불가 | PK, FK |  |
| match_method | match_method_enum | 불가 |  | 01 상품 표의 3단 계단식(1차 코드 → 2차 정규화 펀드명 → 3차 운용사명+설정일) 중 어느 단에서 붙었는지 |
| match_score | decimal | 허용 |  | 매칭 점수. 코드 매칭이면 1.0, 문자열 매칭이면 유사도. precision/scale은 문서에 근거 없어 미정 |
| matched_at | timestamp | 불가 |  |  |

- PK: (document_id, product_id)
- FK: (document_id) → document(document_id)
- FK: (product_id) → product(product_id)

## section

| 칼럼 | 논리 타입 | NULL | 키 | 설명 |
|---|---|---|---|---|
| section_id | int | 불가 | PK | 내부 발급 서러게이트 키 |
| document_id | int | 불가 | FK |  |
| raw_object_id | int | 불가 | FK |  |
| run_id | varchar | 불가 | FK | EXTRACT run. section_id는 이 run 안의 서러게이트이며 새 EXTRACT run에서는 새로 발급된다(공개 링크는 (run_id, section_id) 쌍) |
| section_seq | int | 불가 |  | 한 파일/실행 안의 전역 순번. 부 안의 절 번호와 다름 |
| part_seq | int | 허용 |  | 원문 부 번호. 요약 등 부 체계 밖 구간은 NULL |
| source_section_no | varchar | 허용 |  | 원문 절 번호. 부마다 반복되며 비숫자 번호도 보존 |
| section_kind | section_kind_enum | 불가 |  | summary도 실제 원문 구간, 가짜 집계 절 생성 금지 |
| char_start | int | 허용 |  | file_extraction의 canonical text 기준 0-based Unicode code point 시작 |
| char_end | int | 허용 |  | 같은 텍스트 기준 exclusive 끝. 성공한 절은 0 <= start < end <= text_length |
| quality_flags | text | 허용 |  | JSON 배열. SHORT_TEXT 등 계산 적합성 표시; 추출 실패와 구분 |
| section_title | text | 허용 |  |  |
| section_text | text | 허용 |  | canonical text의 [char_start,char_end) 구간. 실패 시 복구된 텍스트 또는 NULL. 지표용 전처리는 별도 버전으로 추적 |
| extract_status | raw_extract_status_enum | 불가 |  | 추출 성패. 짧다는 이유만으로 실패 처리하지 않는다(03) |

- UNIQUE: (raw_object_id, run_id, section_seq)
- UNIQUE: (section_id, run_id)
- UNIQUE: (section_id, raw_object_id, run_id)
- FK: (document_id) → document(document_id)
- FK: (raw_object_id, run_id) → file_extraction(raw_object_id, run_id)
- FK: (raw_object_id, document_id) → raw_object(raw_object_id, document_id)

## score

| 칼럼 | 논리 타입 | NULL | 키 | 설명 |
|---|---|---|---|---|
| score_id | int | 불가 | PK | 내부 발급 서러게이트 키 |
| target_id | int | 불가 | FK |  |
| run_id | varchar | 불가 | FK | SCORE run. 산식·평가자·모집단 기준이 바뀌면 새 SCORE run(추출 결과는 upstream EXTRACT run 재사용) |
| metric_key | varchar | 불가 | FK | 불변 지표 버전. ASL/축값/CDI/백분위도 서로 다른 지표로 명시 가능 |
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
| score_payload | text | 불가 |  | JSON 계약 v2: 항목별 충족/미충족/해당없음/판정불가, 적용수/평가완료수, 근거 member_id+block_id, 전처리/단위/커버리지. 20 참조 |
| scored_at | timestamp | 불가 |  |  |

- UNIQUE: (run_id, target_id, metric_key, assessor_key)
- UNIQUE: (score_id, run_id)
- FK: (run_id) → pipeline_run(run_id)
- FK: (metric_key) → metric_definition(metric_key)
- FK: (target_id, run_id) → analysis_target(target_id, run_id)
- FK: (population_snapshot_id, run_id, metric_key) → population_snapshot(population_snapshot_id, run_id, metric_key)

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
| normalized_value | text | 허용 |  | 05 1절 4단계 정규화를 거친 문자열. 코드 매칭이면 NULL |
| top1_candidate_product_id | int | 허용 | FK | 유사도가 가장 높았던 상품. 없으면 NULL. 후보일 뿐 실제 매칭이 아니다 |
| top1_similarity | decimal | 허용 |  | 그 후보의 유사도 점수. precision/scale 미정 |
| failure_reason_code | failure_reason_enum | 불가 |  |  |
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
| sha256 | varchar(64) | 불가 |  | 파일 콘텐츠 해시(hex 다이제스트, 64자). 02의 재수집 시 버전 증가 여부·중복 저장 판정 키. 동일 바이트 검출에 사용한다. 해시가 다르더라도 요약/본문의 내용 중복은 가능하므로 대표 문서 선택을 대체하지 않는다 |
| storage_path | text | 불가 |  | 02_raw_storage_policy.md의 raw/{source}/{collected_date}/{object_key_hash}/{file_role}__v{version_seq}.{ext} 규칙. RAW_ROOT 기준 상대경로만 저장, 절대경로 금지(09-22) |
| blob_path | text | 허용 |  | 관문 B 후보 칸(09-16 아키텍트 반영). CAS(blobs/{sha256 앞 2자}/{sha256}) 채택이 관문 B로 미뤄져 현재는 쓰지 않는다 |
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

- FK: (manager_id) → distributor(distributor_id)
- FK: (created_run_id) → pipeline_run(run_id)

## pipeline_run

| 칼럼 | 논리 타입 | NULL | 키 | 설명 |
|---|---|---|---|---|
| run_id | varchar | 불가 | PK | 실행 식별자. 같은 실행 재시도에는 유지. run_kind로 추출 실행과 채점 실행을 구분(22 A2) |
| run_kind | run_kind_enum | 불가 |  | EXTRACT: 수집·추출·절·매칭·fund_group. SCORE: 대상·점수·모집단. 전체 처리 1회 = EXTRACT 1개 + 그것을 참조하는 SCORE 1개 |
| upstream_run_id | varchar | 허용 | FK | SCORE는 필수(참조하는 EXTRACT run). EXTRACT는 NULL. 대상은 SUCCEEDED인 EXTRACT run이고 baseline_date가 같아야 함(적재 검증) |
| is_official | boolean | 불가 |  | 기본 false. 대시보드/API가 서빙하는 공식 채점 실행. SCORE run만 true 가능, 동시에 true는 최대 1개(적재 검증). SUCCEEDED에서만 허용. 기준일별 과거 스냅숏 서빙은 22 B5에서 확장 |
| published_at | timestamp | 허용 |  | 마지막으로 is_official을 true로 바꾼 시각. 공식 해제 시에도 지우지 않음. 전체 게시/해제 로그는 Gate B 감사 로그 |
| baseline_date | date | 불가 |  | SCORE run은 upstream EXTRACT run과 같은 값(적재 검증). 기준일 변경은 새 EXTRACT + 새 SCORE |
| status | run_status_enum | 불가 |  | 실행 완료 이후 결과는 불변. 예외는 is_official/published_at 두 칼럼만 |
| config_manifest | text | 불가 |  | JSON: 파서/전처리/산식/매칭 버전, 용어 사전·고지 감점표·LLM 프롬프트 버전(09-22), 축간 정규화 가중치·임계값 설정, 소스 컷오프, 소스코드 버전. EXTRACT는 파서/매칭 부분, SCORE는 산식/평가자/모집단 부분이 유효 |
| config_sha256 | varchar(64) | 불가 |  |  |
| input_manifest_path | text | 허용 |  | 사용한 raw_object 목록과 상품/매칭/위험등급/판매관계 스냅숏. 완료 실행에 필수. SCORE run은 upstream EXTRACT의 manifest 해시를 함께 기록 |
| input_manifest_sha256 | varchar(64) | 허용 |  |  |
| started_at | timestamp | 불가 |  |  |
| completed_at | timestamp | 허용 |  |  |

- UNIQUE: (run_id, upstream_run_id) — analysis_target 복합 FK 대상
- FK: (upstream_run_id) → pipeline_run(run_id)
- 산식·가중치·평가자 설정만 바뀌면 새 SCORE run을 만들고 기존 EXTRACT run을 가리킨다. file_extraction·section을 다시 적재하지 않는다. 파서·입력 스냅숏이 바뀌면 새 EXTRACT run과 새 SCORE run.
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
| run_id | varchar | 불가 | PK, FK | EXTRACT run |
| extract_status | raw_extract_status_enum | 불가 |  |  |
| canonical_text_path | text | 허용 |  | 공통 RAW_ROOT 기준 상대경로(02). UTF-8/LF 파일 전체 텍스트. 추출 실패 시 NULL 가능. 표/페이지 구조 보존 계약은 19 R5 |
| canonical_text_sha256 | varchar(64) | 허용 |  |  |
| structure_manifest_path | text | 허용 |  | RAW_ROOT 상대경로. 페이지/블록 종류/좌표/강조/텍스트 구간 대응 JSON |
| structure_manifest_sha256 | varchar(64) | 허용 |  |  |
| structure_status | structure_status_enum | 불가 |  | 텍스트 추출 성공과 독립. AVAILABLE/PARTIAL이면 manifest 경로·해시 필수, 그 외 NULL |
| text_length | int | 허용 |  | Unicode code point 수. 절 끝의 MAX로 전체 길이를 추정하지 않음 |
| error_reason | text | 허용 |  |  |
| extracted_at | timestamp | 불가 |  |  |

- PK: (raw_object_id, run_id)
- FK: (raw_object_id) → raw_object(raw_object_id)
- FK: (run_id) → pipeline_run(run_id)

## population_snapshot

| 칼럼 | 논리 타입 | NULL | 키 | 설명 |
|---|---|---|---|---|
| population_snapshot_id | int | 불가 | PK |  |
| run_id | varchar | 불가 | FK | SCORE run |
| baseline_date | date | 불가 |  | SCORE run의 baseline_date와 같아야 함(적재 검증). 칼럼 존치 여부는 22 L4 |
| population_key | varchar | 불가 |  | 실행 안의 층 식별자. 다른 실행에서 같은 문자열을 재사용해도 다른 스냅숏 |
| observation_unit | observation_unit_enum | 불가 |  | fund_section은 동일 의미 절당 펀드 하나; DS 합의 전 생성 금지 |
| metric_key | varchar | 불가 | FK | 이 층이 어느 지표의 모집단인지. 산식·집계 범위·정규화 방식은 metric_definition.definition_manifest가 정본(22 A1: 중복 JSON 칼럼 삭제) |
| product_category | product_category_enum | 불가 |  |  |
| risk_grade | int | 허용 |  |  |
| fund_type | varchar | 허용 |  |  |
| product_class_code | varchar | 허용 |  |  |
| stratification_definition | text | 불가 |  | 실제 사용한 축/조건 JSON. 후보 축을 모두 자동 적용하지 않음 |
| member_count | int | 불가 |  | 클래스/절 개수가 아닌 고유 fund_key 수 |
| minimum_member_count | int | 불가 |  | 최종 층내 백분위는 09-23 조회본 기준 30. 적용 기준은 실행 설정에 고정; 20 참조 |
| excluded_count | int | 불가 |  |  |
| exclusion_counts | text | 불가 |  | JSON. PENDING/NAME_ONLY, 위험등급 결측, 판매상태 미상, 문서 충돌 등. 배정불가 상품을 임의 층에 넣지 않음 |
| membership_manifest_path | text | 불가 |  | 포함/제외 회원과 근거 파일. 정의는 18; n/평균/분위수만으로 백분위 재현 불가 |
| membership_manifest_sha256 | varchar(64) | 불가 |  |  |
| computed_at | timestamp | 불가 |  |  |

- UNIQUE: (run_id, metric_key, population_key) — 22 A1: 같은 실행에서 같은 층을 여러 지표가 쓸 수 있으므로 metric_key 포함
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
| direction | metric_direction_enum | 불가 |  | 22 A4: JSON에서 칼럼으로 승격. 축 합산·백분위 방향 변환을 SQL에서 검증 가능하게 함 |
| definition_status | definition_status_enum | 불가 |  | DRAFT 결과는 공식 통계·API에 노출 금지. 승인 이력 저장 위치는 미결(22 B8) |
| definition_manifest | text | 불가 |  | JSON: 단위, 산식, 분모, 입력/구조 요구, 적용범위, 결측, 집계 순서, 정규화, 승인 근거, 자산 상대경로+sha256. 방향은 direction 칼럼이 정본 |
| definition_sha256 | varchar(64) | 불가 |  |  |

- UNIQUE: (metric_id, version)

## analysis_target

| 칼럼 | 논리 타입 | NULL | 키 | 설명 |
|---|---|---|---|---|
| target_id | int | 불가 | PK | 내부 전용. 공개 API 식별자는 document_id, 그리고 run_id를 동반한 section_id(22 A7) |
| run_id | varchar | 불가 | FK | SCORE run |
| extraction_run_id | varchar | 불가 | FK | 22 A2: 절·파일이 속한 EXTRACT run. (run_id, extraction_run_id) → pipeline_run(run_id, upstream_run_id) 복합 FK로 upstream과 같음을 강제 |
| target_type | target_type_enum | 불가 |  |  |
| target_key | varchar(64) | 불가 |  | 20에 정의한 종류/앵커/정렬한 입력 역할·파일·구간의 정규 JSON SHA-256. run 안의 재시도 멱등성 키이며 run 간 동일 대상 탐지 키가 아님. 공개 ID로 쓰지 않음 |
| section_id | int | 허용 | FK | SECTION만 필수, 다른 유형은 NULL |
| document_id | int | 허용 | FK | DOCUMENT만 필수. 다른 유형은 NULL; 실제 파일 귀속은 member에서 확인 |
| fund_key | varchar | 허용 | FK | FUND만 필수. 다른 유형은 NULL; 통계 연결은 실행 입력/모집단 manifest |
| selection_manifest | text | 불가 |  | 대상 선택 근거, 대표본 정책 버전, 쌍의 방향/목적. 입력은 member에 전부 명시 |

- UNIQUE: (run_id, target_key)
- UNIQUE: (target_id, run_id) — score·evaluation_response 복합 FK 대상
- UNIQUE: (target_id, extraction_run_id) — analysis_target_member 복합 FK 대상
- FK: (run_id) → pipeline_run(run_id)
- FK: (run_id, extraction_run_id) → pipeline_run(run_id, upstream_run_id) — 22 A2: 채점 run의 upstream이 곧 추출 run
- FK: (document_id) → document(document_id)
- FK: (fund_key) → fund_group(fund_key)
- FK: (section_id, extraction_run_id) → section(section_id, run_id) — 22 A2: 채점 run이 아니라 추출 run으로 연결

## analysis_target_member

| 칼럼 | 논리 타입 | NULL | 키 | 설명 |
|---|---|---|---|---|
| member_id | int | 불가 | PK | 내부 전용. API 응답에 노출하지 않음(22 A7) |
| target_id | int | 불가 | FK | SCORE run은 analysis_target에서 조회(중복 칼럼 없음) |
| extraction_run_id | varchar | 불가 | FK | 22 A2: 파일/절이 속한 EXTRACT run. 대상과 같아야 하며 복합 FK로 강제 |
| member_role | member_role_enum | 불가 |  |  |
| member_seq | int | 불가 |  | 같은 역할 안의 1-based 순번 |
| raw_object_id | int | 불가 | FK |  |
| section_id | int | 허용 | FK | 절 전체 참조 시 선택. 파일/추출 실행 일치 복합 FK |
| char_start | int | 허용 |  | 둘 다 NULL이면 파일 전체, 아니면 canonical text의 반열린 구간 |
| char_end | int | 허용 |  |  |

- UNIQUE: (target_id, member_role, member_seq)
- FK: (target_id, extraction_run_id) → analysis_target(target_id, extraction_run_id)
- FK: (raw_object_id, extraction_run_id) → file_extraction(raw_object_id, run_id)
- FK: (section_id, raw_object_id, extraction_run_id) → section(section_id, raw_object_id, run_id)

## score_dependency

| 칼럼 | 논리 타입 | NULL | 키 | 설명 |
|---|---|---|---|---|
| output_score_id | int | 불가 | PK, FK |  |
| input_score_id | int | 불가 | PK, FK |  |
| run_id | varchar | 불가 | FK |  |
| input_role | varchar | 불가 | PK | 축/절/정규화 전 값 등 산식의 입력 역할 |
| applied_weight | decimal | 허용 |  | 실제로 사용한 가중치, 가중 합산이 아니면 NULL |

- PK: (output_score_id, input_score_id, input_role)
- FK: (output_score_id, run_id) → score(score_id, run_id)
- FK: (input_score_id, run_id) → score(score_id, run_id)

## evaluation_run

| 칼럼 | 논리 타입 | NULL | 키 | 설명 |
|---|---|---|---|---|
| evaluation_run_id | varchar | 불가 | PK |  |
| scoring_run_id | varchar | 불가 | FK |  |
| track | evaluation_track_enum | 불가 |  | 서로 다른 조건의 실행은 분리 |
| protocol_manifest_path | text | 불가 |  | 쌍 선정/문항·정답/채점기준/순서/조건/모델/프롬프트/반복/분석계획, 가명 참여자와 계획 응답 슬롯. RAW_ROOT 상대경로 |
| protocol_manifest_sha256 | varchar(64) | 불가 |  |  |
| response_manifest_path | text | 허용 |  | 불변 원응답 모음. 재채점은 동일 파일 참조와 새 evaluation_run, 원응답 수집 이력 보존 |
| response_manifest_sha256 | varchar(64) | 허용 |  |  |
| summary_manifest_path | text | 허용 |  | 집계·통계 결과 및 포함 response_id 목록. 원응답 대체 불가 |
| summary_manifest_sha256 | varchar(64) | 허용 |  |  |
| status | run_status_enum | 불가 |  | SUCCEEDED는 계획 슬롯 terminal + 채점 완료를 뜻하며 효과 검증 성공이 아님 |
| started_at | timestamp | 허용 |  |  |
| completed_at | timestamp | 허용 |  |  |

- UNIQUE: (evaluation_run_id, scoring_run_id)
- FK: (scoring_run_id) → pipeline_run(run_id)

## evaluation_response

| 칼럼 | 논리 타입 | NULL | 키 | 설명 |
|---|---|---|---|---|
| response_id | int | 불가 | PK |  |
| evaluation_run_id | varchar | 불가 | FK |  |
| scoring_run_id | varchar | 불가 | FK |  |
| target_id | int | 불가 | FK | 평가에 제시한 단일 문서/구간 대상. WITHOUT_DOCUMENT도 비교 대상 ID는 유지 |
| pair_key | varchar | 불가 |  | protocol_manifest 내부 문서쌍 키. 서로 다른 설문 문항 체계는 별도 protocol |
| respondent_key | varchar | 불가 |  | 가명 참여자 또는 모델 설정 키. 이름/연락처는 저장하지 않음 |
| question_key | varchar | 불가 |  | protocol_manifest의 불변 문항·정답·채점기준 키 |
| condition | evaluation_condition_enum | 불가 |  |  |
| repetition_no | int | 불가 |  |  |
| presentation_order | int | 불가 |  |  |
| response_status | response_status_enum | 불가 |  |  |
| raw_response | text | 허용 |  | 원응답. ANSWERED이면 필수; 빈 문자열도 실제 제출이면 허용 |
| grading_status | grading_status_enum | 불가 |  |  |
| graded_value | decimal | 허용 |  | GRADED일 때 필수. 응답 누락을 0점으로 만들지 않음 |
| reason_code | varchar | 허용 |  |  |
| response_payload | text | 불가 |  | JSON: 채점자/근거/실제 모델·설정/입력 잘림 여부/토큰/재시도/수집시간/원응답 출처와 해시. 20 참조 |

- UNIQUE: (evaluation_run_id, pair_key, respondent_key, target_id, question_key, condition, repetition_no)
- FK: (evaluation_run_id, scoring_run_id) → evaluation_run(evaluation_run_id, scoring_run_id)
- FK: (target_id, scoring_run_id) → analysis_target(target_id, run_id)

## Enum 상태값

### product_category_enum

`펀드`, `ETF`, `ELS`

### etf_confidence_enum

`KRX_CONFIRMED`, `NAME_ONLY`, `NOT_ETF`, `PENDING`

### distributor_type_enum

`운용사`, `판매사`, `겸업`, `미상`

### document_type_enum

`투자설명서`, `간이투자설명서`, `일괄신고서`, `효력발생안내`, `제재공시`, `분쟁조정결정문`, `금투협 수시공시`, `경영유의공시`

### body_format_enum

`html`, `json`, `xml`, `zip`, `unknown`, `pdf`, `hwp5`, `hwp3`, `hwp_dist`, `xml_only`

### match_method_enum

`code`, `string`, `manual`

### failure_reason_enum

`PENDING_MASTER`, `AMBIGUOUS`, `NO_CANDIDATE`, `NO_CODE_IN_SOURCE`, `BELOW_THRESHOLD`, `NORMALIZE_FAILED`

### match_failure_status_enum

`미해결`, `수동확인중`, `보류`, `해결`, `대상외`

### file_role_enum

`cover_html`, `cover_xml`, `body_pdf`, `api_response`, `attachment`, `prospectus`, `prospectus_simple`, `change_summary`

### collect_status_enum

`success`, `failed`, `permanent_failed`

### raw_extract_status_enum

`EXTRACT_OK`, `EXTRACT_FAILED`, `EXTRACT_UNSUPPORTED_FORMAT`, `EXTRACT_PARTIAL`, `OCR_CANDIDATE`, `EXTRACT_NOT_APPLICABLE`

### parse_status_enum

`PARSE_OK`, `PARSE_PENDING`, `PARSE_NOT_APPLICABLE`, `PARSE_PARTIAL`, `PARSE_FAILED`

### result_status_enum

`PENDING`, `OK`, `NOT_APPLICABLE`, `UNDETERMINED`, `FAILED`

### target_type_enum

`SECTION`, `DOCUMENT`, `DOCUMENT_PAIR`, `FUND`

### run_kind_enum (v2.1)

`EXTRACT`, `SCORE`

### run_status_enum (v2.1, pipeline_run·evaluation_run 공유)

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

### member_role_enum (v2.1)

`PRIMARY`, `SUMMARY`, `BODY`, `EVIDENCE`, `LEFT`, `RIGHT`

### evaluation_track_enum (v2.1)

`HUMAN`, `LLM`

### evaluation_condition_enum (v2.1)

`WITH_DOCUMENT`, `WITHOUT_DOCUMENT`

### response_status_enum (v2.1)

`PENDING`, `ANSWERED`, `MISSING`, `ABORTED`, `FAILED`

### grading_status_enum (v2.1)

`PENDING`, `GRADED`, `UNGRADABLE`, `NOT_APPLICABLE`

상태값은 v2.1에서 모두 enum으로 통일했다(22 A3). 남은 varchar 코드 칼럼은 `score_dependency.input_role`(표 자체가 22 B1 보류 대상), `score.reason_code`, `score.normalization_reason`, `score.assessor_key`, `evaluation_response.reason_code`처럼 값 집합이 지표 계약·프로토콜에 따라 열려 있는 것만이다. 기존 값이 소문자였던 `section_kind`/`match_target`/`observation_unit`은 소문자를 유지했고 새 enum은 대문자다. 조건부 규칙은 해당 칼럼 설명 및 20을 따른다. PK/FK/UNIQUE만으로 대상 역할·상태 조합·의존관계 순환·manifest 내용까지 검증되지는 않는다.

## 공개 식별자 규칙 (v2.1, 22 A7)

| 구분 | 칼럼 | 근거 |
|---|---|---|
| 공개 API 식별자로 사용 | `document.document_id`, `product.product_id`, `fund_group.fund_key`, `distributor.distributor_id` | 실행(run)과 무관하게 안정적 |
| 공개 가능하되 run 파라미터를 항상 동반 | `section.section_id`, `pipeline_run.run_id`, `metric_definition.metric_key` | `section_id`는 EXTRACT run마다 새로 발급되는 서러게이트라 단독으로는 안정적이지 않다. 절 드릴다운 링크는 `(run_id, section_id)` 쌍이어야 공식 run 교체 뒤에도 해석 가능하다. 이때 run_id는 `section.run_id`(EXTRACT run)이다. 클라이언트가 SCORE run_id를 보내면 서버가 `upstream_run_id`로 해석한다. run_id·metric_key는 "어느 채점 실행·어느 지표 버전의 점수인가"를 명시할 때. 기본값은 is_official=true인 SCORE run |
| 내부 전용, 응답에 노출 금지 | `analysis_target.target_id`/`target_key`, `analysis_target_member.member_id`, `score.score_id`, `score_payload` 안의 `member_id`/`block_id`, `raw_object_id`, 파일 경로 | run마다 바뀌는 서러게이트이거나 내부 파일 구조를 드러냄. 근거 구간은 서버가 `(run_id, section_id)` + `char_start/char_end` + 인용 텍스트로 해석해 내려준다. char 범위는 그 EXTRACT run의 canonical text 기준이다 |

"승인된 공식 점수만" 걸러주는 조회 계층(`is_official=true` AND `definition_status='APPROVED'`를 한 곳에 가두는 뷰)은 서빙 계약과 함께 22 B5에서 결정한다. 그 전까지 모든 조회는 두 조건을 직접 걸어야 한다.
