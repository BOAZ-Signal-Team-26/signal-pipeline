# 원본 보관과 수집·파싱 실패 처리 규칙

## 상태

| 항목 | 내용 |
|---|---|
| 상태 | 09-22 재검토안 (09-23 경로 계약·v2.1 보완 포함, 10월 4일 ERD v2.2 반영: 추출 키·derived 경로·워터마크 표, 10월 4일 S3 트리 확정: 원천 키 폴더·소스 7개·적재 순서) |
| 기준일 | 2026-10-04 |
| 담당 | 대현 |
| 승인 | 팀 승인 전 |
| 범위 | 1단계 산출물 2(원본 보관 규칙), 3-1(수집 안 됨·본문 뽑기 실패). 상품 못 찾음은 [상품·법인 매칭 규칙](matching-rules.md) |
| 범위 밖 | 저장 제품, CAS 채택, 원자적 게시, 백업 스케줄, 재처리 큐 구현 → 2단계 데이터 파이프라인 Flow 설계 |

- 경로는 문서·API·실패 응답 모두에 적용하는 논리 경로 제안
- 기존 저장 파일을 이동하거나 덮어쓰지 않음
- 과거의 「0건 = 실패」「500자 미만 = 실패」 규칙은 그대로 구현하지 않음

## 결정 요약

| 결정 | 근거 |
|---|---|
| 원본 바이트는 불변. 덮어쓰지 않고 버전을 쌓음 | 정정본·첨부 교체 때 과거 시점 재현 필요 |
| raw 경로는 `raw/{source}/{읽을 수 있는 원천 키}/{file_role}__v{n}.{ext}`. 수집일·해시 폴더는 쓰지 않음 | 같은 문서의 v2가 같은 폴더에 쌓여야 비교할 수 있고, 폴더 이름만으로 문서를 알아볼 수 있어야 함 |
| `storage_path`는 `RAW_ROOT` 기준 상대경로만 저장 | 절대경로는 환경마다 루트가 달라 DB 덤프 이동 시 전부 무효 |
| 요청(`collection_attempt`)과 원본(`raw_object`)을 다른 단위로 기록 | 타임아웃처럼 바이트가 없는 요청도 기록해야 함 |
| 같은 source·키에서 바이트 SHA-256이 같으면 새 파일 버전을 만들지 않음. 재추출은 실행(run)별로 판단 | 중복 다운로드 생략과 재추출 생략은 다른 규칙 |
| 금투협 수시공시(`uRptGb='O'`)의 같은 공고 안 클래스 행은 다운로드 전에 `server_path + fileNm`으로 접음 | 한 묶음 15행이 같은 파일 집합. [금투협 중복 행·ETF 이름 규칙 검증](records/phase1-erd/kofia-rows-and-etf-rule.md) 「첨부 해시 비교」 |
| 유효한 조회의 정상 0건은 `EMPTY`이며 실패가 아님 | 금감원 `900` 등 정상 빈 결과 존재 |
| 500자·깨진 문자 30%는 실패 기준이 아니라 품질 신호 | 짧은 절은 실제로 존재. 두 값 모두 미검증 잠정값 |

## 원본 보관

### 파일 경로

```text
raw/{source}/{원천 키}/{file_role}__v{n}.{ext}
raw/{source}/{원천 키}/{file_role}__v{n}.{ext}.meta.json
raw/{source}/{기준일 YYYY-MM-DD}/...                 # 스냅숏형 API만(data_go_fund, krx_etf_daily)
```

소스별 실제 모양(키 형식 예시이며 실제 값이 아님):

```text
raw/dart/{접수번호 14자리}/body_pdf__v1.pdf
raw/dart/{접수번호 14자리}/cover_html__v1.html
raw/kofia_disclosure/{companyCd}~{standardDt}~{announceTtl 인코딩}~{tmpV1}/prospectus__v1.pdf
raw/kofia_disclosure/{companyCd}~{standardDt}~{announceTtl 인코딩}~{tmpV1}/attachment-01__v1.pdf
raw/fss_sanction/{examMgmtNo}~{emOpenSeq}~{transCode}~{actGbn}/api_response__v1.json
raw/fss_improvement/{examMgmtNo}~{emOpenSeq}~{transCode}~{actGbn}/api_response__v1.json
raw/fss_dispute/{게시판 ID}~{게시글 번호}/attachment-01__v1.hwp
raw/data_go_fund/{기준일}/page-0001__v1.json
raw/data_go_fund/{기준일}/page-0184__v1.json
raw/data_go_fund/{기준일}/_complete__v1.json
raw/data_go_fund/{기준일}/r2/page-0001__v1.json      # 같은 기준일을 다시 받은 경우(아래 「API 스냅숏 저장 단위」)
raw/krx_etf_daily/{기준일}/api_response__v1.json   # 같은 기준일 바이트가 바뀌면 v2
```

- 금투협 4필드 순서: `companyCd`, `standardDt`, `announceTtl`, `tmpV1`([데이터 테이블·ERD 설계](data-model.md) 「문서와 소스별 키」). 수시공시만 이 4필드로 묶음
- 금감원 제재·경영유의 복합키 순서: `examMgmtNo`, `emOpenSeq`, `transCode`, `actGbn`. 후보 키이며 전수 안정성 미확인(같은 절)
- 분쟁조정은 게시판 ID + 게시글 번호(예: 게시판 `B0000390`의 게시글). 한 글에 첨부가 1~3건이라 `attachment-01` 식 접미가 붙을 수 있음
- DART는 접수번호(14자리 숫자) 하나가 폴더 이름

