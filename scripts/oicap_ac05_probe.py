#!/usr/bin/env python3
"""Generate the real-endpoint protocol evidence required by V02-AC05.

The probe records protocol shape and metric semantics, not generated reasoning text.
It complements (and does not replace) a normal OICAP evidence bundle.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from oicap import __version__
from oicap.metrics import summarize
from oicap.openai_adapter import OpenAIAdapter
from oicap.observations import RequestObservation


def _body(*, usage: bool, max_tokens: int = 64) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": "local",
        "messages": [
            {
                "role": "user",
                "content": "Output exactly: alpha beta gamma delta epsilon zeta eta theta",
            }
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
        "reasoning_budget": 0,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if usage:
        body["stream_options"] = {"include_usage": True}
    return body


def _empty_body() -> dict[str, Any]:
    return {
        "model": "local",
        "messages": [{"role": "user", "content": "Answer only with OK."}],
        "temperature": 0,
        "max_tokens": 1,
    }


async def _execute(
    adapter: OpenAIAdapter,
    request_id: str,
    body: dict[str, Any],
    timeout_s: float,
) -> RequestObservation:
    return await adapter.execute(
        request_id,
        "ac05-protocol",
        body,
        time.perf_counter_ns(),
        timeout_s,
        "server_usage",
    )


def _row_profile(row: RequestObservation) -> dict[str, Any]:
    kinds = [chunk.kind for chunk in row.chunks]
    return {
        "status_code": row.status_code,
        "success": row.success,
        "timed_out": row.timed_out,
        "censored": row.censored,
        "error_type": row.error_type,
        "input_tokens": row.input_tokens,
        "output_tokens": row.output_tokens,
        "response_nonblank": bool(row.response_text.strip()),
        "response_sha256": (
            hashlib.sha256(row.response_text.encode("utf-8")).hexdigest()
            if row.response_text
            else None
        ),
        "chunk_count": len(kinds),
        "chunk_kinds": {kind: kinds.count(kind) for kind in sorted(set(kinds))},
    }


def _nonstreaming(endpoint: str) -> dict[str, Any]:
    body = _body(usage=True)
    body["stream"] = False
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter_ns()
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read())
        finished = time.perf_counter_ns()
    message = payload.get("choices", [{}])[0].get("message", {})
    content = message.get("content") if isinstance(message, dict) else None
    usage = payload.get("usage")
    return {
        "status_code": int(response.status),
        "elapsed_ms": (finished - started) / 1_000_000.0,
        "content_nonblank": isinstance(content, str) and bool(content.strip()),
        "content_sha256": (
            hashlib.sha256(content.encode("utf-8")).hexdigest()
            if isinstance(content, str) and content
            else None
        ),
        "usage_present": isinstance(usage, dict),
    }


def _invalid_route(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    return urlunsplit((parsed.scheme, parsed.netloc, "/v1/oicap-ac05-invalid", "", ""))


def _redacted_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


async def probe(endpoint: str) -> dict[str, Any]:
    adapter = OpenAIAdapter(endpoint)
    usage_present = await _execute(adapter, "usage-present", _body(usage=True), 60)
    usage_absent = await _execute(adapter, "usage-absent", _body(usage=False), 60)
    empty_200 = await _execute(adapter, "empty-200", _empty_body(), 60)
    timeout = await _execute(adapter, "timeout", _body(usage=True), 0.001)
    http_error = await _execute(
        OpenAIAdapter(_invalid_route(endpoint)),
        "http-error",
        _body(usage=True),
        5,
    )

    successful_summary = summarize([usage_present])
    empty_mixed_summary = summarize([usage_present, empty_200])
    timeout_mixed_summary = summarize([usage_present, timeout])
    successful_e2e = successful_summary["latency_ms"]["end_to_end"]
    empty_mixed_e2e = empty_mixed_summary["latency_ms"]["end_to_end"]
    timeout_mixed_e2e = timeout_mixed_summary["latency_ms"]["end_to_end"]

    result = {
        "schema_version": "0.1",
        "criterion": "V02-AC05",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "oicap_version": __version__,
        "endpoint": _redacted_endpoint(endpoint),
        "cases": {
            "stream_usage_present": _row_profile(usage_present),
            "stream_usage_absent": _row_profile(usage_absent),
            "http_200_no_substantive_content": _row_profile(empty_200),
            "timeout_right_censored": _row_profile(timeout),
            "http_error": _row_profile(http_error),
            "non_streaming": await asyncio.to_thread(_nonstreaming, endpoint),
        },
        "positive_controls": {
            "empty_response_excluded_from_success_latency": {
                "passed": (
                    empty_mixed_summary["requests"]["successful"] == 1
                    and empty_mixed_e2e["count"] == successful_e2e["count"] == 1
                    and empty_mixed_e2e["mean"] == successful_e2e["mean"]
                ),
                "mixed_errors": empty_mixed_summary["requests"]["errors_by_type"],
            },
            "timeout_excluded_from_success_latency_and_in_failure_time": {
                "passed": (
                    timeout_mixed_summary["requests"]["timed_out"] == 1
                    and timeout_mixed_summary["requests"]["censored"] == 1
                    and timeout_mixed_e2e["count"] == successful_e2e["count"] == 1
                    and timeout_mixed_e2e["mean"] == successful_e2e["mean"]
                    and timeout_mixed_summary["latency_ms"]["time_to_failure"]["count"] == 1
                )
            },
            "chunk_intervals_never_labelled_token_intervals": {
                "passed": (
                    successful_summary["latency_ms"]["inter_chunk_latency"]["count"] > 0
                    and successful_summary["latency_ms"]["itl"]["availability"] == "unavailable"
                    and successful_summary["latency_ms"]["tpot"]["availability"] == "unavailable"
                ),
                "inter_chunk_latency": successful_summary["latency_ms"][
                    "inter_chunk_latency"
                ],
                "itl": successful_summary["latency_ms"]["itl"],
                "tpot": successful_summary["latency_ms"]["tpot"],
            },
        },
    }
    cases = result["cases"]
    controls = result["positive_controls"]
    stream_present = cases["stream_usage_present"]
    result["qualification_passed"] = bool(
        stream_present["success"]
        and stream_present["input_tokens"] is not None
        and stream_present["output_tokens"] is not None
        and stream_present["chunk_kinds"].get("role_empty", 0) >= 1
        and stream_present["chunk_kinds"].get("content", 0) >= 2
        and cases["stream_usage_absent"]["success"]
        and cases["stream_usage_absent"]["input_tokens"] is None
        and cases["stream_usage_absent"]["output_tokens"] is None
        and not cases["http_200_no_substantive_content"]["success"]
        and cases["http_200_no_substantive_content"]["error_type"]
        == "empty_or_non_substantive_response"
        and cases["timeout_right_censored"]["timed_out"]
        and cases["timeout_right_censored"]["censored"]
        and cases["http_error"]["error_type"] == "http_error"
        and cases["non_streaming"]["content_nonblank"]
        and cases["non_streaming"]["usage_present"]
        and all(control["passed"] for control in controls.values())
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = asyncio.run(probe(args.endpoint))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    if not result["qualification_passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
