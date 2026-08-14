from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

from .contracts import ContractSet
from .observations import RequestObservation
from .openai_adapter import OpenAIAdapter
from .workloads import WorkloadItem, deterministic_sequence, load_jsonl


@dataclass(frozen=True)
class RunResult:
    observations: list[RequestObservation]
    started_ns: int
    finished_ns: int


async def execute_load_point(
    contracts: ContractSet,
    endpoint: str,
    api_key: str | None = None,
    adapter: OpenAIAdapter | None = None,
) -> RunResult:
    run = contracts.run
    scenario = contracts.scenario
    measurement = run["measurement"]
    request_count = int(measurement["requests"])
    warmup_count = int(run.get("warmup", {}).get("requests", 0))
    seed = int(run.get("seed", 0))
    timeout_s = float(run["timeout_s"])
    max_in_flight = int(run["max_in_flight"])
    token_authority = str(run["token_accounting"]["authority"])
    items = load_jsonl(contracts.workload_path)
    allowed_classes = {str(item["id"]) for item in scenario["workload_classes"]}
    unexpected = sorted({item.workload_class for item in items} - allowed_classes)
    if unexpected:
        raise ValueError(f"Workload rows contain undeclared classes: {unexpected}")
    class_weights = {
        str(item["id"]): float(item["weight"])
        for item in scenario["workload_classes"]
    }
    sequence = deterministic_sequence(
        items,
        warmup_count + request_count,
        seed,
        class_weights,
    )
    warmup_sequence = sequence[:warmup_count]
    measurement_sequence = sequence[warmup_count:]
    selected_adapter = adapter or OpenAIAdapter(endpoint, api_key or os.getenv("OICAP_API_KEY"))
    retry_policy = run["retry_policy"]

    async def execute_with_policy(*args: object) -> RequestObservation:
        return await _execute_with_retries(
            selected_adapter.execute,
            args,
            int(retry_policy["max_attempts"]),
            float(retry_policy["backoff_ms"]),
            {str(value) for value in retry_policy["retry_on"]},
        )

    arrival = scenario["arrival"]
    think_time_ms = float(scenario.get("session", {}).get("think_time_ms", 0))
    if think_time_ms < 0:
        raise ValueError("scenario.session.think_time_ms must be >= 0.")
    started_ns = time.perf_counter_ns()
    observations: list[RequestObservation] = []
    if warmup_sequence:
        if arrival["kind"] == "closed_loop":
            observations.extend(
                await _closed_loop(
                    warmup_sequence,
                    execute_with_policy,
                    started_ns,
                    int(arrival["active_users"]),
                    max_in_flight,
                    timeout_s,
                    token_authority,
                    "warmup",
                    think_time_ms,
                )
            )
        else:
            observations.extend(
                await _open_loop(
                    warmup_sequence,
                    execute_with_policy,
                    started_ns,
                    float(arrival["rate_per_s"]),
                    max_in_flight,
                    timeout_s,
                    token_authority,
                    "warmup",
                )
            )
    measurement_start_ns = time.perf_counter_ns()
    if arrival["kind"] == "closed_loop":
        observations.extend(await _closed_loop(
            measurement_sequence,
            execute_with_policy,
            measurement_start_ns,
            int(arrival["active_users"]),
            max_in_flight,
            timeout_s,
            token_authority,
            "measurement",
            think_time_ms,
        ))
    else:
        observations.extend(await _open_loop(
            measurement_sequence,
            execute_with_policy,
            measurement_start_ns,
            float(arrival["rate_per_s"]),
            max_in_flight,
            timeout_s,
            token_authority,
            "measurement",
        ))
    return RunResult(
        observations=sorted(observations, key=lambda item: item.request_id),
        started_ns=started_ns,
        finished_ns=time.perf_counter_ns(),
    )


Execute = Callable[..., Awaitable[RequestObservation]]


