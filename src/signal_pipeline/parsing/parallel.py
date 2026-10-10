"""파일 단위 병렬 실행. 작업마다 별도 프로세스를 띄워, 시간이 초과되면 그 프로세스를 종료한다.

스레드나 `subprocess.run(timeout)`은 파이썬 코드 안에서 멈춘 작업을 끝내지 못한다.
자식은 결과를 임시 파일에 쓰고 끝나며, 부모는 프로세스 종료만 기다린다. 파이프로 결과를 받으면
자식이 큰 결과를 보내다 멈췄을 때 부모가 수신에서 막혀 시간 제한을 검사하지 못하기 때문이다.
결과는 입력 순서대로 돌려준다(실행 기록 순서 고정).
"""

from __future__ import annotations

import multiprocessing as mp
import pickle
import tempfile
import time
from collections import deque
from collections.abc import Callable
from multiprocessing.connection import wait
from pathlib import Path
from typing import Any

START_METHOD = "spawn"  # macOS·Linux 공통으로 안전한 방식. 시험에서만 fork로 바꾼다


def _child(out: str, func: Callable[..., Any], args: tuple) -> None:
    try:
        result: tuple[str, Any] = ("ok", func(*args))
    except BaseException as exc:  # noqa: BLE001 — 자식의 어떤 오류도 부모에 전달
        result = ("error", f"{type(exc).__name__}: {exc}")
    tmp = Path(out + ".tmp")
    tmp.write_bytes(pickle.dumps(result))
    tmp.replace(out)  # 다 쓴 파일만 보이게 한다


def _collect(out: Path, exitcode: int | None) -> tuple[str, Any]:
    try:
        return pickle.loads(out.read_bytes())
    except (OSError, EOFError, pickle.UnpicklingError):
        return ("died", f"종료 코드 {exitcode}")


def run_isolated(
    func: Callable[..., Any],
    jobs: list[tuple],
    *,
    workers: int,
    timeout: float,
) -> list[tuple[str, Any]]:
    """`func(*job)`을 job마다 별도 프로세스로 실행(동시 `workers`개, 각 `timeout`초).

    입력 순서대로 (상태, 값). 상태 "ok"면 값은 반환값, "error"면 오류 문장,
    "timeout"이면 시간 초과, "died"면 결과 없이 프로세스가 끝난 경우(메모리 부족 등).
    """
    ctx = mp.get_context(START_METHOD)
    results: list[tuple[str, Any] | None] = [None] * len(jobs)
    pending = deque(range(len(jobs)))
    running: dict[int, tuple[int, Any, float, Path]] = {}  # sentinel → 작업
    with tempfile.TemporaryDirectory(prefix="run_isolated_") as tmp:
        while pending or running:
            while pending and len(running) < max(1, workers):
                index = pending.popleft()
                out = Path(tmp) / f"{index}.pkl"
                proc = ctx.Process(target=_child, args=(str(out), func, jobs[index]))
                proc.start()
                running[proc.sentinel] = (
                    index,
                    proc,
                    time.monotonic() + timeout,
                    out,
                )
            nearest = min(deadline for _, _, deadline, _ in running.values())
            for sentinel in wait(list(running), max(0.0, nearest - time.monotonic())):
                index, proc, _, out = running.pop(sentinel)
                proc.join()
                results[index] = _collect(out, proc.exitcode)
            now = time.monotonic()
            for sentinel, (index, proc, deadline, _) in list(running.items()):
                if deadline <= now:
                    del running[sentinel]
                    proc.kill()
                    proc.join()
                    results[index] = ("timeout", f"{timeout:g}초 시간 초과")
    return [r for r in results if r is not None]
