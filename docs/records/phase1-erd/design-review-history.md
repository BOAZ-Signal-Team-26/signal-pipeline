# ERD 설계 변천과 검토 기록

## 개요

| 항목 | 값 |
|---|---|
| 단계 | 1단계 데이터 테이블·ERD 설계(9월 16일) 근거 기록 |
| 범위 | ERD 판 변천(9 → 14 → 20개 표)과 세 차례 검토 기록 |
| 검토 | 09-22 재검토, 09-23 미결정 포함 재검토, 09-23 v2 6관점 검토 |
| 현행 설계 | [데이터 테이블·ERD 설계](../../data-model.md), [스키마 명세](../../schema-catalog.md), [DBML](../../schema.dbml) |
| 작업 기록 원본 | 저장소 루트 [WORK_LOG](../../../WORK_LOG.md) |
| 읽는 법 | 각 절의 14표·절 전용 score·NOT NULL 설명은 당시 구조. 현행 제약으로 적용하지 않음 |

## 변천 요약

| 날짜 | 판 | 표 | 관계 | enum | 주요 변경 | 검증 |
|---|---|---|---|---|---|---|
| 09-16~20 | 초기 논리 스키마 | 9 | — | — | 상품(클래스)·판매사·상품_판매사·문서·문서_상품·절·점수·매칭_실패·원본파일 | 조인 키 대조표(현재 [조인 키 확인 기록](join-key-checks.md)) |
| 09-22 | 재검토안 | 14 | 31 | — | fund_group, collection_attempt, pipeline_run, file_extraction, population_snapshot 추가 | `@dbml/core` 파싱, Mermaid 관계 31개 일치 |
| 09-23 | v2 | 20 | 45 | — | score 대상 일반화, 표 6개 추가 | — |
| 09-23 | v2.1 | 20 | 47 | 30 | 6관점 검토의 즉시 반영 조치: 실행 분리·공식 run 마커·모집단 유일키·enum 통일·지표 방향·공개 ID 규칙 | `@dbml/core` 파싱, Mermaid 관계 47개 일치 |

## 9표 → 14표 재검토(09-22)

### 판정과 범위

- 판정: 큰 방향은 적절. 기존 9개 표를 그대로 적재 구현에 쓰기에는 키·입도·계보·결측 처리 누락
- 유지한 것: 상품 클래스와 공시 문서의 N:M 분리, 원본 불변, 펀드 단위 통계, 마스킹된 분쟁조정을 상품에 강제로 붙이지 않는 점
- 성격: Notion과 저장소를 대조한 설계 수정안
  - 수행하지 않은 것: 생산 DB 변경, 크롤러 실행, 외부 API 재수집, Notion 편집, Notion 완료 상태·담당자 승인 변경
  - 당시 남은 것: 09-30 칼럼/인계 승인, 10-07 저장 계층 선택, 10-14 최종 JSON 계약
- 원칙: 실측 결과와 팀 결정은 근거로 인용. 그 위에 선택한 칼럼·타입·제약은 「09-22 제안」으로 구분
- 방법: 요구사항 대조·대안 비교·결정 기록 방식(architecture 스킬) 적용

### 09-22 이력 (당시 논리 스키마 문단)

- 기존 9개 표에 fund_group, collection_attempt, pipeline_run, file_extraction, population_snapshot을 더해 14개
- 앞의 셋을 raw_object에 합치면 상품 묶음·요청·실행 단위가 파일 단위와 충돌
- 실행별 추출 결과가 없으면 과거 절 재현 불가
- 대안과 비용: [데이터 테이블·ERD 설계](../../data-model.md) 「표 설계 근거」

### 대조한 Notion 근거

