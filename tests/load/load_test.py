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

POLL_INTERVAL_SEC = 0.5
MAX_POLL_CONNECTIONS = 100


@dataclass
class TaskResult:
    task_id: str
    circuit: str
    submit_time: float
    submit_latency: float
    completed_at: float | None = None
    status: str = "pending"
    result: dict | None = None
    error: str | None = None

    @property
    def duration(self) -> float | None:
        if self.completed_at is None:
            return None
        return self.completed_at - self.submit_time


@dataclass
class LoadTestConfig:
    tasks: int = 20
    concurrency: int = 10
    base_url: str = "http://localhost:8000"
    timeout: int = 120
    shots: int = 1024


@dataclass
class LoadTestReport:
    results: list[TaskResult] = field(default_factory=list)
    wall_start: float = 0.0
    submission_end: float = 0.0
    wall_end: float = 0.0

    @property
    def submission_duration(self) -> float:
        return self.submission_end - self.wall_start

    @property
    def wall_duration(self) -> float:
        return self.wall_end - self.wall_start


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
) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            async with sem:
                resp = await client.get(f"/tasks/{result.task_id}")
            resp.raise_for_status()
        except (httpx.PoolTimeout, httpx.ConnectTimeout, httpx.ReadTimeout):
            await asyncio.sleep(POLL_INTERVAL_SEC)
            continue

        body = resp.json()
        status = body.get("status")

        if status == "completed":
            result.status = "completed"
            result.result = body.get("result")
            result.completed_at = time.time()
            return
        if status == "error":
            result.status = "failed"
            result.error = body.get("message", "unknown error")
            result.completed_at = time.time()
            return

        await asyncio.sleep(POLL_INTERVAL_SEC)

    result.status = "timeout"
    result.completed_at = time.time()


async def run_load_test(cfg: LoadTestConfig) -> LoadTestReport:
    report = LoadTestReport()
    submit_sem = asyncio.Semaphore(cfg.concurrency)
    poll_sem = asyncio.Semaphore(min(cfg.tasks, MAX_POLL_CONNECTIONS))

    pool_limits = httpx.Limits(
        max_connections=MAX_POLL_CONNECTIONS * 2,
        max_keepalive_connections=MAX_POLL_CONNECTIONS // 2,
        keepalive_expiry=30,
    )
    async with httpx.AsyncClient(
        base_url=cfg.base_url,
        timeout=httpx.Timeout(30.0, pool=60.0),
        limits=pool_limits,
    ) as client:
        circuit_names = list(CIRCUITS)
        choices = [random.choice(circuit_names) for _ in range(cfg.tasks)]
        report.wall_start = time.time()

        report.results = await asyncio.gather(
            *(submit_task(client, submit_sem, n, CIRCUITS[n]) for n in choices)
        )
        report.submission_end = time.time()
        print(
            f"Submitted {len(report.results)} tasks in "
            f"{report.submission_duration:.2f}s"
        )

        await asyncio.gather(
            *(poll_task(client, poll_sem, r, cfg.timeout) for r in report.results)
        )
        report.wall_end = time.time()

    return report


# -- Reporting ----------------------------------------------------------------


