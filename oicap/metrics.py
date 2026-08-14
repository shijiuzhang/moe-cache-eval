from __future__ import annotations

import math
from collections import Counter
from statistics import fmean
from typing import Iterable

from .observations import RequestObservation


METRICS_VERSION = "0.1"


def _ms(delta_ns: int) -> float:
    return delta_ns / 1_000_000.0


def quantile(values: list[float], probability: float) -> float | None:
    """Linear interpolation on sorted samples (Hyndman-Fan type 7)."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def distribution(values: Iterable[float]) -> dict[str, float | int | None]:
    samples = list(values)
    return {
        "count": len(samples),
        "mean": fmean(samples) if samples else None,
        "p50": quantile(samples, 0.50),
        "p95": quantile(samples, 0.95),
        "p99": quantile(samples, 0.99),
        "max": max(samples) if samples else None,
    }


def observation_metrics(obs: RequestObservation) -> dict[str, object]:
    schedule_lag = _ms(obs.t_submit_ns - obs.t_scheduled_ns)
    ttft = (
        _ms(obs.t_first_token_ns - obs.t_submit_ns)
        if obs.t_first_token_ns is not None
        else None
    )
    first_chunk_gap = (
        _ms(obs.t_first_token_ns - obs.t_first_chunk_ns)
        if obs.t_first_token_ns is not None and obs.t_first_chunk_ns is not None
        else None
    )
    end_to_end = (
        _ms(obs.t_complete_ns - obs.t_submit_ns)
        if obs.t_complete_ns is not None
        else None
    )
    itl = [
        _ms(right - left)
        for left, right in zip(obs.token_timestamps_ns, obs.token_timestamps_ns[1:])
    ]
    generated = obs.output_tokens
    tpot = None
    if (
        generated is not None
        and generated >= 2
        and obs.t_first_token_ns is not None
        and obs.t_complete_ns is not None
    ):
        tpot = _ms(obs.t_complete_ns - obs.t_first_token_ns) / (generated - 1)
    return {
        "schedule_lag_ms": schedule_lag,
        "ttft_ms": ttft,
        "first_chunk_to_token_ms": first_chunk_gap,
        "end_to_end_ms": end_to_end,
        "itl_ms": itl,
        "tpot_ms": tpot,
    }


def summarize(observations: Iterable[RequestObservation]) -> dict[str, object]:
    rows = list(observations)
    summary = _summarize_rows(rows)
    classes = sorted({row.workload_class for row in rows})
    summary["by_workload_class"] = {
        class_id: _summarize_rows([row for row in rows if row.workload_class == class_id])
        for class_id in classes
    }
    summary["realized_workload_mix"] = {
        class_id: sum(row.workload_class == class_id for row in rows) / len(rows)
        for class_id in classes
    } if rows else {}
    return summary


def _summarize_rows(rows: list[RequestObservation]) -> dict[str, object]:
    per_request = [observation_metrics(row) for row in rows]
    measured_start = min((row.t_submit_ns for row in rows), default=None)
    terminal_times = [
        time
        for row in rows
        for time in [row.t_complete_ns or row.t_error_ns]
        if time is not None
    ]
    measured_end = max(terminal_times, default=measured_start)
    duration_s = (
        (measured_end - measured_start) / 1_000_000_000.0
        if measured_start is not None and measured_end is not None
        else 0.0
    )
    successful = [row for row in rows if row.success]
    output_tokens = sum(row.output_tokens or 0 for row in successful)
    input_tokens = sum(row.input_tokens or 0 for row in successful)
    error_counts = Counter(row.error_type for row in rows if row.error_type)
    submit_times = sorted(row.t_submit_ns for row in rows)
    submission_span_s = (
        (submit_times[-1] - submit_times[0]) / 1_000_000_000.0
        if len(submit_times) >= 2
        else None
    )
    intervals = [
        (row.t_submit_ns, terminal)
        for row in rows
        for terminal in [row.t_complete_ns or row.t_error_ns]
        if terminal is not None
    ]

    def scalar(name: str) -> list[float]:
        return [float(value) for item in per_request if (value := item[name]) is not None]

    itl_samples = [float(value) for item in per_request for value in item["itl_ms"]]
    return {
        "schema_version": "0.1",
        "metrics_version": METRICS_VERSION,
        "requests": {
            "total": len(rows),
            "successful": len(successful),
            "timed_out": sum(row.timed_out for row in rows),
            "censored": sum(row.censored for row in rows),
            "success_rate": len(successful) / len(rows) if rows else None,
            "errors_by_type": dict(sorted(error_counts.items())),
            "attempts_total": sum(row.attempts for row in rows),
            "retried": sum(row.attempts > 1 for row in rows),
            "successful_after_retry": sum(row.success and row.attempts > 1 for row in rows),
        },
        "latency_ms": {
            "schedule_lag": distribution(scalar("schedule_lag_ms")),
            "ttft": distribution(scalar("ttft_ms")),
            "first_chunk_to_token": distribution(scalar("first_chunk_to_token_ms")),
            "end_to_end": distribution(scalar("end_to_end_ms")),
            "itl": distribution(itl_samples),
            "tpot": distribution(scalar("tpot_ms")),
        },
        "throughput": {
            "measurement_duration_s": duration_s,
            "completed_requests_per_s": len(successful) / duration_s if duration_s > 0 else None,
            "output_tokens_per_s": output_tokens / duration_s if duration_s > 0 else None,
            "input_plus_output_tokens_per_s": (
                (input_tokens + output_tokens) / duration_s if duration_s > 0 else None
            ),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
        "load_realization": {
            "peak_in_flight": peak_overlap(intervals),
            "submission_span_s": submission_span_s,
            "achieved_submission_rate_per_s": (
                (len(submit_times) - 1) / submission_span_s
                if submission_span_s and submission_span_s > 0
                else None
            ),
        },
    }


def peak_overlap(intervals: list[tuple[int, int]]) -> int:
    events: list[tuple[int, int]] = []
    for start, end in intervals:
        events.append((start, 1))
        events.append((end, -1))
    # At equal timestamps, completion is processed before a new submission.
    active = 0
    maximum = 0
    for _, delta in sorted(events, key=lambda item: (item[0], item[1])):
        active += delta
        maximum = max(maximum, active)
    return maximum