| 요소 | 의미 |
|---|---|
| source | 서비스/엔드포인트 이름공간. 7개: `dart`, `kofia_disclosure`, `fss_sanction`, `fss_improvement`, `fss_dispute`, `data_go_fund`(공공데이터포털 펀드상품기본정보), `krx_etf_daily`(KRX ETF 일별 매매정보). 제재와 경영유의 API는 구분 |
| 원천 키 | 문서 하나를 가리키는 키(문서 키). DB `raw_object.source_object_key`에서 파일 역할·첨부 번호를 뺀 부분이며, 같은 문서의 역할별 파일(`body_pdf`·`cover_html`·`prospectus`·`attachment-01` 등)은 이 폴더 하나에 둠. 필드가 여러 개면 `~`로 연결. 퍼센트 인코딩은 `/`, `~`, `%`, 제어 문자만 하고 한글은 그대로 둠. 인코딩 후 200바이트를 넘으면 앞부분을 남기고 `-h` + 전체 키 SHA-256 앞 12자를 붙임. 원본 필드 값은 meta.json에 JSON으로 보존 |
| 기준일 폴더 | 스냅숏형 API(`data_go_fund`, `krx_etf_daily`)만 사용. 값은 원천 기준일 YYYY-MM-DD이며 수집일이 아님 |
| file_role | cover_html / cover_xml / body_pdf / api_response / attachment / prospectus / prospectus_simple / change_summary |
| `attachment-01` 식 접미 | 같은 file_role 첨부가 여럿일 때 파일명에 붙임. 파일명 규칙이며 file_role 값이 아님 |
| n | 동일 source/원천 키의 바이트 버전(`version_seq`). 1부터 시작 |
| ext | 실제 콘텐츠 형식에 따라 결정. 오류 HTML을 pdf로 저장하지 않음 |

API 스냅숏 저장 단위:

- `data_go_fund`: 기준일 폴더 아래 페이지당 객체 1개(`page-NNNN__v{n}.json`, 바이트 버전 `n`은 `version_seq`). 마지막에 `_complete__v{n}.json`(페이지 수·건수)을 씀. 이 파일이 있어야 그 기준일 스냅숏을 유효로 봄
- 같은 기준일을 다시 받았는데 바이트가 바뀌었으면 기존 파일을 덮어쓰지 않고 `{기준일}/r2/`, `r3/` 폴더를 새로 만듦. 가장 높은 번호의 폴더 중 `_complete`가 있는 것이 그 기준일의 유효 스냅숏. 바이트가 같으면 새로 쓰지 않음
- `krx_etf_daily`: 기준일당 파일 1개

압축:

- raw는 압축하지 않음. 받은 바이트를 그대로 저장하므로 `sha256`이 원천 응답의 해시와 같은 뜻을 유지

바꾼 이유:

- 수집일 폴더는 같은 문서를 다시 받을 때마다 폴더가 갈라져 v1과 v2를 한곳에서 볼 수 없음. 원천 키 폴더는 같은 문서의 모든 버전을 한 폴더에 모음
- 해시 폴더는 사람이 읽을 수 없어 DB 없이는 어느 문서의 파일인지 알 수 없음. 읽을 수 있는 원천 키는 폴더 이름만으로 문서를 찾고, DB 행이 빠진 원본도 `source_object_key`와 대조해 복원할 수 있음
- 폴더 이름과 DB `source_object_key`를 같은 인코딩 함수로 만들면 두 값이 어긋나지 않고, 사람이 읽는 경로와 DB 조회 키가 하나가 됨
- 옛 `{문서키}__v1.meta.json`은 DART XML/PDF의 metadata가 충돌했으므로 meta.json은 확장자까지 포함한 정확한 파일명에 붙임
- 역할만 추가해도 같은 역할의 여러 첨부를 구분하지 못하므로 `attachment-01` 식 접미를 둠


### 원본과 요청의 구분

- `raw_object`: 실제 저장한 바이트의 버전. SHA-256·storage_path 필수
- `storage_path`: `RAW_ROOT` 기준 상대경로만 저장(09-22). 위 「파일 경로」 형식이며, 오브젝트 스토리지로 옮기면 이 상대경로가 그대로 객체 키
- `collection_attempt`: 요청 한 번. 바이트가 없으면 `raw_object_id=NULL`인 시도만 기록. 가짜 파일·빈 해시를 만들지 않음
- HTTP 오류라도 응답 바이트가 있으면 원본으로 보존 가능. `collect_status=failed`인 파일은 본문 추출 대상에서 제외
- 정상 빈 API 응답도 바이트가 있으면 보존하고 시도 outcome=`EMPTY`로 기록
- 포털·KRX·목록 응답은 `document_id=NULL`로 저장. 파일 보관을 위해 가짜 공시 문서를 만들지 않음
- 문서와 파일 연결은 별개. 같은 바이트가 여러 문서에 나오면 각 문서의 연결을 남김. CAS로 실체를 공유할지는 별도 결정(「미결」)
- 고아 객체(S3에는 있으나 `raw_object` 행이 없는 객체)는 삭제하지 않음. 재시도에서 같은 키·같은 바이트가 나오면 그 객체를 채택하고, 주간 보고에 고아 객체 목록만 남김
- 적재 순서와 단계별 실패 처리는 「적재 순서」

