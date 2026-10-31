# 작업 기록

## 2026-10-25 — 로컬 DDL을 스키마 3개로 배치, `document.distributor_id` 외래 키 제외, 시도 결과에 `STARTED` 추가 (#58)

- 기준: PR #59 데이터 엔지니어링·인프라(주영) 리뷰(10월 22일), signal-infra `docs/storage-design.md` 3.6(10월 18일 승인), [원본 보관 규칙](docs/storage-and-failure-rules.md) 「적재 순서」 1·5
- 바꾼 것
  - `db/migrations/001_erd_v2_2.sql`: 스키마 `raw`·`staging`·`mart`를 만들고 표 17개·외래 키 참조·인덱스에 스키마를 붙임(5 / 9 / 3). 검색 경로(search_path)에 의존하지 않음
  - `document.distributor_id → distributor` 외래 키 제외(raw에서 staging을 가리킴). 대신 `db/checks/document_distributor.sql`(0행이어야 함). DBML 관계는 논리 관계라 그대로 두고 메모만 추가
  - `collection_attempt.outcome` CHECK와 DBML `attempt_outcome_enum`에 `STARTED` 추가. NOT NULL은 유지
  - [데이터 테이블·ERD 설계](docs/data-model.md) 「물리 결정」 6 추가, 「DBML과 물리 형태의 차이」·「운영 규칙」 갱신. `db/apply.py` 설명에 「적용한 파일을 고치면 DB를 새로 만듦」 추가
- 바꾸지 않은 것: 계정·권한(grant)·기본 권한은 RDS 구축 때 별도 마이그레이션. DBML 표에 스키마 이름을 붙이지 않음
- 검증: 빈 DB에 3회 적용 오류 0건, 2·3회째 스키마 덤프 같음. 스키마별 표 5 / 9 / 3, `public` 0, 외래 키 41, CHECK 63, 일반 인덱스 14, NOT NULL 칼럼 127. `@dbml/core` 파싱 표 17·관계 42·enum 27. pytest 98개 통과(스키마별 표 수 대조 추가), ruff 통과

## 2026-10-21 — 로컬 PostgreSQL에 수집·절 분할 결과 4개 표 적재 (#62)

