# 펀드·ETF 설명 리스크 대시보드 (`dashboard/`)

설계 정본: [대시보드 연결·내보내기 계약·3화면 와이어프레임](../docs/dashboard-design.md)

## 1. 의존성 분리 원칙

- 이 폴더의 의존성(`requirements.txt`)은 EC2 파이프라인 가상환경(`pyproject.toml`·`uv.lock`)과 분리한다.
- 로컬에서 실행할 때는 `uv run --with-requirements dashboard/requirements.txt`를 사용해 루트 가상환경을 건드리지 않는다.

## 2. 로컬 내보내기 파일 생성 (선착수 원천)

```bash
uv run --with-requirements dashboard/requirements.txt \
  python dashboard/build_exports.py \
  --residual-csv ../signal-data/exports/residual/axis4_residual__20261128.csv \
  --residual-json ../signal-data/exports/residual/axis4_residual__20261128.json \
  --judgments-csv ../signal-data/exports/runs/score-20261124T155900Z-7260/axis4_judgments.csv \
  --sanction-csv ../signal-data/exports/axis4_sanction/negative_control__20261125.csv \
  --out-root ../signal-data/exports/dashboard
```

- `build_exports.py`는 판정 CSV의 SHA-256을 잔차 요약 JSON과 대조하고, 펀드 묶음별 항목 상태 건수(있음·없음·판정 불가·적용 대상 아님) 불일치 0건을 검증한 뒤 `official.json`과 Parquet 파일을 생성한다.
- 공개 식별자 규칙에 따라 내부 ID(`score_id`, `target_key`, `raw_object_id`)와 로컬 파일 경로는 내보내기 파일에서 제외한다.

## 3. 로컬 실행

```bash
DASHBOARD_DATA_ROOT=../signal-data/exports/dashboard \
uv run --with-requirements dashboard/requirements.txt \
  streamlit run dashboard/app.py
```

## 4. Streamlit Community Cloud 배포 (S3 전환)

1. Streamlit Community Cloud 앱 설정에서 저장소 `BOAZ-Signal-Team-26/signal-pipeline`, 진입 파일 `dashboard/app.py`를 지정한다.
2. 앱 비밀값(Secrets)에 아래 키를 등록한다(`exports/*` 읽기 전용 IAM 사용자 키).

```toml
DASHBOARD_DATA_ROOT = "s3://<버킷명>/exports"
AWS_ACCESS_KEY_ID = "..."
AWS_SECRET_ACCESS_KEY = "..."
AWS_DEFAULT_REGION = "ap-northeast-2"
```

3. `dashboard/data_loader.py`가 `s3://` 접두어를 감지해 같은 `official.json`·Parquet 계약을 읽으므로 앱 코드를 수정할 필요가 없다.