### 버전·중복·재추출

동일 source/source_object_key의 최신 버전과 바이트 SHA-256을 비교.

1. 같으면 새 파일 버전을 만들지 않고 collection_attempt가 기존 raw_object를 참조
2. 다르면 version_seq를 늘려 새 파일 저장
3. 같은 파일을 같은 파서 버전으로 이미 추출해 EXTRACT_OK가 되었으면 다시 추출하지 않음(추출 키 = 원본 파일 × 파서 버전, v2.2). 재사용은 EXTRACT_OK 행만이며, FAILED·PARTIAL 행은 다음 실행이 같은 키 행을 덮어씀(created_run_id를 그 실행으로 갱신). 완료 결과 불변은 EXTRACT_OK 행에만 적용. EXTRACT_OK 행에 딸린 section 행은 삭제·재발급하지 않음. SCORE 실행은 입력 manifest에 사용한 (raw_object_id, parser_version) 목록을 고정하며 이전 실행이 만든 추출 결과도 읽을 수 있음(created_run_id는 출처 기록일 뿐 입력 판별에 쓰지 않음). 파서·전처리 버전이 다르면 새로 추출. 중복 다운로드 생략과 재추출 생략을 같은 규칙으로 처리하지 않음. 덮어쓰기로 사라지는 실행별 실패 기록은 `runs/{run_id}/extraction_attempts.jsonl`에 남김(아래 「추출 실패와 절 품질」, 10월 9일)
4. 같은 run_id의 재시도는 키를 유지하고 결과를 멱등 처리. 완료된 실행의 결과는 수정하지 않음

| 칼럼 | 뜻 |
|---|---|
| `document.version_no` | 확인된 공시 정정 계보 |
| `raw_object.version_seq` | 파일 바이트 버전 |
| `file_extraction.parser_version` | 추출에 쓴 파서 버전. 추출 결과의 키 일부 |
| `run_id` | 처리 실행 |

- 해시가 같다는 이유로 두 공시가 정정 관계가 아니라고 결론 내리지 않음

### 금투협 클래스 행 중복 제거

| 규칙 | 내용 |
|---|---|
| 적용 조건 | 수시공시(`uRptGb='O'`, `tsCd` 접두 `2OF`)만 |
| 접는 단위 | 같은 공고 안에서 동일 `server_path + fileNm`을 가리키는 클래스 행 |
| 시점 | 다운로드 전 |
| sha256 | 검증용으로만 사용 |
| 하지 않는 것 | 서로 다른 공고·날짜의 같은 파일명이 항상 불변이라고 가정하지 않음. 정기공시를 수시 4필드로 접지 않음 |

- 정기공시는 평균 1.08행으로 사실상 1행 = 문서 1건. 정기공시에 중복 제거를 걸면 서로 다른 보고서를 하나로 지움
- 실측 근거: 운용사 4곳 묶음 4개(14~15행)에서 행별 첨부 집합이 전부 1종. 미래에셋 15행의 투자설명서는 전부 1,022,426바이트, 같은 sha256. `fileNm` 고유 수 = sha256 고유 수. [금투협 중복 행·ETF 이름 규칙 검증](records/phase1-erd/kofia-rows-and-etf-rule.md) 「첨부 해시 비교」「파일명 중복 제거 판단」
- 수시공시 4필드 문서키: [데이터 테이블·ERD 설계](data-model.md) 「문서와 소스별 키」

### Metadata

모든 파일 metadata에 포함할 항목.

| 항목 | 내용 |
|---|---|
| raw_object_id, source, source_object_key, version_seq | 원본 식별 |
| document_id, source_doc_key, source_key_payload | 문서 파일이면 원천 공시 식별, API 스냅숏이면 NULL |
| file_role, file_name, original_file_name, server_path | 역할·서버명·표시명·서버 위치 |
| body_format, content_type, sha256, storage_path | 실제 형식·바이트 해시·저장 경로 |
| collected_at, source_baseline_date | UTC 수집 시각과 원천 기준일 |
| request_params, endpoint/download_url | 인증값을 제거한 JSON/URL. 헤더 AUTH_KEY, serviceKey, crtfc_key, authKey 등 원문 금지 |
| credential_ref | 필요하면 비밀값 저장소의 참조 이름만 |
| http_status, source_result_code, collect_status | 전송 / 업무 응답 / 파일 검증 결과 구분 |
| attempt_id, run_id | 파일을 확보한 요청·실행 연결 |

- DB에서 빠진 원본도 복원할 수 있도록 파일 식별·해시·원천 정보를 함께 남김
- 파일이 없는 실패 요청은 시도 로그가 복구 원천
- 요청 로그 출력 시 인증 URL을 노출하지 않음

### DART와 소스 간 중복

- 공개 `viewer.do` 표지는 HTML(`cover_html`)로 보관. 공개 뷰어 표지 실측을 API `document.xml` 응답 실측으로 취급하지 않음
- `document.xml` API 응답은 ZIP을 원바이트로 보관. 내부 XML/PDF 동봉 여부는 확인 후 기록
- 공개 뷰어 경로와 API 경로를 섞어 문서당 정확히 2파일을 강제하지 않음
- 본문 PDF는 별도 `body_pdf`
- 간이투자설명서는 DART 본문 PDF 안의 요약 구간일 수 있음. 별도 첨부라고 가정하지 않음([DART 본문 PDF 부·절 분할 실현성 검증](records/phase1-erd/dart-section-split.md) 「함의」)
- 금투협 간이 PDF와 DART 본문 속 요약 구간은 파일 해시가 달라도 내용이 중복될 수 있음. 파일 해시 교집합 0은 내용 중복 0의 증거가 아님([2단계 데이터 파이프라인 Flow 설계 입력](pipeline-flow.md) 「먼저 측정할 것: 소스 간 중복률」)
- CAS는 바이트 저장 중복은 해결하지만 비교 모집단의 펀드·대표본 중복은 해결하지 못함

