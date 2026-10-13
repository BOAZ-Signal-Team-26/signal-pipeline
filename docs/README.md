# signal-pipeline 설계 문서 안내

읽는 순서, 프로젝트 전제, 단계·상태, 문서 소유 규칙, 표기 규칙, 옛 문서 번호 대응.

## 읽는 순서

| 순서 | 문서 | 읽으면 알게 되는 것 |
|---|---|---|
| 1 | README (이 문서) | 프로젝트 전제, 단계, 현재 상태 |
| 2 | [데이터 테이블·ERD 설계](data-model.md) | 표 20개가 각각 무엇을 담는지, 표끼리 어떻게 이어지는지 |
| 3 | [데이터 소스 수집 명세](data-sources.md) | 각 소스에서 무엇을 어떻게 받는지 |
| 4 | [원본 보관과 수집·파싱 실패 처리 규칙](storage-and-failure-rules.md) | 받은 원본을 어떻게 보관하고 실패를 어떻게 기록하는지 |
| 5 | [상품·법인 매칭 규칙](matching-rules.md) | 문서를 상품·법인에 어떻게 붙이는지 |
| 6 | [점수 저장과 비교 모집단](scoring-and-population.md) | 점수를 어떤 단위로 저장하고 무엇과 비교하는지 |
| 7 | [데이터 처리 요구 명세](processing-requirements.md) | 데이터 사이언스에 넘기는 파일의 칼럼, 절 경계, 결측 표기, 소스별 워터마크 검증 |
| 8 | [2단계 데이터 파이프라인 Flow 설계 입력](pipeline-flow.md), [3단계 입출력 Schema 설계 입력](io-schema.md) | 다음 단계가 이어받는 것 |
| 참조 | [스키마 명세](schema-catalog.md), [DBML](schema.dbml) | 칼럼 단위 확인 |
| 근거 | [records/](records/) | 결정의 실측 근거와 검토 이력 |

## 프로젝트 전제

### 한 줄 정의

- 판매 중인 금융상품 설명서를 전수 채점해 절마다 설명 난독성 점수를 산출하고, 그 기준을 비대면 가입 플로우에 적용해 개선안 도출

### 최종 산출물 3종

| 산출물 | 스키마에서의 위치 | 이유 |
|---|---|---|
| 전수 채점 파이프라인(카탈로그형) | 본체. 스키마는 이것을 위해 설계 | — |
| 문서 1건 진단(점수·취약 지점) | 별도 업로드 기능 없이 대시보드 드릴다운 화면으로 흡수. 수집 층을 우회하는 진입 경로 없음 | 드릴다운이 성립하려면 점수가 문서 단위가 아니라 절 단위로 저장되어야 함 |
| 가입 플로우 개선안 | 스키마 밖. 화면 순서 테이블 만들지 않음 | 대상이 PDF가 아니라 앱 가입 플로우. 수동 1회성 분석 |

### CDI(설명 난독성 지표)의 성격

- 정규화 점수. 「72점」은 단독으로 의미 없음
- 비교 모집단(동일 상품군·동일 위험등급) 안의 위치로만 읽음 → 상품 표에 층화 키 필요
- 상세: [점수 저장과 비교 모집단](scoring-and-population.md) 「정규화와 층내 백분위」

### 09-09 확정 사항

| 항목 | 값 |
|---|---|
| 상품군 | 펀드, ETF, ELS |
| CDI 산출 대상 | 펀드와 ETF만. ELS는 CDI 계산 안 함 |
| 고지 충실도 | 09-09 기록은 ELS 고지 충실도 점수를 별도로 둠. 09-23 사전 안건은 고지 충실도를 점수로 추진, 펀드·ETF 적용 범위·합산 방식·분모는 미결 → [점수 저장과 비교 모집단](scoring-and-population.md) 「CDI와 고지 충실도」 |
| 옛 검증 계획 | 과거의 수동 라벨 200건 계획은 최신 검증 설계 확정으로 취급하지 않음 |

- 09-09의 ETF 식별 규칙(「상장지수」 포함)은 대체됨: [ERD 설계 변천과 검토 기록](records/phase1-erd/design-review-history.md) 「대체된 옛 규칙」
- 09-09의 소스 4종 조인 키 후보와 위험등급·분쟁조정 전제는 대체 표시와 함께 [조인 키 확인 기록](records/phase1-erd/join-key-checks.md) 「조인 키 확인 현황」

