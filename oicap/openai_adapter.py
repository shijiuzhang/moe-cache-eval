from __future__ import annotations

import asyncio
import itertools
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .observations import ChunkObservation, RequestObservation


@dataclass(frozen=True)
class OpenAIAdapter:
    endpoint: str
    api_key: str | None = None

    async def execute(
        self,
        request_id: str,
        workload_class: str,
        body: dict[str, Any],
        scheduled_ns: int,
        timeout_s: float,
        token_authority: str,
        phase: str = "measurement",
    ) -> RequestObservation:
        return await asyncio.to_thread(
            self._execute_sync,
            request_id,
            workload_class,
            body,
            scheduled_ns,
            timeout_s,
            token_authority,
            phase,
        )

    def _execute_sync(
        self,
        request_id: str,
        workload_class: str,
        body: dict[str, Any],
        scheduled_ns: int,
        timeout_s: float,
        token_authority: str,
        phase: str,
    ) -> RequestObservation:
        submitted_ns = time.perf_counter_ns()
        observation = RequestObservation(
            request_id=request_id,
            workload_class=workload_class,
            phase=phase,
            t_scheduled_ns=scheduled_ns,
            t_submit_ns=submitted_ns,
            request_body=body,
            token_timing_authority=token_authority,
        )
        if (
            token_authority == "synthetic_one_token_per_content_event"
            and "oicap_test" not in body
        ):
            raise ValueError(
                "synthetic_one_token_per_content_event is restricted to the "
                "deterministic oicap_test protocol; use server_usage or none for real endpoints."
            )
        payload = dict(body)
        payload["stream"] = True
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        headers["X-OICAP-Request-ID"] = request_id
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        observation.t_send_start_ns = time.perf_counter_ns()
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                observation.status_code = int(response.status)
                substantive_started = False
                content_event_count = 0
                first_byte = response.read(1)
                if first_byte:
                    observation.t_first_byte_ns = time.perf_counter_ns()
                first_line = first_byte + response.readline() if first_byte else b""
                lines = itertools.chain([first_line], response) if first_line else response
                for raw_line in lines:
                    received_ns = time.perf_counter_ns()
                    line = raw_line.decode("utf-8").rstrip("\r\n")
                    if not line:
                        continue
                    if observation.t_first_chunk_ns is None:
                        observation.t_first_chunk_ns = received_ns
                    if line.startswith(":"):
                        observation.chunks.append(
                            ChunkObservation(received_ns=received_ns, kind="keepalive")
                        )
                        continue
                    if not line.startswith("data:"):
                        observation.chunks.append(
                            ChunkObservation(received_ns=received_ns, kind="protocol", content=line)
                        )
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        observation.chunks.append(
                            ChunkObservation(received_ns=received_ns, kind="done")
                        )
                        break
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError as exc:
                        raise ValueError(f"Malformed SSE JSON: {data[:120]}") from exc
                    content = _content_from_event(event)
                    kind = _event_kind(event, content)
                    observation.chunks.append(
                        ChunkObservation(received_ns=received_ns, kind=kind, content=content)
                    )
                    if content:
                        content_event_count += 1
                        observation.response_text += content
                        if content.strip() and not substantive_started:
                            substantive_started = True
                            observation.t_first_token_ns = received_ns
                        if (
                            substantive_started
                            and token_authority == "synthetic_one_token_per_content_event"
                        ):
                            observation.token_timestamps_ns.append(received_ns)
                    usage = event.get("usage") if isinstance(event, dict) else None
                    if isinstance(usage, dict) and token_authority in {
                        "server_usage",
                        "synthetic_one_token_per_content_event",
                    }:
                        observation.input_tokens = _optional_int(usage.get("prompt_tokens"))
                        observation.output_tokens = _optional_int(usage.get("completion_tokens"))
            observation.t_complete_ns = time.perf_counter_ns()
            if token_authority == "synthetic_one_token_per_content_event":
                observation.output_tokens = content_event_count
            observation.success = bool(
                observation.status_code is not None
                and 200 <= observation.status_code < 300
                and observation.t_first_token_ns is not None
            )
            if not observation.success:
                observation.error_type = "empty_or_non_substantive_response"
        except urllib.error.HTTPError as exc:
            observation.status_code = int(exc.code)
            observation.t_error_ns = time.perf_counter_ns()
            observation.error_type = "http_error"
            observation.error_message = _safe_error_message(str(exc), self.endpoint)
        except TimeoutError as exc:
            observation.t_error_ns = time.perf_counter_ns()
            observation.timed_out = True
            observation.censored = True
            observation.error_type = "timeout"
            observation.error_message = _safe_error_message(str(exc), self.endpoint)
        except urllib.error.URLError as exc:
            observation.t_error_ns = time.perf_counter_ns()
            if isinstance(exc.reason, TimeoutError):
                observation.timed_out = True
                observation.censored = True
                observation.error_type = "timeout"
            else:
                observation.error_type = "url_error"
            observation.error_message = _safe_error_message(str(exc), self.endpoint)
        except Exception as exc:  # the raw error remains evidence
            observation.t_error_ns = time.perf_counter_ns()
            observation.error_type = type(exc).__name__
            observation.error_message = _safe_error_message(str(exc), self.endpoint)
        return observation


def _content_from_event(event: Any) -> str:
    if not isinstance(event, dict):
        return ""
    choices = event.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    choice = choices[0]
    if not isinstance(choice, dict):
        return ""
    delta = choice.get("delta")
    if isinstance(delta, dict):
        value = delta.get("content")
        return value if isinstance(value, str) else ""
    value = choice.get("text")
    return value if isinstance(value, str) else ""


def _has_reasoning_content(event: Any) -> bool:
    """Identify hidden reasoning events without retaining their sensitive text."""
    if not isinstance(event, dict):
        return False
    choices = event.get("choices")
    if not isinstance(choices, list) or not choices:
        return False
    choice = choices[0]
    if not isinstance(choice, dict):
        return False
    delta = choice.get("delta")
    if not isinstance(delta, dict):
        return False
    value = delta.get("reasoning_content")
    return isinstance(value, str) and bool(value)


def _event_kind(event: Any, content: str) -> str:
    if content:
        return "content"
    if not isinstance(event, dict):
        return "metadata"
    choices = event.get("choices")
    if not isinstance(choices, list) or not choices:
        return "metadata"
    choice = choices[0]
    if not isinstance(choice, dict):
        return "metadata"
    delta = choice.get("delta")
    if not isinstance(delta, dict):
        return "metadata"
    # llama.cpp begins a stream with role=assistant and null content. Keeping the
    # combined shape makes the AC05 role-only/empty-content control observable.
    delta_content = delta.get("content")
    if "role" in delta and (delta_content is None or delta_content == ""):
        return "role_empty"
    if _has_reasoning_content(event):
        return "reasoning"
    if "content" in delta and (delta_content is None or delta_content == ""):
        return "empty"
    return "metadata"


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_error_message(message: str, endpoint: str) -> str:
    from urllib.parse import urlsplit, urlunsplit

    value = urlsplit(endpoint)
    host = value.hostname or ""
    if value.port:
        host = f"{host}:{value.port}"
    redacted = urlunsplit((value.scheme, host, value.path, "", ""))
    return message.replace(endpoint, redacted)