### 파생 텍스트·실행 스냅숏 경로

RAW_ROOT 정의 (09-23 경로 계약 보완안):

- `raw/`, `derived/`, `runs/`, `assets/`, `eval/`, `exports/`, `backups/`를 포함하는 공통 데이터 루트
- 예: 로컬 루트 `/data/signal`, storage_path `raw/dart/...` → 실제 경로 `/data/signal/raw/dart/...`
- 루트를 `/data/signal/raw`로 잡아 `raw/raw`를 만들지 않음
- 기존 운영 설정이 확인되면 이 규약과 대조

파일 참조 공통 규칙:

- canonical_text_path, input_manifest_path, selection_manifest_path, membership_manifest_path, structure_manifest_path도 같은 루트 기준 상대경로(평가 manifest 경로는 평가 표를 추가할 때 같은 규칙)
- 절대경로·상위 경로 이동(`..`)·인증 토큰 포함 URL을 파일 참조로 저장하지 않음
- 스토리지 전환 시 루트/버킷 설정만 바꾸고 상대 객체 키와 해시는 유지. CAS 채택 시 blob_path도 같은 원칙

```text
derived/{raw_sha256}/{parser_version}/text.txt
derived/{raw_sha256}/{parser_version}/structure.json             # file_extraction.structure_manifest_path
runs/{run_id}/inputs.json                                        # EXTRACT·SCORE run 모두
runs/{run_id}/extraction_attempts.jsonl                         # EXTRACT run. 추출 시도 1건당 1줄
runs/{score_run_id}/selection.json                               # pipeline_run.selection_manifest_path (채점 실행만)
runs/{score_run_id}/documents.parquet                            # 채점 입력(데이터 처리 요구 명세)
runs/{score_run_id}/excluded.parquet                             # 비교 집단 제외 목록
runs/{score_run_id}/populations/{population_snapshot_id}.json
runs/{run_id}/llm/{document_id}/{field_name}/attempt-{n}/request.json
runs/{run_id}/llm/{document_id}/{field_name}/attempt-{n}/response.json   # llm_field_extraction.raw_response_path
assets/{종류}/{이름}__v{버전}__{sha256 앞 12자}.{ext}
eval/pilot/{id}/
eval/human-eval/{id}/
eval/sanction-validation/{버전}/
exports/official.json
exports/runs/{score_run_id}/scores.parquet
exports/runs/{score_run_id}/sensitivity/
backups/postgres/{YYYY-MM-DD}/signal.dump                        # + signal.dump.sha256
```

- `derived/`의 키는 원본 파일 × 파서 버전(v2.2 수정 2). 원본 파일은 바이트 해시(raw_object.sha256)로 가리키므로 내부 서러게이트 ID(raw_object_id, 추출 실행 번호)가 경로에 들어가지 않음. 이 방식으로 검토 번호 B9(derived 경로의 서러게이트 ID·내용 주소화)가 해소됨
- 같은 바이트(sha256)가 여러 raw_object로 저장돼도 같은 파서 버전의 결과는 한 경로를 공유하며 내용이 같아 무해함. 쓰기는 sha256 기준 한 번
- 파생 파일은 두 개뿐. 절 텍스트를 따로 저장하지 않음
  - `text.txt`: canonical text 전체
  - `structure.json`: 부·절 제목과 글자 범위, 표 영역(글자 범위), 간이 요약 구간
- 파서 버전 형식 예: `pdftotext-24.02_prep-3`. 소문자·숫자·`.`·`-`·`_`만 쓰고 전처리 버전을 포함함. 추출 도구, 전처리, CPU 아키텍처, 형태소 분석기(텍스트 처리에 영향을 줄 때)가 바뀌면 파서 버전을 올림
- `runs/{run_id}/…`·`populations/`는 실행 아래. 채점 실행은 `pipeline_run.upstream_run_id`로 추출 실행을 가리킴 → 산식만 바뀐 재채점은 `derived/`를 새로 만들지 않음

LLM 호출 저장:

- 시도 한 번당 `request.json`과 `response.json` 두 파일. `raw_response_path`는 `response.json`을 가리키고, 응답 바이트의 해시는 `llm_field_extraction.response_sha256`에 기록(이번 ERD v2.2 PR에서 칼럼 추가)
- 같은 입력의 재호출 생략 여부는 DB 조회로 판단(canonical text sha, prompt sha, 모델, 파라미터, 필드). 생략하면 이전 시도의 경로를 재사용할 수 있음. 생략 규칙 자체는 확정하지 않음(「미결」)

실행 폴더 불변:

- `runs/{run_id}/`(inputs.json, extraction_attempts.jsonl, selection.json, documents.parquet, excluded.parquet, populations, llm)는 완료 후 불변. 조건부 쓰기, 삭제 거부, 실행을 SUCCEEDED로 바꾸기 전 sha256 재대조로 지킴
- 채점 입력 파일(inputs.json, selection.json, documents.parquet, excluded.parquet)은 실행 시작 때 한 번 쓰고 이후 바꾸지 않음. 두 parquet의 sha256은 inputs.json에 기록. 실패한 채점 실행을 다시 돌릴 때는 새 score_run_id를 발급

