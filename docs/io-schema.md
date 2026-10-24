# 3단계 입출력 Schema 설계 입력

3단계 입출력 Schema 설계(기한 2026-10-14)가 확정할 입출력 Schema(프로그램끼리 주고받는 데이터 약속) 2종의 요구와 검증 설계 재검토 입력.

## 상태

| 항목 | 값 |
|---|---|
| 설계 본문 | 미작성. 이 문서는 입력 목록 |
| 기한 | 2026-10-14 |
| 선행 산출물 | CDI 4축 변수표(09-23), 데이터 처리 요구 명세(09-30) |
| 1단계와의 경계 | 09-16 데이터베이스 Schema는 두 계약을 담을 자리만 두고 모양을 미리 확정하지 않음. v2에서 먼저 들어간 모양은 「스키마에 먼저 들어간 모양」 |
| LLM 추출 JSON 공통 계약 | 10월 24일 초안(아래 「LLM 추출 결과 JSON 공통 계약」). 필드별 정의는 6필드 확정(10월 28일) 뒤 Week 7 |

## 확정할 데이터 계약 2종

| 계약 | 생산 | 소비 |
|---|---|---|
| LLM 추출 결과 JSON | 구조화 층(텍스트에서 필드 추출, LLM) | 적재 층, 고지 충실도 판정 |
| CDI 출력(파트 A 고지 점검 + 파트 B 읽기 난이도) | 채점 | 대시보드·API(드릴다운 포함) |

## LLM 추출 결과 JSON 요구

| 소스/필드 | 실제 형태 | 논리 타입·처리 | 목적지 |
|---|---|---|---|
| LLM 6필드 | 최종 이름/형태 미확정 | 문자열·숫자·목록과 값 상태, 근거 구간 정의 필요 | 3단계 계약. score_payload로 대체하지 않음 |
| CDI 지표 | 절/문서/문서쌍 혼재 | 계산 단위·분모·원값·결측 사유를 함께 정의 | metric_key별 score(v2). 지표 계약은 CDI 산식 담당 |

- 6필드: 유형·판매사·위험등급·수수료·원금손실·핵심 위험
  - 이름·타입·출처 절 미확정(6필드 확정 티켓)
  - 원본/근거 구간은 보존, 이름·타입은 임의 확정하지 않음
- 예약 필드(6필드 밖): `risk_grade_basis`(위험등급 산정 기준. 주간 수익률 변동성, VaR 등 산정 방식 이름), `risk_grade_measure`(그 기준의 측정값). 원본 추출값으로 받음. 예약, 추출 미실시. 10월 21일 100건 비용 실측 뒤 추출 여부 결정(PM(대현) 10월 8일). 저장은 llm_field_extraction의 field_name 값이라 표 구조 변경 없음([데이터 테이블·ERD 설계](data-model.md) 「product / fund_group」 risk_grade)
- 필드별 요구
  - 값 상태: 값 있음 / 미발견 / 추출 실패 구분
  - 근거 구간: section 또는 파일 + char 범위
- 결측 규칙
  - 원금손실 고지 미발견: 추출 성공 후 미발견과 추출 자체 실패 구분. 후자를 「고지 없음」으로 계산 금지
  - 수수료 등 중첩 구조·자유 텍스트·목록: 임의 단일 문자열·실수로 평탄화 금지. 값·단위·적용 클래스·근거 section/offset 정의 필요
  - 금액·비율: 단위 없이 숫자만 넘기지 않음
- LLM 6필드 출력은 점수 출력과 별도 계약
- 입력 기록(10월 9일): 시도마다 `request.json`에 보낸 문서 텍스트, `input_sha256`, `inputs`(원본 파일·파서 버전·절 또는 문자 범위)를 남기고 `llm_field_extraction.input_sha256`에 같은 해시를 적음. 해시 규칙과 재호출 생략 조건은 [원본 보관 규칙](storage-and-failure-rules.md) 「LLM 호출 저장」

## LLM 추출 결과 JSON 공통 계약

6필드 전부에 같은 모양으로 적용하는 envelope·상태·결측·근거 규칙. 10월 24일 데이터 엔지니어링·인프라(주영) 초안, PM(대현) 확인 전.

### 적용 범위