### Epic이 정한 아키텍처 5층

| 층 | 책임 | 경계에서 넘기는 것 |
|---|---|---|
| 수집 | 소스별 원본 확보 | 원본 파일 + 메타데이터 |
| 파싱 | 원본을 텍스트로 | 정규화된 텍스트 + 실패 플래그 |
| 구조화 | 텍스트에서 필드 추출 (LLM) | 고정 스키마 JSON |
| 적재 | 3단 저장 | mart 테이블 |
| 품질 | 지표 측정 | 누락률·실패율·일관성 |

- 3단계 입출력 Schema 설계(10-14)에서 「LLM 추출 결과 JSON」과 「CDI 출력」 데이터 계약 2종을 확정
- 09-16 데이터베이스 Schema는 그 둘을 담을 자리만 두고 모양을 미리 확정하지 않음

### 실패 처리 정책과 산출물 대응

| Epic 실패 처리 정책 | 처리 시점 | 현행 위치 |
|---|---|---|
| ① 파싱 실패 격리·재처리 | 1단계 규칙, 재처리 구현은 2단계 | [원본 보관과 수집·파싱 실패 처리 규칙](storage-and-failure-rules.md) |
| ② 저신뢰 추출 플래그 기준 | 3단계 이후. 09-16에는 플래그 칸만 | [3단계 입출력 Schema 설계 입력](io-schema.md) |
| ③ 원본 vs 정정본 중 CDI 계산 대상 | 이력 구현보다 먼저 정해야 하는 규칙 → 09-16에 규칙으로 확정 | [점수 저장과 비교 모집단](scoring-and-population.md) 「기준일과 대표본 선택」 |
| ④ 조인 키 정의 | 스키마 항목 | [데이터 테이블·ERD 설계](data-model.md) 「문서와 소스별 키」 |

| 티켓 실패 처리 규칙 | 요구 | 현행 위치 |
|---|---|---|
| (a) 수집 안 됨 | 판정 기준 + 모아두는 곳 | [원본 보관과 수집·파싱 실패 처리 규칙](storage-and-failure-rules.md) 「수집 실패」 |
| (b) 본문 뽑기 실패 | 판정 기준 + 모아두는 곳 | 같은 문서 「추출 실패와 절 품질」 |
| (c) 상품 못 찾음 | 판정 기준 + 모아두는 곳 + 문자열 유사도 임계치 필수 | [상품·법인 매칭 규칙](matching-rules.md) |

## 설계 단계와 상태

### 단계별 문서

| 단계 | 기한 | 상태 | 현행 설계 문서의 해당 절 | 근거 기록 폴더 |
|---|---|---|---|---|
| 1단계 데이터 테이블·ERD 설계 | 9월 16일 | 확정 전 (v2.1 검토안, 팀·CDI 산식 담당 승인 미완료) | [데이터 테이블·ERD 설계](data-model.md) 전체, [원본 보관과 수집·파싱 실패 처리 규칙](storage-and-failure-rules.md) 전체, [상품·법인 매칭 규칙](matching-rules.md) 전체, [점수 저장과 비교 모집단](scoring-and-population.md) 전체, [데이터 소스 수집 명세](data-sources.md) 전체 | [records/phase1-erd/](records/phase1-erd/) |
| 2단계 데이터 파이프라인 Flow 설계 | 9월 30일 | 시작 전 | [2단계 데이터 파이프라인 Flow 설계 입력](pipeline-flow.md) | 기록이 생기면 records/phase2-pipeline/ |
| 3단계 입출력 Schema 설계 | 10월 14일 | 착수 전 | [3단계 입출력 Schema 설계 입력](io-schema.md) | 기록이 생기면 records/phase3-io-schema/ |

| 단계 | 확정하는 것 |
|---|---|
| 1단계 | 데이터베이스 Schema(테이블·조인 키), 원본 보관 규칙, 실패 처리 규칙 3건 |
| 2단계 | 소스 4종 → 대시보드 흐름 다이어그램, DB·원문 저장소·Airflow 환경 |
| 3단계 | LLM 추출 결과 JSON, CDI 출력 데이터 계약 2종 |