`assets/`(불변, 이름·버전·해시 12자로 경로가 정해짐):

| 종류 | 내용 |
|---|---|
| dictionaries | 사전 |
| standards | 작성기준 시행일별 판 |
| metrics | 지표 정의·가중치·기준집단 |
| prompts | 프롬프트 |
| morph | 형태소 분석기 버전·옵션 |
| rules | 표준문안·표 판정 규칙 |

- `config_manifest`가 이 파일의 경로와 sha256을 가리킴

`eval/`(접근 제한 접두어):

- `pilot/{id}/`, `human-eval/{id}/`, `sanction-validation/{버전}/`(제재 사례 매핑표, 대조군). 평가용 사례는 규칙을 만들 때 보지 않도록 하위 폴더를 나눔
- 전용 IAM 역할만 읽을 수 있음

`exports/`:

- `official.json`: 현재 공식 채점 실행을 가리키는 포인터. `is_official`이 바뀔 때만 갱신
- `runs/{score_run_id}/`: `scores.parquet`, `sensitivity/`. 채점 결과만 둠. 채점 입력 `documents.parquet`·`excluded.parquet`는 실행 폴더 `runs/{score_run_id}/`에 둠

`backups/`:

- `postgres/{YYYY-MM-DD}/signal.dump`와 `signal.dump.sha256`. 날짜별 새 키

- 평가(evaluation) 표 연기(v2.2 수정 1)로 평가 실행 결과의 경로는 평가 표를 추가할 때 정함
- manifest 저장 기준(수정 8, B7 정정): 큰 불변 자료는 파일(경로 + sha256), SQL로 거르는 값은 칼럼. 정규 JSON은 키 정렬·UTF-8·구분자 고정 한 줄 규칙으로 충분하며 RFC 8785는 요구하지 않음
- canonical text는 UTF-8/LF, 파일 전체 텍스트 보존. `file_extraction`에 경로·해시·Unicode code point 길이 기록
- 지표에 따라 표·표준문안을 제외할 수 있으나 원문 텍스트를 전역 삭제하지 않음
- 입력·모집단 manifest는 완료 후 불변, 해시 검증·백업 대상. 최소 내용은 [데이터 테이블·ERD 설계](data-model.md) 「적재 검증 규칙」

### 적재 순서

1. `collection_attempt` 기록
2. 응답 완전성 검증
3. sha256 비교. 같으면 S3 쓰기를 생략하고 기존 `raw_object`를 재사용
4. S3 쓰기. `.meta.json`을 먼저, 원본을 나중에 쓰며 새 키에만 씀
5. `raw_object` INSERT와 attempt 갱신을 한 트랜잭션으로 처리
6. 구간 검증을 통과했을 때만 `source_watermark` 전진(5와 별도 트랜잭션)
7. 추출: `derived/` `text.txt` → `structure.json` → DB 행
8. LLM 호출: `runs/…/llm`
9. 채점 입력: `runs/{score_run_id}/` inputs.json·selection.json·documents.parquet·excluded.parquet
10. 채점: `runs/`
11. `exports/`

- 4와 5 사이에 중단되면 S3에 `raw_object` 행이 없는 객체가 남음. 삭제하지 않고 재시도에서 같은 키·같은 바이트이면 채택
- `.meta.json`을 먼저 쓰므로 원본이 있는 객체는 항상 meta.json이 있음

## 수집 실패

수집 요청, 응답 파일, 실행별 추출, 절의 상태를 분리. 점수 계산 가능 여부는 추출 성공 여부와 다름.

| collection_attempt.outcome | 판정 | 처리 |
|---|---|---|
| SUCCESS | 정상 업무 코드, 응답 구조·완전성 검증 통과 | 원본 저장 또는 기존 파일 참조 |
| EMPTY | 유효한 조회 조건에서 정상 자료 없음 | 성공한 조회로 기록. 행 0건 자체를 실패로 세지 않음 |
| RETRYABLE_FAILED | 타임아웃·일시적 5xx | 같은 run_id, attempt_no 증가 |
| PERMANENT_FAILED | 잘못된 요청·폐기 URL 등 재시도로 해결 불가 | 원인 수정 전 자동 반복 중단 |
| CONFIG_ERROR | 401/403, 승인·키 설정, 필수 요청값·조회창 누락 | 설정 확인. 같은 요청 자동 반복 안 함 |
| RATE_LIMITED | HTTP 429, API 일일·분당 한도 | Retry-After 또는 확인된 한도 복구 뒤 재개. 영구 자료 없음으로 처리하지 않음 |

- HTTP 상태와 업무 응답 코드를 별도 칼럼에 저장
- 타임아웃은 `http_status=NULL`, 바이트가 없으면 `raw_object_id=NULL`
- 파일이 있으면 실패 응답도 「원본 보관」 규칙대로 보존하고 `raw.collect_status`로 후속 처리 대상에서 제외

### 소스별 검증