- 공통 계약이 정하는 것: 필드 1건의 JSON envelope, 상태값과 `result_status` 대응, 결측 표기, 값 표기 규칙(원문·단위·목록), 근거 위치 형식, 입력 참조 형식
- 필드별 정의가 정하는 것(6필드 확정 10월 28일 뒤, Week 7): 필드 이름, `value`의 타입과 구조, 출처 절, 표지(HTML) 출처 필드의 근거 표기
- 계약 밖: 문서 작성기준일은 규칙 기반 추출([데이터 처리 요구 명세](processing-requirements.md) 4-4). 부·절 제목 위치는 `structure.json`이 정본. 둘 다 LLM 입력을 고를 때 참조만 함

| 파일·칼럼 | 내용 | 규칙 |
|---|---|---|
| `request.json` | 보낸 문서 텍스트, `input_sha256`, `inputs`, 프롬프트·모델 식별 | 입력 정본([원본 보관 규칙](storage-and-failure-rules.md) 「LLM 호출 저장」) |
| `response.json` | 모델 원응답 바이트 그대로 | 불변. 해시는 `llm_field_extraction.response_sha256` |
| `llm_field_extraction.value_json` | 원응답을 이 계약으로 정규화한 결과 | 아래 envelope. 적재 검증 대상 |
| `evidence_section_id`·`evidence_char_start`·`evidence_char_end` | `value_json.evidence[0]` 복사 | 조회용. 정본은 `value_json` |

### envelope (필드 1건)

| 키 | 타입 | 필수 | 의미 |
|---|---|---|---|
| `contract_version` | int | 필수 | 이 계약의 판. 지금 1 |
| `field_name` | string | 필수 | `llm_field_extraction.field_name`과 같은 값 |
| `status` | string | 필수 | 아래 「상태값」 5개 중 하나 |
| `value` | 필드별 | `status = FOUND`일 때 필수, 그 외 null | 구조는 필드별 정의 |
| `raw_text` | string | `FOUND`일 때 필수 | 값의 원문. 정규화하지 않음 |
| `reason_code` | string | `FOUND`가 아닐 때 필수 | 아래 「결측 표기」 |
| `evidence` | 배열 | `FOUND`일 때 1개 이상, 그 외 빈 배열 | 아래 「근거 위치」 |
| `notes` | string | 선택 | 모델이 남긴 설명. 판정에 쓰지 않음 |

### 상태값

| `status` | `result_status` 칼럼 | `value` | `reason_code` | 의미 |
|---|---|---|---|---|
| FOUND | OK | 필수 | null | 문서에서 값을 찾음 |
| NOT_FOUND | OK | null | NOT_IN_DOCUMENT | 추출은 끝났고 문서에 해당 내용이 없음. 「고지 없음」 판정의 입력 |
| UNDETERMINED | UNDETERMINED | null | AMBIGUOUS, SOURCE_SECTION_MISSING | 읽었으나 하나로 정하지 못함, 또는 출처 절이 추출되지 않음 |
| NOT_APPLICABLE | NOT_APPLICABLE | null | OUT_OF_SCOPE | 문서 종류·상품 유형상 이 필드의 대상이 아님 |
| FAILED | FAILED | null | CALL_FAILED, PARSE_FAILED, SCHEMA_INVALID, EVIDENCE_NOT_LOCATED | 호출·파싱·계약 검증·근거 위치 변환 실패. 재호출 대상 |

- `result_status = PENDING`은 계획 행. `value_json`은 NULL
- 「문서에 값이 없음」은 `OK` + `NOT_FOUND`로 둠(10월 24일 제안). 채점의 파트 A 「없음 = OK·raw_score 0」([데이터 테이블·ERD 설계](data-model.md) 「두 파트 출력의 저장 계약」)과 같은 방식이고, DDL의 「OK이면 `value_json` 필수」 제약을 만족함. enum 변경 없음. [데이터 테이블·ERD 설계](data-model.md) 「미결」의 「없음」 결과 행은 이 결정으로 닫음
- 적재 검증: `status`와 `result_status`의 대응이 위 표와 같음. `FOUND`면 `value`·`evidence` 있음, 아니면 `value` null·`evidence` 빈 배열. `reason_code`는 표의 목록 안

### 결측 표기