- 현행 설계 문서는 단계와 무관하게 `docs/` 바로 아래 주제별로 둠
- 프로세스·WBS·스프린트 계획: [Project-Management](https://github.com/BOAZ-Signal-Team-26/Project-Management). 이 저장소는 「무엇을 어떻게 만들 것인가」만 다룸

### 현재 검토안 (2026-09-23)

| 항목 | 값 |
|---|---|
| 판 | ERD v2.1 |
| 규모 | 20개 표 · 47개 관계 · enum 30개 |
| v2.1 반영 | 추출 run/채점 run 분리, 공식 run 마커, 모집단 유일키 수정, enum 통일 |
| 담는 것 | 절·문서·문서쌍·펀드 대상, 계산 불가 결과, 점수 집계 근거, 사람·LLM 원응답 |
| 정본 | [데이터 테이블·ERD 설계](data-model.md), [DBML](schema.dbml), [스키마 명세](schema-catalog.md) |
| 승인 | 팀·CDI 산식 담당 승인 미완료. 운영 DB 적용 미완료 |
| 09-30 결정 대기 | 표 제외 등 10건(검토 번호 B1~B10) + 09-30 추가 3건(B11~B13, 두 파트 출력의 저장 계약) → [데이터 테이블·ERD 설계](data-model.md) 「미결」 |
| 이전 검토 근거 | [ERD 설계 변천과 검토 기록](records/phase1-erd/design-review-history.md) |

### 저장소 구성

- 09-22 [저장소 구성 결정](https://app.notion.com/p/3e2e1ac70505818cbf66d63c9b45e782): Github 저장소 3개

| 저장소 | 담는 것 |
|---|---|
| `signal-pipeline` | 코드 + 설계 |
| `signal-infra` | 클라우드 구축 |
| `Project-Management` | 계획 |

- 폴더 초안의 PostgreSQL/Alembic 예시는 DB 제품 승인으로 간주하지 않음

## 문서 소유 규칙

| 사실 유형 | 소유 문서 |
|---|---|
| 엔드포인트 · 요청 전문 · 파라미터 · 인증 · 페이징 · 응답 구조 · 호출 주의점, 호출 간격·타임아웃·재시도 횟수의 구현값 | [데이터 소스 수집 명세](data-sources.md) |
| 실패 판정 기준 · 상태값 · 재시도 정책 · 격리 · 워터마크 룩백 일수 | [원본 보관과 수집·파싱 실패 처리 규칙](storage-and-failure-rules.md) |
| 원본 경로 · 파일명 · 버전 · 메타데이터 · 중복 판정 정책 | [원본 보관과 수집·파싱 실패 처리 규칙](storage-and-failure-rules.md) |
| 자연키 · 조인 · 칼럼 | [데이터 테이블·ERD 설계](data-model.md), [스키마 명세](schema-catalog.md) |
| 임계치 · 정규화 | [상품·법인 매칭 규칙](matching-rules.md) |
| 점수 단위 · 결측 상태 · 모집단 · 대표본 | [점수 저장과 비교 모집단](scoring-and-population.md) |
| 실측 수치와 그로 인한 판정 | [records/phase1-erd/](records/phase1-erd/) |

- 경계: 「요청·응답이 어떤 형태인가」는 데이터 소스 수집 명세, 「그 형태로 무엇을 할지」는 규칙 문서
- 데이터 소스 수집 명세는 「증분에 쓸 수 있는 요청 변수」까지, 룩백 일수는 실패 처리 규칙이 소유
- 임계치(0.85 / 0.60 / 판매사 0.95)와 정규화 단계의 정본은 매칭 규칙
  - 실측에서 임계치가 맞지 않아 보여도 값을 고치지 않고 실패 목록만 남김
  - 확정은 라벨 200건으로
- 같은 사실은 소유 문서 한 곳에만 쓰고 나머지는 링크

## 표기 규칙

- Project-Management README의 **(사실) / 미정 / 제안** 규칙을 따름

| 설계 문서 표기 | Project-Management 표기 | 뜻 |
|---|---|---|
| **결정** | 제안 → 해당 단계 종료 미팅에서 4인 확정 후 **(사실)** | 초안 작성자가 정한 것. 확정 전까지 제안 |
| **근거** | (출처) | 그 결정을 뒷받침하는 문서·실측 |
| **미확인** | 미정 | 아직 확인되지 않아 채워야 할 것 |
| **확인됨(근거)** | (사실) | 실측·조사로 확정된 것. 괄호 안은 근거 문서. 옛 문서의 「확인됨(nn)」 번호는 아래 「옛 문서 번호 대응」으로 해석 |

| 구분 | 표기 |
|---|---|
| 확정 | 그대로 기재 |
| 추정 | `(추정)` 접미 |
| 미확인 | `[확인 필요: 항목]`. 숫자·날짜를 추정으로 채우지 않음 |

- 문서 간 링크: 상대 링크 + 절 제목(「…」). 절 앵커(`#…`) 쓰지 않음
- 실행 명령은 저장소 루트 기준 경로

## 근거 기록 목록

| 문서 | 내용 |
|---|---|
| [초기 소스 확인과 티켓 메모 대조](records/phase1-erd/initial-source-checks.md) | 09-14 DART 표지 10건, finlife·펀드코드 체계, 외부 검증 영향, 티켓 메모 대조와 원문 부록 |
| [금투협 수시공시 중복 행과 ETF 이름 규칙 검증](records/phase1-erd/kofia-rows-and-etf-rule.md) | 09-19 금투협 중복 행, ETF 「상장지수」 이름 규칙 |
| [조인 키 확인 기록](records/phase1-erd/join-key-checks.md) | 소스 간 연결 판정 현황표, srtnCd·판매회사·분쟁조정·제재공시 실측 |
| [DART 본문 PDF 부·절 분할 실현성 검증](records/phase1-erd/dart-section-split.md) | 09-20 부·절 분할 |
| [소스별 데이터 현황표](records/phase1-erd/source-profile.md) | 문서 4종 × 7항목 |
| [ERD 설계 변천과 검토 기록](records/phase1-erd/design-review-history.md) | 9 → 14 → 20개 표 변천, 09-22·09-23 재검토, v2 6관점 검토 |

- 검증 스크립트와 표본 CSV: [research/](../research/)

## 옛 문서 번호 대응

- 2026-09-29 `gate-a/` `gate-b/` `gate-c/`의 번호 문서를 이 폴더로 통합
- Notion·외부 문서의 옛 번호·옛 경로 해석 기준
- DBML 주석은 2026-09-29에 새 문서 이름으로 교정 완료

### 옛 파일 → 새 문서

| 옛 파일 | 새 문서 | 주요 절 |
|---|---|---|
| gate-a/00 공유 전제 | 이 문서 | 「프로젝트 전제」 |
| gate-a/00b 티켓 메모 사본(09-14) | [초기 소스 확인](records/phase1-erd/initial-source-checks.md) | 「부록: Notion 티켓 메모 사본」 |
| gate-a/01 논리 스키마 | [데이터 테이블·ERD 설계](data-model.md) | 「표 목록과 한 행의 의미」~「ERD」. v2 이전 조인 키 대조표·미확인 목록은 [조인 키 확인 기록](records/phase1-erd/join-key-checks.md) 「조인 키 확인 현황」 |
| gate-a/02 원본 보관 규칙 | [원본 보관과 수집·파싱 실패 처리 규칙](storage-and-failure-rules.md) | 「원본 보관」 |
| gate-a/03 실패 처리 규칙(수집·파싱) | 같은 문서 | 「수집 실패」「재시도와 워터마크」「추출 실패와 절 품질」「문서 파싱 상태」 |
| gate-a/04 점수 저장·모집단 | [점수 저장과 비교 모집단](scoring-and-population.md) | 1~4절 → 「저장 단위와 계산 단위」~「결과 상태와 결측」, 3-1~3-3절·5-1·5-3·5-4절 → 「알려진 분석 위험」, 5-2절 → [2단계 입력](pipeline-flow.md) 「먼저 측정할 것: 소스 간 중복률」, 5-5절 → [3단계 입력](io-schema.md) 「검증 설계 재검토 입력」 |
| gate-a/05 상품 매칭 임계치 | [상품·법인 매칭 규칙](matching-rules.md) | 1절 「상품명 정규화」, 2절 「ETF 판정」, 5절 「임계치」, 6절 「제재공시 법인 매칭」, 7절 「라벨 200건 표본 요건」, 8절 「매칭 실패 기록」, 9절 「법인명 정규화」 |
| gate-a/06 원본·정정본 | [점수 저장과 비교 모집단](scoring-and-population.md) | 1절 → [데이터 테이블·ERD 설계](data-model.md) 「문서와 소스별 키」, 2절 「기준일과 대표본 선택」, 3절 「판매 중 확인」, 4절 「이력 요구」 |
| gate-a/07 조인 키 검증 요청서 | [조인 키 확인 기록](records/phase1-erd/join-key-checks.md) | 「조인 키 확인 현황」. 문자열 매칭 쌍 → [매칭 규칙](matching-rules.md) 「매칭 경로」 |
| gate-a/08 외부 검증 영향 | [초기 소스 확인](records/phase1-erd/initial-source-checks.md) | 「외부 소스 검증 결과의 영향」 |
| gate-a/09 DART 표지 실측 | 같은 문서 | 「DART 표지 10건 실측」 |
| gate-a/10 finlife·코드 체계 | 같은 문서 | 「finlife 범위와 펀드코드 체계」 |
| gate-a/11 티켓 메모 대조 | 같은 문서 | 「티켓 메모 대조 판정」 |
| gate-a/12 금투협 중복 행 (검증 1) | [금투협 중복 행과 ETF 이름 규칙 검증](records/phase1-erd/kofia-rows-and-etf-rule.md) | 「검증 1: 금투협 중복 행」 |
| gate-a/13 ETF 규칙 (검증 2) | 같은 문서 | 「검증 2: ETF 이름 규칙」 |
| gate-a/14 조인 키 실측 | [조인 키 확인 기록](records/phase1-erd/join-key-checks.md) | 1절 「DART 펀드코드 대조」, 2절 「srtnCd 비유일」, 3절 「setpDt 품질」, 4절 「판매회사 명단 소스」, 5절 「분쟁조정 마스킹」, 6절 「제재공시」 |
| gate-a/15 데이터 소스 API 명세 | [데이터 소스 수집 명세](data-sources.md) | 소스별 절. 9절 → 「공통 수집 규칙」 |
| gate-a/16 소스별 데이터 현황표 | [소스별 데이터 현황표](records/phase1-erd/source-profile.md) | 3절 「값 표기」, 8-1절 「제재 API 과거 조회와 미확정 커버리지」 |
| gate-a/17 DART 부·절 분할 (검증 3) | [DART 본문 PDF 부·절 분할 실현성 검증](records/phase1-erd/dart-section-split.md) | 전체 |
| gate-a/18 스키마 재검토(09-22) | [ERD 설계 변천과 검토 기록](records/phase1-erd/design-review-history.md) | 「9표 → 14표 재검토(09-22)」. 4절 → [데이터 테이블·ERD 설계](data-model.md) 「원천 필드 → 논리 타입 → 목적지」「자료형·결측 공통 규칙」, 5절 → 「적재 검증 규칙」, 6절 → 「표 설계 근거」 |
| gate-a/19 미결정 포함 재검토 | 같은 문서 | 「미결정 포함 재검토(09-23)」. 5절 권고 → [점수 저장과 비교 모집단](scoring-and-population.md) 「CDI 지표 설계 권고(승인 아님)」 |
| gate-a/20 ERD 재설계 v2 | [데이터 테이블·ERD 설계](data-model.md) | 무결성 계약 → 「절과 점수 대상」, 구조 정보 → 「원본·수집 시도·추출」, 평가 → 「평가 데이터」, 이관 → 「v1 → v2 이관 절차」, v2.1 절 → 「실행과 비교 모집단」. 점수·결측·모집단 계약 → [점수 저장과 비교 모집단](scoring-and-population.md) |
| gate-a/21 스키마 명세 | [스키마 명세](schema-catalog.md) | 전체 |
| gate-a/22 ERD v2 6관점 검토 | [ERD 설계 변천과 검토 기록](records/phase1-erd/design-review-history.md) | 「v2 6관점 검토」. 09-30 결정 요청 B1~B10 → [데이터 테이블·ERD 설계](data-model.md) 「미결」 |
| gate-a/schema.dbml | [DBML](schema.dbml) | — |
| gate-b/README | [2단계 데이터 파이프라인 Flow 설계 입력](pipeline-flow.md) | 전체 |
| gate-c/README | [3단계 입출력 Schema 설계 입력](io-schema.md) | 「상태」 |
| scripts/, reference/ | [research/scripts/](../research/scripts/), [research/samples/](../research/samples/) | — |

### 옛 내부 표기 → 새 위치

| 옛 표기 | 뜻 | 새 위치 |
|---|---|---|
| J1 | DART 표지 펀드코드 → 상품 단축코드 (코드) | [조인 키 확인 기록](records/phase1-erd/join-key-checks.md) 「조인 키 확인 현황」 |
| J2 | 포털 srtnCd → 상품 단축코드 (코드) | 같은 절, 「srtnCd 비유일」 |
| J3 | 포털 asoStdCd·fndNm·setpDt·fndTp 값 적재 | 같은 절 |
| J4 | DART rcept_no·dcmNo → 문서 키 (코드) | 같은 절 |
| J5 | DART corp_code → 법인 (코드) | 같은 절 |
| J6 | DART 표지 위험등급·명칭 값 적재 | 같은 절 |
| J7 | 금투협 수시공시 tmpV1·standardCd → 펀드코드/표준코드 (코드) | 같은 절 |
| J8 | 금투협 판매사별 펀드 → 판매관계 (코드) | 같은 절, 「판매회사 명단 소스」 |
| J9 | finlife fin_prdt_cd (조인 불성립) | 같은 절, [초기 소스 확인](records/phase1-erd/initial-source-checks.md) 「finlife 범위와 펀드코드 체계」 |
| J10 | KRX ISU_CD → 상품 (이름 매칭) | 같은 절, [ETF 이름 규칙 검증](records/phase1-erd/kofia-rows-and-etf-rule.md) 「검증 2: ETF 이름 규칙」 |
| J11 | 제재공시 → 문서 키 | 같은 절, 「제재공시」 |
| J12 | 제재공시 금융회사명 → 법인 (문자열) | 같은 절, [매칭 규칙](matching-rules.md) 「제재공시 법인 매칭」 |
| J13 | 국가법령정보 MST·JO (미판정) | 같은 절 |
| J14 | 분쟁조정 (연결 불가) | 같은 절, 「분쟁조정 마스킹」 |
| 논리 스키마 미확인 1~25 | v2 이전 논리 스키마의 미확인 목록 | [조인 키 확인 기록](records/phase1-erd/join-key-checks.md) 「조인 키 확인 현황」·「남은 확인」. 자주 참조된 것: 2 = ISU_CD↔srtnCd 대응 소스 없음, 4 = 분쟁조정 판매사명 마스킹, 13 = ELS 식별 키 미정, 22 = 위험등급 원천이 DART 하나가 아님 |
| API 명세 미확인 1~16 | 데이터 소스 API 명세의 미확인 목록 | [데이터 소스 수집 명세](data-sources.md) 「미결」(해소 행은 본문에 반영) |
| 티켓 메모 A1~A8, B1~B3 | 09-14 Notion 티켓 메모 항목 | [초기 소스 확인](records/phase1-erd/initial-source-checks.md) 「부록: Notion 티켓 메모 사본」 |
| 외부 검증 A1 등 | web-verify 항목 | 같은 문서 「외부 소스 검증 결과의 영향」 |
| 6관점 검토 A1~A7 | v2.1 즉시 반영 조치 | [ERD 설계 변천과 검토 기록](records/phase1-erd/design-review-history.md) 「v2 6관점 검토」 |
| 6관점 검토 B1~B10 | 09-30 결정 요청 | [데이터 테이블·ERD 설계](data-model.md) 「미결」 (검토 번호로 괄호 병기 유지) |
| 6관점 검토 C1·H1~H6·M1~M13·L1~L8 | 발견 사항 | [ERD 설계 변천과 검토 기록](records/phase1-erd/design-review-history.md) 「v2 6관점 검토」 |
| 09-23 재검토 R1~R7 | 제기한 문제 | 같은 문서 「미결정 포함 재검토(09-23)」 |

## 미결

### 문서별 미결

| 문서 | 미결 건수 |
|---|---|
| [데이터 테이블·ERD 설계](data-model.md) 「미결」 | 21 (09-30 결정 요청 10 + 기타 11) |
| [점수 저장과 비교 모집단](scoring-and-population.md) 「미결」 | 12 |
| [2단계 입력](pipeline-flow.md) 「미결」 | 6 |
| [3단계 입력](io-schema.md) 「미결」 | 7 |
| [스키마 명세](schema-catalog.md) 「미결」 | 1 (데이터 테이블·ERD 설계로 위임) |
| [ERD 설계 변천과 검토 기록](records/phase1-erd/design-review-history.md) 「미결」 | 3 |
| [데이터 소스 수집 명세](data-sources.md), [원본 보관과 수집·파싱 실패 처리 규칙](storage-and-failure-rules.md), [매칭 규칙](matching-rules.md), 나머지 근거 기록 | 각 문서 「미결」·「남은 확인」 참조 |

### 통합 계획의 확인 필요 16건

| # | 항목 | 현재 위치 / 상태 |
|---|---|---|
| 1 | v2 이전 조인 키 대조표(J1~J14)·미확인 목록 | git 이력에서 복원 → [조인 키 확인 기록](records/phase1-erd/join-key-checks.md) |
| 2 | 옛 점수 문서 3-1~3-3절(문서=펀드 논증, 위험등급 내생성·c안, 매칭 편향) | git 이력에서 복원 → [점수 저장과 비교 모집단](scoring-and-population.md) 「알려진 분석 위험」에 수록 완료 |
| 3 | 제재공시 게시판 전수 5,727 vs 5,735 | [3단계 입력](io-schema.md) 「미결」 |
| 4 | DART viewer.do Referer 필요 여부 | [데이터 소스 수집 명세](data-sources.md) 「미결」 |
| 5 | finlife 소스 존치 | [데이터 테이블·ERD 설계](data-model.md) 「미결」 |
| 6 | 경영유의사항 API 채택 | [데이터 테이블·ERD 설계](data-model.md) 「미결」, [3단계 입력](io-schema.md) 「미결」 |
| 7 | KRX 매칭 실패 229건 처리 방침 | [2단계 입력](pipeline-flow.md) 「미결」 |
| 8 | CDI 검증 방법(분쟁 검정 폐기 여부) | [3단계 입력](io-schema.md) 「미결」 |
| 9 | ETF 판매사 축 분석 결론 재작성 | [점수 저장과 비교 모집단](scoring-and-population.md) 「미결」 |
| 10 | 제재 증분 필터 = inputDate 확정 수준 | [원본 보관과 수집·파싱 실패 처리 규칙](storage-and-failure-rules.md) 「미결」 |
| 11 | 제재 문서 키(emOpenNo 공백, 후보 4필드 안정성) | [데이터 테이블·ERD 설계](data-model.md) 「미결」 |
| 12 | 8차 미팅(09-23) 결정 확정 여부 | [점수 저장과 비교 모집단](scoring-and-population.md) 「미결」 |
| 13 | 티켓 메모 되돌림 8건의 Notion 반영 여부 | [초기 소스 확인](records/phase1-erd/initial-source-checks.md) |
| 14 | 9차 미팅(09-30) 안건 등록 | [데이터 테이블·ERD 설계](data-model.md) 「미결」 |
| 15 | 팀 문서 규칙 6(「저장소 폴더 이름 gate-a/b/c는 고치지 않음」)과 이번 이동의 충돌 | 아래 표 |
| 16 | DBML 주석의 옛 번호 | 해소. 주석만 교정 허용(대현 결정, 2026-09-29). 주석을 새 문서 이름+절 제목으로 교정. 표·칼럼·타입·키·관계·enum 값은 불변 |

| 질문 | 결정 주체 | 필요 시점 |
|---|---|---|
| 팀 문서 규칙(tpm-doc-ko 용어 규칙 6)의 「저장소 폴더 이름 gate-a/b/c는 고치지 않음」 행을 이번 이동에 맞게 갱신 | 대현 | 이동 커밋 전 |
| Notion 등 외부 문서의 옛 경로 링크(`main` 브랜치 기준) 갱신 | 대현 | 이동 커밋 후 [확인 필요: 일자] |