def print_report(report: LoadTestReport, expected_shots: int) -> bool:
    results = report.results
    total = len(results)
    by_status = _group_by_status(results)
    completed = by_status.get("completed", [])
    failed = by_status.get("failed", [])
    timed_out = by_status.get("timeout", [])

    correct = sum(
        1 for r in completed if r.result and sum(r.result.values()) == expected_shots
    )
    durations = sorted(r.duration for r in completed if r.duration is not None)
    submit_lats = [r.submit_latency for r in results]

    throughput = len(completed) / report.wall_duration if report.wall_duration > 0 else 0
    sub_rate = total / report.submission_duration if report.submission_duration > 0 else float("inf")

    print("\n=== Load Test Results ===")
    print(f"Tasks submitted:   {total}")
    print(f"Tasks completed:   {len(completed)}")
    print(f"Tasks failed:      {len(failed)}")
    print(f"Tasks timed out:   {len(timed_out)}")
    print(f"Correctness:       {correct}/{len(completed)} (sum(counts) == {expected_shots})")

    print()
    print(f"Submission phase:  {report.submission_duration:.2f}s ({sub_rate:.1f} tasks/sec)")
    print(f"Avg submit lat:    {statistics.mean(submit_lats) * 1000:.0f}ms")
    print(f"Total wall time:   {report.wall_duration:.1f}s")
    print(f"Throughput:        {throughput:.2f} tasks/sec")

    if durations:
        print(f"Avg completion:    {statistics.mean(durations):.1f}s")
        print(f"Min completion:    {durations[0]:.1f}s")
        print(f"Max completion:    {durations[-1]:.1f}s")
        print(f"P50 completion:    {_percentile(durations, 50):.1f}s")
        print(f"P95 completion:    {_percentile(durations, 95):.1f}s")

    _print_circuit_breakdown(completed)
    _print_failures(failed, timed_out)

    all_ok = len(completed) == total and correct == len(completed)
    print(f"\nOverall: {'PASS' if all_ok else 'FAIL'}")
    return all_ok


def _group_by_status(results: list[TaskResult]) -> dict[str, list[TaskResult]]:
    groups: dict[str, list[TaskResult]] = {}
    for r in results:
        groups.setdefault(r.status, []).append(r)
    return groups


def _print_circuit_breakdown(completed: list[TaskResult]) -> None:
    circuit_durations: dict[str, list[float]] = {}
    for r in completed:
        if r.duration is not None:
            circuit_durations.setdefault(r.circuit, []).append(r.duration)

    if not circuit_durations:
        return

    print("\n--- Per-circuit breakdown ---")
    for name, times in sorted(circuit_durations.items()):
        times.sort()
        print(
            f"  {name}: n={len(times)}, "
            f"avg={statistics.mean(times):.1f}s, "
            f"p50={_percentile(times, 50):.1f}s"
        )


def _print_failures(
    failed: list[TaskResult], timed_out: list[TaskResult]
) -> None:
    if failed:
        print("\n--- Failed tasks ---")
        for r in failed:
            print(f"  {r.task_id}: {r.error}")
    if timed_out:
        print("\n--- Timed-out tasks ---")
        for r in timed_out:
            print(f"  {r.task_id} ({r.circuit})")


def _percentile(sorted_data: list[float], p: float) -> float:
    if not sorted_data:
        return 0.0
    idx = (len(sorted_data) - 1) * (p / 100)
    lower = int(idx)
    upper = lower + 1
    if upper >= len(sorted_data):
        return sorted_data[lower]
    return sorted_data[lower] + (idx - lower) * (sorted_data[upper] - sorted_data[lower])


# -- CLI ----------------------------------------------------------------------


def parse_args() -> LoadTestConfig:
    parser = argparse.ArgumentParser(description="Load test for QASM3 task pipeline")
    parser.add_argument(
        "--tasks", type=int,
        default=int(os.environ.get("LOAD_TEST_TASKS", "20")),
        help="Number of tasks to submit (default: 20)",
    )
    parser.add_argument(
        "--concurrency", type=int,
        default=int(os.environ.get("LOAD_TEST_CONCURRENCY", "10")),
        help="Max concurrent submissions (default: 10)",
    )
    parser.add_argument(
        "--base-url", type=str,
        default=os.environ.get("LOAD_TEST_BASE_URL", "http://localhost:8000"),
        help="API base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--timeout", type=int,
        default=int(os.environ.get("LOAD_TEST_TIMEOUT", "120")),
        help="Per-task poll timeout in seconds (default: 120)",
    )
    parser.add_argument(
        "--shots", type=int,
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
