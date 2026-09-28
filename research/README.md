# 원천 데이터 검증 스크립트와 표본

설계 단계에서 원천 데이터를 직접 호출해 확인할 때 쓴 조사용 스크립트와 그 결과 표본 CSV. 생산 수집 코드는 `src/signal_pipeline/`에 있음.

## 실행 규칙

| 규칙 | 내용 |
|---|---|
| 실행 위치 | 저장소 루트. 명령의 경로는 모두 루트 기준 |
| 인증키 | 현재 작업 폴더의 `.env`에서 읽음(루트에서 실행해야 함). 키 값은 커밋하지 않음(`.gitignore`), 이름만 `.env.example`에 |
| 표본 CSV 위치 | `research/samples/` |
| 스크립트 간 의존 | `hwp_text.py`는 같은 폴더의 `_ole.py`를 import, `fetch_fss_dispute.py`는 같은 폴더의 `hwp_text.py`를 실행. 10개를 같은 폴더에 둬야 동작 |
| 재시도·호출 간격 | 조사 스크립트 공통 재시도 3회(대기 2초·4초), 호출 간격 1초 이상. 생산 수집 계약(최대 5회)과 다름. 근거는 [데이터 소스 수집 명세](../docs/data-sources.md) 「공통 수집 규칙」 |

## 스크립트

| 스크립트 | 용도 | 필요한 키·도구 | 근거 기록 |
|---|---|---|---|
| [`fetch_kofia_ann.py`](scripts/fetch_kofia_ann.py) | 금투협 전자공시 펀드공시검색 조회(XML 출력) | 없음. `curl` 필요 | [금투협 중복 행·ETF 이름 규칙 검증](../docs/records/phase1-erd/kofia-rows-and-etf-rule.md) 「검증 1: 금투협 중복 행」 |
| [`parse_kofia_ann.py`](scripts/parse_kofia_ann.py) | 응답 XML을 행 CSV로 풀고 자연키 묶음 분포 출력 | 없음 | 같은 곳 |
| [`kofia_attachments.py`](scripts/kofia_attachments.py) | 수시공시 첨부 조회·다운로드. 한 묶음의 행들이 같은 파일을 가리키는지 비교 | 없음. `curl` 필요 | 같은 문서 「첨부 해시 비교」 |
| [`fetch_kofia_sales.py`](scripts/fetch_kofia_sales.py) | 판매회사 마스터와 판매사별 펀드 목록. 판매관계 브릿지 입력 | 없음. `curl` 필요 | [조인 키 확인 기록](../docs/records/phase1-erd/join-key-checks.md) 「판매회사 명단 소스」 |
| [`verify_etf_rule.py`](scripts/verify_etf_rule.py) | ETF 「상장지수」 이름 규칙의 누락·오탐률 대조 | `DATA_GO_KR_API_KEY`, `KRX_API_KEY`(서비스 승인 포함) | [금투협 중복 행·ETF 이름 규칙 검증](../docs/records/phase1-erd/kofia-rows-and-etf-rule.md) 「검증 2: ETF 이름 규칙」 |
| [`fetch_fss_sanctions.py`](scripts/fetch_fss_sanctions.py) | 금감원 검사결과제재·경영유의사항 공시 조회 | `FSS_API_KEY`(개인 키 일일 30회 한도) | [조인 키 확인 기록](../docs/records/phase1-erd/join-key-checks.md) 「제재공시」 |
| [`fetch_fss_dispute.py`](scripts/fetch_fss_dispute.py) | 금감원 분쟁조정결정례 게시판 목록·첨부 수집 | 없음 | 같은 문서 「분쟁조정 마스킹」 |
| [`hwp_text.py`](scripts/hwp_text.py) | HWP 5.0 본문 추출(외부 의존성 없음). HWP 3.0은 읽지 못함 | 없음 | 같은 문서 「분쟁조정 마스킹」 |
| [`_ole.py`](scripts/_ole.py) | OLE 복합문서 판독(`hwp_text.py` 내부 모듈) | 없음 | — |
| [`dart_sections.py`](scripts/dart_sections.py) | DART 본문 PDF를 부·절 단위로 분할 | `pdftotext`(poppler) | [DART 본문 PDF 부·절 분할 실현성 검증](../docs/records/phase1-erd/dart-section-split.md) |

- 호출 형식·응답 코드는 [데이터 소스 수집 명세](../docs/data-sources.md)가 소유 문서. 스크립트 주석은 그 절을 가리킴

## 표본