| 소스 | 주의 |
|---|---|
| 금감원 | `resultCode=1` 정상, `900` 정상 빈 결과, `030` 조회창 수정, `033` 한도 복구 대기. 문자열로 보존 |
| 금투협 | `uRptAllYN` 등 필수 인자·1년 미만 조회창을 요청 전에 검증. 잘못된 요청의 0행을 정상 EMPTY로 승인하지 않음 |
| 금투협 | 종료 태그·총건수/수신 행 수 대조. 정기공시를 수시 4필드로 접지 않음 |
| 포털 | 업무 코드 확인 후 객체/배열 item 정규화, 전체 페이지 수신과 totalCount 대조 |
| KRX | 승인·키 오류 구분, 요청 기준일·응답 구조 검증. 휴장·수집 실패·불완전 응답을 상장폐지로 해석하지 않음 |
| DART | 목록·원문 API의 업무 오류와 HTML 뷰어 경로 구분. PDF는 MIME과 실제 형식 확인. API ZIP 내부 구성 미확인 |

- 정상 빈 응답과 전송 바디 0바이트는 다름
- 0건이 불가능해 보이는 구간은 이전 분포·요청 조건을 근거로 품질 경보를 낼 수 있음. 전 소스 공통 실패 규칙으로 확정하지 않음
- 호출 형식과 응답 코드 원문: [데이터 소스 수집 명세](data-sources.md)

## 재시도와 워터마크

| 대상 | 규칙 |
|---|---|
| 타임아웃·5xx | 지수 백오프 최대 5회 |
| 429 | 예외. 한도 정책을 따름 |
| 403·키·서비스 승인 문제 | 자동 재시도 안 함. 즉시 알림 |
| 조사 스크립트의 3회 재시도 | 생산 수집 계약이 아님 |
| HWP 3.0(94건)·배포용 문서(7건) 추출 실패 | 자동 재시도에서 제외. 해결되지 않는 실패를 매일 반복하면 실제 일시적 실패를 찾을 수 없음 |

워터마크 전진 조건(v2.2: 소스별 현재 값은 `source_watermark` 표에 기록. 키 = (source, scope_key), 값 = covered_through):

- 해당 구간의 요청·페이지 완전성 검증이 끝났을 때만 전진
- 정상 EMPTY와 실패·한도 중단을 구분
- 중간 페이지까지만 받은 구간을 성공으로 승인하지 않음
- 갱신 순서는 「적재 순서」 6번: 구간 검증 통과 뒤 원본 적재 트랜잭션과 별도 트랜잭션으로 전진. 이전 값의 이력은 pipeline_run의 input manifest에 남음. 검증한 구간의 시작은 covered_from(첫 실행 시작일, 바꾸지 않음, 룩백 하한), 끝은 covered_through
- 검증 실패·부분 응답이면 source_watermark를 갱신하지 않고 기존 값 유지. 검증 방법(건수 대조, 페이지 끝 확인)은 소스별로 정함(「미결」)

| 소스 | 증분/스냅숏 축 | 주의 |
|---|---|---|
| DART | rcept_dt | 3일 룩백 잠정값(정정본 대비). 접수·원본·첨부 처리 단계 분리 |
| 포털(`data_go_fund`) | basDt, 요청 beginBasDt | setpDt는 설정일이므로 워터마크 아님 |
| KRX ETF(`krx_etf_daily`) | basDd/BAS_DD 일별 전체 | 일별 파일 보존. 완전한 거래일 자료만 차집합 비교. 보관 정책은 「KRX 데이터 보관」 |
| 금투협 공시 | standardDt, 7일 룩백 잠정값 | 백필은 1개월 창 권고. 수시공시만 4필드 묶음 |
| 금투협 판매관계 | 월 기준 + 실제 조회일 | 월 대표일·전건 성공 여부를 함께 보존 |
| 금감원 제재 | inputDate | actReqDate는 사건일. 표본 중 구간 밖 사건일·구간 안 입력일 사례 1건으로 확인. 표본 확대 재검증 필요 |
| 분쟁조정 | 게시판 ID + 게시글 번호 | 상품·법인 마스킹은 수집 실패가 아님. 게시일은 금소법 시행(2021년) 이후 자료만 거르는 기준이라 필수 수집(9차 미팅) |
| 국가법령 | 원천 계약 확인 전 미정 | 조문 해시 후보. 법적 서류 대응을 먼저 확인 |
| finlife | 현재 CDI 핵심 범위 제외 | 펀드·ETF·ELS 상품 마스터로 사용하지 않음 |

금감원 API 커버리지:

- 과거 조회 0건을 「그 기간에 제재가 없었다」로 쓰지 않음
- 저장 표본은 2026-09 8건. 게시판(5,735건)과 API의 범위 차이는 별도 조사 대상([소스별 데이터 현황표](records/phase1-erd/source-profile.md) 「제재 API 과거 조회와 미확정 커버리지」)
- API가 항상 최근 한 달만 제공한다는 서버 정책은 확인되지 않음
- 라벨 소스 전환은 팀 과제. 크롤러는 전환하지 않음


### KRX 데이터 보관 (10월 4일 PM 초안, 10월 6일 재감사 수치 반영)

크롤러 2차의 KRX 수집 전에 필요한 3건.