| 근거 | 확인한 요구 / 상태 |
|---|---|
| [7차 미팅 09-20](https://app.notion.com/p/3e1e1ac70505814c8283ffa6c472d8d8) 안건 4 | 성공 상태값, 펀드 단위 통계, fund_key 고정, run_id 통일, 모집단 별도 표의 팀 결정 |
| [데이터 테이블·ERD 산출물](https://app.notion.com/p/3e0e1ac705058115b023e714be75b2c8) | 9개 표와 아직 실제 칸으로 옮기지 않은 실행/모집단, 남은 6개 조사 |
| [Schema & Relation 티켓](https://app.notion.com/p/3d6e1ac7050581f3aa6cda6e22f7d119) | 논리 스키마·원본·실패 규칙의 인계 범위 |
| [Join 확인 티켓](https://app.notion.com/p/3d6e1ac705058146938bd512f410364b) | 소스별 코드·문자열·연결 불가 구분 |
| [Week 4](https://app.notion.com/p/3e1e1ac70505813984f1f64af2fe9090) | DART·포털·KRX 우선, 금투협·금감원은 Week 5, 09-30 인계 |
| [Flow·서버 환경 티켓](https://app.notion.com/p/3e1e1ac7050581f5b9e4c3331a1f17b1) | run_id 발급·모집단 생성 지점, DB는 10-07 이후 |
| [CDI 산출 단위](https://app.notion.com/p/3d6e1ac7050581d3a541d488e1b0f3ce) | 절 채점·펀드 통계 확정, 짧은 절 처리는 변수표로 이관 |
| [CDI 4축 변수 티켓](https://app.notion.com/p/3d6e1ac7050581568e30e53cb38f56a7) | 절/문서/문서쌍 계산 단위 구분 필요, 공식·일부 임계값 미정 |
| [CDI 참고문헌 검토](https://app.notion.com/p/3e1e1ac7050581b8b8cee9281c108348) | ASL에서 표 제외하지만 고지용 표 정보 보존, 요약-본문 비교, 높은 CDI=어려움 |
| [6필드 확정 티켓](https://app.notion.com/p/3e1e1ac7050581c4ae29c5f64334390c) | 유형·판매사·위험등급·수수료·원금손실·핵심 위험의 이름/타입/출처 절 미확정 |
| [판매사별 제재 라벨 티켓](https://app.notion.com/p/3e1e1ac7050581c6856fe90d677dad68) | 제재 API 8건으로 과거 전수 라벨 불가. 게시판 경로 검토 필요 |
| [데이터 소스 실측 문서](https://app.notion.com/p/3e0e1ac70505814387aecac5b73ef7cf) | 원천 응답과 접근 제약 |
| [09-20 티켓 대조 기록](https://app.notion.com/p/3e1e1ac7050580ecbef4e3cf0f9dd223) | asoStdCd 체계 및 DART status=014 관련 조사 |
| [초기 프로젝트 최종안](https://app.notion.com/p/3c1e1ac70505809c87b8db8a2b52065e) | 프로젝트 목적. 이후 변경된 소스/검증 방식의 최종 근거로 쓰지 않음 |

- 조회 당시 09-21 편집본과 본문에 09-22 실측이 적힌 자료를 함께 읽음
- 편집일만으로 권위를 정하지 않음. 회의 결정·실측·초기 제안의 차이 반영

### 수정한 결함

| 우선순위 | 기존 문제 | 반영 |
|---|---|---|
| P0 | emOpenNo가 8/8 공백인데 문서 자연키로 지정 | 소스 이름공간 + 검사/순번/구분 후보 복합키, 원천 키 payload·충돌 격리 |
| P0 | ERD의 short_code UK가 실측 중복과 충돌 | UK 제거. 후보 코드 매칭 후 전체 코드/운용사 확인 |
| P0 | 절 → 문서만 연결돼 어느 첨부/바이트인지 모름 | 절 → 파일·실행 복합 FK, 파일 → 문서 일치 FK |
| P0 | run_id·모집단은 채택됐지만 주석에만 존재 | pipeline_run·population_snapshot과 실제 FK |
| P0 | 같은 원본의 파서 재실행이 파일 상태를 덮어씀 | file_extraction의 (raw_object_id, run_id) PK |
| P0 | 타임아웃에도 raw_object의 해시/경로 필수 | collection_attempt로 바이트 없는 실패 표현, raw는 실제 파일 |
| P0 | 문서 FK가 없는 포털/KRX/목록 응답을 저장할 수 없음 | raw_object.document_id nullable + source/object key |
| P1 | fund_key가 매번 계산되는 파생키로 남음 | fund_group 고정 키와 상품 FK, 모자·호수 보존 |
| P1 | 포털에 운용사가 없는데 manager_id 필수 | 연결 전 NULL 허용. 임의 운용사 생성 금지 |
| P1 | 판매사코드가 없어서 확인된 코드 조인을 구현 못 함 | kofia_sales_code, 판매관계 API 원본 FK·observed_date |
| P1 | 미확정 정정 계보를 NOT NULL로 강제 | is_correction/lineage_id NULL 허용 |
| P1 | 일반 비ETF/판정 보류의 boolean·enum 조합 불완전 | NOT_ETF 추가, 보류의 is_etf/category는 NULL |
| P1 | 부마다 반복되는 절 번호, 전체 텍스트 위치 소실 | 전역 순번 + 원문 부·절 + canonical text의 시작/끝 |
| P1 | 500자 미만=추출 실패가 정상 짧은 절을 제거 | 추출 성패와 SHORT_TEXT/계산 적합성 분리 |
| P1 | 날짜 미상=판매 중, 설정일=판매시작일 | inception_date 분리, 확인/후보/미상 구분 |
| P1 | 해시 동일=정정 아님 / 문서=펀드라는 과도한 가정 | 파일 중복·공시 정정·대표본 선택을 구분 |
| P1 | n/평균/분위수만 보존하면 과거 백분위 재현 불가 | 입력·모집단 구성원 manifest와 해시 |
| P1 | XML/PDF 두 파일의 meta.json 이름 충돌 | 모든 소스에서 파일 식별자·역할·버전 포함 |
| P1 | 응답 0건을 일괄 실패 처리 | 정상 EMPTY, 요청 검증 실패, API 오류·한도 구분 |
| P1 | 수집 파라미터 전체 저장이 API 키를 남김 | 비밀값 제거 JSON, credential_ref만 |
| P1 | 제재 사건일과 공시 입력일 보관 칸 부재 | action_date와 source_input_at 분리 |
| P1 | 법인 후보를 상품 실패 FK에 넣을 수 없음 | target_type와 법인 후보 FK, 해결 상태 |

- P0: 적재/재현을 직접 막는 결함. P1: 잘못된 연결·모집단·품질 판정으로 이어지는 결함
- 실제 운영 장애 이력이라는 뜻 아님

### 저장된 표본 재집계

- 새 API 호출이 아니라 저장소 CSV를 읽어 확인

| 표본 | 재집계 | 의미 |
|---|---|---|
| fss_sanctions_sample.csv | 8행, emOpenNo 공백 8행 | 기존 자연키 사용 불가 |
| 같은 표본 | (examMgmtNo, emOpenSeq, transCode, actGbn) 8종 | 후보키 사용 가능성. 8건 유일성이 전체·미래 유일성을 증명하지 않음 |
| 같은 표본 | actOrganCon의 '-' 1, actOfficerCon의 '-' 1, actEmpCon의 '-' 3 | 기존 현황표의 7/8·7/8·5/8은 '-' 개수와 반대로 적힘. 원천 문자열 보존 |
| dart_sections_sample.csv | 9문서, 294행, 찾음 O 292 / X 2 | 절 위치 검증 표본. 전체 본문 추출 성공률 아님 |
| 같은 표본 | (문서, 절번호) 126종 / (문서, 부, 절번호) 294종 | 절 번호 반복을 설계에서 반드시 구분 |
| kofia_sales_companies.csv | 200행, saleCompCd 200종, 전부 6자리 | 운용사 3자리 코드와 분리된 판매사 코드 필요 |

- DART CSV는 제목·시작행·찾음 여부만 있음 → 실제 절 길이 분포·500자 미만 비율 계산 불가
- 금투협 코드 중복률·ETF 매칭률 등 전건 수치는 09-19~20 실측 인용. 새로 전수 수집했다고 주장하지 않음
- 표본 파일: [research/samples](../../../research/samples/)

### 당시 구조의 score 제약

- 09-22 당시: score PK = score_id, `(run_id, section_id, score_type)` UNIQUE, `section_id` NOT NULL, `raw_score` NOT NULL
- v2가 대체. 현행으로 적용하지 않음

### 검증 기록 (09-22)

- 저장 CSV 3종 직접 재집계(위 표)
- `@dbml/core` 실제 파서로 14개 테이블 구문·참조 해석 성공. 검증 중 section의 indexes 블록 뒤에 칼럼이 있던 문법 오류 수정
- DBML과 Mermaid의 테이블 이름 집합 14개 일치, 부모→자식 관계(중복 포함) 31개 일치. 누락됐던 raw_object→section 관계 추가. Mermaid 이미지 렌더링은 미실행
- PostgreSQL SQL 내보내기 스모크 검증 성공(메모리 생성만). DB 제품 선택·물리 DDL 승인·실제 DB 적용 아님
- 변경한 Markdown과 보고서의 상대 파일 링크 21개 존재 확인. `git diff --check` 통과
- 소스 현황표의 제재 `-` 개수를 1/8·1/8·3/8로 정정. 과거 0건 응답으로 연간 전수·보존 정책을 단정한 설명과 KRX 차집합을 상장폐지로 확정한 설명 수정
- 논리 제안이므로 DB 마이그레이션 적용·운영 데이터 무결성 검증 완료 아님

## 미결정 포함 재검토(09-23)

- 검토 기준: 당시 로컬 저장소와 아래 Notion 조회본
- 당시 상태: 14개 표가 현행 논리 검토안, 최종 표 수 미정. 16개/17개는 구현 대안의 예이지 완료 보장 아님
- 회의 승인·생산 코드 구현·DB 적용을 대신하지 않음

### 근거와 상태

| 출처 | 확인한 상태 | 설계에 반영하는 수준 |
|---|---|---|
| [데이터 테이블·ERD](https://app.notion.com/p/3e0e1ac705058115b023e714be75b2c8) | 최종 재조회 편집시각 2026-09-22T15:30:30.986Z. 14개 표와 Mermaid 반영 | 본문 갱신 확인. 외부 대화형 아티팩트 내용은 미검증 |
| [8차 미팅 09-23](https://app.notion.com/p/3e3e1ac7050581929ac1defef0e90b7e) | 09-22 작성, 상태는 안건 사전 정리. 결정처럼 쓴 문장과 미체크 항목 공존 | 점수화·사람/LLM 병행 방향을 설계 입력으로 반영. 세부안 승인으로 해석하지 않음 |
| [9차 미팅 09-30](https://app.notion.com/p/3e3e1ac705058124ae0ad164ff707615) | 사전 안건. 점검표 분모·근거 절·적용 서류 미해결 | 후보 절/미완성 점검표를 확정 입력으로 사용하지 않음 |
| [CDI 4축 변수표 티켓](https://app.notion.com/p/3d6e1ac7050581568e30e53cb38f56a7) | 개발 중, 계산 단위 열·합산 공식·분모 필요 | 지표별 계약 승인 전 표 개수 확정 금지 |
| [CDI 산출 단위](https://app.notion.com/p/3d6e1ac7050581d3a541d488e1b0f3ce) | 절 채점·펀드 통계, 짧은 절 처리 이관 | 유지 |
| [저장소 구성](https://app.notion.com/p/3e2e1ac70505818cbf66d63c9b45e782) | 09-22 저장소 3개 결정. 폴더 구조·보호 규칙은 초안, 이전 작업 미완료 | 구조 결정과 실제 개명·이관 완료를 구분 |
| [파이프라인 Flow](https://app.notion.com/p/3e1e1ac7050581f5b9e4c3331a1f17b1) | 입력 설명에 아직 9개 표 표현 | 14개 논리안 참조로 동기화 필요 |

- 같은 ERD 페이지의 최초 ID 조회는 09-21의 9개 표 본문 반환. 검색 결과와 충돌해 URL로 재조회하여 14개 표 본문 확인. 첫 조회만으로 갱신 실패 판정하지 않음
- 페이지 날짜가 회의일이라고 회의가 완료된 것 아님
- 8차 미팅 말미의 「미결 없음」이 본문의 미체크 결정 항목을 해소하지 않음

### 제기한 문제와 v2 해소 위치

- 결론: 두 영역(문서/쌍 지표, 검증 결과)의 확장은 필요하지만 두 표로 고정할 수 없음

| 검토 번호 | 문제 | 닫을 조건(당시) | v2 해소 위치 |
|---|---|---|---|
| R1 | 문서·펀드 최종 점수와 백분위의 저장 계약 없음. `score.section_id` NOT NULL, `score.normalized_score`는 절 비교용 | metric_id/산식 버전, 계산 대상, 원자값→축값→최종값 의존, 집계·정규화 순서, 출력값·계산불가 사유 위치, fund_key/대표 파일/모집단 연결 승인 | analysis_target(DOCUMENT/FUND), metric_definition, score_dependency |
| R2 | 「검증 결과 표 하나」는 평가 단위 결정 전의 가정. 사람 트랙(같은 유형 3쌍·총 18명·문서당 4문항·역균형 제안)과 LLM 트랙(문항 수 미정)의 단위가 다름. 참고문헌의 12문항을 확정값으로 옮기지 않음 | 가명 참여자/모델, 문서쌍·파일/구간, 문항·정답·채점기준 버전, 원응답·채점값, 제시 순서, with/without-document, 반복 ID, 모델/프롬프트/설정, 평가 대상 scoring run, 결측·중단 사유 | evaluation_run, evaluation_response (DBML 존치는 09-30 결정 대기) |
| R3 | 추출 성공과 채점 가능성 사이의 상태 저장 없음. `raw_score` NOT NULL이라 숫자 없는 결과를 행으로 못 남김 | 결과 상태·nullable 원점수. 0점 대입 금지. 고지 판정 충족/미충족/해당 없음/판정 불가 분리 | result_status + NULL raw_score, 고지 항목 판정 4종 |
| R4 | JSON 칸의 존재만으로 스키마 영향이 없어지지 않음. 복수 평가자·축별 기준 집단·다중 근거·문서 점수 드릴다운은 키 재검토 조건. JSON 안 ID는 DBML FK가 보장하지 않음 | payload에 계약 버전, metric_id, 값·단위·분모·상태·근거 정의 | assessor_key, 별도 metric_key/score 행, analysis_target_member, payload v2 |
| R5 | canonical text만으로 표·페이지·시각적 구조가 보존되지 않음. ASL 표 제외·표지 1페이지 이내 고지 계산에 페이지·블록 대응 필요 가능 | 지표 입력 요구 확인 후 구조 manifest 또는 블록/근거 관계 선택. 요약–본문 구간쌍·파일쌍의 방향·버전·중복 기준 | file_extraction.structure_status·structure_manifest, DOCUMENT_PAIR 규칙 |
| R6 | 고지 충실도 축의 점수화 방향과 산출 가능 상태를 구분해야 함. 배점·분모·적용 상품군·법적 서류 대응·근거 절은 열림 | 후보 절 보존, 빈 항목을 미충족 판정하지 않음 | [점수 저장과 비교 모집단](../../scoring-and-population.md) 「CDI와 고지 충실도」·「미결」 |
| R7 | 경로·버전 계약을 수집 동결 전에 구체화해야 함. RAW_ROOT가 raw/의 상위인지 raw/ 자체인지 정하지 않으면 raw/raw 중복 경로 | 파생 텍스트·입력·모집단 manifest에도 같은 이식성 원칙. 자산은 불변 파일 참조 + 내용 해시 | RAW_ROOT 상대경로 규칙, 자산 경로+sha256 |

- R2 보충: 관계형 분리 저장과 평가 실행 + 불변 응답 manifest를 비교. SQL 조회 요구가 낮으면 파일 보존도 가능. 표 하나로 모든 입도를 합치는 것도 자동으로 적절하지 않음
- R3 보충: 성공 점수만 score에 저장하고 시도/제외 사유를 실행 결과 manifest에 보존하는 대안도 검토
- R7 보충: LLM은 모델·설정·실제 응답을 남겨도 제공자 내부 변경에 따른 동일 출력까지 보장하지 않음

### 유지할 부분과 결정 후 바뀔 부분 (당시)

| 구분 | 현재 처리 | 닫는 기준 |
|---|---|---|
| 원본/요청/추출/절의 실행 계보 | 14개 표 기반 유지 | 수집 09-25 계약 동결 시 source_object_key·상태·상대경로 규약 확인 |
| 점수화 방향·버전 보존 | 최신 안건 반영, 산식 확정은 분리 | 다빈·민석의 계산 단위/분모/근거/적용범위 승인 |
| 문서/쌍 지표와 검증 결과 | 확장 영역 2개, 표 수 미정 | 위 R1~R5에 맞춘 행 단위·키·저장 위치 승인 |
| 모집단 구성원 | 파일 manifest 유지 가능 | SQL 역조회/운영 요구가 있을 때 member 표 검토 |
| 저장소 3개 | 구성 결정 기록 | 개명·권한·이관·링크 변경은 별도 실행 작업 |
| 노션 ERD/외부 아티팩트 | 본문은 14개 확인, 동기화 결함 아래 명시 | 동일 DBML 기준으로 칼럼·제약·관계 검증 후 완료 판정 |

- 09-23 변수표 최소 항목: 지표별 단위, 입력 구간/형식, 분자·분모, 결측 상태, 산식/방향, 집계 순서, 출력 대상
- 이 표를 09-26 인계 초안 입력으로 쓰고 09-30 리뷰에서 미완료 행 명시
- 승인 전 예약 표를 빈 정의로 DBML에 추가하지 않음(당시 원칙. v2가 이 원칙을 건너뛴 점은 「v2 6관점 검토」에서 지적)
- 09-22 재검토 문서의 「아직 결정이 필요한 항목」 중 「확장 영역 2개(표 수 미정)」 행은 v2(20표)로 해소

### Notion 동기화 오류

- 14개로 늘린 본문에도 로컬 정본과 다르거나 승인 수준을 과장한 표현 잔존
  - 「DART 표지 XML + PDF라 2행」: 공개 표지는 HTML, API ZIP 내부 미확인. 파일 수 고정 금지
  - 「단축코드 5자리 하나=한 행」: 클래스 입도와 코드 유일성은 별개. 중복 후보 검증 필요
  - 「score PK=(실행, 절, 점수유형)」: 실제 PK는 score_id, 앞 조합은 UNIQUE
  - 「14→16개」, 「7개 결정은 표 변경 없음」: R1~R5 조건에 따라 달라지는 추정
  - 「09-22 물리화 완료」: DBML 논리 모델 반영이며 운영 DB 구축 아님
  - 파이프라인 티켓은 아직 9개 표를 입력으로 소개. 기존 회의 사실을 바꾸지 말고 현재 입력 버전을 덧붙이는 방식이 적절
- 노션 최신 본문·Mermaid 확인과 외부 대화형 ERD 아티팩트 갱신 검증은 별개. 아티팩트를 열어 검사하지 않았으므로 갱신 완료로 보고하지 않음

### 미체크 박스 집계

- 사용자가 확인해 준 사람·LLM 병행/사람 합친 안, 고지 충실도 점수화, 문서간 층내 백분위는 재논의하지 않음
- 8차 미팅 조회본의 미체크 박스: 10+7+7+8+4+3 = 39개. 요약의 34개와 다름
- 방향이 정해진 항목도 체크가 남아 있어 39개를 독립 미결 결정 수라고 부르지 않음
- 용어 빈도 합: 이 재검토 시점 관찰 7+0+6+3=16(총 17개로 적힘) → 09-23 회의록이 7+0+7+3=17로 정정 설명 포함
- 미결 항목별 권고 표: [점수 저장과 비교 모집단](../../scoring-and-population.md) 「CDI 지표 설계 권고(승인 아님)」

### 검증 (09-23 재검토)

- 변경 범위: 검토 기록·정책·DBML 주석 중심. 14개 표의 칼럼·키·관계를 임의 확정·추가하지 않음
- `@dbml/core` 파싱 성공: 14개 표, 31개 관계. 이전 판과 칼럼·타입·PK/NOT NULL/UNIQUE 속성 동일
- DBML과 Mermaid의 부모→자식 관계 목록(중복 포함) 일치
- 변경 Markdown 및 문서의 상대 파일 링크 24개 존재 확인, `git diff --check` 통과
- 미수행: 실제 DB 적용, CDI 계산, 외부 대화형 ERD 렌더링. Notion은 조회·대조만, 원문 수정 없음

## v2 재설계 결론

- 09-23 재검토의 R1~R7은 타당
- 기존 `score.section_id NOT NULL`, `raw_score NOT NULL`, `(run_id, section_id, score_type)` UNIQUE는 문서/쌍 지표, 숫자 없는 결과, 복수 평가자를 수용하지 못함
- 원응답·문서 최종값·구조 정보도 보존 필요
- 타당하지 않은 주장: 「두 영역이니 두 표 추가」, 「나머지는 JSON이므로 관계 변경 없음」
- 근거: [8차 미팅 09.23](https://app.notion.com/p/3e3e1ac7050581929ac1defef0e90b7e)(조회 편집시각 2026-09-23T09:35:04.418Z), [CDI 변수표 티켓](https://app.notion.com/p/3d6e1ac7050581568e30e53cb38f56a7), [기존 ERD](https://app.notion.com/p/3e0e1ac705058115b023e714be75b2c8), 당시 로컬 논리 스키마·점수 정책·09-22/09-23 검토 문서, Project-Management의 WBS
- 8차 회의록 결론 칸은 비어 있고 세부 선택 체크도 남음
  - 반영: 사람·LLM 병행, 고지 점수화, 층내 백분위 방향
  - 반영하지 않음: 의견란의 가중치·분모·임계값을 승인된 산식으로 만드는 것
- 기존 티켓에는 과거 4인 동의가 체크됨. 프로젝트 관리 문서의 미기록 표기와 다름
  - 과거 체크 보존, v2의 별도 인수는 미완료로 기록
- 선택한 구조(14 → 20개)와 대안: [데이터 테이블·ERD 설계](../../data-model.md) 「표 설계 근거」

## v2 6관점 검토

### 검토 개요

| 항목 | 값 |
|---|---|
| 검토 대상 | v2(20표·FK 45개) 시점의 DBML, ERD 재설계 문서, 스키마 명세 |
| 검토자 | architect, data-engineer, data-scientist, platform-engineer, cloud-architect, backend-developer (AI 에이전트 6개, 파일 수정 없음) |
| 분담 | 표 판정은 앞의 5개 관점, backend는 API·서빙 관점만 |
| 성격 | 팀 승인된 최종 결정 아님 |
| 반영 후 정본 | v2.1(20표·FK 47개): [DBML](../../schema.dbml), [스키마 명세](../../schema-catalog.md), [데이터 테이블·ERD 설계](../../data-model.md) |

- 원 검토의 파일:줄 번호 근거는 반영 전 파일 기준이라 생략. 원문은 git 이력의 원 검토 문서

### 한줄 결론

- 진단은 맞고 처방이 과함
- 기존 score의 `section_id`·`raw_score` NOT NULL 결함 수정은 필요
- 20개 표는 규모상 문제없음(run당 약 8M행, 5~10GB 추정)
- 새 표 6개 중 3개(metric_definition, analysis_target, analysis_target_member 축소)는 유지, 3개(score_dependency, evaluation_run, evaluation_response)는 미승인 산식·프로토콜을 표로 먼저 반영한 것이라 보류 대상
- 표가 늘어난 근거(문서/쌍 대상, 숫자 없는 결과, 복수 평가자)는 정당
- 같은 날 09-23 재검토가 「물리 표 수는 아직 정하지 않는다」, 「승인 전 예약 표를 빈 정의로 DBML에 추가하지 않는다」, 「표 수는 그다음」이라 적었고 v2가 이를 건너뜀
- 표 개수보다 큰 비용: run_id 하나가 수집·추출·채점을 묶는 복합 FK 사슬, DBML 밖 조건부 규칙 약 40개
- 가장 많이 겹친 결함은 `pipeline_run` 한 표(실행 종류 분리·상류 참조·공식 run 마커)로 모임
- 표 제외 여부는 09-30 팀 결정 필요

### 새 표 6개 판정

| 표 | 판정 | 5인 중 동의 | 이유 |
|---|---|---|---|
| metric_definition | 유지(얇게) | 5/5 | score_type enum 2값 고정 대체. 칼럼 최소화 |
| analysis_target | 유지 | 4/5 (architect는 score 병합 제안) | 절/문서/쌍/펀드 대상 실제 요구. FUND 대표문서 선택 기준 미문서화 |
| analysis_target_member | 축소 유지 | 4/5 | SECTION까지 PRIMARY member 강제 → target.section_id와 중복. PAIR 역할은 프로토콜 확정 후 |
| score_dependency | 보류 | 5/5 | 집계 공식·가중치 DRAFT. 14표 ADR을 뒤집는데 대체 ADR 없음 |
| evaluation_run | 보류/별도 영역 | 5/5 | 프로토콜 미정. 파일 manifest로 충분 |
| evaluation_response | 보류/별도 영역 | 5/5 | 사람 실험 원응답을 수집 DB에 섞음. 접근제한 메커니즘 없음 |

### 발견 사항

| 검토 번호 | 심각도 | 항목 | 내용 | 지적 관점 |
|---|---|---|---|---|
| C1 | CRITICAL | run_id 복합 FK 사슬 | score→target→member→file_extraction/section + 「산식 변경은 새 run」 → 가중치만 바꿔도 추출·절 재적재. evaluation_run도 같은 형태 | architect, platform, cloud |
| C2 | CRITICAL | population_snapshot UNIQUE 충돌 | (run_id, population_key)에 metric_key 필요. 같은 층 두 지표면 충돌 | architect, backend |
| C3 | CRITICAL | pipeline_run 마커 부재 | 「공식/최신 run」 포인터 없음. run_kind(EXTRACT/SCORE) / upstream_run_id / 공식 마커 필요. analysis_target·member는 extraction_run_id로 추출 계층 참조 | architect, platform, data-engineer, backend |
| H1 | HIGH | 3단계 계약 선점 | payload v2, target_key, 구조 manifest, protocol이 미정 상태에서 스키마에 먼저 들어감 | architect, platform |
| H2 | HIGH | 물리 구현 지정 | 「CHECK/트리거로 구현」을 DB 선택 전에 정함(DuckDB 트리거 없음, SQLite FK 기본 OFF, BigQuery PK/FK 미강제) | platform, cloud |
| H3 | HIGH | 수집 API 명세 오해석 | 데이터 소스 API 명세는 대시보드 API가 아니라 수집 명세(「어떻게 호출해서 받아오는가」). 서빙 계층 계약 없음 | backend |
| H4 | HIGH | DRAFT 지표가 공식 점수에 섞임 | definition_status='APPROVED' 강제 지점 없음. 모든 조회가 조인을 기억해야 함. 승인 점수 뷰(score_current)로 단일화 필요 | data-scientist, backend |
| H5 | HIGH | 경로+sha 7쌍 산재 | artifact 표 + fsck 필요. DBML 밖 명세로 산재 | platform, cloud |
| H6 | HIGH | 원본 보관 경로 표 미갱신 | structure/protocol/response/summary manifest 경로 추가 필요. 2단계 입력 문서의 참조 갱신 필요 | platform |
| M1 | MEDIUM | 칼럼 이름 충돌 | population_snapshot.metric_definition text 칼럼이 동명 표와 이름 충돌·내용 중복 | architect, platform, cloud |
| M2 | MEDIUM | 상태 칼럼 혼재 | varchar 상태 칼럼 14개 vs enum 13개 혼재. 로더 오타가 오류 없이 통과 | architect, platform, cloud |
| M3 | MEDIUM | score.target_type 부재 | 「target_type 일치」 규칙이 3표 조인 트리거 | architect, platform |
| M4 | MEDIUM | 승인 이력 자리 없음 | definition_status 가변인데 승인 이력 저장 자리 없음. DRAFT 개발 출력 저장 위치 미정의 | architect, platform |
| M5 | MEDIUM | 쌍 목적이 JSON 안 | DOCUMENT_PAIR purpose(summary_body/comparison)가 selection_manifest JSON 안 → 역할 개수 CHECK 불가 | platform |
| M6 | MEDIUM | 평가 표와 완료 run 불변 모순 | 평가 표가 채점 run에 복합 FK. 완료 run 불변이라 미채점 문서 평가 시 모순. run 보존 정책 필요 | architect, cloud |
| M7 | MEDIUM | derived 경로에 서러게이트 ID | run_id, raw_object_id, population_snapshot_id 포함 → PK 재발급 시 경로 무효. manifest 내용 주소화 권고 | cloud |
| M8 | MEDIUM | target_key가 run별 section_id 포함 | run 간 동일 대상 탐지 불가. 「idempotency」는 같은 run 재시도 한정. 정규 JSON 규칙을 RFC 8785로 고정 필요 | data-engineer, cloud |
| M9 | MEDIUM | 방향이 JSON 안 | metric_definition.direction이 JSON 안 → 축 합산 부호 오류를 SQL에서 못 잡음. evaluation_response에 grader_key 없어 채점자 간 일치도가 JSON 파싱 의존 | data-scientist |
| M10 | MEDIUM | 인라인 JSON vs 파일 기준 없음 | 인라인 JSON text 약 13개 vs 파일 경로+sha 8쌍 | platform, cloud |
| M11 | MEDIUM | API가 상태 조합을 숫자로 합침 | result_status(5)×normalization_status(3)를 `score: number|null`로 합치면 0/계산불가/해당없음 구분 불가. 응답 envelope에 status·reason 필수 | backend |
| M12 | MEDIUM | 내부 식별자 노출 | score_payload의 member_id/block_id는 내부 식별자. API 그대로 전달 시 내부 구조 노출·암묵 계약 | backend |
| M13 | MEDIUM | 사람 실험 자료 분리 없음 | 원응답이 공개 원본과 같은 RAW_ROOT·DB. 「접근 제한」 문구만 있음. PII 잔여: raw_response 자유 텍스트, response_payload 채점자 실명 가능, 가명↔실명 대응표 위치 미정 | cloud |
| L1 | LOW | nullable 복합 FK | MATCH SIMPLE 전제 명시 필요 | architect |
| L2 | LOW | run status 열거값 불일치 | evaluation_run.status vs pipeline_run.status | data-scientist, architect |
| L3 | LOW | timestamp 시간대 | 원본 보관 규칙은 UTC 전제 → 「UTC」 명시 | cloud |
| L4 | LOW | population_snapshot.baseline_date 잔존 | 「기준일은 run으로」와 어긋남 | architect |
| L5 | LOW | FK 대상 없는 UNIQUE | member (member_id, run_id), population (id, run_id) | platform, architect |
| L6 | LOW | match_failure.target_type 이름 | target_type_enum과 이름 같고 의미 다름 | platform |
| L7 | LOW | 판매사 필터 경로 둘 | product_distributor / document.distributor_id 두 경로 OR. 날짜 필터 기준 칼럼 미정 | backend |
| L8 | LOW | 멤버십 비대칭 근거 | population 멤버십(파일)과 target 멤버십(관계형) 비대칭 근거를 스키마 명세에 한 줄 | data-engineer |

- 집계: CRITICAL 3 · HIGH 6 · MEDIUM 13 · LOW 8

### pipeline_run 교차 이슈

- 6관점에서 pipeline_run 지적이 가장 많이 겹침
  - run 종류 분리(EXTRACT vs SCORE): architect, platform, data-engineer, backend
  - 상류 run 참조(upstream_run_id): architect, platform, cloud
  - 공식 run 마커(is_official/is_current): architect, backend
- 셋 다 같은 근본 문제(run_id 하나가 수집·추출·채점을 묶는 복합 FK 사슬)로 귀결

### 즉시 반영 조치 (v2.1)

- 기준: 명백한 결함. 09-23 사용자 승인, 팀 결정 불필요, 되돌릴 수 있는 논리안

| 검토 번호 | 조치 | 반영 상태 | 해소한 발견 |
|---|---|---|---|
| A1 | population_snapshot UNIQUE (run_id, population_key) → (run_id, metric_key, population_key). (population_snapshot_id, run_id) UNIQUE 삭제. 동명 표와 중복이던 metric_definition text 칼럼 삭제 | 반영 완료 — DBML population_snapshot, 스키마 명세 | C2, M1 |
| A2 | pipeline_run에 run_kind(EXTRACT/SCORE) / upstream_run_id(자기 참조) / is_official / published_at 추가, status → run_status_enum, UNIQUE (run_id, upstream_run_id). analysis_target.extraction_run_id를 (run_id, extraction_run_id) → pipeline_run(run_id, upstream_run_id) 복합 FK로 강제. analysis_target_member는 run_id를 없애고 (target_id, extraction_run_id)로 참조. section/file_extraction FK는 extraction_run_id로(FK 45→47) | 반영 완료 — DBML, [데이터 테이블·ERD 설계](../../data-model.md) 「실행과 비교 모집단」. architect 재검증 지적 반영 | C1, C3 |
| A3 | varchar 코드 칼럼 15개(evaluation_run.status 포함) → enum 16개(run_status_enum은 pipeline_run·evaluation_run 공유). score_dependency.input_role은 보류 표라 varchar 유지. 기존 소문자 값 3개 enum은 소문자 유지, 새 enum은 대문자 | 반영 완료 — DBML enum 블록, 스키마 명세 「Enum 상태값」 | M2, L2, L6 |
| A4 | metric_definition.direction(HIGHER_IS_HARDER/HIGHER_IS_BETTER/NONE) 칼럼 승격 | 반영 완료 — DBML metric_definition | M9(direction 부분) |
| A5 | 무결성 계약 도입부 「물리 DB CHECK/트리거로 구현」 → 「검증 규칙 목록, 구현 방식은 2단계(DB 중립 적재 검증 기본)」 | 반영 완료 — [데이터 테이블·ERD 설계](../../data-model.md) 「절과 점수 대상」 | H2 |
| A6 | 원본 보관 경로 표에 structure/protocol/response/summary manifest 경로 추가, derived/는 EXTRACT run 아래. 2단계 입력 문서의 참조를 v2 문서로 | 반영 완료 — [원본 보관과 수집·파싱 실패 처리 규칙](../../storage-and-failure-rules.md) 「파생 텍스트·실행 스냅숏 경로」, [2단계 입력](../../pipeline-flow.md) | H6 |
| A7 | 공개 식별자 규칙(document_id/product_id/fund_key 공개; section_id·run_id·metric_key는 run 파라미터 동반 — section_id는 EXTRACT run마다 재발급되는 서러게이트라 단독 공개 불가; target_*/member_id/block_id/score_id 내부 전용) | 반영 완료 — [스키마 명세](../../schema-catalog.md) 「공개 식별자 규칙」. architect 재검증의 section_id 분류 오류 수정 | M8, M12 |

- 반영으로 해소: C1, C2, C3, H2, H6, M1, M2, M9(direction 부분), L2, L6
- 미해소: 나머지. 09-30 결정 요청 B1~B10은 [데이터 테이블·ERD 설계](../../data-model.md) 「미결」

### 관점별 요약

#### architect

- 진단은 맞으나 처방이 과함. score에 칼럼 몇 개(target_type, 앵커 3개, target_key, metric_key, assessor_key, result_status, reason_code, numerator/denominator)를 더하면 풀릴 문제를 표 6개로 풂
- 대안 15표: 기존 14 + metric_definition(축소). 입력·근거는 score_payload에, 평가는 파일 manifest로
  - 잃는 것: 구간·입력 계보의 FK 강제, DAG SQL 조회, 평가 응답 SQL 조회
  - 요구가 증명되면 표로 승격(14표 시점 manifest 원칙)
- population_snapshot UNIQUE 충돌(C2)을 유일하게 발견. 다수 의견(analysis_target 유지)과 갈린 유일한 관점

#### data-engineer

- 적재 순서를 끝까지 추적: 순환 없음. population_snapshot↔score 단방향
- score/score_dependency는 PENDING 선삽입 후 하위→상위 UPDATE라 append-only 아님
- 09-23 재검토(평가 표 수 미정)와 v2(2표 확정)가 같은 날 모순
- protocol_manifest 안의 pair_key/question_key는 SQL FK가 아니라 manifest 재생성 시 오류 없이 어긋날 수 있음(v2 문서도 인정). 적재 검증 작업 명세 없음
- nullable anchor 패턴은 표준 트레이드오프로 유지 권장. FUND 대표문서 선택 기준 미문서화

#### data-scientist

- 지원되는 분석: 절→축→최종 가중 집계, 최소 30·미병합 층내 백분위, 비율 지표, 계산불가 5분기, mixed-effects용 평가 칼럼(4/12/18 하드코딩 없음, PII 없음)
- 못 하는 분석: 채점자 간 일치도(grader_key 없음), 재채점 전후 비교(JSON 참조뿐), DRAFT 차단(문서 규약뿐), 방향 검증(direction이 JSON 안)
- 「표가 너무 많다」의 실체: analysis_target_member의 SECTION 강제 1곳과 score_dependency의 이른 설계 1곳

#### platform-engineer

- DBML 밖 규칙 약 42개 집계: 단일 행 CHECK 14, 교차 행 트리거/검증기 16, 파일 내용 검증 10
- 2~3명 파트타임 기준 3~5 인·주(추정)를 채점 행 1건 적재 전에 선행. 수집→파싱만이면 규칙 6개
- 09-26 인계 골든패스, 표 배치 권고(지금 17, 3단계 예약 3, 삭제 0): [2단계 입력](../../pipeline-flow.md) 「검토 의견(승인 아님)」

#### cloud-architect

- run당 행 수·용량 추정, SQLite 비권고, 원본 저장(연 약 250GB 추정), 최소 아키텍처: [2단계 입력](../../pipeline-flow.md) 「검토 의견(승인 아님)」

#### backend-developer

- 데이터 소스 API 명세는 첫 줄부터 수집 문서. 09-14 공유 전제가 확정한 대시보드 드릴다운을 소비할 계약이 저장소에 없음
- 드릴다운·Top-N 쿼리 부담: [2단계 입력](../../pipeline-flow.md) 「검토 의견(승인 아님)」
- 공식 run 포인터 부재(C3)와 target_key의 run-scoped 성격(공개 ID 불가) 지적
- score_current 뷰(공식 run ∧ APPROVED)와 응답 envelope 제안: [3단계 입력](../../io-schema.md) 「CDI 출력 요구」

### 검증 결과

- 반영 전 파일에서 팀 리드가 직접 대조 확인한 리뷰 주장
  - population_snapshot UNIQUE가 (run_id, population_key)이고 metric_key 미포함: 확인
  - pipeline_run에 run_kind·공식 run 마커 없음, document.is_current는 DART 정정본 계보 전용: 확인
  - 데이터 소스 API 명세가 수집 API 명세(「데이터 소스 API 명세」, 「어떻게 호출해서 받아오는가 하나」): 확인
  - 09-23 재검토의 「물리 표 수는 아직 정하지 않는다」, 「승인 전 예약 표를 빈 정의로 DBML에 추가하지 않는다」, 「표 수는 그다음」: 원문 확인
  - 2단계 입력 문서가 논리 스키마와 09-22 재검토를 우선 참조: 확인
  - 원본 보관 경로 표에 text/inputs/populations만 있음: 확인
  - evaluation_run이 scoring_run_id를 별도로 둠: 확인
- 즉시 반영 조치 후 검증(v2.1)
  - `@dbml/core` 파서 통과: 20개 표·47개 관계·enum 30개. 모든 FK 부모 칼럼의 PK/UNIQUE 존재. PostgreSQL SQL 메모리 내보내기 성공
  - 논리 스키마 Mermaid 관계선 47개 = DBML 47개. `git diff --check` 통과
  - 상태성 varchar 잔여: score_dependency.input_role(보류 표) 하나
- architect 에이전트 1차 반영 검증(파일 수정 없이 판정만)
  - A1~A6 DBML 반영 정확. Mermaid 관계선 47개 직접 셈 일치. 09-30 결정 항목 선점 없음(표 삭제·병합 없음, 평가 표는 enum 타입만 변경)
  - HIGH-1: 공개 식별자 표가 `section_id`를 「run 무관 안정 ID」로 분류한 것은 오류. 절은 EXTRACT run마다 재적재되어 section_id가 바뀜 → `(run_id, section_id)` 쌍으로 공개하도록 수정. 반영
  - M-1: `analysis_target.extraction_run_id = upstream_run_id`를 적재 검증에만 맡김 → pipeline_run UNIQUE (run_id, upstream_run_id) + 복합 FK로 강제. 반영
  - M-2: run 종류와 자식 표 일치 검증 목록 누락 → v2.1 절에 추가. 반영
  - M-3: is_official/published_at이 「완료 run 불변」과 충돌 → 예외 명시, published_at은 해제 시에도 유지, 기준일별 서빙은 서빙 계약(B5)으로. 반영
  - M-4: run 칼럼의 kind 주석 누락(section, file_extraction, collection_attempt, match_failure, fund_group) → 주석 추가. 반영. 매칭 성공/실패의 run 비대칭은 기존 문제로 09-30 검토에 남김
  - M-5: 기준일 규칙 불일치 → SCORE.baseline_date = upstream EXTRACT, population_snapshot.baseline_date = SCORE run으로 통일. 반영. L4(칼럼 존치)는 미결 유지
  - L-1: member.run_id가 FK 한 곳에만 쓰임 → 칼럼 삭제, (target_id, extraction_run_id)로 참조. 반영
  - L-2 대소문자, L-3 normalization_reason 누락, 잔여 문구 5곳: 반영
  - 약한 선점 지적 3곳(run_status_enum 공유, eval manifest 경로 위치, is_official 전역 1개): 인지하고 B4·B5에 위임. 되돌리기 쉬운 수준
- architect 2차 재확인
  - HIGH-1, M-1~M-5, L-1~L-3 모두 DBML·v2 문서·논리 스키마에 반영 확인
  - M-1 복합 FK는 nullable upstream_run_id와 충돌 없음: 자식 두 칼럼이 NOT NULL이라 SCORE run만 매칭되고, analysis_target.run_id가 SCORE run임도 FK로 강제
  - L-1 뒤 member의 SCORE run 조회는 target 조인으로 충분
  - 새 지적 N-1(스키마 명세의 run kind 주석 6곳·population.baseline_date 설명 누락), N-2(`(run_id, section_id)`의 run_id가 EXTRACT run임을 명시): 반영
  - 판정: 스키마 구조 결함 없음. v2.1 즉시 반영 조치 종결
- 검증하지 않은 항목
  - 실제 DB 적용·마이그레이션, 조건부 적재 검증 구현, 실제 데이터 파일럿
  - 행 수·용량·작업량 추정치(cloud·platform)의 정확성
  - 외부 대화형 ERD 아티팩트·Notion 갱신

## 대체된 옛 규칙

### 09-09 ETF 문자열 규칙

- 원문 규칙: 「정규화된 상품명에 「상장지수」 문자열이 위치와 무관하게 포함되면 ETF로 판정한다(09-09 확정).」
- 정규화에서 분리한 근거(09-14): 서로 다른 상품명을 같은 문자열로 만드는 정규화가 아니라, 정규화가 끝난 문자열 하나를 보고 상품군을 분류하는 별개의 판정 규칙. 정규화 단계 표에 두면 「정규화 = 매칭 전처리」 성격과 어긋남
- 대체(09-19 실측, 09-22 적용): 누락 0/938, 오탐 14.4~30.3% → KRX 대조를 1차 판정으로, 문자열은 후보 선별에만
- 09-19 판정의 「재현율 100%라 후보를 놓치지 않는다」 문장은 정정됨: 0/938은 이름으로 붙는 범위(KRX 1,167건의 80.4%) 안의 값. 「재현율 100%」로 읽지 않음
- 현행: [매칭 규칙](../../matching-rules.md) 「ETF 판정」

### 매칭 실패 구 분류(A~D) 대응

| 구 코드 | 신 코드 | 비고 |
|---|---|---|
| (해당 없음) | PENDING_MASTER | 구 분류에 없던 상태. 매칭 시도 이전에 마스터가 아직 없는 정상 대기, 실패 아님. DART가 금투협·공공데이터포털보다 6~18일 선행 |
| A. 임계치 미달 | BELOW_THRESHOLD | 코드 있는 소스 잔여 건은 상품명 유사도 0.60 미만, 코드 없는 소스는 판매사명 유사도 0.95 미만 또는 단독 후보·교차 확인 조건 미충족 |
| B. 후보 없음 | NO_CANDIDATE / NO_CODE_IN_SOURCE로 분리 | 신규상품·상장폐지처럼 후보가 없으면 NO_CANDIDATE, 분쟁·제재처럼 소스 구조상 코드·상품명이 없으면 NO_CODE_IN_SOURCE |
| C. 다중 후보 동점 | AMBIGUOUS | 코드 없는 소스에서 단독 후보 조건 미충족도 흡수 |
| D. 정규화 실패 | NORMALIZE_FAILED | 동일 |

- 당시 표시: 초안. 실제 실패 사례를 현황표·조인 대조표에서 본 뒤 세분화 예정(미확인)
- 현행 사유 코드: [매칭 규칙](../../matching-rules.md) 「매칭 실패 기록」

### 티켓 메모의 두 벌 임계치 안

- 09-14 티켓 메모 제안: 소스 성격별 두 벌 임계치(코드 있는 소스 전용 「0.80 미만만 제외하는 재현율 우선 벌」 / 분쟁·제재 엄격 규칙)
- 아키텍트 판정: 채택하지 않음. 단일 표(0.85 자동 / 0.60~0.85 수동 / 0.60 미만 실패) 유지, 적용 범위(코드 조인 잔여 건) 명시
  - 0.80 벌은 0.60~0.85 수동 확인 구간과 기능이 겹침
- 판매사 임계치: 0.90 → 0.95
- 불채택 사유 상세: [매칭 규칙](../../matching-rules.md) 「임계치」

## v2.2 수정 확정안 (09-30 재검토)

- 09-29~30 5개 관점(데이터 사이언스, 데이터 엔지니어링, 데이터베이스 설계, 실행 재현성·운영, 소스 데이터 적합성) 재검토의 판정은 「부분 축소」. 9차 미팅 승인 뒤 v2.2로 반영
- 수정 1~9의 원문과 결정 대기 A~I는 [데이터 테이블·ERD 설계 티켓](https://app.notion.com/p/3d6e1ac7050581f3aa6cda6e22f7d119) 「9월 30일 재검토」 절. 관점별 보고서는 이 폴더에 추가 예정
- 아래 1~9는 티켓 표의 요지. 10은 09-30에 덧붙인 항목

| # | 수정 | 내용 | 영향 문서 |
|---|---|---|---|
| 1 | 채점·평가 표 4개 연기 | score_dependency, evaluation_run, evaluation_response, analysis_target_member를 DBML에서 빼고 예약 계약으로만 남김. 평가 결과는 프로토콜 확정 전까지 CSV와 설정 파일 | schema.dbml, [데이터 테이블·ERD 설계](../../data-model.md), [스키마 명세](../../schema-catalog.md) |
| 2 | 추출 결과 키 변경 | file_extraction·section 키를 추출 실행 번호에서 파일 × 파서 버전으로. B9 함께 해소 | schema.dbml, [원본 보관과 수집·파싱 실패 처리 규칙](../../storage-and-failure-rules.md) |
| 3 | 코드 체계 불일치 해소 | 공공데이터포털 표준코드의 K55·KR5 혼재를 체계별로 받음 | schema.dbml, [데이터 테이블·ERD 설계](../../data-model.md), [매칭 규칙](../../matching-rules.md) |
| 4 | 절 식별 칼럼 추가 | 제4부 절 구성이 문서마다 달라 section에 정규 절 분류 칼럼 추가 | schema.dbml, [DART 절 분할](dart-section-split.md) |
| 5 | 빠진 표 2개 추가 | LLM 6필드 추출 결과 표, 소스 워터마크 표 | schema.dbml, [데이터 테이블·ERD 설계](../../data-model.md), [2단계 입력](../../pipeline-flow.md) |
| 6 | 채울 수 없는 칼럼 제거 | 판매개시일·판매종료일, 공모 여부, `fin_prdt_cd`, `document.pblntf_detail_ty` 등 | schema.dbml, [스키마 명세](../../schema-catalog.md) |
| 7 | 형식 오류 정정 6건 | 코드 자릿수 근거, 날짜 형식 분리, char 단위 명시, 절 상태값, 금투협 칸, 운용사 코드 대응 | [데이터 테이블·ERD 설계](../../data-model.md), [데이터 소스 수집 명세](../../data-sources.md), schema.dbml |
| 8 | B7 정정 | manifest 저장 기준 통일만 채택, RFC 8785 요구 삭제 | [원본 보관과 수집·파싱 실패 처리 규칙](../../storage-and-failure-rules.md) |
| 9 | B8 기각 | 지표 승인 이력 표 없이 칼럼 또는 manifest 기록 | [데이터 테이블·ERD 설계](../../data-model.md) 「미결」 |

### 수정 10 (09-30 추가): 두 파트 출력의 저장 계약

- 상태: 09-29 팀 논의 결론, 9차 미팅(09-30) 확정(두 파트 출력 결정). 근거 위치 형식(B11)은 결정 대기(9차 미팅 결정 기록 없음)
- 배경: 문서 1건의 결과를 파트 A(고지 점검, 축 4 고지 충실도)와 파트 B(읽기 난이도, 축 1~3 합산)로 나눠 내고 한 숫자로 합치지 않기로 함
- 내용
  - 축 4 항목별 판정은 금소법 19조 항목 번호 기반 metric_key 단위로 score 행에 저장. 상태 있음/없음/판정 불가는 기존 result_status와 raw_score로 표현하고 근거 위치를 score_payload에 둠
  - 파트 B 합산 점수는 별도 metric_key. 층내 백분위는 그 행의 정규화 칼럼. 두 파트를 합친 단일 CDI metric_key는 만들지 않음
  - 근거 위치: payload v2의 member_id 의존이 수정 1(analysis_target_member 연기)과 충돌. 안 1 `(section_id, char_start, char_end)`로 member_id·block_id 제거(권고), 안 2 analysis_target_member 유지. 결정 대기(B11, 9차 미팅 결정 기록 없음)
  - 판매사 × 제재 라벨 표는 ERD에 만들지 않음. 제재 사건 매핑표(축 4 검증용, 수십 건)는 평가 자료로 CSV + 설정 파일 또는 evaluation 표에 두며 결정 대기 G와 함께 정함(B12). 대조군 문서 묶음 식별 방법은 미결(B13)
- 표 수 변화 없음. 결정 대기 I(축 4 판정 상태 저장)는 score 칼럼 쪽으로 정리 가능
- 영향 문서: [데이터 테이블·ERD 설계](../../data-model.md) 「두 파트 출력의 저장 계약」·「미결」 B11~B13, schema.dbml(metric_definition·score_payload 주석), [스키마 명세](../../schema-catalog.md), [점수 저장과 비교 모집단](../../scoring-and-population.md) 「고지 항목 판정」, [3단계 입력](../../io-schema.md)

## 9차 미팅(09-30) 결과

| 항목 | 결과 |
|---|---|
| 두 파트 출력(축 4 분리) | 확정. 판매사별 제재 건수 표는 정답지로 쓰지 않음. 법 조문 = 축 4 기준, 분쟁조정 결정문 = 감점표 재료, 사람 이해도 조사 = 축 1~3 검증. 수정 10은 이 결정으로 확정 |
| 제재문 역할 | 확인대기. 데이터 사이언스(다빈)가 축 4 검증 자료가 아니라 기준인지 질문. 분석·리서치(민석)가 2026-10-04까지 조사 |
| 상품 범위 | 1차 구현은 펀드·ETF(펀드 1순위, ETF 2순위). ELS·예금성·대출성·보장성 제외. ELS enum 값과 회차 규칙은 남기고 Phase 2 검토 |
| 제재공시 게시판 정찰(10~20건) | 데이터 엔지니어링·인프라(주영), 2026-10-04. 결과로 크롤러 제작 판단 |
| 위험등급 | 같은 펀드의 클래스끼리 등급이 달라도 펀드 단위 규칙을 만들지 않고 클래스 등급을 그대로 씀. 층 배정 적용 방식은 데이터 사이언스(다빈) 확인대기 |
| 분쟁조정 게시일 | 금소법 시행(2021년) 이후 자료만 거르는 기준이라 필수 유지. 수집 스크립트의 게시일 미파싱은 분석·리서치(민석) 확인, 2026-10-04 |
| CSP(클라우드 사업자) | AWS 사용 확정, GCP 병행 여부 검토 중. 비용 지원 없음 → 비용 추정 재검토 필요 |

- 결정 기록 없음: 결정 A~I, B11~B13, v2.2 수정 1~9 승인, 축 4 분모, v2.2 기한. 각 항목의 상태는 그대로 둠

## 미결

| 질문 | 결정 주체 | 필요 시점 |
|---|---|---|
| Notion 데이터 테이블·ERD 페이지와 파이프라인 Flow 티켓을 v2.1(20표·47관계) 기준으로 갱신했는지 | 대현 | 2026-09-30 |
| 외부 대화형 ERD 아티팩트 갱신 검증 | 대현 | 2026-09-30 |
| 행 수·용량·작업량 추정치(약 8M행, 5~10GB, 규칙 약 42개, 3~5 인·주)의 실측 검증 | [담당 미정] | 2단계 파일럿 시 [확인 필요: 일자] |
