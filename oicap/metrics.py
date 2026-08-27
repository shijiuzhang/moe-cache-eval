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
    content_timestamps = [
        chunk.received_ns
        for chunk in obs.chunks
        if chunk.kind == "content"
    ]
    inter_chunk = [
        _ms(right - left)
        for left, right in zip(content_timestamps, content_timestamps[1:])
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
        "inter_chunk_latency_ms": inter_chunk,
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
    measured = [(row, observation_metrics(row)) for row in rows]
    successful_rows = [row for row in rows if row.success]
    successful = [(row, values) for row, values in measured if row.success]
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
    output_tokens = sum(row.output_tokens or 0 for row in successful_rows)
    input_tokens = sum(row.input_tokens or 0 for row in successful_rows)
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
    service_durations_s = [
        (terminal - submitted) / 1_000_000_000.0
        for submitted, terminal in intervals
    ]

    def scalar(pairs: list[tuple[RequestObservation, dict[str, object]]], name: str) -> list[float]:
        return [float(value) for _, item in pairs if (value := item[name]) is not None]

    def populated(
        values: Iterable[float], population: str, request_count: int
    ) -> dict[str, float | int | str | None]:
        result = distribution(values)
        result["population"] = population
        result["request_count"] = request_count
        return result

    itl_samples = [float(value) for _, item in successful for value in item["itl_ms"]]
    inter_chunk_samples = [
        float(value)
        for _, item in successful
        for value in item["inter_chunk_latency_ms"]
    ]
    token_timing_available = bool(successful_rows) and all(
        row.token_timing_authority == "synthetic_one_token_per_content_event"
        for row in successful_rows
    )
    itl_distribution = populated(
        itl_samples,
        "authoritative_token_intervals_from_successful_requests",
        len(successful_rows),
    )
    itl_distribution["availability"] = "available" if token_timing_available else "unavailable"
    itl_distribution["unavailable_reason"] = (
        None if token_timing_available else "no_authoritative_per_token_timestamps"
    )
    failure_times = [
        (terminal - row.t_submit_ns) / 1_000_000.0
        for row in rows
        if not row.success
        for terminal in [row.t_error_ns or row.t_complete_ns]
        if terminal is not None
    ]
    overlap = overlap_statistics(intervals)
    return {
        "schema_version": "0.1",
        "metrics_version": METRICS_VERSION,
        "requests": {
            "total": len(rows),
            "successful": len(successful_rows),
            "timed_out": sum(row.timed_out for row in rows),
            "censored": sum(row.censored for row in rows),
            "success_rate": len(successful) / len(rows) if rows else None,
            "errors_by_type": dict(sorted(error_counts.items())),
            "attempts_total": sum(row.attempts for row in rows),
            "retried": sum(row.attempts > 1 for row in rows),
            "successful_after_retry": sum(row.success and row.attempts > 1 for row in rows),
        },
        "latency_ms": {
            "schedule_lag": populated(
                scalar(measured, "schedule_lag_ms"), "all_requests", len(rows)
            ),
            "ttft": populated(
                scalar(successful, "ttft_ms"), "successful_requests", len(successful_rows)
            ),
            "first_chunk_to_token": populated(
                scalar(successful, "first_chunk_to_token_ms"),
                "successful_requests",
                len(successful_rows),
            ),
            "end_to_end": populated(
                scalar(successful, "end_to_end_ms"),
                "successful_requests",
                len(successful_rows),
            ),
            "inter_chunk_latency": populated(
                inter_chunk_samples,
                "content_chunk_intervals_from_successful_requests",
                len(successful_rows),
            ),
            "itl": itl_distribution,
            "tpot": populated(
                scalar(successful, "tpot_ms"),
                "successful_requests_with_at_least_two_authoritative_output_tokens",
                len(successful_rows),
            ),
            "time_to_failure": populated(
                failure_times, "failed_requests_with_observed_terminal_time", len(rows) - len(successful_rows)
            ),
        },
        "throughput": {
            "measurement_duration_s": duration_s,
            "completed_requests_per_s": len(successful_rows) / duration_s if duration_s > 0 else None,
            "output_tokens_per_s": output_tokens / duration_s if duration_s > 0 else None,
            "input_plus_output_tokens_per_s": (
                (input_tokens + output_tokens) / duration_s if duration_s > 0 else None
            ),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
        "load_realization": {
            "peak_in_flight": overlap["peak_in_flight"],
            "mean_in_flight": overlap["mean_in_flight"],
            "overlap_window_s": overlap["overlap_window_s"],
            "mean_in_flight_before_final_submission": overlap[
                "mean_in_flight_before_final_submission"
            ],
            "concurrency_maintenance_window_s": overlap[
                "concurrency_maintenance_window_s"
            ],
            "mean_request_service_time_s": (
                sum(service_durations_s) / len(service_durations_s)
                if service_durations_s
                else None
            ),
            "service_time_request_count": len(service_durations_s),
            "submission_span_s": submission_span_s,
            "achieved_submission_rate_per_s": (
                (len(submit_times) - 1) / submission_span_s
                if submission_span_s and submission_span_s > 0
                else None
            ),
        },
    }


def peak_overlap(intervals: list[tuple[int, int]]) -> int:
    return int(overlap_statistics(intervals)["peak_in_flight"])


def closed_loop_concurrency_model(
    load_realization: dict[str, object],
    active_users: int,
    think_time_ms: float,
) -> dict[str, float | str | None]:
    observed_value = load_realization.get("mean_in_flight_before_final_submission")
    service_value = load_realization.get("mean_request_service_time_s")
    observed = float(observed_value) if observed_value is not None else None
    service_s = float(service_value) if service_value is not None else None
    think_s = think_time_ms / 1000.0
    if think_s <= 0:
        expected = float(active_users)
        method = "declared_active_users"
    elif service_s is not None and service_s > 0:
        expected = active_users * service_s / (service_s + think_s)
        method = "interactive_response_time_law"
    else:
        expected = None
        method = "interactive_response_time_law_unavailable"
    ratio = (
        observed / expected
        if observed is not None and expected is not None and expected > 0
        else None
    )
    return {
        "method": method,
        "observed_mean_in_flight": observed,
        "expected_mean_in_flight": expected,
        "mean_request_service_time_s": service_s,
        "declared_think_time_s": think_s,
        "realization_ratio": ratio,
    }


def overlap_statistics(intervals: list[tuple[int, int]]) -> dict[str, float | int | None]:
    if not intervals:
        return {
            "peak_in_flight": 0,
            "mean_in_flight": None,
            "overlap_window_s": 0.0,
            "mean_in_flight_before_final_submission": None,
            "concurrency_maintenance_window_s": 0.0,
        }
    events: list[tuple[int, int]] = []
    for start, end in intervals:
        events.append((start, 1))
        events.append((end, -1))
    # At equal timestamps, completion is processed before a new submission.
    active = 0
    maximum = 0
    area_ns = 0
    ordered = sorted(events, key=lambda item: (item[0], item[1]))
    previous = ordered[0][0]
    for timestamp, delta in ordered:
        area_ns += active * (timestamp - previous)
        previous = timestamp
        active += delta
        maximum = max(maximum, active)
    window_ns = ordered[-1][0] - ordered[0][0]
    first_submission_ns = min(start for start, _ in intervals)
    final_submission_ns = max(start for start, _ in intervals)
    maintenance_window_ns = final_submission_ns - first_submission_ns
    maintenance_area_ns = sum(
        max(0, min(end, final_submission_ns) - max(start, first_submission_ns))
        for start, end in intervals
    )
    return {
        "peak_in_flight": maximum,
        "mean_in_flight": area_ns / window_ns if window_ns > 0 else None,
        "overlap_window_s": window_ns / 1_000_000_000.0,
        "mean_in_flight_before_final_submission": (
            maintenance_area_ns / maintenance_window_ns
            if maintenance_window_ns > 0
            else None
        ),
        "concurrency_maintenance_window_s": maintenance_window_ns / 1_000_000_000.0,
    }
