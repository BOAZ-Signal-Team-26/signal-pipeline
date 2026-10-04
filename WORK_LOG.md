# 작업 기록

## 2026-10-04 — 리뷰 지적 반영과 S3 세부 규칙 확정

- 위험등급 규칙 PR의 CodeRabbit 지적 2건 반영: 법적 근거와 10월 4일 PM 결정 분리, 클래스 등급과 펀드 대표 등급 구분 명시.
- ERD v2.2 PR의 지적 11건 중 10건 반영, 1건은 미결로 이관: 대표 등급 근거 문서가 같은 펀드의 대표 문서인지 적재 검증에 추가, 이관 3단계에서 제거된 키 사용 중단, B11 근거 형식 정리, 텍스트·절 재사용 경로에서도 LLM 추출 단계 연결, 타입 표기 4곳, 본문 추출 실패의 파트 B 전파, 스냅숏 페이지 파일 버전 경로, 원천 키 폴더 = 문서 키, 스크립트 인코딩·접미사 처리. 실행별 추출 시도 이력 보존 방법은 [데이터 테이블·ERD 설계](docs/data-model.md) 「미결」에 추가(주영, 10월 7일).
- S3 세부 4건 중 3건 확정: 스냅숏 수명 주기는 생성 30일 뒤 날짜 기준, 퍼센트 인코딩은 `/`·`~`·`%`·제어 문자만(한글 그대로)·200바이트 초과는 `-h` + SHA-256 앞 12자, 같은 기준일 재수집은 `r2/` 폴더. `.meta.json` 유무는 미결 유지.

## 2026-10-04 — KRX 데이터 보관 정책 3건 초안 (PM, 마감 10월 7일)

- 소스 이름 `krx_etf_daily`, 일별 파일 프로젝트 종료까지 보관(삭제 없음, 10년 소급 조회 가능)을 [원본 보관 규칙](docs/storage-and-failure-rules.md) 「KRX 데이터 보관」에 정리.
- KRX 매칭 실패 229건을 공공데이터포털 전체 목록과 재대조. 규칙 4개(괄호 표기 제거, 브랜드 개명 4건, 환헤지 표기, `TR`→`Total Return`)로 149건 자동 연결, 49건은 PM(대현) 확인 후 연결, 10건은 확인 필요, 21건은 보류. 보류였던 38건을 같은 발행사의 포털 상품과 다시 대조해, 포털이 이름을 다르게 쓴 7건(예: `미국`→`US`, `테슬라`→`TSLA`)은 확정, 단어가 빠진 10건은 확인 필요, 가장 가까운 상품이 다른 상품인 21건은 보류로 나눔. 처음에는 이름이 그대로 들어 있는지만 보고 「포털에 없다」고 판단했으나 틀렸음([매칭 규칙](docs/matching-rules.md) 「KRX 매칭 실패 처리」). 처음에는 `TR`을 떼고 대조해 9건을 `TR`이 아닌 ETF에 잘못 연결했고, 같은 날 발견해 고침. 환헤지 표기 점검을 후보가 1개일 때도 적용하지 않아 `PLUS 미국S&P500(H)`(환헤지)를 환노출형 펀드에 잘못 연결한 것도 같은 날 외부 검토에서 발견해 보류로 바꿈. 결과 `research/samples/krx_unmatched_rematch.csv`, 확인 결과 `krx_rematch_confirmed.csv`·`krx_rematch_review.csv`, 스크립트 `research/scripts/rematch_krx_unmatched.py`. 상품 코드(ISIN)로 검증할 수 있는지 확인했으나 포털 필드에 KRX 코드가 없어 불가, 브랜드와 운용사 코드 교차 확인(187/191 일치, 어긋난 4건은 미래에셋 옛 코드 225)으로 대신함.
- [2단계 입력](docs/pipeline-flow.md) 미결 2행 갱신(229건은 팀 확인 대기, 적재 주기는 주영 유지).

## 2026-10-04 — 운용사 연결 순서 결정 (ERD v2.2 수정 12)