| `reason_code` | 상태 | 뜻 | 재호출 |
|---|---|---|---|
| NOT_IN_DOCUMENT | NOT_FOUND | 출처 절을 읽었고 해당 내용이 없음 | 안 함 |
| SOURCE_SECTION_MISSING | UNDETERMINED | 출처 절이 `SECTION_BOUNDARY_NOT_FOUND`이거나 입력에 없음 | 안 함(재추출 뒤 새 입력) |
| AMBIGUOUS | UNDETERMINED | 서로 다른 값이 여러 곳에 있어 하나로 못 정함. 후보는 `notes`에 | 안 함 |
| OUT_OF_SCOPE | NOT_APPLICABLE | 필드 대상 아님(예: ETF에 판매사 필드) | 안 함 |
| CALL_FAILED | FAILED | API 오류·시간 초과 | 함 |
| PARSE_FAILED | FAILED | 응답이 JSON이 아님 | 함 |
| SCHEMA_INVALID | FAILED | envelope·필드 구조 검증 실패 | 함 |
| EVIDENCE_NOT_LOCATED | FAILED | `quote`를 절 텍스트에서 찾지 못함 | 함 |

- 「추출 실패」(FAILED·UNDETERMINED)를 「문서에 없음」(NOT_FOUND)으로 계산하지 않음. 채점은 NOT_FOUND만 「고지 없음」으로 봄
- 재호출 생략 조건은 [원본 보관 규칙](storage-and-failure-rules.md) 「LLM 호출 저장」 그대로. NOT_FOUND·UNDETERMINED·NOT_APPLICABLE은 같은 입력·프롬프트·모델이면 재사용

### 값 표기 공통 규칙

- `raw_text`: 모델이 값으로 읽은 원문 구간 그대로. 공백·기호 정리 금지
- 숫자: `{"amount": 1.5, "unit": "%"}`. 단위 없는 숫자 금지. 통화 단위는 `KRW`. 원문 표기는 `raw_text`
- 날짜: `YYYY-MM-DD`
- 목록·중첩 구조(수수료 등): 배열·객체 유지. 단일 문자열·실수로 평탄화하지 않음
- 적용 클래스: `applies_to`(클래스 이름 배열, 전체 적용이면 null)
- `value`의 구조 자체는 필드별 정의

### 근거 위치

- `evidence[{"section_id", "char_start", "char_end", "quote"}]`. 여러 구간 허용, 첫 항목이 대표 구간이고 칼럼 3개에 복사
- 범위는 그 절의 파서 버전이 만든 canonical text 기준 Unicode code point 반열린 구간, 절 범위 안([데이터 테이블·ERD 설계](data-model.md) 「적재 검증 규칙」 15)
- 모델은 `quote`(원문 인용)와 절을 돌려주고, 변환기가 절 텍스트에서 위치를 찾아 `char_start`·`char_end`를 채움. `quote` = canonical text의 그 구간. 못 찾으면 FAILED(EVIDENCE_NOT_LOCATED)
- 표지(HTML) 출처 필드의 근거 형식은 필드별 정의에서 정함(「미결」)

### 입력 참조 (`request.json`)

| 키 | 내용 |
|---|---|
| `document_id`, `field_name`, `attempt_no` | `llm_field_extraction` 유일키 |
| `prompt_id`, `prompt_sha256`, `model_name`, `model_params` | 프롬프트 설정 파일 식별과 모델 파라미터. 해시 규칙은 칼럼과 같음 |
| `inputs[]` | `{raw_object_id, raw_sha256, parser_version, section_ids 또는 char 범위}`. 잇는 순서가 곧 텍스트 순서 |
| `input_text` | 보낸 문서 텍스트. `inputs` 순서로 빈 줄 하나(`\n\n`)로 이음 |
| `input_sha256` | `input_text`의 UTF-8/LF 바이트 sha256. 정규화 없음 |

- 해시 규칙과 재호출 생략 조건은 [원본 보관 규칙](storage-and-failure-rules.md) 「LLM 호출 저장」
- 작성기준일 같은 문서 칼럼 값은 프롬프트 템플릿 변수로 넣을 수 있고 `input_text`에 넣지 않음(템플릿 제외 규칙)

### 예시

필드 이름은 예시용. 6필드 이름은 10월 28일 확정.

`request.json`