| 항목 | 정한 것 |
|---|---|
| 저장 경로 소스 이름 | `krx_etf_daily`. 경로 `raw/krx_etf_daily/{기준일 YYYY-MM-DD}/` 아래 기준일당 파일 1개(「파일 경로」) |
| 스냅숏 보관 기간 | 받은 일별 파일은 지우지 않음(`raw/` 규칙, 프로젝트 종료까지). 하루치가 작아 비용 영향 없음. KRX는 최소 10년 소급 조회가 되므로 잃어도 다시 받을 수 있음. 프로젝트 종료 뒤 보관처는 저장 계층 계획의 11월 15일 결정을 따름 |
| 매칭 실패 229건 처리 | [상품·법인 매칭 규칙](matching-rules.md) 「KRX 매칭 실패 처리」. 10월 6일 1,167종목 재감사 결과 확인된 연결 223건(`KRX_CONFIRMED`로 적재), 이름 후보만 932건(`NAME_ONLY`), 보류 12건(`PENDING`). 229건만 보면 확인 98·이름 후보만 124·보류 7 |

## 추출 실패와 절 품질

- 추출 결과는 `file_extraction(raw_object_id, parser_version)`에 보존(v2.2: 실행 번호가 아니라 파서 버전). EXTRACT_OK 결과가 있으면 재추출하지 않음
- 옛 raw_object.extract_status의 단일 현재값은 쓰지 않음
- 실행별 추출 시도 기록(10월 9일 PM(대현) 확정, 데이터 엔지니어링·인프라(주영) 리뷰 제안): `file_extraction`은 FAILED·PARTIAL 행을 다음 실행이 덮어쓰므로 실행마다의 실패 기록이 남지 않음. 그래서 EXTRACT 실행은 `runs/{run_id}/extraction_attempts.jsonl`에 시도 1건당 1줄을 씀. 표는 추가하지 않음
  - 칼럼: `run_id`, `raw_object_id`, `raw_sha256`, `parser_version`, `action`(EXTRACTED / SKIPPED_EXISTING_OK), `extract_status`, `error_reason`, `started_at`, `finished_at`
  - 이미 EXTRACT_OK인 파일을 건너뛴 것도 `SKIPPED_EXISTING_OK`로 한 줄 남김. 그 실행의 처리 분모에 들어감
  - 실행별 파일 단위 실패 건수·실패율·유형은 이 파일에서 셈. `file_extraction`은 파일 × 파서 버전의 현재 상태만 담음
  - 크롤러의 요청 시도 기록(`runs/{run_id}/attempts.jsonl`, `collection_attempt` 칼럼)과 같은 방식. 실행 완료 뒤 불변(「실행 폴더 불변」)

| extract_status | 의미 |
|---|---|
| EXTRACT_OK | 원래 있는 텍스트가 정상 추출됨 |
| EXTRACT_FAILED | 일반 추출 실패. 사유 보존 |
| EXTRACT_UNSUPPORTED_FORMAT | 지원하지 않는 형식(HWP 3.0 등). 자동 재시도 제외 |
| EXTRACT_PARTIAL | 일부만 복구됨(배포용 문서 등). 전체 본문 성공으로 세지 않음. 자동 재시도 제외 |
| OCR_CANDIDATE | OCR 경로가 필요한 입력(BMP 내장 4건 등). 자동 성공 아님 |
| EXTRACT_NOT_APPLICABLE | 본문 추출 대상이 아닌 표지·API metadata 등 |
| SECTION_BOUNDARY_NOT_FOUND | section 전용(v2.2 신설). 파일 추출은 성공했으나 이 절의 본문 경계(시작·끝)를 찾지 못함. 파일 추출 실패와 구분. char 범위 NULL 허용. 재시도 시 같은 파서 버전의 행을 덮어쓰거나 새 파서 버전에서 다시 시도 |

품질 신호 규칙:

- 파일 전체가 예상보다 짧거나 깨진 문자 비율이 큰 것은 품질 의심 신호
- 500자·30%는 미검증 잠정값이며 모든 절에 적용하는 실패 기준이 아님
- 정상 추출된 짧은 절은 EXTRACT_OK 유지, `quality_flags`에 SHORT_TEXT 기록
- 구체 문자수 기준값과 문장·어절 분모는 CDI 산식 담당(다빈)이 정함
- 500자 미만이어도 정상적인 짧은 절을 버리지 않음
- 깨진 문자 30% 규칙은 Unicode·표·수학기호가 있는 금융문서에서 재검증 필요
- 파일 전체 추출 성공과 절 경계 찾기는 별도 검증. 표본의 292/294는 절 경계를 찾은 비율이지 텍스트 품질 성공률이 아님
- `section_text`는 실패 시 복구 문자열 또는 NULL 허용. 「실패해도 본문이 항상 있다」고 가정하지 않음
- 표 제거(ASL 계산용)와 표 보존(고지 충실도용)은 지표별 파생 처리. canonical text에서 표를 지우지 않음
- `EXTRACT_OK`는 채점의 필요조건이며 충분조건이 아님. 분모 0·짧은 절·미정 산식은 계산 상태·사유로 다룸

## 문서 파싱 상태

- `(document_id, 파서 버전 집합)` 단위 집계(v2.2: 실행별이 아니라 선택한 파일 × 파서 버전 기준)
- 그 실행이 선택한 파일 버전과 채점 대상 역할 집합만 집계. 과거 파일 버전 전체를 세지 않음
- 대상 목록은 입력 manifest에 고정

집계 우선순위:

1. CDI 비대상 문서: PARSE_NOT_APPLICABLE
2. 파일 선택·필수 수집·추출이 끝나지 않음: PARSE_PENDING
3. 대상 집합이 비어 있지 않고 전부 EXTRACT_OK: PARSE_OK
4. 평가 완료 후 하나 이상 EXTRACT_OK 또는 EXTRACT_PARTIAL: PARSE_PARTIAL
5. 평가 완료 후 정상·부분 텍스트가 전혀 없거나 필수 파일이 영구 수집 실패: PARSE_FAILED

