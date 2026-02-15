#!/usr/bin/env python3
"""
Load test for the async QASM3 task processing pipeline.

Submits N tasks concurrently, polls until completion, validates correctness,
and prints a summary report with throughput and latency metrics.

Usage:
    python3 tests/load/load_test.py --tasks 20 --concurrency 10
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import statistics
import sys
import time
from dataclasses import dataclass, field

import httpx

# ---------------------------------------------------------------------------
# Circuit variants (mixed workload)
# ---------------------------------------------------------------------------

CIRCUITS = {
    "small_1q_hadamard": (
        'OPENQASM 3;\ninclude "stdgates.inc";\nqubit[1] q;\nbit[1] c;\nh q[0];\nc[0] = measure q[0];'
    ),
    "medium_3q_ghz": (
        'OPENQASM 3;\ninclude "stdgates.inc";\nqubit[3] q;\nbit[3] c;\n'
        "h q[0];\ncx q[0], q[1];\ncx q[1], q[2];\n"
        "c[0] = measure q[0];\nc[1] = measure q[1];\nc[2] = measure q[2];"
    ),
    "large_5q_entangled": (
        'OPENQASM 3;\ninclude "stdgates.inc";\nqubit[5] q;\nbit[5] c;\n'
        "h q[0];\ncx q[0], q[1];\ncx q[1], q[2];\ncx q[2], q[3];\ncx q[3], q[4];\n"
        "h q[1];\nh q[3];\n"
        "c[0] = measure q[0];\nc[1] = measure q[1];\nc[2] = measure q[2];\n"
        "c[3] = measure q[3];\nc[4] = measure q[4];"
    ),
}

CIRCUIT_NAMES = list(CIRCUITS.keys())

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class TaskResult:
    task_id: str
    circuit: str
    submit_time: float  # epoch
    submit_latency: float  # seconds
    complete_time: float | None = None
    status: str = "pending"
    result: dict | None = None
    error: str | None = None

    @property
    def completion_time(self) -> float | None:
        if self.complete_time is None:
            return None
        return self.complete_time - self.submit_time


@dataclass
class LoadTestConfig:
    tasks: int = 20
    concurrency: int = 10
    base_url: str = "http://localhost:8000"
    timeout: int = 120
    shots: int = 1024
    poll_interval: float = 0.5


@dataclass
class LoadTestReport:
    results: list[TaskResult] = field(default_factory=list)
    submission_start: float = 0.0
    submission_end: float = 0.0
    wall_start: float = 0.0
    wall_end: float = 0.0


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


async def submit_task(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    circuit_name: str,
    qasm: str,
) -> TaskResult:
    async with sem:
        t0 = time.time()
        resp = await client.post("/tasks", json={"qc": qasm})
        latency = time.time() - t0

    resp.raise_for_status()
    body = resp.json()
    return TaskResult(
        task_id=body["task_id"],
        circuit=circuit_name,
        submit_time=t0,
        submit_latency=latency,
    )


async def poll_task(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    result: TaskResult,
    timeout: int,
    poll_interval: float,
) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            async with sem:
                resp = await client.get(f"/tasks/{result.task_id}")
            resp.raise_for_status()
        except (httpx.PoolTimeout, httpx.ConnectTimeout, httpx.ReadTimeout):
            await asyncio.sleep(poll_interval)
            continue

        body = resp.json()
        status = body.get("status")

        if status == "completed":
            result.status = "completed"
            result.result = body.get("result")
            result.complete_time = time.time()
            return
        elif status == "error":
            result.status = "failed"
            result.error = body.get("message", "unknown error")
            result.complete_time = time.time()
            return

        await asyncio.sleep(poll_interval)

    result.status = "timeout"
    result.complete_time = time.time()


async def run_load_test(cfg: LoadTestConfig) -> LoadTestReport:
    report = LoadTestReport()
    submit_sem = asyncio.Semaphore(cfg.concurrency)
    # Allow more concurrent polls than submissions, but cap to avoid pool exhaustion
    poll_sem = asyncio.Semaphore(min(cfg.tasks, 100))

    pool_limits = httpx.Limits(
        max_connections=200, max_keepalive_connections=50, keepalive_expiry=30
    )
    async with httpx.AsyncClient(
        base_url=cfg.base_url,
        timeout=httpx.Timeout(30.0, pool=60.0),
        limits=pool_limits,
    ) as client:
        # --- submission phase ---
        circuits = [random.choice(CIRCUIT_NAMES) for _ in range(cfg.tasks)]
        report.wall_start = report.submission_start = time.time()

        submit_coros = [
            submit_task(client, submit_sem, name, CIRCUITS[name]) for name in circuits
        ]
        report.results = await asyncio.gather(*submit_coros)
        report.submission_end = time.time()

        print(
            f"Submitted {len(report.results)} tasks in "
            f"{report.submission_end - report.submission_start:.2f}s"
        )

        # --- polling phase ---
        poll_coros = [
            poll_task(client, poll_sem, r, cfg.timeout, cfg.poll_interval)
            for r in report.results
        ]
        await asyncio.gather(*poll_coros)
        report.wall_end = time.time()

    return report


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_report(report: LoadTestReport, expected_shots: int) -> bool:
    results = report.results
    total = len(results)
    completed = [r for r in results if r.status == "completed"]
    failed = [r for r in results if r.status == "failed"]
    timed_out = [r for r in results if r.status == "timeout"]

    # correctness check
    correct = 0
    for r in completed:
        if r.result and sum(r.result.values()) == expected_shots:
            correct += 1

    completion_times = [
        r.completion_time for r in completed if r.completion_time is not None
    ]
    submit_lats = [r.submit_latency for r in results]

    sub_duration = report.submission_end - report.submission_start
    wall_duration = report.wall_end - report.wall_start
    throughput = len(completed) / wall_duration if wall_duration > 0 else 0

    print("\n=== Load Test Results ===")
    print(f"Tasks submitted:   {total}")
    print(f"Tasks completed:   {len(completed)}")
    print(f"Tasks failed:      {len(failed)}")
    print(f"Tasks timed out:   {len(timed_out)}")
    print(
        f"Correctness:       {correct}/{len(completed)} "
        f"(sum(counts) == {expected_shots})"
    )

    print()
    sub_rate = total / sub_duration if sub_duration > 0 else float("inf")
    print(f"Submission phase:  {sub_duration:.2f}s ({sub_rate:.1f} tasks/sec)")
    print(f"Avg submit lat:    {statistics.mean(submit_lats) * 1000:.0f}ms")
    print(f"Total wall time:   {wall_duration:.1f}s")
    print(f"Throughput:        {throughput:.2f} tasks/sec")

    if completion_times:
        completion_times.sort()
        print(f"Avg completion:    {statistics.mean(completion_times):.1f}s")
        print(f"Min completion:    {min(completion_times):.1f}s")
        print(f"Max completion:    {max(completion_times):.1f}s")
        print(f"P50 completion:    {_percentile(completion_times, 50):.1f}s")
        print(f"P95 completion:    {_percentile(completion_times, 95):.1f}s")

    # per-circuit breakdown
    circuit_stats: dict[str, list[float]] = {}
    for r in completed:
        if r.completion_time is not None:
            circuit_stats.setdefault(r.circuit, []).append(r.completion_time)

    if circuit_stats:
        print("\n--- Per-circuit breakdown ---")
        for name in CIRCUIT_NAMES:
            times = circuit_stats.get(name, [])
            if times:
                print(
                    f"  {name}: n={len(times)}, "
                    f"avg={statistics.mean(times):.1f}s, "
                    f"p50={_percentile(sorted(times), 50):.1f}s"
                )

    # failure details
    if failed:
        print("\n--- Failed tasks ---")
        for r in failed:
            print(f"  {r.task_id}: {r.error}")
    if timed_out:
        print("\n--- Timed-out tasks ---")
        for r in timed_out:
            print(f"  {r.task_id} ({r.circuit})")

    all_ok = len(completed) == total and correct == len(completed)
    print(f"\nOverall: {'PASS' if all_ok else 'FAIL'}")
    return all_ok


def _percentile(sorted_data: list[float], p: float) -> float:
    if not sorted_data:
        return 0.0
    k = (len(sorted_data) - 1) * (p / 100)
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return sorted_data[f]
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> LoadTestConfig:
    parser = argparse.ArgumentParser(description="Load test for QASM3 task pipeline")
    parser.add_argument(
        "--tasks",
        type=int,
        default=int(os.environ.get("LOAD_TEST_TASKS", "20")),
        help="Number of tasks to submit (default: 20)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=int(os.environ.get("LOAD_TEST_CONCURRENCY", "10")),
        help="Max concurrent submissions (default: 10)",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=os.environ.get("LOAD_TEST_BASE_URL", "http://localhost:8000"),
        help="API base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.environ.get("LOAD_TEST_TIMEOUT", "120")),
        help="Per-task poll timeout in seconds (default: 120)",
    )
    parser.add_argument(
        "--shots",
        type=int,
        default=int(os.environ.get("SHOTS", "1024")),
        help="Expected shots for correctness validation (default: 1024)",
    )
    args = parser.parse_args()
    return LoadTestConfig(
        tasks=args.tasks,
        concurrency=args.concurrency,
        base_url=args.base_url,
        timeout=args.timeout,
        shots=args.shots,
    )


def main() -> None:
    cfg = parse_args()
    print(
        f"Starting load test: {cfg.tasks} tasks, "
        f"concurrency={cfg.concurrency}, "
        f"base_url={cfg.base_url}, "
        f"timeout={cfg.timeout}s, "
        f"expected_shots={cfg.shots}"
    )
    report = asyncio.run(run_load_test(cfg))
    ok = print_report(report, cfg.shots)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