```json
{
  "document_id": 123,
  "field_name": "principal_loss_notice",
  "attempt_no": 1,
  "prompt_id": "principal_loss_notice:v1",
  "prompt_sha256": "…64자…",
  "model_name": "claude-sonnet-5-5",
  "model_params": {"temperature": 0},
  "inputs": [
    {"raw_object_id": 456, "raw_sha256": "…64자…", "parser_version": "pdfplumber-0.11_prep-8", "section_ids": [7891, 7892]}
  ],
  "input_text": "…절 7891 텍스트…\n\n…절 7892 텍스트…",
  "input_sha256": "…64자…"
}
```

`value_json` — 값 있음

```json
{
  "contract_version": 1,
  "field_name": "principal_loss_notice",
  "status": "FOUND",
  "value": {"present": true},
  "raw_text": "투자원금의 손실이 발생할 수 있으며",
  "reason_code": null,
  "evidence": [
    {"section_id": 7891, "char_start": 1204, "char_end": 1223, "quote": "투자원금의 손실이 발생할 수 있으며"}
  ],
  "notes": null
}
```

`value_json` — 문서에 없음

```json
{
  "contract_version": 1,
  "field_name": "principal_loss_notice",
  "status": "NOT_FOUND",
  "value": null,
  "raw_text": null,
  "reason_code": "NOT_IN_DOCUMENT",
  "evidence": [],
  "notes": null
}
```

`value_json` — 미적용

```json
{
  "contract_version": 1,
  "field_name": "distributor_names",
  "status": "NOT_APPLICABLE",
  "value": null,
  "raw_text": null,
  "reason_code": "OUT_OF_SCOPE",
  "evidence": [],
  "notes": "ETF는 판매사 목록을 적지 않음"
}
```

`value_json` — 판정 불가

```json
{
  "contract_version": 1,
  "field_name": "risk_grade",
  "status": "UNDETERMINED",
  "value": null,
  "raw_text": null,
  "reason_code": "AMBIGUOUS",
  "evidence": [],
  "notes": "표지 3등급, 본문 4등급"
}
```

`value_json` — 실패

```json
{
  "contract_version": 1,
  "field_name": "fee_structure",
  "status": "FAILED",
  "value": null,
  "raw_text": null,
  "reason_code": "PARSE_FAILED",
  "evidence": [],
  "notes": "응답이 JSON이 아님. 원응답은 response.json"
}
```

### 미결

| 질문 | 결정 주체 | 필요 시점 |
|---|---|---|
| 「없음」 = `OK` + `NOT_FOUND` 채택 | PM(대현) | [데이터 테이블·ERD 설계](data-model.md) 「미결」 행을 닫을 때 |
| 표지(HTML) 출처 필드의 근거 형식 | 필드별 정의 | 6필드 확정(10월 28일) 뒤 |
| 6필드 이름·`value` 구조·출처 절 | 분석·리서치(민석)·데이터 사이언스(다빈) → 데이터 엔지니어링·인프라(주영) | 10월 28일 |
| 프롬프트 설정 파일 위치·버전 규칙 | 데이터 엔지니어링·인프라(주영) | 추출 모듈 구현 때 |

## CDI 출력 요구

