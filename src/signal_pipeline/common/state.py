"""소스별 워터마크. 「어디까지 빠짐없이 받았는가」를 기록한다.

규칙(docs/storage-and-failure-rules.md 「재시도와 워터마크」)
- 구간 완전성 검증 뒤에만 전진한다. DART는 접수일(rcept_dt) 하루가 한 구간
- 다음 실행은 워터마크에서 룩백 일수만큼 거슬러 올라간 날부터 본다. DART 룩백 3일은 잠정값
  (같은 문서 「미결」. 룩백 구간에서 새로 발견된 문서 수를 기록해 확정 근거로 씀)
- 앞선 날로 되돌리지 않는다

위치: {RAW_ROOT}/state/{source}.json
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path


class Watermark:
    def __init__(self, raw_root: str | Path, source: str) -> None:
        self.source = source
        self.path = Path(raw_root) / "state" / f"{source}.json"

    def load(self) -> date | None:
        if not self.path.exists():
            return None
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return date.fromisoformat(data["rcept_dt"])

    def start_date(self, lookback_days: int) -> date | None:
        """워터마크가 없으면 None(첫 실행, 시작일은 호출하는 쪽이 정함)."""
        current = self.load()
        return current - timedelta(days=lookback_days) if current else None

    def advance(self, day: date, run_id: str) -> bool:
        """그날을 빠짐없이 받은 뒤에만 호출한다. 워터마크보다 앞선 날이면 바꾸지 않는다."""
        current = self.load()
        if current is not None and day <= current:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "source": self.source,
            "rcept_dt": day.isoformat(),
            "run_id": run_id,
            "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        temp = self.path.with_name(self.path.name + ".part")
        temp.write_text(
            json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        temp.replace(self.path)
        return True