- 빈 집합을 「모두 성공」으로 계산하지 않음
- 부분 복구만 있는 경우가 PARTIAL과 FAILED에 동시에 해당하지 않음
- cover_html·cover_xml 등 본문 비대상 파일은 본문 상태 집계에서 제외. 위험등급·코드 추출 품질은 별도 추적
- 파일 단위 집계와 절 단위 품질은 별개. 문서 PARSE_OK만 보고 실패한 절을 채점하지 않음

## 미결

| 질문 | 결정 필요 주체 | 필요 시점 |
|---|---|---|
| CAS(`blobs/{sha256}`)를 채택하는가. 금투협 중복 제거는 `fileNm`으로 해소됐고, 소스 간 내용 중복은 CAS로 잡을 수 없음. 남은 근거가 있는지 재판단 | 대현·팀 | 09-30 2단계 설계 확정 |
| 저장 제품, 원자적 게시 방식, manifest 백업 스케줄 | 팀 | 09-30 2단계 설계 확정 |
| DART 3일·금투협 7일 룩백 잠정값 확정 | [담당 미정] | 수집기 구현 전 |
| 금감원 제재 증분 `inputDate` 판정을 다른 달 표본으로 재검증 | 대현 | 제재 수집기 구현 전 |
| 500자·깨진 문자 30% 품질 신호의 기준값과 분모(문장·어절) | 다빈 | 절 분할 실패율 산출(10-01~10-14) 전 |
| DART `document.xml` ZIP 내부 구성(XML만인지, PDF 동봉인지) | 주영 | DART 수집기 구현 전 |
| 결측 원인을 구분하는 상태값: 문서 4종의 「첨부 없음」과 API 3종의 「필드 비어 있음」이 같은 칼럼 이름을 씀([소스별 데이터 현황표](records/phase1-erd/source-profile.md) 「표 구조를 바꿀 문제 2건」) | [담당 미정] | 09-30 2단계 설계 확정 |
| 결측률 칸의 분모 칸: 분쟁조정 사건 814 / 금융투자 187 / 첨부 845 / 첨부 213단위가 섞임 | [담당 미정] | 09-30 2단계 설계 확정 |
| 룩백 재조회 방식 확정과 소스별 워터마크 검증 방법(건수 대조·페이지 끝 확인 등). 표는 v2.2의 source_watermark | 주영 | 2단계 설계 |
| 평가 표·자료의 접근 분리 중 DB 쪽: 같은 DB 유지 vs eval 스키마(검토 번호 B4). 저장소 쪽은 같은 버킷의 `eval/` 접두어 + 전용 IAM으로 정함. 축 4 사건 단위 검증 자료(제재 사례 매핑표, 대조군 문서 목록, 두 명 독립 판정 결과)도 접근 제한 대상에 넣을지 함께 정함. 이 자료는 규칙을 만들 때 보지 않아야 하므로(09-29 팀 논의 결론, 9차 미팅(09-30) 확정. 제재문 역할은 확인대기) 분리 쪽이 자연스러움 | 팀 | 09-30 |
| LLM 같은 입력 재호출 생략 규칙(DB 조회 항목은 정함, 생략 조건 자체는 미정) | 데이터 사이언스(다빈)·데이터 엔지니어링·인프라(주영) | 2026-10-15 추출 시작 전 |
| 스냅숏형 API 객체(`page-NNNN__v{n}.json`, `_complete__v{n}.json`)에도 `.meta.json`을 둘지. 재수집 파일명은 10월 4일 확정(같은 기준일 바이트가 바뀌면 `r2/`, `r3/` 폴더) | 데이터 엔지니어링·인프라(주영) | 수집기 구현 전 |

## 참고

- 호출 형식·응답 코드: [데이터 소스 수집 명세](data-sources.md)
- 표 구조와 manifest 최소 내용: [데이터 테이블·ERD 설계](data-model.md) 「원본·수집 시도·추출」「적재 검증 규칙」
- 2단계로 넘긴 항목 목록: [2단계 데이터 파이프라인 Flow 설계 입력](pipeline-flow.md) 「1단계에서 넘어온 결정 대기 항목」
- 실측 근거: [금투협 중복 행·ETF 이름 규칙 검증](records/phase1-erd/kofia-rows-and-etf-rule.md), [DART 본문 PDF 부·절 분할 실현성 검증](records/phase1-erd/dart-section-split.md), [소스별 데이터 현황표](records/phase1-erd/source-profile.md)
- CAS 보류 판정 경위: [09-14 초기 소스 확인](records/phase1-erd/initial-source-checks.md) 「티켓 메모 대조 판정」
- 대체된 판단: 「0건 = 실패」 → EMPTY(09-22), 「500자 미만·깨진 문자 30% = 추출 실패」 → 품질 신호(09-22), 「KRX 차집합 = 상장폐지 확정」 → 후보 신호, 「원본 경로 `raw/{source}/{yyyy}/{mm}/{dd}/{source_doc_key}/{filename}` + CAS 즉시 채택」(티켓 메모) → 현 경로 규칙과 CAS 보류, 「금투협 중복 제거 = sha256」 → 같은 공고 안 `server_path + fileNm`