- 결정(PM(대현) 승인): 운용사 연결은 금투협 공시 목록의 운용사 코드를 1단계, 표준코드 자리 + 대응표를 2단계로 함. 펀드·ETF 공통. KR5 체계 미결 해소.
- 근거: KR5 체계 표준코드의 운용사 자리는 펀드명과 일치 약 57%(K55 약 91%). 공시 목록 조회로 KR5 ETF 운용사가 현재 운용사로 나옴(대응표에 없는 225 포함).
- [schema.dbml](docs/schema.dbml)·[스키마 명세](docs/schema-catalog.md)·[데이터 테이블·ERD 설계](docs/data-model.md): distributor.kofia_disclosure_company_code 추가. 표 17·관계 42·enum 26 그대로.
- [매칭 규칙](docs/matching-rules.md) 「운용사 연결 순서」 신설, 미결 KR5 행 삭제. [운용사 코드 대조 기록](docs/records/phase1-erd/manager-code-check.md)에 근거 추가.

## 2026-10-04 — 대응표에 없는 운용사 코드 7종 정리

- 공공데이터포털 펀드상품기본정보 전체(183,724행)를 받아 K55 체계 운용사 코드 100종을 금투협 운용사 대응표와 대조. 대응표에 없는 코드 7종(113행)을 확인.
- [매칭 규칙](docs/matching-rules.md) 「대응표에 없는 운용사 코드」 절 신설: 237은 한화자산운용(213) 별칭 코드로 연결(금투협 공시 목록 조회로 확인, 운용사 코드 A01021), 보험사 4종·증권사 1종·사모 1종은 Phase 1 대상 아님. 대응표에 없는 코드는 `match_failure`에 `NO_CANDIDATE`로 기록.
- [데이터 테이블·ERD 설계](docs/data-model.md), [데이터 소스 수집 명세](docs/data-sources.md), [schema.dbml](docs/schema.dbml)의 「확인 대기」 문구를 위 절 참조로 변경. KR5 체계 상품(ETF 포함)의 운용사 연결 방법을 미결에 추가.

## 2026-10-04 — S3 트리 확정 반영

- 기준: PM(대현) 승인 S3 트리 확정안. 같은 내용을 signal-infra 저장소 `docs/storage-design.md` 3.2절에도 반영.
- [원본 보관과 수집·파싱 실패 처리 규칙](docs/storage-and-failure-rules.md): raw 경로를 `raw/{source}/{원천 키}/{file_role}__v{n}.{ext}`로 변경(수집일·해시 폴더 폐지, 스냅숏형 API만 기준일 폴더), 소스별 실제 모양 예시, 「바꾼 이유」, API 스냅숏 저장 단위(`page-NNNN.json` + `_complete.json`), raw 압축 안 함, 고아 객체 정책, `derived/` 파일 2개와 파서 버전 형식, `runs/…/llm`, `assets/`, `eval/`, `exports/`, `backups/` 경로, 「적재 순서」 절 신설.
- [schema.dbml](docs/schema.dbml)·[스키마 명세](docs/schema-catalog.md): document.source 소스 7개, raw_object.storage_path 경로 형식, llm_field_extraction.response_sha256 칼럼 추가와 raw_response_path 설명. 표·관계·enum 수는 그대로(17·42·26).
- [데이터 테이블·ERD 설계](docs/data-model.md) 「v2.2」: 수정 11 추가, 표 목록 문구. [데이터 소스 수집 명세](docs/data-sources.md): 저장 소스 이름 표(`data_go_fund`, `krx_etf_daily`).
- 새로 남긴 미결: 스냅숏 객체의 meta.json 유무와 재수집 파일명, 퍼센트 인코딩 범위·해시 접미사 형식, LLM 재호출 생략 규칙(기존 유지), 평가 자료 DB 쪽 접근 분리.
- 수행하지 않은 것: 커밋·푸시, Notion 동기화.

## 2026-10-04 — ERD v2.2 반영 (이슈 #42)