| 파일 | 행 수 | 수집일 | 출처 | 근거 기록 |
|---|---|---|---|---|
| [`kofia_mgmt_codes.csv`](samples/kofia_mgmt_codes.csv) | 538 (원본 536건 + 09-22 별칭 2행) | 2026-09-14 추출, 09-22 보강 | 금투협 공지 첨부 양식의 부속 시트(운용사 코드 3자리, 운용사명, 단축명, 변경전 운용사명). 공식 마스터가 아니라 갱신 주기 미확인 | [상품·법인 매칭 규칙](../docs/matching-rules.md) 「법인명 정규화」 |
| [`kofia_ann_sample.csv`](samples/kofia_ann_sample.csv) | 1,499 | 2026-09-19 | 금투협 펀드공시 2026-08-13~15 조회 | [금투협 중복 행·ETF 이름 규칙 검증](../docs/records/phase1-erd/kofia-rows-and-etf-rule.md) 「표본」 |
| [`kofia_pdf_hash_check.csv`](samples/kofia_pdf_hash_check.csv) | 4 | 2026-09-19 | 금투협 공고 묶음 4개(운용사 4곳, 14~15행)의 첨부 sha256 비교 | 같은 문서 「첨부 해시 비교」 |
| [`kofia_sales_companies.csv`](samples/kofia_sales_companies.csv) | 200 | 2026-09-22 저장소 추가 | 금투협 판매회사 마스터(`saleCompCd` 6자리, 한글 법인명) | [조인 키 확인 기록](../docs/records/phase1-erd/join-key-checks.md) 「판매회사 명단 소스」 |
| [`etf_rule_check.csv`](samples/etf_rule_check.csv) | 1,602 | 2026-09-19 (기준일 차 4건 09-20) | 공공데이터포털 183,649건 × KRX 1,167건 대조. 일치 938 / 매칭 실패 229 / 오탐 후보 435 | [금투협 중복 행·ETF 이름 규칙 검증](../docs/records/phase1-erd/kofia-rows-and-etf-rule.md) 「검증 2: ETF 이름 규칙」 |
| [`dart_sections_sample.csv`](samples/dart_sections_sample.csv) | 294 | 2026-09-20 | DART 투자설명서 9건의 부·절 분해. 절 적중 292/294 | [DART 본문 PDF 부·절 분할 실현성 검증](../docs/records/phase1-erd/dart-section-split.md) 「표본」 |
| [`fss_dispute_sample.csv`](samples/fss_dispute_sample.csv) | 15 | 2026-09-20 | 분쟁조정결정례 글 8개의 첨부 15건 메타와 추출 결과 | [조인 키 확인 기록](../docs/records/phase1-erd/join-key-checks.md) 「분쟁조정 마스킹」 |
| [`fss_sanctions_sample.csv`](samples/fss_sanctions_sample.csv) | 8 | 2026-09-22 | 금감원 제재공시 2026-09 한 달분 전량(원천 13필드) | [소스별 데이터 현황표](../docs/records/phase1-erd/source-profile.md) 「재현과 표본 파일」 |
| [`fss_sanctions_match_result.csv`](samples/fss_sanctions_match_result.csv) | 8 | 2026-09-22 | 위 8건을 판매회사 마스터 200곳에 이름으로 붙인 결과. 매칭성공 4 / 대상외 4 / 매칭실패 0 | 같은 곳, [상품·법인 매칭 규칙](../docs/matching-rules.md) 「제재공시 법인 매칭」 |

- 행 수는 머리행 제외
- `kofia_mgmt_codes.csv`에서 `mgmt_code` `240`·`223`은 두 번씩 나옴. `former_name → mgmt_name` 조회용으로만 사용하고, `mgmt_code`를 기본키로 쓰려면 행을 합친 뒤 사용
- `fss_sanctions_sample.csv` 본문에는 `u2018`·`u2019` 같은 글자 그대로의 이스케이프 코드와 줄바꿈 자리의 `n`이 들어 있음. 원천 응답 그대로이며 치환하지 않음

## 예시 명령

저장소 루트에서 실행:

```bash
# 금투협 공시 3일치 → 행 CSV
python3 research/scripts/fetch_kofia_ann.py 20260813 20260815 | python3 research/scripts/parse_kofia_ann.py > out.csv

# ETF 이름 규칙 검증 (결과는 research/samples/etf_rule_check.csv)
python3 research/scripts/verify_etf_rule.py --base-date 20260904 --cache /tmp/funds.json

# 제재공시 한 달분
python3 research/scripts/fetch_fss_sanctions.py --from 2026-09-01 --to 2026-09-30 > s.csv

# DART 투자설명서 1건 부·절 구조
python3 research/scripts/dart_sections.py 20260911000067
```