- 두 파트 출력: 09-29 팀 논의 결론, 9차 미팅(09-30) 확정
  - 문서 1건의 CDI 결과를 파트 A와 파트 B 두 출력으로 냄. 한 숫자로 합산하지 않음
  - 파트 A(고지 점검) = 축 4 고지 충실도. 금융소비자보호법(금소법) 19조 항목별 판정
    - 항목마다 item_key, status(있음/없음/판정 불가, 적용 대상 아님은 따로), 근거 위치(절·문자 범위), 감점 표현 후보와 그 위치
    - 합산 점수·백분위 없음
  - 파트 B(읽기 난이도) = 파일럿 전 축 1 언어 복잡도·축 2 용어 부담 합산(10-04). 축 3 구조 접근성은 파일럿 뒤 새 버전에서 다시 넣음
    - 그 버전의 축 각각의 원값·[0,1] 변환값, 가중 합산값, 같은 상품군 × 위험등급 층 안 백분위, 고칠 곳의 위치
    - 가중치 값은 11-12 원점수 산출 전 다빈 제안·팀 승인(9차 미팅). 파일럿 전 출발점은 축 1·2 각 1/2. 출력에 파트 B 지표 버전(metric_key)과 가중치 버전을 함께 기록
    - 축 하나라도 판정 불가이면 합산값과 백분위도 판정 불가(「결과 상태와 결측」 「축 안 결측」). 그 버전에 없는 축은 결측이 아님
    - 그 버전에 없는 축(파일럿 전 축 3)은 axes에 남기고 status `NOT_IN_VERSION`으로 표시. 출력 전용 값이며 score 행은 만들지 않음. 출력 모양을 버전과 무관하게 유지하기 위함
    - 2-1·2-2에는 사전에 없는 단어(미분류)의 종류 수·목록·사전 버전을 함께 기록. 미분류는 2-1 분모에만 들어감
  - 작성기준 항목 점검(10-02 변수표) = 파트 A 옆 별도 출력, 파트 B에 합산하지 않음
    - 투자설명서: 작성기준 17~22장 항목 중 있는 개수와 못 찾은 항목명(3-1a), 표지 다음 페이지 유의사항 위치 준수(3-1b-①, 작성기준 17-1-6), 작성기준 조문 순서와 다른 항목명(3-1b-②, 점수 아닌 메모)
    - 간이투자설명서: 작성기준 제25장 21개 항목 중 있는 개수, 자리·순서가 작성기준과 다른 항목명(간이 3-1a·3-1b)
    - 해당 없는 항목은 사유와 함께 따로 표시하고 누락으로 세지 않음. 비교한 작성기준 판(시행일)을 함께 기록
    - 펀드에 간이투자설명서 대표가 없으면 간이 점검만 판정 불가(SUMMARY_NOT_FOUND). 파트 A·B는 그대로 냄
  - 산식·검증: [점수 저장과 비교 모집단](scoring-and-population.md) 「CDI와 고지 충실도」·「검증」
- 결과 상태 5종 × 정규화 상태 3종 조합을 API가 `score: number|null`로 합치면 0/계산 불가/해당 없음 구분 불가
- 응답 envelope에 status·reason 필수. 파트 A 항목과 파트 B 각 값에 모두 적용
- 응답 envelope 제안(backend 관점, 승인 아님). 09-29 결론에 맞춰 두 파트 구조로 갱신

```json
{
  "part_a_disclosure": {
    "items": [
      {
        "item_key": "disclosure_item_07",
        "status": "MET | UNMET | NOT_APPLICABLE | UNDETERMINED",
        "reason": "...",
        "evidence": [{"quote": "...", "section_id": 0, "char_start": 0, "char_end": 0}],
        "penalty_phrases": [{"phrase": "...", "section_id": 0, "char_start": 0, "char_end": 0}]
      }
    ]
  },
  "part_b_readability": {
    "axes": [
      {"axis": 1, "result": {"status": "...", "value": null, "reason": "..."}, "transformed": null},
      {"axis": 2, "result": {"status": "...", "value": null, "reason": "..."}, "transformed": null},
      {"axis": 3, "result": {"status": "NOT_IN_VERSION", "value": null, "reason": "파일럿 전 버전에는 축 3 없음"}, "transformed": null}
    ],
    "metric_key": "...",
    "weights_version": "...",
    "result": {"status": "...", "value": null, "reason": "..."},
    "normalization": {
      "status": "...", "percentile": null, "reason": "...",
      "population": {"key": "...", "member_count": 0, "minimum_required": 30}
    },
    "fix_locations": [{"axis": 1, "quote": "...", "section_id": 0, "char_start": 0, "char_end": 0}]
  },
  "drafting_standard_check": {
    "prospectus": {
      "standard_effective_date": "...",
      "result": {"status": "...", "found": 0, "required": 0, "reason": "..."},
      "missing_items": ["..."],
      "position_check": {"status": "MET | UNMET | UNDETERMINED", "item": "투자결정시 유의사항(표지 다음 페이지)", "reason": "..."},
      "order_differs_items": ["..."],
      "not_applicable_items": [{"item": "...", "reason": "..."}]
    },
    "summary_prospectus": {
      "standard_effective_date": "...",
      "result": {"status": "...", "found": 0, "required": 21, "reason": "..."},
      "missing_items": ["..."],
      "order_differs_items": ["..."],
      "not_applicable_items": [{"item": "...", "reason": "..."}]
    }
  }
}
```