- 기준: 9월 30일 재검토 확정안. 수정 1~9와 B11 안 1은 10월 3일 팀 채널에서 이의 없이 확정, 수정 10은 9차 미팅(9월 30일) 확정. 결정 대기 A(병합)·C(펀드 관측치 표 없음)·E(코드 체계별 두 칼럼)와 10월 4일 판단 항목 3건(펀드 대표 위험등급 칼럼, 클래스 등급 불일치 기록, 문서 작성기준일)은 기본값으로 반영하고 「결정 대기」로 표시했다.
- [schema.dbml](docs/schema.dbml): 표 20 → 17, 관계 47 → 42, enum 30 → 26. 채점·평가 표 4개 연기, analysis_target을 score에 병합, file_extraction·section 키를 원본 파일 × 파서 버전으로 변경, llm_field_extraction·source_watermark 추가, 채울 수 없는 칼럼 5개 제거, 정규 절 분류·작성기준일·펀드 대표 위험등급 칼럼 추가.
- 문서: [데이터 테이블·ERD 설계](docs/data-model.md)에 「v2.2」 절(변경표, 결정 대기와 반대 결정 시 범위)과 「예약 계약(승인 뒤 추가)」 신설, 표 목록·ERD(관계선 42개)·미결·결정 표 갱신. [스키마 명세](docs/schema-catalog.md)는 DBML과 칼럼 단위로 맞춤. [원본 보관과 수집·파싱 실패 처리 규칙](docs/storage-and-failure-rules.md)(derived 경로, 재추출 규칙, 워터마크), [매칭 규칙](docs/matching-rules.md)(코드 체계 분기), [DART 절 분할](docs/records/phase1-erd/dart-section-split.md)(제4부 절 구성 실측), [데이터 소스 수집 명세](docs/data-sources.md), [2단계 입력](docs/pipeline-flow.md), [점수 저장과 비교 모집단](docs/scoring-and-population.md), [3단계 입력](docs/io-schema.md), [ERD 설계 변천과 검토 기록](docs/records/phase1-erd/design-review-history.md), 두 README 맞춤.
- 검증: `@dbml/core` 파싱, 모든 FK 부모 칼럼의 PK/UNIQUE 확인, PostgreSQL 내보내기 성공, 스키마 명세와 DBML 칼럼 대조, Mermaid 관계선 수와 DBML 관계 수 일치.
- 새로 남긴 미결: 판매 중 여부의 판단 근거, 정규 절 분류 값 규칙(F), LLM 6필드 추출 표의 문서/파일 단위, 문서쌍 지표의 입력 저장 방식, selection manifest 위치, 워터마크 검증 방법.
- 수행하지 않은 것: 커밋·푸시, Notion 동기화.

## 2026-10-04 — 펀드 위험등급 처리 규칙 반영

- 기준: Notion 9차 미팅 하위 페이지 「펀드 위험등급 처리 규칙 근거(10/3과제)」(데이터 사이언스(다빈)). PM이 제안대로 채택했다.
- [데이터 테이블·ERD 설계](docs/data-model.md) 「상품과 법인」: 종류형 펀드 등급 1개 원칙, 대표 등급 출처(간이 표제, 없으면 투자설명서 표지), 작성기준일 시점 기준, 클래스 등급 불일치는 확인 대상, 판매사 자체 등급 미사용, 모자형·재간접 처리, 외국 엄브렐러 펀드 제외. 9차 미팅 결과 표의 「확인대기」 해소. v2.2 판단 항목에 펀드 대표 위험등급 칼럼과 불일치 기록 위치 추가.
- [스키마 명세](docs/schema-catalog.md) risk_grade 행, [점수 저장과 비교 모집단](docs/scoring-and-population.md) 「층화와 결측」에 같은 규칙 반영.
- PM 결정 2건(다빈 제안에 없던 것): 간이가 없는 펀드는 투자설명서 표지 등급, 외국 엄브렐러 펀드는 Phase 1 제외.
- 수행하지 않은 것: DBML 변경, 클래스 간 등급 차이 건수 확인(다빈, 10-08).

## 2026-10-04 — 10-02 CDI 4축 변수표 반영