- 기준: 11차 미팅(10월 14일) 안건 7. 11월 12일 원점수 산출의 기준 실행 환경을 로컬 PostgreSQL로 둠. 적재 입력의 파서 버전은 추출기와 같은 값(`extract.parser_version()`, 이 브랜치에서는 prep-7)
- 바꾼 것: [local_load.py](src/signal_pipeline/loading/local_load.py) 신설. `document`·`raw_object`·`file_extraction`·`section`과 외래 키로 꼭 필요한 `pipeline_run` 1행을 적재
  - 다시 적재: 트랜잭션 하나에서 `TRUNCATE ... RESTART IDENTITY CASCADE` 뒤 자연키 순으로 넣음. 시각은 입력 파일 값만 써서 두 번 실행해도 ID·내용이 같음. CASCADE로 같이 비워질 하위 표(`score` 등)에 행이 있으면 `--force` 없이는 멈춤. 하위 표는 표 이름 문자열이 아니라 oid로 따라감(검색 경로가 달라도 빠지지 않음)
  - 스키마: 접속 옵션으로 검색 경로를 `raw,staging,mart`로 둠. `TRUNCATE` 대상은 스키마를 붙여 씀
  - 이 스크립트는 로컬 기준선용 일회성 적재. DAG 적재는 `file_extraction` 재사용·덮어쓰기 규칙 때문에 upsert로 Week 7에 따로 만듦
  - 추출 기록: prep-7 전체 실행 중 마지막 것(`runs/extract-20261013T112709Z-dad0`). `text.txt`·`structure.json` 해시를 추출 기록과, `structure.json`의 원본 해시·파서 버전을 `raw_object`와 대조해 다르면 멈춤
  - `document`: `received_date`는 접수번호 앞 8자리. `report_name`·`is_correction`·`document_type`은 목록 응답(`raw/dart/_list/`)의 `report_nm`에서 수집기와 같은 규칙(`classify_report`)으로 정함. 목록 레코드 원문은 `source_record_payload`. 목록에 없거나 투자설명서가 아닌 접수면 멈춤. 본문 PDF 파일명의 「간이」는 문서 종류에 쓰지 않음(PR #63 리뷰: 해당 2건은 정정 투자설명서 접수에 첨부 본문만 간이투자설명서 파일). 표지 HTML 파싱이 필요한 칼럼은 Week 7
  - `raw_object.source_object_key`는 `{접수번호}/{file_role}`. 뷰어 목차(`viewer_tree`)는 `file_role` enum에 없어 적재하지 않음(enum 추가는 후속 이슈)
  - PDF 바이트가 같은 두 문서(20260918000190, 20260918000389)는 문서마다 `raw_object`·`section`을 따로 둠([원본 보관 규칙](docs/storage-and-failure-rules.md): 같은 바이트가 여러 문서에 나오면 각 문서의 연결을 남김)
- 결과(10월 25일, 로컬 `signal-pg-local`, 스키마 3개 DDL): `document` 504(정정 469, 정정 아님 35, 모두 투자설명서), `raw_object` 1,354(본문 PDF 502, 표지 HTML 503, 표지 XML 349), `file_extraction` 502, `section` 17,251(`structure.json` 501개 합계 17,217 + 중복 문서 34). 경계 실패 480개는 글자 위치·본문 NULL. 실행 약 9초. `db/checks/document_distributor.sql` 0행
- 검증
  - 두 번 실행: 5개 표의 행 수와 전체 내용 md5가 같음
  - CASCADE 보호: 롤백할 트랜잭션에서 `raw.source_watermark`에 1행을 넣으면 검색 경로가 `raw,staging,mart`일 때와 `public`일 때 모두 `raw.source_watermark`를 찾아 멈춤
  - 원본 대조(전수): 문서별 절 수 차이 0건, 찾은 절 16,771개의 `section_text`가 `text.txt` 잘라 낸 값과 모두 같음, 표본 10개 절의 위치·제목 일치, 외래 키 고아·자연키 중복 0건, `raw_object.sha256`과 `.meta.json` 불일치 0건
  - pytest 101개 통과(목록 기반 문서 종류, 목록에 없는 접수 테스트 추가), `ruff format`·`ruff check` 통과
- 적재 결과 점검 [load_checks.py](src/signal_pipeline/loading/load_checks.py)(읽기 전용, 10월 25일): 11차 미팅 로컬 점검 체크리스트(행 수·외래 키 고아·경계 실패 범위 NULL·파서 버전·원본과 `derived/` 해시 전수)와 [데이터 테이블·ERD 설계](docs/data-model.md) 「적재 검증 규칙」 중 적재한 표에 해당하는 1·4·6·7·12·16·17, `document` 목록 기반 칼럼 결측. 기대 행 수는 디스크 입력에서 다시 셈. 하나라도 실패하면 종료 코드 1. 10월 25일 21개 항목 모두 통과, 가동 점검 대조표에 기록. DDL 오류 0과 2회 실행 비교는 `db/apply.py`·`local_load --checksum`으로 따로 확인

## 2026-10-21 — 절 경계 보완 규칙 2개, 파서 버전 prep-8 (#60)

- 기준: prep-7 502건의 절 경계 실패(`SECTION_BOUNDARY_NOT_FOUND`) 483개 원인 분석과 보완 규칙 시험(PM(대현), 10월 20일, 테스트&리서치 문서 「절 경계 실패 483개 절 원인 분석과 보완 규칙 시험」)
- 바꾼 것([dart_sections.py](src/signal_pipeline/parsing/dart_sections.py), [extract.py](src/signal_pipeline/parsing/extract.py))
  - 부 표제 거르기: 목차 뒤 「제N부」 줄 뒤에 글이 있으면 목차 부 제목 앞 4글자가 들어 있거나 유사도 0.6 이상일 때만 표제로 봄. 제1부 본문의 「제2부 중 … 참고하시기 바랍니다」를 표제로 잡아 제1부 뒷부분이 제2부로 들어가던 문제(실패 100개). 글자가 두 번씩 찍힌 표제(「제제 33 부부」)는 한 번씩으로 되돌림
  - 절 시작 네 번째 규칙: 기존 세 규칙이 모두 실패하면 앞 절 뒤 같은 번호의 40자 이하 줄 중 목차 제목과 유사도(`difflib.SequenceMatcher`)가 가장 높은 줄(0.6 이상)을 받음. 번호 뒤 점이 빠진 줄(「2 연도별 설정 및 판매 현황」)도 받음. 합본 관련회사 절은 받지 않음
- 결과(prep-7 `text.txt` 501건에 저장소 파서 재실행, 구조 없는 2건 제외): 목차 절 실패 480 → 41, 절 적중률 97.00%(15,535/16,015) → 99.74%(15,974/16,015). prep-7에서 찾은 절의 시작 위치 변화 0, 사라짐 0, 절 범위 규칙 위반 0. 앞 절에 합쳐져 있던 절이 분리되어 끝 위치가 바뀐 절 348개, 부 범위가 바뀐 문서 26건
- 남은 41개: 목차는 회사별·본문은 합본인 관련회사 절 17, 본문에 절 없음 12, 제목이 완전히 다름 5, 유사도 0.6 미만 3, 절 순서 뒤바뀜 2, 글자 번호(「다.」) 하위 항목 1, 목차에 같은 제목 두 번 1. 억지로 맞추면 오검출이라 실패로 둠
- 바꾸지 않은 것: `structure.json` 형식, 관련회사 절 처리, 유사도 0.6보다 낮은 기준·동의어 목록(시험에서 효과 없음 또는 오검출 위험)
- 유사도 규칙은 뒤 절이 앞의 세 규칙으로 잡히는 줄보다 앞에서만 찾음. 목차 부 제목이 4글자 미만이면 제목 전체로 대조, 목차 부 표제의 겹친 글자도 되돌림(PR #61 코드래빗 리뷰). 반영 뒤 502건 수치 같음
- 목차 「제N부」 단독 줄 다음이 절 항목(「1. 투자대상」)이면 부 제목을 비워 둠. 그 절 제목을 부 제목으로 쓰면 본문 「제1부 모집 …」 표제가 걸러져 분할에 실패함(PR #61 데이터 엔지니어링·인프라(주영) 재현, 10월 24일). 반영 뒤 502건 수치 같음
- 검증: pytest 107개 통과(다른 부 언급 문장, 부 제목 한두 글자 차이, 제목 가운데가 다른 절·점 빠진 번호, 같은 번호의 다른 제목은 받지 않음, 겹친 글자 표제, 뒤 절 안 번호 목록 줄, 짧은 부 제목, 목차 부 표제 다음 절 항목 테스트 추가), `ruff format`·`ruff check` 통과

## 2026-10-14 — 결정 대기 E 확정(구분 칼럼 + 값 칼럼), `.meta.json` 확정, 해시 규칙·기록 순서 보강

- 기준: 11차 미팅(10월 14일) 안건 4. 데이터 엔지니어링·인프라(주영) 10월 13일 PR #43 답변과 PM(대현) 10월 14일 크로스체크
- E: `product.kofia_fund_code`·`standard_code` 두 칼럼을 `std_code_scheme`(enum K55/KR5/KRM/OTHER) + `std_code`(varchar 12)로 교체. enum 26 → 27개. 조인은 (체계, 값) 쌍으로만([매칭 규칙](docs/matching-rules.md) 「코드 체계 분기」)
- 크로스체크(금투협 수시공시 표본 1,499행, 고유 코드 1,200건): 상품 1건이 두 체계 코드를 가지는 경우 0건. ETF 대조 표본 938종목도 0건. 같은 `fund_key` 안에서 클래스마다 체계가 다른 묶음 29개(클래스 2개 이상 88개 중) → 「같은 펀드는 같은 체계」 가정 금지 규칙 추가
- 미결 2건 삭제: K55·KR5·KRM 밖 접두 보존 위치(OTHER로 흡수, [데이터 테이블·ERD 설계](docs/data-model.md)·[매칭 규칙](docs/matching-rules.md)), 스냅숏형 소스 `.meta.json`(둔다, [원본 보관 규칙](docs/storage-and-failure-rules.md))
- `input_sha256` 해시 규칙에 「유니코드 정규화 안 함」, 「절 잇는 순서는 `request.json`의 `inputs` 순서」 추가. 적재 순서 1·5를 「시작 행 기록 → 결과 갱신」으로 명시
- 기록 문서(records)는 본문을 두지 않고 J7·금투협 검증 결정 줄에 바뀐 저장 방식 주석만 추가
- 검증: `@dbml/cli` dbml2sql 파싱, `git diff --check`

## 2026-10-13 — 제4부 관련회사 절: 목차 합본·본문 분리 문서 대응, 파서 버전 prep-7 (#50)

- 기준: PR #51 데이터 사이언스(다빈) 표본 검토(10월 12일) 지적 2번(표본 31번, 목차는 「기타 집합투자기구 관련회사」 한 절인데 본문은 회사별 절)
- 실측(prep-6 502건): 목차 합본·본문 분리 31건. 31건 모두 관련회사 본문이 앞 절로 들어감(문서당 2,458~4,530자, 합계 85,102자). 제4부 밖으로는 번지지 않음
- 바꾼 것([dart_sections.py](src/signal_pipeline/parsing/dart_sections.py), [extract.py](src/signal_pipeline/parsing/extract.py))
  - 목차 제4부 마지막 절이 「기타 … 관련회사」이면, 마지막으로 찾은 절 뒤에서 관련회사 이름(집합투자재산 관리·보관회사, 일반사무관리회사, 집합투자기구 평가회사, 채권평가회사, ESG 평가 등)으로 시작하는 「N.」 줄을 절로 받음. 제목 40자 이하, 번호가 커질 때만. 아무 「N.」 줄이나 받으면 번호 목록 232줄(33건)을 잘못 잡아 쓰지 않음
  - `structure.json`: 절에 `in_toc`(목차 절 true, 본문에서만 찾은 절 false, 요약정보·other null), 최상위에 `toc_replaced_sections`(본문 절로 대신한 목차 절. 경계 실패로 세지 않음)
  - 요약 `body_found`는 찾았거나 대신한 목차 절 수(`toc_section_count`를 넘지 않음), 목차에 없는 본문 절 수는 `body_only`
- 결과(`--workers 4`, 502/502 EXTRACT_OK): 31건 모두 관련회사 절을 찾음(본문 절 126개, 대신한 목차 절 30개). 절 적중 15,567 → 15,597/16,080(96.8% → 97.0%). 나머지 470건은 prep-6과 절·블록·텍스트가 같음
- 독립 검증(관련회사 이름 목록을 쓰지 않음): 31건 중 10건을 PDF 글자 크기·굵기·위치로 읽은 절 표제와 대조해 불일치 0건. 목차·본문 모두 합본인 문서 10건은 PDF에서도 합본(관련회사가 「가.」「나.」 하위 항목). 31건 제4부 경계는 이어지고 겹침 없음
- 남은 것: 목차·본문 모두 분리인데 목차에 없는 「7. ESG 평가회사」 절이 있는 3건, 목차는 분리·본문은 합본인 4건, 목차에 제4부 절이 없는 15건, 목차·본문 제목이 다른 절(예: 「수탁회사」 / 「신탁업자」)은 그대로. `docs/processing-requirements.md` 4-6에 새 필드 2개 반영은 데이터 엔지니어링·인프라(주영) 후속 PR에 요청
- 검증: pytest 96개 통과(목차 합본·본문 분리 받음, 목차·본문 합본의 번호 목록은 받지 않음 테스트 추가), `ruff format`·`ruff check` 통과

## 2026-10-13 — 금감원 제재 `inputDate` 판정 확정, 제재공시 법인 매칭 실패 사유 2개 추가

- 기준: 제재공시 목록 수집·매핑 검토 실측(PM(대현), 10월 13일). OPEN API 13회 호출, 제재공시 게시판 표본 63건, 법인 매칭 표본 20건
- `inputDate` 판정: 10월 1일~13일 조회 12건 중 10건이 사건일 9월·입력일 10월이라 확정. [원본 보관 규칙](docs/storage-and-failure-rules.md)·[소스 확인](docs/data-sources.md) 미결 행을 지우고 본문에 근거를 적음. API로 받을 수 있는 자료가 2026-09-03 입력분 이후뿐이라는 실측도 [소스 확인](docs/data-sources.md)에 적음
- 실패 사유 2개 추가([schema.dbml](docs/schema.dbml) `failure_reason_enum`, [매칭 규칙](docs/matching-rules.md), [스키마 명세](docs/schema-catalog.md)): `OUT_OF_SCOPE_SECTOR`(펀드를 판매·운용하지 않는 업권), `NOT_IN_MASTER`(대상 업권이지만 금투협 대응표에 없음을 검수로 확인). 둘 다 실패율 분모에서 제외. 표·칼럼 추가 없음
- 표본 20건 결과: 법인 매핑 14건(판매사 6, 운용사 7, 둘 다 1), 대상 외 2건, 대응표에 없음 3건, 표기 차이 1건(대응표 이름 「하나은행(구.KEB하나은행)」). 상품을 특정할 수 있는 첨부 0/8
- 바꾸지 않은 것: 표·관계·enum 종류 수(enum 값만 2개 추가), 칼럼. 괄호 안 옛 상호를 별칭으로 쓰는 정규화 단계 추가는 제안만 함(데이터 엔지니어링·인프라(주영) 확인 뒤)
- 검증: `@dbml/cli` dbml2sql 파싱 통과. `git diff --check` 통과

## 2026-10-13 — 위험등급 2(클래스 등급 불일치 기록 위치) 기본값으로 확정

- 기준: PM(대현) 10월 13일 결정. 별도 표 전환 기준이던 클래스 간 등급 차이 건수는 받지 않았고, PR #49 데이터 처리 요구 명세가 이 기본값을 전제로 병합됨
- 바꾼 것: [데이터 테이블·ERD 설계](docs/data-model.md) 상단 상태 표·「v2.2」 결정 상태 표·「상품과 법인」·「미결」, [매칭 규칙](docs/matching-rules.md), [스키마 명세](docs/schema-catalog.md), [schema.dbml](docs/schema.dbml) `CLASS_GRADE_MISMATCH` Note의 「결정 대기」를 확정으로 바꿈. 기록 위치는 match_failure 실패 사유 `CLASS_GRADE_MISMATCH` + 상세 JSON, 별도 표 없음
- 바꾸지 않은 것: 표·관계·enum 수, 칼럼. `processing-requirements.md` 「v2.2 결정 대기 기본값」 문구(데이터 엔지니어링·인프라(주영) 담당 문서)
- 검증: `@dbml/cli` dbml2sql 파싱 통과. `git diff --check` 통과

## 2026-10-12 — PR #51 리뷰 반영: `structure.json` 4-6 형식, 표 분리 실패 분리, 실행 기록 즉시 기록 (#50)

- 기준: PR #51 리뷰 댓글(10월 11일, 검토 요청 5건 답변과 PR #49 4-6 반영 요청), PR #49 `docs/processing-requirements.md` 4-6
- 파서 버전 `pdfplumber-0.11_prep-5`. `structure.json` 형식이 바뀌어 새 경로로 다시 추출함
- 필드 이름을 PR #43 설계에 맞춤(10월 12일 PM 결정, `file_extraction` 칼럼 이름과 같게): `schema_version` → `contract_version`(값 3), `text_sha256` → `canonical_text_sha256`, `text_path` → `canonical_text_path`. 실행 기록은 `structure_path`·`structure_sha256` → `structure_manifest_path`·`structure_manifest_sha256`. 원본은 `raw_sha256` 유지
- `structure.json`
  - 최상위 `table_regions`·`page_furniture_regions` → `blocks` 원소(`kind`, `char_start`, `char_end`, 시작 위치 순)
  - 새 블록 3종: `subheading`(「가.」 level 1, 「(1)」 level 2. 범위를 찾은 본문 절 안에서만, 표·머리글 안 줄은 제외), `summary_label`(요약정보 구간 안 표의 첫 열 칸), `emphasis`(굵게 보이는지, `font`/`stroke`, 색 `#RRGGBB`, 검정이면 null)
  - 외곽선 덧그리기는 PDF 글자 그리기 방식(Tr 1·2·5·6)으로 판별. pdfminer가 글자에 이 값을 남기지 않아 `pdf_layout._track_render_mode`에서 글자를 만들 때 붙임
  - 색은 4-6대로 검정만 null. MS Word 문서는 본문이 짙은 회색(#3B3838)이라 본문 줄도 `emphasis` 블록으로 남음
  - `table_split_status`(OK/FAILED) 추가. `find_tables` 오류는 파일 실패가 아니라 표 분리 실패로 기록: 표·첫 열 칸 없음, 텍스트·절은 그대로, 구조가 있으면 `structure_status = PARTIAL`, 실행 기록 `error_reason`에 「표 분리 실패: 쪽·오류」. 표 분리가 실패한 결과는 다음 실행에서 건너뛰지 않고 다시 추출
  - `headings_source` 삭제. 책갈피가 없으면 `bookmark_check = null`. 대조할 때 숫자가 아닌 절 번호는 건너뜀
- 실행
  - `extraction_attempts.jsonl`을 파일 하나가 끝날 때마다 덧붙임(끝난 순서). 부모 프로세스가 도중에 멈춰도 끝난 파일 기록은 남음
  - 부모 프로세스는 파일별 `structure` 전체 대신 요약에 필요한 값만 받음(`extract.digest`)
  - 동시 작업 수 기본값 4 → 환경 변수 `EXTRACT_WORKERS`, 없으면 2(PR #28 Airflow 동시 작업 2). `--workers`로 덮어씀
  - 실행 요약에 블록 종류별 개수, 표 분리 실패 문서 수 추가. 표 안 글자 비율은 표 분리가 성공한 문서만
- 결과(10월 12일, 표본 40건, `--workers 2`): 텍스트화 40/40, 「제N부」 미검출 1건(20260903000270, 간이투자설명서만 담긴 PDF), 절 적중 1,195/1,230, 표 분리 실패 0건. 블록 수 emphasis 31,612·subheading 4,814·table 4,274·page_furniture 3,506·summary_label 2,064. `structure.json` 최대 0.55MB. 처리 시간 140초, 최대 메모리 약 107MB(arm64)
- 검증: pytest 95개 통과(제목 앞부분 일치, 번호 목록 줄 제외, 앞 문장에 붙은 부 표제, 블록 형식·정렬, 하위 제목 범위·표 안 줄 제외, 요약정보 칸, 강조 판별·색 변환(검정만 null), 표 분리 실패 → PARTIAL·재추출, 실행 기록 즉시 기록 순서, 동시 작업 수 환경 변수), `ruff format`·`ruff check` 통과
- 절 분할 보완(파서 버전 `prep-6`, PR #51 데이터 사이언스(다빈) 표본 검토 10월 12일)
  - 목차 제목과 본문 제목 중 짧은 쪽이 긴 쪽의 앞부분이면 같은 절로 봄(목차 「운용전문인력에 관한 사항」 / 본문 「5. 운용전문인력」). 절 번호가 같고, 겹치는 앞부분 4자 이상, 본문 줄 40자 이하일 때만(본문 번호 목록 줄 제외)
  - 앞 문장 끝에 붙은 부 표제(「…업무 등제 5부. 기타 …」)를 찾음. pdfplumber가 세로 간격이 좁은 두 줄을 한 줄로 합쳐 생김. 목차에 있는데 본문에서 못 찾은 부만, 앞뒤로 찾은 부 사이에서만, 표제 뒤 글이 목차의 부 제목과 맞을 때만(교차참조 「제5부의 내용 중 …」 제외)
  - 결과(10월 12일, 502건, `--workers 4`, 703초): 절 적중 15,567/16,080(96.8%, `prep-4` 대비 100개 늘고 잃은 절 0개), 부 적중 2,417/2,418, 5개 부를 모두 찾은 문서 498/500(20260918000258 해결)
  - 남은 것: 5부 중 4부만 찾은 2건(20260910000245, 20260916000160)은 본문에 표제 줄이 없음. 제목이 앞부분만 같은 경우가 아닌 미검출(중간 단어가 다름, 본문 오탈자, 제목이 아예 다름)은 그대로. 제4부 합본·분리(목차 1절, 본문 여러 절)는 본문 번호 목록을 절로 잘못 잡을 위험이 있어 보류
- 바꾸지 않은 것
  - `has_sentences` 판정(「다.」): 표본 40건 실측 뒤 데이터 사이언스(다빈)가 결정
  - 표 글자 범위 계산(bbox 안 첫 글자~끝 글자): 2단 배치 쪽에서 본문이 섞이는지 확인은 남음
  - `summary_label`은 명세대로 요약정보 안 모든 표의 첫 열 칸이라 위험등급 표의 「1」·「매우 높은 위험」 같은 칸도 들어감. 거를지는 데이터 사이언스(다빈) 확인 뒤
  - PR #43 문서 수정(실행별 추출 시도 기록 칼럼 목록, `structure_status` Note의 UNAVAILABLE manifest, PARTIAL 재추출 예외, `coordinate_system` 삭제)은 PR #43에서 함

## 2026-10-12 — PR #51 리뷰 반영: 실행별 추출 시도 기록 칼럼, 구조 manifest 형식, 표 분리 실패 재추출

- 기준: PR #51 리뷰 댓글(10월 11일)의 PR #43 수정 요청 4건과 PR #49 `docs/processing-requirements.md` 4-6
- 바꾼 것:
  - [원본 보관 규칙](docs/storage-and-failure-rules.md) 「추출 실패와 절 품질」: `extraction_attempts.jsonl` 칼럼 목록을 PR #51 구현과 같게 20개로 늘리고 칼럼별 뜻 추가. DB에 그대로 넣는 대상이 아니라 `file_extraction` 행의 원천이라고 명시. 「EXTRACT_OK면 재추출하지 않음」에 표 분리 실패(`table_split_status = FAILED`, 구조가 있으면 `structure_status = PARTIAL`) 예외 추가. 같은 문서 「버전·중복·재추출」 3번에도 같은 예외
  - [데이터 테이블·ERD 설계](docs/data-model.md): `structure_status` 규칙에서 UNAVAILABLE도 EXTRACT_OK이면 manifest 경로·해시 필수(부·절은 없어도 표·쪽 머리글 구간은 있음). PARTIAL에 표 분리만 실패한 경우 포함. manifest 저장 항목을 4-6 기준으로 고침(좌표·block_id 삭제). 구조 manifest 형식에서 `coordinate_system` 삭제, `raw_object_id` → `raw_sha256`, `structure_status`·`table_split_status` 추가. 처리 규칙 6에 재추출 예외
  - [3단계 입출력 Schema 설계 입력](docs/io-schema.md) 구조 manifest 행: 같은 형식으로
  - [schema.dbml](docs/schema.dbml)·[스키마 명세](docs/schema-catalog.md) `file_extraction`: `structure_status` Note, `parser_version` Note, 표 Note에 위 두 규칙. `structure_status_enum.PARTIAL` Note에 표 분리 실패 포함
- 바꾸지 않은 것: 표·관계·enum 수, 칼럼. `parser_version` 예시값(`pdftotext-24.02_prep-3`). `extract_status`의 EXTRACT_PARTIAL 뜻(일부만 복구된 문서)
- 검증: `@dbml/cli` dbml2sql 파싱 통과. `git diff --check` 통과


## 2026-10-12 — 데이터 처리 요구 명세: 8절 PR #43 답글 반영, `summary_labels` 칼럼 추가

- 기준: PR #43 PM(대현) 답글(10월 11일)
- [데이터 처리 요구 명세](docs/processing-requirements.md) 8절
  - 금감원 제재: API 정기 수집도 보류에 포함. 축 4 검증용 사례 표본 확보는 보류와 별개
  - 룩백 구간 신규 발견 수를 세는 범위 정의. 지연 일수 분포를 함께 기록
  - 다루지 않는 소스: PR #43 미결 문구와 맞춤. 금투협 판매관계는 `source` 값 이름도 함께 정함. finlife는 현재 수집 대상 아님
- 「상태」 표 기준 판: 8절을 PR #43 10월 11일 갱신분과 대조
- 2절·4-6·5절: `summary_labels` 칼럼 추가(`SIMPLE` 행, 10월 12일 다빈 요청). 표 분리 실패면 NULL, 사유 `SUMMARY_TABLE_LABELS_FAILED`
- 「상태」 표·10절: 다빈 승인(10월 12일) 기록
- 바꾸지 않은 것: 금감원 `inputDate` 재검증 미결(PR #43 문서. PM(대현)이 고치기로 함)
- 바꾸지 않은 것: 축 1·2 계산 범위, 후보 탈락·펀드 제외 구조, 본문 없는 PDF 판정(PR #49 답글로 제안, 동의 뒤 반영)

## 2026-10-11 — 소스별 구간 검증 미결 범위 정정, 금감원 제재 정기 수집 보류 반영

- 기준: 데이터 엔지니어링·인프라(주영) PR #43 리뷰(10월 11일, 룩백 재조회·소스별 구간 검증 반영분)와 10월 7일 10차 미팅 안건 3(제재공시 게시판 크롤러 보류).
- 바꾼 것:
  - [원본 보관 규칙](docs/storage-and-failure-rules.md) 「재시도와 워터마크」: PR #49 8절이 다루는 것은 5종(DART·공공데이터포털·KRX·금투협 공시·금감원 제재)뿐이라고 범위를 밝힘. 미결 행 문구를 5종으로 좁히고, 금투협 판매관계·분쟁조정, 국가법령 검증 방법 미결 2행 추가(담당 주영).
  - 같은 절 금감원 제재 행: 게시판 크롤러 보류(10차 미팅)와 API 정기 수집도 같은 검토(PM(대현), 10월 14일) 결과까지 보류함을 나눠 적음. 룩백 미정.
  - finlife 행: 「미정」을 「해당 없음(현재 수집 대상 아님)」으로. 소스 존치가 [소스 확인](docs/data-sources.md) 미결이라 「CDI 범위 제외」로 확정하지 않음.
  - KRX 행에 휴장일 확인 수단(거래소 영업일 정보), 룩백 항목에 covered_from 하한 근거(10월 5일 크롤러 실측)를 PR #49 8절과 같게 넣음.
  - [데이터 테이블·ERD 설계](docs/data-model.md) 미결 행과 [schema.dbml](docs/schema.dbml) `source_watermark` Note에서 「소스별 검증은 PR #49 8절」을 5종으로 좁힘.
- 바꾸지 않은 것: 표·관계·enum 수(표 17, 관계 42, enum 26), 칼럼 수. 리뷰 범위 밖 권고 4건(`inputDate` 재검증 미결 시점, 판매관계 `source` 값 이름, 신규 발견 수를 세는 범위, 축 4 표본 확보와 보류의 구분)은 PR 답글로 제안만 함. PR #49 8절의 금감원 제재 「상태」 칸(「10월 7일 미팅에 제안(결정 전)」)은 다른 브랜치라 그대로 둠. 「정찰 뒤 크롤러 결정」이 남은 다른 문서(pipeline-flow.md, data-sources.md, data-model.md, scoring-and-population.md)는 10월 14일 검토 결과가 나온 뒤 함께 고침.
- 검증: `@dbml/core` 파서 표 17·관계 42·enum 26 통과. `git diff --check` 통과.

## 2026-10-11 — 데이터 처리 요구 명세: PR #49 리뷰 반영과 `structure.json` 필드 정의

- 기준: PR #49 리뷰(PM(대현) 10월 7일·8일, 데이터 사이언스(다빈) 10월 10일), PR #51의 PM(대현) 요청(10월 10일), 10차 미팅(10월 7일)
- [데이터 처리 요구 명세](docs/processing-requirements.md)
  - 2절: 입력 파일 불변·재실행은 새 `score_run_id` 문장 추가. `documents.parquet`·`excluded.parquet` 위치를 `runs/{score_run_id}/`로 확정, `exports/` 사본 없음
  - 칼럼: `text_excl_tables`·`headings_source` 삭제. `source_section_no`를 문자열로 변경. 파서 버전 예시를 `pdfplumber-0.11_prep-4`로 변경
  - 4-2: 분할은 규칙, 책갈피는 검증에만 씀(10월 10일 PM 결정)
  - 4-3: ASL은 받는 쪽이 `text`에서 구간을 빼서 계산. 구간 합치기 규칙 추가. 칸 안에 문장이 있는 표는 ASL에 넣고 표를 모두 뺀 ASL은 비교용(10월 10일 다빈 결정). 텍스트·표 모두 pdfplumber
  - 4-6 신설: `structure.json` 필드(최상위, `blocks` 5종, 책갈피 대조, 표 분리 실패 시 다시 추출, 넣지 않는 것과 이유)
  - 5절: 표 분리 실패 표기를 `table_regions = NULL`로. 6절: 사유 코드 9개 확정
  - 8절: PR #43 반영 위치, PR #47 미병합, 금감원 게시판 크롤러 보류(10월 7일), 다루지 않는 소스 표시
  - 상태 표·10절: PM 승인, 다빈 의견 반영 기록
  - 미결: 결정된 4행 삭제(`documents.parquet` 위치, 사유 코드, 표 안 문장, PDF 라이브러리). `has_sentences` 판정 기준 1행 추가
- 바꾸지 않은 것
  - `structure.json` 필드 이름: PR #51 리뷰에서 확정
  - `has_sentences` 판정 기준: 「다.」 유지, PR #51 표본 실측 뒤 결정
  - `scoring-and-population.md`의 ASL 정의(「표 제외」): PM 담당 문서라 PR #49 답글로 알림
  - 8절 소스별 검증 방법

## 2026-10-10 — DART 투자설명서 텍스트 추출·절 분할과 실패율 산출 (#50)

- 범위: 크롤러가 받은 본문 PDF(`raw/dart/{접수번호}/body_pdf__v{n}.pdf`, 접수번호별 최신 판)를 텍스트로 바꾸고 부·절로 나눠, 파일·문서·절 단위 실패율을 실행마다 남긴다
- 코드(`src/signal_pipeline/parsing/`)
  - `dart_sections.py`: 순수 함수. `research/scripts/dart_sections.py` 알고리즘을 옮기고 결과를 줄 번호 대신 글자 위치(반열린 구간)로 냄. 「제N부」를 못 찾으면 `SectionSplitError`
  - `extract.py`: `pdftotext -layout -enc UTF-8`, 파서 버전 `pdftotext-{주.부}_prep-{n}`. PR #43 경로 `derived/{raw_sha256}/{parser_version}/text.txt`·`structure.json`(text.txt를 먼저 씀). `structure.json`의 `text_sha256`이 text.txt와 같으면 건너뜀. `runs/{run_id}/extraction_attempts.jsonl`은 실행 끝에 한 번 씀, `run.json`에 실패율 요약
  - #47 공통 모듈의 `_write_atomic`·`_append`를 공개 이름 `write_atomic`·`append`로 바꿈(크롤러 호출부 함께 수정)
- 실데이터에서 고친 분할 규칙(옮긴 알고리즘 기준)
  - 띄어 쓴 표제(「제 3 부」), 표제만 있는 줄, 목차 줄 끝 점선·쪽 번호를 인식(20건 중 5건 「제N부」 미검출 → 0건)
  - 절을 앞 절보다 뒤에서만 찾음. 뒤 절 제목이 앞쪽 본문에 먼저 맞아 구간이 거꾸로 잡힌 12건 해결(`prep-2`)
  - 목차 뒤에서는 앞에서 고른 부보다 번호가 큰 표제만 고름. 쪽 머리글 「제 1 부」·「제 2 부 [별첨1]」 반복으로 본문 부를 놓친 문서 해결(`prep-3`)
- 결과(10월 10일, 9월 1일~29일 공시 본문 PDF 502건, `pdftotext-24.09_prep-3`)
  - 텍스트화 502/502(100%), 파일 실패 0건
  - 「제N부」 미검출 2건(20260903000270, 20260911000012): 둘 다 간이투자설명서만 담긴 PDF라 부·절 구조 없음으로 기록
  - 부 적중 2,418/2,418, 5개 부를 모두 찾은 문서 500/500
  - 절 적중 15,475/16,080(96.2%). 문서별 최저 77.4%, 하위 10% 88.6%, 중앙값 97.1%
  - 500자 미만 절 32.1%, 깨진 문자 비율 0.3 이상 절 0건(두 기준 모두 미검증 잠정값). 처리 시간 약 2분(arm64)
  - 접수번호 2건(20260918000190, 20260918000389)은 PDF 바이트가 같아 파생 텍스트 하나를 함께 씀
- 형식 메모: `extraction_attempts.jsonl` 칼럼은 PR #43 목록에 `raw_storage_path`·`source_key`·`structure_status`·`text_*`·`structure_*`·`section_count`·`section_found_count`를 더함. DB 전이라 `raw_object_id`는 null
- 검증: pytest 59개 통과(분할 규칙·글자 위치 불변식·회귀 3건, 건너뛰기·실패 기록, pdftotext 시간 제한·파일 단위 오류 격리), `ruff format`·`ruff check` 통과
- PR #51 CodeRabbit 리뷰 반영(10월 10일): 목차 뒤 본문 「제N부」 표제가 1~2개면 목차 표제를 부로 쓰지 않고 구조 없음으로 기록(502건 중 해당 0건이라 결과 변화 없음), pdftotext 300초 시간 제한, 파일 1건의 예상 밖 오류는 `EXTRACT_FAILED`로 기록하고 실행 계속
- 수행하지 않은 것(1차): 표 영역·`blocks`(PR #49), 간이투자설명서 구간 분리, `canonical_section_code` 값, DB 적재, S3 업로드, OCR, 데이터 사이언스(다빈) 표본 검토 → 표 영역은 아래 2차에서 함

### 2차 변경 (PM 결정 10월 10일, 파서 버전 `pdfplumber-0.11_prep-4`)

- 결정 2건
  - PDF 추출 라이브러리를 pdfplumber(MIT)로 통일. PR #49 4-3의 「남는 제약」(표를 찾은 도구와 텍스트를 만든 도구가 같아야 함) 때문에 텍스트 추출도 pdftotext에서 pdfplumber로 바꿈
  - `source_section_no`는 문자열 유지(PR #43 ERD 기준). 코드 변경 없음
- 텍스트 추출(`pdf_layout.py` 신설, `extract.py`)
  - 쪽마다 보이지 않는 요소(흰색으로 채우고 외곽선 없는 사각형, 흰색 선; 패턴 등 숫자가 아닌 색은 보이는 것)를 뺀 쪽에서 layout 텍스트와 표(`find_tables` 기본 설정)를 같이 얻음. 쪽 사이는 `\f`, UTF-8·LF
  - 출력 글자마다 원래 PDF 글자(pdfplumber text map)를 알 수 있어 표 bbox를 글자 범위로 바꿈(글자 중심이 bbox 안인 첫 글자~끝 글자)
  - 줄 끝 공백과 쪽 앞뒤 빈 줄은 뗌. NUL(일부 PDF가 공백 대신 냄)과 `\r`은 공백으로 바꿈
  - pdfplumber 기본 layout은 글자 묶음(똑바른 글자·회전 글자) 순서대로 줄을 쌓아, 쪽 머리글을 나중에 그린 PDF에서 「제3부 …」 표제가 쪽 끝으로 밀림(41건). 글자를 위 → 아래로 다시 정렬해 만듦(`layout_textmap`)
- `structure.json`(스키마 2, PR #49 2절·4-2·4-3)
  - 절 원소: `section_title` → `title`(본문 줄 제목 그대로, 못 찾은 절은 목차 제목), `title_char_start`·`title_char_end`(제목 줄 범위) 추가, `char_start`는 제목 줄 시작 포함. `section_kind` = `body` / `summary` / `other`, 요약정보·other는 `part_seq`·`source_section_no`가 null, `section_seq`는 글자 위치 순 전역 순번
  - 요약정보 시작: 줄 시작의 「[요약정보]」·「<요약정보>」(없으면 「요약정보」만 있는 줄). 다음 줄이 「제N부」면 목차 항목이라 건너뜀. 끝: 목차가 뒤에 없으면 첫 본문 부 직전, 요약정보 뒤에 정식 투자설명서의 표지·목차가 오는 문서(109건)는 그 목차가 있는 쪽의 시작까지. 그 사이와 맨 앞은 `other`. 「제N부」를 못 찾은 문서는 요약정보 끝을 정할 수 없어 구간을 만들지 않음
  - `page_furniture_regions`: 쪽마다 첫·끝 줄 중 숫자를 #로 바꿨을 때 쪽의 30% 이상(최소 3쪽)에서 반복되는 줄, 쪽 번호만 있는 끝 줄. 텍스트에서 지우지 않음
  - `table_regions`: `{char_start, char_end, has_sentences}`. `has_sentences`는 표 안에 「다.」로 끝나는 문장이 있음
  - `headings_source`: PDF 책갈피가 있으면 `BOOKMARK`, 없으면 `RULE`. 분할은 두 경우 모두 지금 규칙(RULE) 그대로. 책갈피가 있는 문서는 규칙으로 찾은 부·절을 책갈피와 대조한 개수를 `bookmark_check`에 남기고 요약에 재현율·정밀도를 냄
  - `structure_status`(AVAILABLE / UNAVAILABLE)를 `structure.json`에도 기록. 「제N부」를 못 찾은 문서(UNAVAILABLE)도 `structure.json`을 씀(표·머리글 구간은 있고 `parts`·`sections`는 빈 목록)
- 실행(`extract.py`, `parallel.py` 신설)
  - 건너뛰기: `structure.json`의 `text_sha256`이 `text.txt`와 같은 EXTRACT_OK 문서 전부(UNAVAILABLE 포함)
  - 파일 단위 병렬(기본 4개, `--workers`). 파일마다 별도 프로세스(spawn)를 띄우고 300초가 지나면 프로세스를 종료해 `EXTRACT_FAILED`(`timeout`)로 기록. 기록 순서는 입력 순서. 프로세스가 결과 없이 끝난 경우도 같은 방식으로 기록(`died`)
  - 결과는 파이프 대신 임시 파일(pickle, `.tmp`에 쓴 뒤 교체)로 받고, 부모는 `multiprocessing.connection.wait`로 프로세스 종료 신호를 기다림. 파이프 수신 대기로 300초 제한이 무시되던 문제(PR #51 CodeRabbit 지적)와, 결과가 크면 자식이 파이프에 막히던 문제를 함께 해결(10월 10일)
- 분할 규칙 보완(layout 텍스트에서 나타난 형태, 각각 시험 추가)
  - 표제 줄 길이는 연속 공백을 하나로 보고 잼(글자 간격 공백으로 60자를 넘어 놓친 문서)
  - 목차 옆 세로 글자(「CONTENTS」)가 줄 앞에 붙은 형태를 인식(7건)
- 결과(10월 10일, 같은 502건, `pdfplumber-0.11_prep-4`; 괄호는 `pdftotext-24.09_prep-3`)
  - 텍스트화 502/502(502/502), 파일 실패 0건. 「제N부」 미검출 2건(2건, 같은 문서 둘)
  - 부 적중 2,416/2,418(2,418/2,418), 5개 부를 모두 찾은 문서 497/500(500/500). 절 적중 15,467/16,080(15,475/16,080, 96.2%). 문서별 최저 64.5%(77.4%), 하위 10% 88.6%(88.6%), 중앙값 97.1%(97.1%)
  - 요약정보 구간이 있는 문서 469건(줄 시작 표시가 있는 문서 중 목차 항목뿐인 24건은 요약정보 없음으로 봄). 머리글 구간이 있는 문서 499건
  - 표 51,328개, 표가 하나도 없는 문서 0건, 문장이 든 표 15,754개. 표 안 글자 비율 중앙값 55.0%(PR #49 10월 7일 확인은 생성 도구별 40~53%; 이번 값은 표 구간에 칸 사이 공백이 포함돼 5~10%p 높음)
  - 책갈피 문서 149건: 부 재현율 100%·정밀도 96.0%, 절 재현율 95.9%·정밀도 90.3%
  - 처리 시간 655초(4개 병렬, arm64). 같은 명령 두 번째 실행은 502건 모두 `SKIPPED_EXISTING_OK`(20초)
  - 5개 부 중 4개만 찾은 문서 3건(prep-3은 5개): 본문 부 표제가 한 줄로 잡히지 않음. 확인한 1건은 표제가 앞 문장 끝에 붙음(pdfplumber가 세로 간격이 가까운 줄을 한 줄로 합침). 규칙을 맞추지 않고 그대로 둠
  - 깨진 PDF 확인(임시 폴더): 0바이트·시그니처 없음은 `EXTRACT_UNSUPPORTED_FORMAT`, 잘린 PDF·본문 없는 PDF는 `EXTRACT_FAILED`(pdfplumber 오류 사유), 시간 제한 3초로 줄이면 117쪽 PDF가 `timeout`으로 끝남
- 검증: pytest 83개 통과(기존 59개 유지·수정 + 요약정보·other, 제목 줄 범위, 머리글, 표 bbox → 글자 범위, 색 판정, 쪽 안 줄 정렬, UNAVAILABLE 건너뛰기, 시간 초과·프로세스 종료·큰 결과(500만 자)와 결과 없는 종료, 책갈피 대조), `ruff format`·`ruff check` 통과
- 바꾸지 않은 것: 분할 알고리즘(RULE), 책갈피 우선 분할(대조 결과를 PM이 본 뒤 정함), `source_section_no` 문자열, `canonical_section_code`(null), `blocks`(null), 하위 제목(「가.」「(1)」) 구간
- 수행하지 않은 것(2차): 문장이 든 표를 ASL에서 뺄지 정하는 일(데이터 사이언스(다빈)), DB 적재, S3 업로드, OCR, 간이투자설명서만 담긴 PDF 2건의 구조화

## 2026-10-09 — 실행별 추출 시도 기록 위치 확정, 워터마크 갱신 순서 정정, LLM 입력 해시 추가

- 기준: 데이터 엔지니어링·인프라(주영) PR #43 리뷰 1번(10월 6일)과 PM(대현) 10월 9일 결정. 10월 14일 가동 점검의 「파싱 실패율 수치 산출」(이슈 #50)이 실행별 실패 기록을 근거로 씀.
- 바꾼 것:
  - [원본 보관과 수집·파싱 실패 처리 규칙](docs/storage-and-failure-rules.md): EXTRACT 실행이 `runs/{run_id}/extraction_attempts.jsonl`에 추출 시도 1건당 1줄을 씀. 칼럼, 건너뛴 파일(`SKIPPED_EXISTING_OK`)도 기록, 실패율은 이 파일에서 센다는 규칙을 「추출 실패와 절 품질」에 추가. 「파일 경로」 목록, 「버전·중복·재추출」 3번, 「실행 폴더 불변」 목록에 같은 파일을 넣음.
  - [데이터 테이블·ERD 설계](docs/data-model.md): 미결 「실행별 추출 시도·상태 이력」 행을 지움. `file_extraction` 상태 칼럼 설명을 「파일 × 파서 버전의 현재 상태」로 고치고 시도 이력 위치를 적음.
  - [schema.dbml](docs/schema.dbml): `file_extraction` Note에 시도 이력 위치 한 문장 추가.
- 데이터 엔지니어링·인프라(주영) 리뷰 2번 후반 반영(10월 7일 반영에서 누락): [schema.dbml](docs/schema.dbml) `source_watermark` Note의 갱신 순서를 「적재 순서」에 맞춤. 이전 Note는 「원본 저장 → 수집 시도 기록」 순서였고 워터마크 전진이 별도 트랜잭션이라는 점이 없었음. 규칙(시도 기록 먼저, 결과는 나중에 갱신)을 유지함(PM(대현) 10월 9일 결정). 이유: 요청·저장 도중 프로세스가 끝나도(EC2 예산 자동 중지, 메모리 부족 등) 「시작했으나 결과 없음」 행이 남아 재시도 대상과 실패율 분모로 잡힘.
- 데이터 엔지니어링·인프라(주영) 리뷰 4번 반영: 주영이 데이터 처리 요구 명세([PR #49](https://github.com/BOAZ-Signal-Team-26/signal-pipeline/pull/49) 8절)에 적은 룩백 재조회 방식과 소스별 구간 완전성 검증을 [원본 보관 규칙](docs/storage-and-failure-rules.md) 「재시도와 워터마크」에 옮김(룩백 규칙 1항목, 소스 표에 「구간 완전성 검증」 열). 미결은 룩백 일수 확정, KRX 휴장일 0행 확인 방법, DART 건수 대조 구현으로 좁힘. data-model.md 미결 행과 schema.dbml `source_watermark` Note의 「미결」 표현도 맞춤.
- 데이터 엔지니어링·인프라(주영) 리뷰 3번 반영(PM(대현) 10월 9일 결정): `llm_field_extraction.input_sha256`(NOT NULL) 추가, 재호출 생략 조회 인덱스 (document_id, field_name, input_sha256, prompt_sha256) 추가. 입력 정본은 `request.json`의 문서 텍스트와 `inputs` 목록. (raw_object_id, parser_version) 필수 안은 채택하지 않음(문서 단위 추출이라 파일 여러 개를 한 행에 담을 수 없고, 보낸 텍스트가 절 일부·전처리 결과일 수 있음). 해시 규칙(UTF-8/LF, 절 구분 빈 줄), 재호출 생략 조건, 적재 검증을 [원본 보관 규칙](docs/storage-and-failure-rules.md) 「LLM 호출 저장」에 확정하고 미결 「재호출 생략 규칙」 행을 두 문서에서 지움. [스키마 명세](docs/schema-catalog.md), [데이터 테이블·ERD 설계](docs/data-model.md) 표 설명과 적재 검증 15, [3단계 입출력 Schema 설계 입력](docs/io-schema.md) 맞춤.
- 결정 상태 정정: [데이터 테이블·ERD 설계](docs/data-model.md) 「v2.2」 결정 상태 표에 C(펀드 관측치 표 없음)의 10월 8일 PM(대현) 확정을 반영(데이터 사이언스(다빈) 이의 확인 대기). 상단 상태 표의 「10월 4일 판단 항목 3건」을 실제 나열 수와 같은 4건으로 고침.
- 위험등급 1·3 확정 반영: 10월 7일 10차 미팅에서 결정 완료된 펀드 대표 위험등급 칼럼(`fund_group.representative_risk_grade`와 근거 칼럼 2개, `risk_grade_source_enum`)과 문서 작성기준일(`document.report_base_date`)을 [데이터 테이블·ERD 설계](docs/data-model.md) 결정 상태 표·표 목록·미결, [schema.dbml](docs/schema.dbml) note, [스키마 명세](docs/schema-catalog.md)에서 「결정 대기」에서 「확정」으로 옮김. 10월 4일 판단 항목 중 결정 대기는 클래스 등급 불일치 기록(위험등급 2)과 간이 대표 역할 2건. PR #41과 표현을 맞춤.
- 대시보드 연결과 맞춤(signal-infra PR #28 검토): `documents.parquet`를 `runs/`로 옮기면서 `exports/`만 읽는 대시보드가 문서 정보를 읽을 수 없게 됨. 채점 실행 마지막 단계에서 `exports/runs/{score_run_id}/dashboard_documents.parquet`(대시보드 전용 내보내기)를 쓰도록 「파일 경로」·`exports/` 설명에 추가하고, 담을 칼럼은 미결로 둠. `extraction_attempts.jsonl`은 실행이 끝날 때 한 번 올리도록 명시(`runs/` 조건부 쓰기와 충돌 방지).
- 구현과의 차이(기록만): PR #47 크롤러는 원본 파일을 저장한 뒤 `attempts.jsonl`에 결과까지 한 줄로 씀(시작 행 없음). 실패 요청은 기록되고 워터마크 전진 조건은 규칙과 같아 데이터 누락은 없음. 도중 종료된 시도만 기록되지 않음. DB 적재 구현(쉬는 기간, 10월 15일~28일) 때 「적재 순서」대로 시작 행 INSERT 뒤 결과 UPDATE로 맞춤.
- 바꾸지 않은 것: 표·관계·enum 수(표 17, 관계 42, enum 26). 칼럼은 235 → 236(`input_sha256`). `file_extraction`의 FAILED·PARTIAL 덮어쓰기 규칙. 「적재 순서」 본문. 리뷰 3번(LLM 추출 입력 특정, `input_sha256`)은 LLM 추출 시작일이 쉬는 기간(10월 15일~28일) 뒤로 바뀌어 그때까지 미결로 둠.
- 검증: `@dbml/core` 파서 표 17·관계 42·enum 26 통과. 스키마 명세 칼럼 236개가 DBML과 같음. `git diff --check` 통과.


## 2026-10-09 — 펀드 대표 위험등급 칼럼 표기를 ERD v2.2에 맞춤

- [스키마 명세](docs/schema-catalog.md) `product.risk_grade` 설명과 [데이터 테이블·ERD 설계](docs/data-model.md) 「v2.2」 판단 항목의 「대표 등급 칼럼은 현재 스키마에 없음, 결정 대기」를 ERD v2.2(PR #43)의 `fund_group.representative_risk_grade`와 근거 칼럼 2개로 고침. 10월 7일 10차 미팅에서 확정됨.
- 같은 문서 「미결」 표에서 펀드 대표 위험등급 칼럼과 작성기준일 칼럼을 빼고 확정 사실을 적음(CodeRabbit 지적, 10월 7일 10차 미팅에서 위험등급 1·3 결정 완료).
- 바꾸지 않은 것: 클래스 등급 불일치 기록 위치(v2.2 결정 대기), 대표 등급 출처·기준 시점 규칙, DBML(칼럼 추가는 PR #43).

## 2026-10-08 — 분석·리서치 10월 7일 조사 반영, PM 결정 기록, 칼럼 값 유형 표시

- 기준: 분석·리서치(민석) 10월 7일 조사(Notion 「금소법 19조 점검표」, 「설명서와 DART 투자설명서 대응관계」, 「고지 충실도의 기준과 검증 자료」, 「위험등급 산정 규칙」, 티켓 「설명의무 누락 검출 점검표 v0 확정」의 결과물)와 PM(대현) 10월 8일 지시.
- 10월 7일 조사 반영 4건(현재 설계와 어긋나지 않고 팀 결정이 따로 필요 없는 내용):
  - 고지 충실도 판정 기준: 9월 29일 결론(법 조문 = 기준, 제재문 = 검증 자료)이 맞다는 근거를 [점수 저장과 비교 모집단](docs/scoring-and-population.md) 「검증」에 보강. 판정 기준은 금소법 19조·시행령·감독규정, 해석 보조는 금융위 설명의무 가이드라인, 제재문·분쟁조정 결정문은 검증 자료로만 씀. 제재문 역할의 「확인대기」 표시를 지움.
  - 측정 범위의 한계: 금소법 설명서와 투자설명서는 같은 문서가 아니며 공모펀드는 설명서의 상품정보 부분을 투자설명서로 대신 판정함. 대신 판정할 수 있는 범위와 없는 범위를 같은 문서 「고지 항목 판정」에 신설한 절에 적고, [설계 문서 안내](docs/README.md) 「한 줄 정의」에서 링크. 프로젝트 정의는 바꾸지 않음.
  - 금소법 19조 대응표 10개 묶음의 처리 결과(판정 대상·이관·범위 밖·해당없음·적용 대상 필터)와 청약철회(대리판정 불가), 19조 ③항(점검표 전체의 법적 근거)을 같은 문서에 신설한 절에 적음.
  - 위험등급: [데이터 테이블·ERD 설계](docs/data-model.md) 위험등급 설명에 현재 방침(운용사 공시 등급 사용, 다시 매기지 않음, 판매사 등급 미사용, 산정 주체 칼럼 없음)이 10월 7일 조사와 같다는 근거 한 줄 추가.
- PM 결정 기록 3건(10월 7일 제안 검토 후 기존 설계 유지, 10월 8일 PM(대현) 결정):
  - 고지 항목 판정값 4종(MET / UNMET / NOT_APPLICABLE / UNDETERMINED) 유지, 「불확실」 값 추가 안 함. 임계값 근처 판정은 판정 불가로 두고 사람이 검토. 위치: 점수 저장과 비교 모집단 「결정 요약」.
  - CDI 축 1~3 원값은 문서 단위 직접 계산(10월 2일 변수표) 유지. 절 단위 원지표 저장 뒤 집계 방식 채택 안 함. 위치: 같은 표.
  - 근거 위치 형식 절 + 문자 범위(10월 3일 확정) 유지, 문장 테이블 신설 안 함. 위치: 데이터 테이블·ERD 설계 「결정 요약」.
  - 임베딩 유사도 판정 방식은 별도 티켓 「고지 점검 임베딩 유사도 판정 방식 검증 계획 수립」(기한 10월 14일)에서 다룬다는 한 줄을 점수 저장과 비교 모집단 「결정 요약」 아래에 둠.
- 위험등급 산정 요소값 자리: llm_field_extraction은 필드마다 한 행(field_name 값)이라 DBML을 바꾸지 않고 예약 필드 이름 2개(`risk_grade_basis` 산정 기준, `risk_grade_measure` 측정값)를 문서에만 정의. 예약, 추출 미실시. 10월 21일 100건 비용 실측 뒤 추출 여부 결정(PM(대현) 10월 8일). 위치: 데이터 테이블·ERD 설계 「product / fund_group」 risk_grade, [3단계 입출력 Schema 설계 입력](docs/io-schema.md) 「LLM 추출 결과 JSON 요구」. 9월 14일 「요소별 값 저장 채택 안 함」 판정([초기 소스 확인](docs/records/phase1-erd/initial-source-checks.md) 「네 충돌의 판정」 2번) 옆에 10월 8일 변경(자리만 둠)을 적음.
- 칼럼 값 유형 표시: [스키마 명세](docs/schema-catalog.md)의 표 17개, 칼럼 235개에 「값 유형」 열 추가(원본값 / 판정값 / 계산값 / 외부값 / 관리값). 문서 상단 「값 유형 범례」에 다섯 값의 정의. DB 칼럼은 추가하지 않음.
- 검증: schema.dbml 변경 없음(파서 재실행 불필요). 스키마 명세의 표·칼럼 이름이 DBML과 같음(표 17, 칼럼 235). `git diff --check` 통과.
- 바꾸지 않은 것과 이유:
  - 결정 대기 F(정규 절 분류 값 규칙 안 「제1·2·3·5부는 부·절 번호, 제4부는 소분류명」): 반영하지 않음. PM 결정 전이라 data-model.md·schema.dbml·스키마 명세·DART 절 분할·설계 문서 안내의 해당 문구를 이전 상태(「값 규칙은 결정 대기 F」)로 유지.
  - 분쟁조정 필터 날짜를 게시일에서 가입일로 바꾸는 안: 현재 설계(게시일)를 바꾸는 제안이고 담을 칼럼이 없음. PM 결정 필요.
  - 점검표 세부 판정 항목(판정 대상 항목 수, 등급 산정 근거 항목의 판정 목록, 제2부 10절 라목 위치, 11절 판정 범위): 원천끼리 맞지 않거나 저장소에 근거가 없어 티켓에서 확인 중.
  - 표·관계·enum 수, 칼럼 구성, DBML.
- 수행하지 않은 것: 푸시, Notion 동기화, 위험등급 요소값 추출.

## 2026-10-07 — ERD v2.2 PR 리뷰 반영: 채점 입력 위치와 워터마크 시작일

- 데이터 처리 요구 명세(PR #49) 결정 반영: `documents.parquet`·`excluded.parquet`를 `exports/runs/`에서 실행 폴더 `runs/{score_run_id}/`로 옮김. `exports/`에는 채점 결과만 둠. 채점 입력 파일은 실행 시작 때 한 번 쓰고 바꾸지 않으며, 실패한 채점 실행은 새 score_run_id로 다시 돌림([원본 보관 규칙](docs/storage-and-failure-rules.md) 「실행 폴더 불변」「적재 순서」).
- run_id 설명에서 같은 실행 안의 요청 재시도(유지)와 채점 재실행(새 run_id)을 구분.
- 데이터 엔지니어링·인프라(주영) 리뷰 2번 반영: `covered_from`을 누적 구간의 시작일(첫 실행 시작일, 바꾸지 않음, 룩백 하한)로 확정.
- CodeRabbit 지적 반영: v1 → v2 이관을 (section, 지표) 단위로 바꾸고 score_type → metric_key·assessor_key 대응표를 먼저 만들도록 명시([데이터 테이블·ERD 설계](docs/data-model.md) 「v1 → v2 이관 절차」).
- 바꾸지 않은 것: 표 17·관계 42·enum 26, 칼럼 구성. 리뷰 1번(실행별 추출 시도 기록)·3번(LLM 추출 입력 특정)은 이번에 정하지 않음(10월 14일·15일 전 결정).

## 2026-10-07 — DART 투자설명서 크롤러 1차 (#45)

- 범위: OPEN DART 목록(`list.json`, `pblntf_ty=G`)에서 report_nm으로 투자설명서(정정본 포함)를 골라 표지 XML(`document.xml`)·뷰어 트리(`main.do`)·뷰어 표지(`viewer.do`)·본문 PDF(`download.do`)를 받는다. 증권신고서·일괄신고서는 건수만 세고 받지 않는다(목록 응답 원본에는 남음)
- 공통 모듈(`src/signal_pipeline/common/`)
  - `http.py`: httpx 클라이언트. 간격 1초·동시 1개, 타임아웃·5xx는 최초 1회 + 재시도 최대 5회(1·2·4·8·16초), 401·403·429는 재시도 없음, 결과를 `attempt_outcome_enum` 6종으로 분류, 기록에서 인증 인자 제외
  - `storage.py`: 10월 4일 확정 경로(PR #43) `raw/{source}/{원천 키}/{file_role}__v{n}.{ext}` + `.meta.json`. 원천 키 인코딩(`/`·`~`·`%`·제어 문자만, 200바이트 초과 시 `-h` + SHA-256 앞 12자), 같은 바이트면 새 판을 만들지 않음, `.meta.json`을 먼저 쓰고 원본을 나중에 씀
  - `runlog.py`: `runs/{run_id}/run.json`(`pipeline_run` 칼럼), `attempts.jsonl`(`collection_attempt`, 시도 1번 = 1줄), `raw_objects.jsonl`(종료 시 `input_manifest`). DB 가동 전이라 `document_id`는 접수번호, `raw_object_id`는 `storage_path`로 대신함
  - `state.py`: 접수일 하루 단위 워터마크. 그날을 빠짐없이 받았을 때만 전진, 다음 실행은 워터마크 − 룩백 3일(잠정)부터. 룩백은 첫 실행 시작일보다 앞으로 가지 않음
- 결정: 저장 위치는 환경변수 `RAW_ROOT`(`.env.example`에 항목 추가), run_id는 `extract-{UTC 시각}-{임의 4자}`, User-Agent는 프로젝트명 + 저장소 주소, `document.xml` 014(파일 없음)는 `PERMANENT_FAILED`로 기록하고 그날 완료를 막지 않음
- 제안(확인 필요): DART 목록 응답 경로 `raw/dart/_list/{접수일}/page-NNNN__v{n}.json`. PR #43에 DART 목록 예시가 없어 스냅숏형 소스(`data_go_fund`) 모양을 따름
- 10월 4일 실호출 확인: 증권신고서·일괄신고서는 본문 PDF가 없고 본문이 절마다 HTML 노드로 나뉨, `document.xml`은 014. 시험 실행에서 신고서 요청이 전체의 약 절반이라 수집 대상에서 제외(10월 5일)
- 수집 결과(10월 5일, `--from 2026-09-01 --max-pdf 500`): 본문 PDF 500건(810MB, 평균 1.62MB, 모두 `%PDF-` 확인), 접수일 9월 1일~29일 완료·워터마크 9월 29일, 요청 2,552번, 61분. 결과 분류 SUCCESS 2,384·PERMANENT_FAILED 146·EMPTY 10. 투자설명서 503건 중 `document.xml` 014가 146건(29%). 표지·본문 노드 없음 3건. 다운로드 타임아웃 12번은 재시도로 모두 성공
- 경로 변경(10월 5일): 수집분 1,884개를 옛 경로(수집일·해시 폴더)에서 새 경로로 옮김(바이트 그대로, SHA-256 대조 일치). 실행 기록의 `storage_path`를 고치고 대응표 `runs/_path_migration_20261005.tsv`를 남김
- 검증: pytest 40개 통과(재시도·분류·인증값 제외, 경로·원천 키 인코딩·판 번호, 실행 기록·워터마크·룩백, report_nm 분류·트리 파싱·노드 찾기·PDF 링크), `ruff format`·`ruff check` 통과. 경로 변경 뒤 같은 명령을 다시 실행해 신규 0건·건너뜀 50건·요청 4번 확인(9월 26일~29일)
- PR #47 리뷰 반영(10월 7일): 목록 조회 실패를 실행 요약 `list_failures`에 기록하고 하나라도 있으면 실행을 `FAILED`·종료 코드 1로 끝냄. 인증 키(`crtfc_key` 등)를 담은 요청만 리다이렉트를 따르지 않음(3xx는 `PERMANENT_FAILED`). 테스트 2개 추가해 pytest 42개 통과, 실제 목록 API 1회 호출로 정상 응답 확인. 문서 단위 재시도 실패로 미완료가 된 날은 아직 실행 상태에 반영하지 않음
- 수행하지 않은 것: 문서 반영(`data-sources.md`에 신고서 구조·OPEN DART status 코드표, ERD `file_role_enum`에 `viewer_tree` 추가)은 PM 검토 뒤로 미룸. S3 저장(`RAW_ROOT`가 로컬 폴더), DB 기록(`collection_attempt`·`source_watermark`), 공공데이터포털·KRX 수집(2차), 절 단위 분할, CI에 pytest 추가

## 2026-10-06 — KRX 대응표 정본만 유지

- KRX ETF 1,167건 대응표의 중간 산출물 9개(초기 감사표·요약, 중복·기타 후보표, 229건 재대조 CSV, 40건 표본 목록, 생성 스크립트 3개)를 저장소에서 제거. 정본 `research/samples/krx_link_review_v2.csv`와 근거표 `krx_issuer_review.csv`, 재대조 스크립트 `rematch_krx_unmatched.py`만 유지. 229건 재대조의 행별 메모는 정본의 `review_note` 열에 합침. 제거 파일은 git 이력에 보존.

## 2026-10-04 — 리뷰 지적 반영과 S3 세부 규칙 확정

- 위험등급 규칙 PR의 CodeRabbit 지적 2건 반영: 법적 근거와 10월 4일 PM 결정 분리, 클래스 등급과 펀드 대표 등급 구분 명시.
- ERD v2.2 PR의 지적 11건 중 10건 반영, 1건은 미결로 이관: 대표 등급 근거 문서가 같은 펀드의 대표 문서인지 적재 검증에 추가, 이관 3단계에서 제거된 키 사용 중단, B11 근거 형식 정리, 텍스트·절 재사용 경로에서도 LLM 추출 단계 연결, 타입 표기 4곳, 본문 추출 실패의 파트 B 전파, 스냅숏 페이지 파일 버전 경로, 원천 키 폴더 = 문서 키, 스크립트 인코딩·접미사 처리. 실행별 추출 시도 이력 보존 방법은 [데이터 테이블·ERD 설계](docs/data-model.md) 「미결」에 추가(주영, 10월 7일).
- S3 세부 4건 중 3건 확정: 스냅숏 수명 주기는 생성 30일 뒤 날짜 기준, 퍼센트 인코딩은 `/`·`~`·`%`·제어 문자만(한글 그대로)·200바이트 초과는 `-h` + SHA-256 앞 12자, 같은 기준일 재수집은 `r2/` 폴더. `.meta.json` 유무는 미결 유지.

## 2026-10-04 — KRX 데이터 보관 정책 3건 초안 (PM, 마감 10월 7일)

- 소스 이름 `krx_etf_daily`, 일별 파일 프로젝트 종료까지 보관(삭제 없음, 10년 소급 조회 가능)을 [원본 보관 규칙](docs/storage-and-failure-rules.md) 「KRX 데이터 보관」에 정리.
- KRX 매칭 실패 229건을 공공데이터포털 전체 목록과 재대조. 규칙 4개(괄호 표기 제거, 브랜드 개명 4건, 환헤지 표기, `TR`→`Total Return`)로 149건 자동 연결, 70건은 PM(대현) 확인 후 연결, 10건은 보류. 보류였던 38건을 같은 발행사의 포털 상품과 다시 대조해 28건을 확정함(포털이 이름을 다르게 쓴 경우: 단어 순서, 생략, 영어 표기). 확정 근거는 같은 발행사 내 후보 1개, 설정일과 KRX 종목 코드 순서의 일치, 일부는 웹 확인이며 행마다 `krx_unmatched_rematch.csv`의 `메모`에 구분해 적음. 처음에는 이름이 그대로 들어 있는지만 보고 「포털에 없다」고 판단했으나 틀렸음([매칭 규칙](docs/matching-rules.md) 「KRX 매칭 실패 처리」). 처음에는 `TR`을 떼고 대조해 9건을 `TR`이 아닌 ETF에 잘못 연결했고, 같은 날 발견해 고침. 환헤지 표기 점검을 후보가 1개일 때도 적용하지 않아 `PLUS 미국S&P500(H)`(환헤지)를 환노출형 펀드에 잘못 연결한 것도 같은 날 외부 검토에서 발견해 보류로 바꿈. 결과 `research/samples/krx_unmatched_rematch.csv`(사람이 확정한 판단도 이 파일 하나에 남기고, 입력용 CSV 2개는 이 파일에 합쳐 없앰), 스크립트 `research/scripts/rematch_krx_unmatched.py`. 상품 코드(ISIN)로 검증할 수 있는지 확인했으나 포털 필드에 KRX 코드가 없어 불가, 브랜드와 운용사 코드 교차 확인(187/191 일치(이후 재검토로 연결이 늘어 건수는 바뀜), 어긋난 4건은 미래에셋 옛 코드 225)으로 대신함.
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
