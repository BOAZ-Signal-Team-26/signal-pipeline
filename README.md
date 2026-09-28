# signal-pipeline

BOAZ Signal Team의 「판매 중인 금융상품 설명서를 전수 채점해 설명 난독성 지도를 만드는 파이프라인」 저장소입니다. 생산 코드(수집·파싱·채점·추출)와 설계 문서, 원천 데이터 검증용 스크립트·표본 CSV를 함께 둡니다. 옛 이름은 `Signal-Pipeline-Design`이며, 옛 주소는 GitHub가 새 주소로 자동 연결합니다.

## 폴더 구조

| 폴더 | 담는 것 | 주 담당 |
|---|---|---|
| `src/signal_pipeline/common/` | 상태값 정의, 원본 경로 규칙, DB 모델 등 모든 모듈이 같이 쓰는 코드 | 대현 |
| `src/signal_pipeline/collectors/` | 소스별 수집기 (DART·공공데이터포털·KRX·금투협·금감원) | 주영 |
| `src/signal_pipeline/parsing/` | PDF 부·절 분해 | 주영·다빈 |
| `src/signal_pipeline/scoring/` | CDI 산식 (노트북에서 확정한 산식을 함수로 옮기는 곳) | 다빈 |
| `src/signal_pipeline/extraction/` | LLM 고지 항목 추출 | 민석 |
| `notebooks/` | 탐색·실측 노트북. 확정된 산식은 `scoring/`에서 import만 하고 복사하지 않음 | 다빈·민석 |
| `data-assets/` | 용어 사전, 감점표, 프롬프트, 검증 라벨 (파일 이름에 버전 표기) | 다빈·민석 |
| `docs/` | 설계 문서. 현행 설계는 `docs/` 바로 아래, 근거 기록은 `docs/records/` | 대현 |
| `research/` | 원천 데이터 검증 스크립트(`research/scripts/`)와 표본 CSV(`research/samples/`) | 대현 |

- 원본 PDF·파생 텍스트·실행 결과는 `raw/`, `derived/`, `runs/`에 두며 커밋하지 않습니다 (`.gitignore` 처리, 공개 저장소).
- 패키지 이름이 `signal`이 아니라 `signal_pipeline`인 이유: 파이썬 기본 모듈 `signal`과 이름이 같으면 import가 충돌합니다.

## 개발 환경

[uv](https://docs.astral.sh/uv/)가 필요합니다. 파이썬 버전은 `.python-version`(3.12)을 따르며 uv가 자동으로 설치합니다.

```bash
uv sync                      # 가상환경 생성, 패키지와 개발 도구 설치
uv run pre-commit install    # 커밋 전 검사 켜기 (저장소를 받은 뒤 1회)
cp .env.example .env         # API 키는 .env에만 적음
```

커밋할 때마다 아래 검사가 자동으로 돌아갑니다. PR에서도 같은 검사를 자동 검사(CI)로 한 번 더 합니다.

| 검사 | 걸리면 |
|---|---|
| 비밀 키 검사 (gitleaks) | 커밋 중단. 키를 지우고 다시 커밋 |
| 1MB 넘는 파일 | 커밋 중단. `raw/` 등 커밋하지 않는 폴더로 옮김 |
| 개인 키 파일 | 커밋 중단 |
| 노트북 셀 출력 (nbstripout) | 출력을 지운 뒤 커밋 중단. 다시 `git add` 후 커밋 |

## 설계 문서

- 읽는 순서, 설계 단계(1단계 9월 16일 / 2단계 9월 30일 / 3단계 10월 14일)와 상태, 현재 검토안(ERD v2.1, 20개 표·47개 관계), 표기 규칙: [docs/README.md](docs/README.md)
- 검증 스크립트·표본 CSV 안내: [research/README.md](research/README.md)
- 프로세스·WBS·스프린트 계획: [Project-Management](https://github.com/BOAZ-Signal-Team-26/Project-Management). 이 저장소는 「무엇을 어떻게 만들 것인가」만 다룹니다.