- 기준: Notion 「CDI 4축 변수표 (10/2)」(데이터 사이언스(다빈)). 9차 미팅(09-30) 회의록과 dev 브랜치 문서를 대조한 뒤, 변수표를 지표 구성의 기준으로 삼고 설계 문서를 맞췄다.
- [점수 저장과 비교 모집단](docs/scoring-and-population.md): 계산 단위를 「절 채점, 문서 = f(절)」에서 「문서 단위 직접 계산, 절은 위치용」으로 변경. 지표 구성 표, 작성기준 항목 점검의 파트 A 옆 출력, 축 안 결측 규칙, 요약 비교 Phase 2, 추가 버전 자산(형태소 분석기·작성기준 판 등), 사전 구성(문서 내 용어 제외), 미결 갱신(가중치 기한 11-12, 파일럿 확인 3건, 간이 입력 경로, 표 분리 방법). 축 3 정의는 변수표를 따르기로 PM 결정, 9차 회의록의 「중요 조항의 문서 내 상대 위치」는 쓰지 않음.
- [데이터 테이블·ERD 설계](docs/data-model.md): 두 파트 저장 계약에 작성기준 항목 점검 행 추가. 「10-02 변수표가 ERD에 주는 영향」 절 신설(SECTION score 보류, 문서쌍 Phase 2와 결정 대기 항목 A의 관계, 작성기준일·작성기준 판·표 영역 저장 필요). DBML은 바꾸지 않았다.
- [3단계 입출력 Schema 설계 입력](docs/io-schema.md): 가중치 기한 문구, 축 판정 불가 전파, 작성기준 항목 점검 출력 요구와 envelope 제안 블록 추가.
- [2단계 데이터 파이프라인 Flow 설계 입력](docs/pipeline-flow.md): 4단계 상자를 문서 단위 채점으로 수정, 파트 A 옆 작성기준 항목 점검 표시.
- PM 확정(10-04): 3-1a 파트 A 옆 출력과 3-5 Phase 2 이동(변수표 제안) 승인. 층당 고유 fund_key 30개 이상·층 병합 없음(8차 미팅 기준) 확정.
- 변수표 재검토(데이터 사이언스·데이터 엔지니어링) 반영: 펀드당 대표 문서를 역할별 하나씩(투자설명서·간이)으로 변경(PM 확정), 입력 추출 실패 결과 상태·사유 코드 표 추가, 미분류 단어 기록 위치 추가(2-1 분모 포함·분자 제외는 09-30 다빈 계산 계획 기준), 사전 확장 미결을 다빈 계획(「용어의 정의」 10건 확인, 10-07)으로 갱신, 미결 표에 주영 확인 2건(부·절 제목 위치 추출, 글꼴 굵기·색 추출) 추가, 대표 문서 우선순위 기한을 10-07로 갱신.
- 10-04 다빈 제안 반영(PM 승인): 파일럿 전 파트 B = 축 1·2(가중치 출발점 각 1/2), 투자설명서 3-1b-① 위치 준수는 파트 A 옆 작성기준 항목 점검으로, 3-1b-② 순서 일치도는 메모만, 축 3은 파일럿 뒤 3-2·3-3으로 재도입. 파트 B는 축 구성별 지표 버전으로 분리하고 공식 run에는 한 버전만. 출력의 축 3은 `NOT_IN_VERSION`(제안). 데이터 사이언스·데이터 엔지니어링·데이터베이스 검토로 DBML 변경 불필요 확인. 함께 반영: 펀드 대표 문서 규칙(투자설명서 PRIMARY 1 + 간이 0~1), 축간 변환 기준집단과 층내 백분위 비교 집단 구분.
- 수행하지 않은 것: DBML 변경, 결정 대기 항목 A·B11 결정, Notion 변수표 페이지 댓글.

## 2026-09-23 — ERD v2 6관점 검토와 A 조치 반영 (v2.1)