- 예시의 `disclosure_item_07`은 이름 형식 예시. 실제 item_key 목록은 금소법 19조 항목 확정 뒤 정함
- `drafting_standard_check`는 10-02 변수표의 작성기준 항목 점검(3-1a, 3-1b-① 위치 준수와 3-1b-② 순서 메모, 간이 3-1a·3-1b)을 담는 자리. `order_differs_items`는 점수가 아닌 메모. 필드 이름은 제안이며 확정 형식이 아님
- 예시의 `evidence`·`penalty_phrases`·`fix_locations` 위치 형식(section_id, char_start, char_end)은 결정 요청 B11 안 1로 확정(10월 3일, [데이터 테이블·ERD 설계](data-model.md) 「두 파트 출력의 저장 계약」). 필드 이름(`evidence`·`penalty_phrases`·`fix_locations`)은 제안이며 확정 형식이 아님
- 상태 정의: [점수 저장과 비교 모집단](scoring-and-population.md) 「결과 상태와 결측」
- 식별자
  - 공개 가능: document_id, product_id, fund_key, distributor_id, section_id(v2.2: 키가 원본 파일 × 파서 버전이라 run 불필요)
  - run 파라미터 동반: run_id, metric_key
  - 내부 전용·노출 금지: score_id, target_key, raw_object_id, 파일 경로
  - 근거 구간은 서버가 `section_id` + char 범위 + 인용 텍스트로 해석해 전달(B11 안 1)
  - 규칙 정본: [스키마 명세](schema-catalog.md) 「공개 식별자 규칙」
- 출력 문구: 확인 가능한 사실로만 씀. 「제재 가능성」 같은 추정 표현 대신 「19조 N번 항목을 문서에서 찾지 못함」(09-29 팀 논의 결론, 9차 미팅(09-30) 확정)
- 승인 점수만 거르는 조회 계층(`is_official` ∧ `APPROVED`)과 서빙 API 계약: 09-30 결정 대기(검토 번호 B5, [데이터 테이블·ERD 설계](data-model.md) 「미결」)
- 기존 수집 API 명세(데이터 소스 명세)는 대시보드 서빙 계약이 아님. 드릴다운을 소비할 계약은 저장소에 없음

## 스키마에 먼저 들어간 모양

- 아래 4개는 v2(09-23)에서 데이터베이스 Schema에 먼저 들어감
- 3단계에서 확정·수정 대상. 현재 모양을 최종 계약으로 간주하지 않음

| 항목 | 현재 모양 | 정의 위치 |
|---|---|---|
| score_payload v2 | `contract_version`, `unit`, `items[{item_key,status,reason,evidence[{section_id,char_start,char_end}]}]`(v2.2: B11 안 1, member_id·block_id 제거), `applicable_count`, `assessed_count`, `coverage`, `preprocessing` | [점수 저장과 비교 모집단](scoring-and-population.md) 「고지 항목 판정」. 저장 계약은 항목별 score 행 기준으로 바뀜([데이터 테이블·ERD 설계](data-model.md) 「두 파트 출력의 저장 계약」 참조). 근거 위치는 B11 안 1로 확정되어 `evidence[{section_id,char_start,char_end}]` 형식만 씀(`member_id`는 쓰지 않음) |
| target_key | `{contract_version:3, target_type, anchor, selection_policy_version}`(v2.2: members 제거)의 정규 JSON SHA-256. run 안 재시도 멱등성 키, 공개 ID 아님 | [데이터 테이블·ERD 설계](data-model.md) 「절과 점수 대상」 |
| 구조 manifest | `{contract_version,raw_sha256,parser_version,canonical_text_sha256,structure_status,table_split_status,blocks,missing_regions}`(주요 필드. 전체는 데이터 처리 요구 명세 4-6) | [데이터 테이블·ERD 설계](data-model.md) 「원본·수집 시도·추출」 |
| 평가 protocol_manifest | 문서쌍·target_ids·문항/정답/채점기준·조건·반복·프롬프트·계획 응답 슬롯(evaluation 표는 v2.2에서 연기) | [데이터 테이블·ERD 설계](data-model.md) 「예약 계약(승인 뒤 추가)」 |

- 6관점 검토 지적: 미정 상태에서 3단계 계약을 스키마가 먼저 정함. 정규 JSON 규칙을 RFC 8785로 고정할지는 09-30 결정 대기(검토 번호 B7)

## 검증 설계 재검토 입력