async def _execute_with_retries(
    execute: Execute,
    args: tuple[object, ...],
    max_attempts: int,
    backoff_ms: float,
    retry_on: set[str],
) -> RequestObservation:
    history: list[dict[str, object]] = []
    first_submit_ns: int | None = None
    first_send_start_ns: int | None = None
    final: RequestObservation | None = None
    for attempt in range(1, max_attempts + 1):
        final = await execute(*args)
        if first_submit_ns is None:
            first_submit_ns = final.t_submit_ns
            first_send_start_ns = final.t_send_start_ns
        history.append(
            {
                "attempt": attempt,
                "t_submit_ns": final.t_submit_ns,
                "t_send_start_ns": final.t_send_start_ns,
                "t_first_byte_ns": final.t_first_byte_ns,
                "t_first_chunk_ns": final.t_first_chunk_ns,
                "t_first_token_ns": final.t_first_token_ns,
                "t_complete_ns": final.t_complete_ns,
                "t_error_ns": final.t_error_ns,
                "status_code": final.status_code,
                "success": final.success,
                "timed_out": final.timed_out,
                "error_type": final.error_type,
                "error_message": final.error_message,
            }
        )
        if final.success or attempt == max_attempts or not _retryable(final, retry_on):
            break
        if backoff_ms:
            await asyncio.sleep(backoff_ms / 1000.0)
    assert final is not None
    final.attempts = len(history)
    final.attempt_history = history
    # User-visible latency starts at the first attempt. Chunk/token timestamps
    # remain those of the terminal attempt, so retry cost is not erased.
    final.t_submit_ns = first_submit_ns or final.t_submit_ns
    final.t_send_start_ns = first_send_start_ns
    return final


def _retryable(row: RequestObservation, retry_on: set[str]) -> bool:
    if row.timed_out and "timeout" in retry_on:
        return True
    if row.status_code is not None and f"http_{row.status_code}" in retry_on:
        return True
    return bool(row.error_type and row.error_type in retry_on)


async def _closed_loop(
    sequence: list[WorkloadItem],
    execute: Execute,
    started_ns: int,
    active_users: int,
    max_in_flight: int,
    timeout_s: float,
    token_authority: str,
    phase: str,
    think_time_ms: float = 0,
) -> list[RequestObservation]:
    worker_count = min(active_users, max_in_flight, len(sequence))
    queues = [sequence[index::worker_count] for index in range(worker_count)]

    async def worker(worker_index: int, queue: list[WorkloadItem]) -> list[RequestObservation]:
        rows: list[RequestObservation] = []
        for offset, item in enumerate(queue):
            if offset and think_time_ms:
                await asyncio.sleep(think_time_ms / 1000.0)
            scheduled_ns = time.perf_counter_ns()
            rows.append(
                await execute(
                    f"{phase[0]}-r{worker_index:04d}-{offset:06d}",
                    item.workload_class,
                    item.body,
                    scheduled_ns,
                    timeout_s,
                    token_authority,
                    phase,
                )
            )
        return rows

    nested = await asyncio.gather(*(worker(index, queue) for index, queue in enumerate(queues)))
    return [row for group in nested for row in group]


async def _open_loop(
    sequence: list[WorkloadItem],
    execute: Execute,
    started_ns: int,
    rate_per_s: float,
    max_in_flight: int,
    timeout_s: float,
    token_authority: str,
    phase: str,
) -> list[RequestObservation]:
    semaphore = asyncio.Semaphore(max_in_flight)
    interval_ns = round(1_000_000_000 / rate_per_s)

    async def one(index: int, item: WorkloadItem) -> RequestObservation:
        scheduled_ns = started_ns + index * interval_ns
        delay = (scheduled_ns - time.perf_counter_ns()) / 1_000_000_000
        if delay > 0:
            await asyncio.sleep(delay)
        async with semaphore:
            return await execute(
                f"{phase[0]}-r{index:010d}",
                item.workload_class,
                item.body,
                scheduled_ns,
                timeout_s,
                token_authority,
                phase,
            )

    return list(await asyncio.gather(*(one(index, item) for index, item in enumerate(sequence))))