- v2(20표)를 architect·data-engineer·data-scientist·platform-engineer·cloud-architect·backend-developer 6개 관점으로 검토해 [22](docs/records/phase1-erd/design-review-history.md)에 정리했다. 결론: 진단(19 R1/R3)은 맞고 처방이 과함. 표 수보다 run_id 결합과 DBML 밖 규칙 약 40개가 실제 비용.
- 조치를 A(팀 결정 없이 고칠 수 있는 명백한 결함, 즉시 반영)와 B(09-30 팀 결정 요청)로 나눴다. A만 반영했다.
- A 반영 파일: [schema.dbml](docs/schema.dbml)(run_kind/upstream_run_id/is_official/published_at, extraction_run_id, population_snapshot 유일키·중복 칼럼, enum 16개, metric_definition.direction), [20](docs/data-model.md)(A5 문구, v2.1 절), [21](docs/schema-catalog.md)(칼럼·키·enum·공개 식별자 규칙), [01](docs/data-model.md)(6절, ERD), [02](docs/storage-and-failure-rules.md)(경로 표), [gate-b/README](docs/pipeline-flow.md)(참조), README(관계 수).
- architect 에이전트가 1차 반영을 검증했다(A1~A6 정확, HIGH 1건: section_id를 run 무관 공개 ID로 분류한 오류). HIGH-1과 M-1~M-5·L-1~L-3을 2차 반영했다: extraction_run_id를 복합 FK로 upstream과 묶음, member.run_id 삭제, run 종류·기준일·공식 run 검증 목록을 20에 추가, 공개 식별자 표에서 section_id를 "(run_id, section_id) 쌍" 행으로 이동. 상세는 22 「검증 결과」.
- 검증(2차 반영 뒤): `@dbml/core` 파서 20개 표·47개 관계·enum 30개 통과, 모든 FK 부모 칼럼의 PK/UNIQUE 확인, PostgreSQL SQL 메모리 내보내기 성공, Mermaid 관계선 47개 일치, `git diff --check` 통과. 상태성 varchar 칼럼 잔여는 `score_dependency.input_role`(B1 보류 표) 하나.
- 커밋 63ed75e로 `origin/main`에 푸시했다(v2 + v2.1 함께).
- Notion 동기화(요약과 GitHub 링크만, 정본은 GitHub): 「데이터 테이블·ERD 설계」 산출물 페이지(상단 정본 안내 callout, pipeline_run 설명, 인수 체크, 검증 결과, 9절 v2.1 요약 신설 — 표별 상세 2·3·7절은 v2 스냅숏으로 두고 갱신하지 않음), 「Schema & Relation」 티켓(한 줄 요약, v2.1 요약, Mermaid의 pipeline_run·analysis_target·member 블록과 관계선, 검증, 남은 것, 인수 체크, 설계 문서 링크), 「파이프라인 Flow」 티켓(입력 표 20개·실행 모델·09-26 골든패스·경로 규약, 완료 조건의 run_id 항목, 선행 의존). 회의록 원문은 수정하지 않았다. 「9차 미팅 09-30」 페이지는 조회 결과에 삭제 표시가 있어 B 안건 추가를 보류했다.
- 수행하지 않은 것: B 조치(표 제외·artifact 표·평가 스키마 분리·서빙 계약·grader_key 등)는 09-30 결정 대기, 실제 DB 적용. 22의 행 수·작업량 추정치는 검증하지 않았다.

## 2026-09-23 — ERD v2 중단 작업 이어서 완료

- 재개 시 작업 트리에서 20개 표로 수정된 DBML, 01 본문, 20 재설계 문서를 확인했다. 이전 세션 대화 전체가 아닌 저장된 작업 기록과 파일을 기준으로 이어갔다.
- 01의 오래된 14개 표 그림을 20개 표·45개 FK 관계로 갱신했다. 복합 FK는 한 선으로 표시하고 nullable 관계를 반영했다.
- 누락된 [21 스키마 명세](docs/schema-catalog.md)를 DBML에서 생성했다. 전체 245개 칼럼과 PK/UNIQUE/FK·상태값을 담았다.
- README와 04 점수 정책을 v2에 맞췄다. 문서/쌍/펀드 점수, 원자값·축값·최종값의 개별 행, NULL 원점수와 결과 상태, 독립 정규화 상태를 반영했다. 18·19는 과거 검토 이력임을 표시했다.
- 검증: 실제 `@dbml/core` 파서 20개 표·45개 관계 통과, 모든 FK 부모 칼럼의 PK/UNIQUE 확인, DBML과 Mermaid의 테이블·관계·FK 칼럼 목록 일치, 관련 Markdown 상대 링크 32개 존재 확인, PostgreSQL SQL 메모리 내보내기 성공, `git diff --check` 통과.
- 검증은 논리 구조와 문서 일관성 범위다. Mermaid 이미지 렌더링, 조건부 적재 검증 구현, 실제 데이터 파일럿, 운영 DB 적용은 수행하지 않았다. SQL 내보내기는 DB 제품 선정이 아니다.
- 이번 재개에서는 Notion을 새로 조회하거나 수정하지 않았다. 20의 기존 조회 기록을 보존했으며 산식·배점·평가 프로토콜·물리 DB 결정은 미확정으로 유지한다. 커밋·푸시는 하지 않았다.

