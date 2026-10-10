"""파일 단위 병렬 실행. 작업마다 별도 프로세스를 띄워, 시간이 초과되면 그 프로세스를 종료한다.

스레드나 `subprocess.run(timeout)`은 파이썬 코드 안에서 멈춘 작업을 끝내지 못한다.
결과는 입력 순서대로 돌려준다(실행 기록 순서 고정).
"""

from __future__ import annotations

import multiprocessing as mp
import time
from collections import deque
from collections.abc import Callable
from multiprocessing.connection import Connection, wait
from typing import Any

START_METHOD = "spawn"  # macOS·Linux 공통으로 안전한 방식. 시험에서만 fork로 바꾼다


def _child(conn: Connection, func: Callable[..., Any], args: tuple) -> None:
    try:
        conn.send(("ok", func(*args)))
    except BaseException as exc:  # noqa: BLE001 — 자식의 어떤 오류도 부모에 전달
        conn.send(("error", f"{type(exc).__name__}: {exc}"))
    finally:
        conn.close()


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
    running: dict[Connection, tuple[int, Any, float]] = {}
    while pending or running:
        while pending and len(running) < max(1, workers):
            index = pending.popleft()
            parent, child = ctx.Pipe(duplex=False)
            proc = ctx.Process(target=_child, args=(child, func, jobs[index]))
            proc.start()
            child.close()  # 부모 쪽 사본을 닫아야 자식이 끝날 때 EOF가 온다
            running[parent] = (index, proc, time.monotonic() + timeout)
        nearest = min(deadline for _, _, deadline in running.values())
        ready = wait(list(running), max(0.0, nearest - time.monotonic()))
        for conn in ready:
            index, proc, _ = running.pop(conn)
            try:
                results[index] = conn.recv()
            except EOFError:
                results[index] = ("died", f"종료 코드 {proc.exitcode}")
            conn.close()
            proc.join()
        now = time.monotonic()
        for conn, (index, proc, deadline) in list(running.items()):
            if deadline <= now:
                del running[conn]
                proc.kill()
                proc.join()
                conn.close()
                results[index] = ("timeout", f"{timeout:g}초 시간 초과")
    return [r for r in results if r is not None]