- 상태: 이 절의 「분쟁 상품군의 CDI가 더 높은지 검정」과 판매사 단위 제재 대조는 09-29 결론으로 정답지 용도 폐기(09-29 팀 논의 결론, 9차 미팅(09-30) 확정). 남는 쓰임은 CDI 완성 뒤 외부 기준 변수로 비교만. 아래 내용은 판단 근거 기록으로 보존
- 현행 검증 설계: [점수 저장과 비교 모집단](scoring-and-population.md) 「검증」(축 4는 제재문 사건 단위, 파트 B는 사람 이해도 조사. 파일럿 전 파트 B는 축 1·2)

### 분쟁조정 라벨이 성립하지 않는 이유

- 상태: 09-29 결론으로 정답지 용도 폐기. 분쟁조정 결정문의 현행 용도는 고지 감점표 표현의 재료
- 09-14 공유 전제·팀 용어 사전의 검증 방법: 「분쟁 상품군의 CDI가 더 높은지 검정」
- 분쟁조정 결정문은 상품·판매사·운용사 모두 마스킹
  - 마스킹 기호 4종: `●` `○` `▣` `▤`
  - 표본: 결정문 8건 → 글 8개의 첨부 15건 전부 확인(1만~2만 4천 자)
  - 상품도 판매사도 붙일 수 없음 → 위 검정 성립하지 않음
- 더 근본적인 불일치: 분쟁조정은 대부분 사모펀드 투자제안서, 측정 대상은 공모 투자설명서
- 남은 가능성: 업종(증권·은행·보험·카드·손해보험)은 남음 → 판매 채널 유형 축으로 사용 가능. 채택 여부는 3단계 사안
- 본문에 남는 상품 유형(「전문투자형 사모투자신탁」 등)만으로 상품군 수준 대조가 가능한지 미확인
- 분쟁·제재 187건 전건 수동 확인을 전제로 한 라벨 200건 표본은 분쟁조정 187건을 수동으로도 붙일 수 없어 재설계 필요([매칭 규칙](matching-rules.md) 「라벨 200건 표본 요건」)
- 근거: [조인 키 확인 기록](records/phase1-erd/join-key-checks.md) 「분쟁조정 마스킹」

### 제재공시 = 판매사 단위 신호

- 상태: 09-29 결론으로 정답지 용도 폐기. 남는 쓰임은 CDI 완성 뒤 외부 기준 변수로 비교만(제재 종류 좁힘·2021년 이후·판매사 규모 통제). 제재문의 현행 용도는 축 4 사건 단위 검증. 검증 자료인지 기준인지는 확인대기(9차 미팅): 분석·리서치(민석), 2026-10-04
- 제재공시는 판매사명 실명(`finInstName`), 상품명 마스킹(`㉮펀드`)
- CDI를 상품에 붙이는 축과 제재를 판매사에 붙이는 축은 층이 다름. 검증 설계에서 같은 축으로 두지 않음
- 경영유의사항 API: 판매사 단위 라벨 후보. 상품에는 붙지 않으므로 「CDI 평균이 높은 판매사가 조치를 많이 받는다」 형태의 약한 대조
- 근거: [조인 키 확인 기록](records/phase1-erd/join-key-checks.md) 「제재공시」

### 제재공시 기반 분석의 형태 (09-20 기록)

- 상태: 09-29 결론으로 정답지 용도 폐기. 남는 쓰임은 CDI 완성 뒤 외부 기준 변수로 비교만. 아래 설계와 위험 표는 기록으로 보존
- 폐기 사유 4가지(09-29): 제재 사유 대부분이 설명서와 무관, 펀드 설명서 작성 주체는 판매사가 아니라 운용사, 제재가 대형사에 편중, 게시판 자료가 2000년부터라 CDI 기준일과 시기 불일치. 같은 표로 보정하고 검정하면 순환

- 성립하는 형태: 상품·절 단위 CDI를 판매사 단위로 재집계(판매사가 파는 펀드들의 CDI 중앙값 등) → 제재 이력과의 연관을 보는 판매사 단위 탐색 분석
- 적합한 방법: 비모수 검정(Mann-Whitney U), 제재 건수를 종속변수로 한 포아송·음이항 회귀(표본이 작고 치우칠 것으로 예상)
- 결론: 상품 수준 검정을 판매사 수준 약한 연관 분석으로 낮춤. 인과가 아닌 탐색적 신호로만 보고