아래 기록은 v2 재설계 이전 검토 이력이다.

## 2026-09-23 — Notion 대조 및 미결정 사항을 포함한 ERD 재검토

### 요청과 기준

- 요청: 재설계된 ERD를 미완료 조사·미결정 사항까지 고려해 재검토하고, Notion 내용을 설계 문서에 반영. 이후 회의록의 미결정 항목에 대해서만 권고 방향 정리.
- 검토 시작 기준 커밋: `09650c6`.
- 기존 커밋 `fec9dbb`는 9→14개 표 재검토안, `09650c6`는 상대경로·자산 버전·예약 표 관련 보완이다. 두 커밋은 이번 작업 시작 시 이미 존재했다.
- 상세 검토: [19_pending_decisions_review.md](docs/records/phase1-erd/design-review-history.md).

### 확인한 Notion 자료

- [데이터 테이블·ERD](https://app.notion.com/p/3e0e1ac705058115b023e714be75b2c8): 최초 조회는 이전 9개 표 본문을 반환. 검색 결과와 대조한 뒤 URL 재조회로 14개 표와 Mermaid 반영 확인. 확인한 편집시각은 `2026-09-22T15:30:30.986Z`.
- [8차 미팅 09-23](https://app.notion.com/p/3e3e1ac7050581929ac1defef0e90b7e): 안건 사전 정리 상태. 계산 단위·배점·분모·검증 조건 등 미결 항목 확인.
- [9차 미팅 09-30](https://app.notion.com/p/3e3e1ac705058124ae0ad164ff707615): 점검표의 법적 적용, 후보 절, 분모·판정 규칙 미결 확인.
- [CDI 변수표](https://app.notion.com/p/3d6e1ac7050581568e30e53cb38f56a7), [산출 단위](https://app.notion.com/p/3d6e1ac7050581d3a541d488e1b0f3ce), [참고문헌](https://app.notion.com/p/3e1e1ac7050581b8b8cee9281c108348), [CDI 초안](https://app.notion.com/p/3d6e1ac70505806f96eac8145e3c95a1).
- [저장소 구성](https://app.notion.com/p/3e2e1ac70505818cbf66d63c9b45e782): 저장소 3개 결정과 실제 개명·이관·권한 설정 작업을 구분.
- [파이프라인 Flow](https://app.notion.com/p/3e1e1ac7050581f5b9e4c3331a1f17b1): 입력 설명에 기존 9개 표 표현이 남아 있음.

조회본 기준으로 기록했다. 이후 회의 결과나 팀원 조사 변경 시 다시 대조해야 한다. 마지막 회의록 재조회 시도는 도구 오류로 실패했으며, 권고는 같은 작업 중 앞서 성공적으로 읽은 본문에 근거한다.

### 수정한 문서

| 파일 | 반영 내용 |
|---|---|
| [19 재검토](docs/records/phase1-erd/design-review-history.md) | 근거·결정 상태, 설계 쟁점 7개, 미결 항목별 권고, Notion 동기화 오류와 검증 결과 신설 |
| [18 기존 검토](docs/records/phase1-erd/design-review-history.md) | “예약 표 2개”를 “확장 영역 2개, 표 수 미정”으로 수정. score PK와 UNIQUE 구분 정정 |
| [01 논리 스키마](docs/data-model.md) | 미결정에 따라 기존 키·관계도 재검토할 수 있음을 명시하고 19 연결 |
| [04 점수 정책](docs/scoring-and-population.md) | 고지 충실도 점수화 방향 반영. 배점·분모·적용범위 미결, 계산 불가와 최종 문서 점수 저장 문제 명시 |
| [00 공유 전제](docs/README.md) | 과거 점수 적용범위와 최신 방향을 구분. 과거 라벨 계획을 검증 확정안으로 취급하지 않도록 보완 |
| [15 API 명세](docs/data-sources.md) | 고지 충실도의 오래된 필터 표현 정리, 법적 서류 대응·적용범위는 별도 미결로 유지 |
| [02 원본 보관](docs/storage-and-failure-rules.md) | RAW_ROOT의 공통 데이터 루트 의미와 파생 텍스트·manifest 상대경로 보완안 명시 |
| [schema.dbml](docs/schema.dbml) | 계산 불가 결과·구조 정보·파생 경로 관련 주석 보완. 표·칼럼·키·관계는 유지 |
| [README](README.md) | 최신 재검토 링크와 저장소 3개 구성 결정, 실제 이관 미완료 구분 |

### 주요 판단

1. 현행 논리안은 **14개 표·31개 관계**다. “14→16개로 끝남”은 확정할 수 없다. 문서/문서쌍 지표와 검증이라는 두 확장 영역의 입도·키·저장 계약부터 결정한다.
2. score의 PK는 `score_id`, `(run_id, section_id, score_type)`은 UNIQUE다. `section_id`와 `raw_score`가 NOT NULL이므로 문서 결과나 계산 불가 결과를 JSON 칸만으로 자동 수용할 수 없다.
3. 문서 최종 점수·백분위 저장, 평가 원응답, 여러 구간의 근거, 표·페이지 구조 보존은 미결이다. 파일 manifest와 관계형 저장을 요구에 맞게 비교한다.
4. 사용자가 확정했다고 알려준 사람·LLM 병행/사람 합친 안, 고지 충실도 점수화, 문서간 층내 백분위는 재논의하지 않았다. 관련 세부 조건만 권고했다.
5. 조회 회의록의 미체크 박스는 `10+7+7+8+4+3=39개`다. 이미 방향이 정해진 항목도 체크가 남아 있으므로 독립 미결 결정이 39개라고 단정하지 않는다.
6. 우선순위는 **계산 단위·필수 입력·분모·판정 불가 상태·저장 위치**다. 주영의 09-26 인계 초안에 함께 영향을 준다. 배점·임계값은 그 계약 안에서 버전 관리한다.

권고는 팀 승인된 결정이 아니다. 특히 정의어 2회 이하, 상호참조 감점, 요약 유사도, 축별 정규화·가중치는 파일럿과 합의가 필요하다.

### 검증 결과

- 실제 `@dbml/core` 파서 통과: 14개 표·31개 관계.
- HEAD 대비 칼럼·타입·PK/NOT NULL/UNIQUE 속성 동일 확인.
- DBML과 Mermaid 부모→자식 관계 목록(중복 포함) 일치.
- 당시 변경 Markdown과 19 문서의 상대 링크 24개 존재 확인.
- `git diff --check` 통과.

실제 DB 적용·CDI 계산·외부 대화형 ERD 렌더링은 수행하지 않았다. 이전 작업의 SQL 내보내기 검증과 이번 작업의 검증을 혼동하지 않는다.

### 완료 범위와 다음 작업

- 완료: Notion 조회·대조, 로컬 설계 문서 반영, 미결 항목 권고, 구조 일관성 검사, 본 작업 기록 작성.
- 이번 작업에서는 **Notion 원문 수정, 커밋·푸시, 저장소 개명·파일 이관을 수행하지 않았다.** 문서 변경은 작업 트리에 남아 있다.
- 다음: 회의 결과로 결정 상태를 갱신하고, 문서/문서쌍 관측값·평가 결과·계산 불가 상태 계약을 구체화한 뒤 ERD를 수정한다.
- Notion에는 남은 오류(파일 형식·고정 파일 수·PK 표현·표 수 단정·물리화 표현)와 Flow 티켓의 9개 표 설명을 동기화해야 한다. 외부 아티팩트의 실제 갱신 여부도 별도로 확인한다.
