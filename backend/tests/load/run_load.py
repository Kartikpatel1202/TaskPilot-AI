"""Phase 6 controlled load test — LOCAL ONLY (loopback API, local fixture pages, local Redis db 15).

    cd backend
    python -m tests.load.run_load --profile all            # A=10, B=25, C=50 concurrent users
    python -m tests.load.run_load --profile A --iterations 5 --json out.json

What it measures (and what it does not)
  * A real uvicorn server on 127.0.0.1 with the deterministic MOCK planner (LLM latency is the mock's configured
    delay, NOT a real provider), SQLite file database (NOT PostgreSQL), in-process planning queue.
  * Per virtual user: one telemetry WebSocket held open + N x (POST /tasks -> poll until planned -> GET /task-history
    -> GET /health/ready). Reports p50/p95/p99 per endpoint, planning latency, API error rate, WS disconnects,
    process RSS / CPU of this process (server and client share it — see notes).
  * Browser: concurrent Chromium session startup and screenshot capture against a local fixture page.
  * Redis queue: enqueue -> reserve -> ack throughput and wait time on the local Redis (skipped if unavailable).
It never contacts a third-party website. Numbers are specific to this machine and run; never extrapolate them.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import ctypes
import json
import os
import platform
import socket
import sys
import tempfile
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import uvicorn
import websockets

PROFILES = {"A": 10, "B": 25, "C": 50}
TERMINAL_PLANNING = {"PLANNED", "NEEDS_CLARIFICATION", "FAILED", "CANCELLED", "COMPLETED"}


# ---------------------------------------------------------------------------- process stats (no psutil dependency)

def rss_mb() -> float | None:
    """Resident memory of THIS process (server + load clients share it)."""
    if sys.platform == "win32":
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        if k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
            return round(pmc.WorkingSetSize / 2**20, 1)
        return None
    try:
        import resource

        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    except Exception:  # noqa: BLE001
        return None


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, int(round(q / 100 * (len(ordered) - 1)))))
    return round(ordered[k] * 1000, 1)


def summary(values: list[float]) -> dict[str, Any]:
    return {"n": len(values), "p50_ms": pct(values, 50), "p95_ms": pct(values, 95), "p99_ms": pct(values, 99),
            "max_ms": round(max(values) * 1000, 1) if values else None}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------- server

class Server:
    def __init__(self, settings: Any) -> None:
        from app.main import create_app

        self.port = free_port()
        self.app = create_app(settings)
        self.server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="warning", ws="websockets"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> Server:
        self.thread.start()
        deadline = time.time() + 30
        while not self.server.started:
            if time.time() > deadline:
                raise RuntimeError("server did not start")
            time.sleep(0.05)
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=30)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}/api/v1"


# ---------------------------------------------------------------------------- API workload

async def virtual_user(base: str, iterations: int, lat: dict[str, list[float]], counters: dict[str, int]) -> None:
    sid = str(uuid4())
    ws_url = base.replace("http://", "ws://") + f"/ws/{sid}"
    ws = None
    try:
        t = time.perf_counter()
        ws = await websockets.connect(ws_url, open_timeout=10, origin="http://localhost:3000")  # type: ignore[arg-type]
        lat["ws_connect"].append(time.perf_counter() - t)
    except Exception:  # noqa: BLE001
        counters["ws_connect_failed"] += 1
    reader = asyncio.create_task(_drain(ws, counters)) if ws is not None else None
    async with httpx.AsyncClient(timeout=30, headers={"Origin": "http://localhost:3000"}) as client:
        for i in range(iterations):
            counters["requests"] += 1
            t = time.perf_counter()
            try:
                r = await client.post(f"{base}/tasks", json={"command": f"Open youtube.com and search for lofi music {i}", "session_id": sid,
                                                              "input_mode": "TEXT"})
            except httpx.HTTPError:
                counters["errors"] += 1
                continue
            lat["POST /tasks"].append(time.perf_counter() - t)
            if r.status_code >= 400:
                counters["errors"] += 1
                counters[f"status_{r.status_code}"] += 1
                continue
            task_id = r.json()["task_id"]
            started = time.perf_counter()
            state = None
            while time.perf_counter() - started < 60:
                counters["requests"] += 1
                t = time.perf_counter()
                g = await client.get(f"{base}/tasks/{task_id}")
                lat["GET /tasks/{id}"].append(time.perf_counter() - t)
                if g.status_code >= 400:
                    counters["errors"] += 1
                    break
                state = g.json()["state"]
                if state in TERMINAL_PLANNING:
                    break
                await asyncio.sleep(0.05)
            lat["planning (submit->planned)"].append(time.perf_counter() - started)
            counters[f"planned_state_{state}"] += 1
            for name, path in (("GET /task-history", f"/task-history?session_id={sid}&limit=20"), ("GET /health/ready", "/health/ready")):
                counters["requests"] += 1
                t = time.perf_counter()
                g = await client.get(base + path)
                lat[name].append(time.perf_counter() - t)
                if g.status_code >= 400:
                    counters["errors"] += 1
                    counters[f"status_{g.status_code}"] += 1
    if ws is not None:
        if ws.close_code is not None:
            counters["ws_disconnected_unexpectedly"] += 1
        await ws.close()
    if reader is not None:
        reader.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await reader


async def _drain(ws: Any, counters: dict[str, int]) -> None:
    with contextlib.suppress(Exception):
        async for _ in ws:
            counters["ws_messages"] += 1


async def api_profile(settings_factory: Any, users: int, iterations: int) -> dict[str, Any]:
    lat: dict[str, list[float]] = defaultdict(list)
    counters: dict[str, int] = defaultdict(int)
    with Server(settings_factory()) as srv:
        cpu0, wall0 = time.process_time(), time.perf_counter()
        rss_before = rss_mb()
        await asyncio.gather(*(virtual_user(srv.base, iterations, lat, counters) for _ in range(users)))
        wall = time.perf_counter() - wall0
        cpu = time.process_time() - cpu0
        rss_after = rss_mb()
    return {
        "users": users, "iterations_per_user": iterations, "wall_seconds": round(wall, 2),
        "throughput_req_per_s": round(counters["requests"] / wall, 1) if wall else None,
        "error_rate": round(counters["errors"] / max(1, counters["requests"]), 4),
        "counters": dict(counters),
        "latency": {k: summary(v) for k, v in lat.items()},
        "process_cpu_percent_of_one_core": round(100 * cpu / wall, 1) if wall else None,
        "rss_mb_before": rss_before, "rss_mb_after": rss_after,
    }


# ---------------------------------------------------------------------------- browser workload

async def browser_profile(settings_factory: Any, sessions: int) -> dict[str, Any]:
    from app.browser.manager import BrowserManager
    from tests.browser.conftest import RecordingTelemetry, make_guard
    from tests.conftest import _FixtureHandler

    import http.server

    fixture = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    threading.Thread(target=fixture.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{fixture.server_address[1]}"
    settings = settings_factory(browser_test_allowed_origins=origin, browser_dev_fixtures_enabled=True, browser_max_sessions=20)
    manager = BrowserManager(settings, guard=make_guard(origin), telemetry=RecordingTelemetry())  # type: ignore[arg-type]
    startup: list[float] = []
    shots: list[float] = []
    failures = 0

    async def one() -> None:
        nonlocal failures
        sid = uuid4()
        try:
            t = time.perf_counter()
            session = await manager.get_or_create_session(sid)
            await session.page.goto(f"{origin}/index.html")
            startup.append(time.perf_counter() - t)
            for _ in range(3):
                t = time.perf_counter()
                await session.page.screenshot(type="jpeg", quality=settings.browser_screenshot_quality)
                shots.append(time.perf_counter() - t)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print("browser failure:", type(exc).__name__, str(exc)[:160], file=sys.stderr)

    rss_before = rss_mb()
    t0 = time.perf_counter()
    try:
        await asyncio.gather(*(one() for _ in range(sessions)))
    finally:
        wall = time.perf_counter() - t0
        rss_peak = rss_mb()
        await manager.shutdown()
        fixture.shutdown()
    return {"concurrent_sessions": sessions, "failures": failures, "wall_seconds": round(wall, 2),
            "session_startup_incl_first_navigation": summary(startup), "screenshot_capture": summary(shots),
            "rss_mb_this_process_before": rss_before, "rss_mb_this_process_after": rss_peak,
            "note": "Chromium runs in child processes; their memory is not included in RSS above."}


# ---------------------------------------------------------------------------- redis queue workload

async def redis_profile(jobs: int, consumers: int) -> dict[str, Any]:
    from redis.asyncio import from_url

    from app.queue.base import Job
    from app.queue.redis_queue import RedisJobQueue

    url = os.environ.get("TASKPILOT_TEST_REDIS_URL", "redis://127.0.0.1:6379/15")
    r = from_url(url, decode_responses=True, socket_connect_timeout=5)
    try:
        await r.ping()
    except Exception as exc:  # noqa: BLE001
        return {"skipped": f"Redis unavailable at {url}: {type(exc).__name__}"}
    prefix = f"tp:load:{uuid4().hex[:8]}:"
    q = RedisJobQueue(r, "load", max_depth=jobs + 10, max_attempts=3, prefix=prefix)
    waits: list[float] = []
    t0 = time.perf_counter()
    for i in range(jobs):
        await q.enqueue(Job(kind="load", payload={"i": i}))
    enqueue_s = time.perf_counter() - t0
    done = 0

    async def consumer(n: int) -> None:
        nonlocal done
        wid = f"load-{n}"
        while done < jobs:
            got = await q.reserve(wid, timeout=0.2)
            if got is None:
                continue
            job, raw = got
            waits.append(time.time() - job.enqueued_at)
            await q.ack(wid, raw, job)
            done += 1

    t1 = time.perf_counter()
    await asyncio.wait_for(asyncio.gather(*(consumer(n) for n in range(consumers))), timeout=120)
    drain_s = time.perf_counter() - t1
    keys = [k async for k in r.scan_iter(f"{prefix}*")]
    if keys:
        await r.delete(*keys)
    await r.aclose()
    return {"jobs": jobs, "consumers": consumers, "enqueue_per_s": round(jobs / enqueue_s, 1), "drain_per_s": round(jobs / drain_s, 1),
            "queue_wait (enqueue->reserve)": summary(waits), "note": "Local Redis on the same machine; no network latency."}


# ---------------------------------------------------------------------------- main

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", choices=["A", "B", "C", "all"], default="all")
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--mock-latency-ms", type=int, default=350, help="Mock planner delay (the default config value).")
    parser.add_argument("--skip-browser", action="store_true")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    from app.config import Settings

    tmp = Path(tempfile.mkdtemp(prefix="taskpilot-load-"))

    def settings_factory(**overrides: Any) -> Settings:
        base: dict[str, Any] = {
            "app_env": "development", "log_level": "WARNING", "enable_demo_endpoints": False, "agent_provider": "mock",
            "agent_mock_latency_ms": args.mock_latency_ms, "database_url": f"sqlite+aiosqlite:///{(tmp / f'load-{uuid4().hex[:6]}.db').as_posix()}",
            "redis_url": "", "rate_limit_enabled": False, "websocket_max_connections": 200, "commerce_enabled": False,
            "integrations_enabled": False, "file_download_storage": str(tmp / "downloads"), "cors_origins": "http://localhost:3000",
        }
        base.update(overrides)
        return Settings(_env_file=None, **base)  # type: ignore[call-arg]

    selected = list(PROFILES) if args.profile == "all" else [args.profile]
    report: dict[str, Any] = {
        "machine": {"platform": platform.platform(), "python": platform.python_version(), "cpu_count": os.cpu_count()},
        "config": {"planner": "mock", "mock_latency_ms": args.mock_latency_ms, "database": "SQLite file", "iterations": args.iterations},
        "profiles": {},
    }
    for name in selected:
        users = PROFILES[name]
        print(f"== Profile {name}: {users} users", file=sys.stderr)
        entry: dict[str, Any] = {"api": asyncio.run(api_profile(settings_factory, users, args.iterations))}
        if not args.skip_browser:
            entry["browser"] = asyncio.run(browser_profile(settings_factory, min(users, 10)))
        entry["redis_queue"] = asyncio.run(redis_profile(jobs=users * 20, consumers=min(users, 8)))
        report["profiles"][name] = entry
    text = json.dumps(report, indent=2, default=str)
    print(text)
    if args.json:
        args.json.write_text(text, encoding="utf-8")
    with contextlib.suppress(Exception):
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