| # | 주의할 점 | 내용 |
|---|---|---|
| 1 | 생태학적 오류 | 판매사 수준 상관을 「CDI 높은 상품이 문제」로 확장 불가. 보고서에 「판매사 단위 신호」 명시 |
| 2 | ETF 제외 | 09-20 기록: 판매사별 펀드 소스가 ETF 0건이라 판매사 집계 불가. 09-22 정정: 은행 채널만 0건, 증권사 6건 → [확인 필요: ETF 판매사 축 결론 재작성] |
| 3 | 의사 반복(pseudo-replication) | 한 펀드가 여러 판매사에 걸려 같은 CDI가 여러 판매사 평균에 중복 반영. 판매사 간 독립성이 깨져 단순 p값 과신 금지 |
| 4 | 시간 순서 | 제재는 `actReqDate` 시점 사건, CDI는 `baseline_date` 스냅숏. 제재 이전의 CDI를 봐야 해석 성립 |
| 5 | 개념적 거리 | 제재 사유에 구두 설명 문제 등 문서와 무관한 것이 많음. CDI와 제재의 이론적 연결이 약하다는 점을 해석에 명시 |
| 6 | 선택편향 | 외은지점·저축은행은 판매사 표에 없음. 「매칭 실패」가 아니라 「대상 외」로 분류해야 실패율이 실제보다 크게 나오지 않음. 게시판 전체 중 자산운용 업권 건수 미확인 → 표본 크기 사전 계산 필요 |

## 미결

| 질문 | 결정 주체 | 필요 시점 |
|---|---|---|
| LLM 6필드의 이름·타입·출처 절 | 민석·다빈 정의표 → 주영 인계 | 정의표 2026-09-30, JSON 2026-10-14 |
| 판매사별 라벨 표(제재공시 기반)의 재료: API 확보 8건으로는 표 불성립. 게시판 경로(2000년 이후 5,735건) 사용 또는 금감원에 API 노출 범위 확인. 09-29 결론으로 라벨 표는 정답지로 쓰지 않음. 게시판 경로는 축 4 검증용 정찰(10~20건)로 용도 변경. 정찰은 데이터 엔지니어링·인프라(주영), 2026-10-04(9차 미팅) | 민석 | 2026-10-07 이전 |
| 제재공시 게시판 전수: 09-14 공유 전제 5,727건 vs 티켓 메모·현황표 5,735건. 조회일 확인 후 다르면 날짜 병기 | 대현·주영 | 2026-10-07 이전 |
| CDI 검증 방법: 「분쟁 상품군 CDI 검정」 폐기와 대체 확정. 09-29 팀 논의 결론, 9차 미팅(09-30) 확정: 정답지 용도 폐기, 축 1~3은 사람·LLM 평가, 축 4는 제재문 사건 단위 검증(제재문 역할은 확인대기: 분석·리서치(민석), 2026-10-04). 정찰은 데이터 엔지니어링·인프라(주영), 2026-10-04(9차 미팅). 남은 것은 정찰 결과와 대조군 선정 기준([점수 저장과 비교 모집단](scoring-and-population.md) 「미결」) | 다빈 | 2026-10-14 |
| 경영유의사항 API를 판매사 단위 라벨 후보로 채택할지. 09-20 안건 결과 기록 없음. 09-29 결론으로 판매사 단위 라벨은 정답지로 쓰지 않으므로 이 용도의 채택 이유가 약해짐 | 팀 / 09-20 회의록 확인 | 2026-09-30 |
| 분쟁조정 업종 정보를 판매 채널 유형 축으로 쓸지 | 다빈 | 2026-10-14 |
| CDI 출력 응답 envelope 채택 여부 | 팀 (서빙 계약 결정과 함께, 검토 번호 B5) | 2026-10-14 |

## 참고

- 제재 API 과거 조회 0건 응답과 미확정 커버리지(최근 24개월 중 2026-09만 8건): [소스별 데이터 현황표](records/phase1-erd/source-profile.md) 「제재 API 과거 조회와 미확정 커버리지」
- 제재공시 인터페이스·결과 필드 13개: [데이터 소스 수집 명세](data-sources.md)
- 스키마: [데이터 테이블·ERD 설계](data-model.md), [스키마 명세](schema-catalog.md)
