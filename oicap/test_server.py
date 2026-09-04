from __future__ import annotations

import json
import threading
import time
from contextlib import AbstractContextManager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .protocol import DETERMINISTIC_PROTOCOL_HEADER, DETERMINISTIC_PROTOCOL_ID


class DeterministicServer(AbstractContextManager["DeterministicServer"]):
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        *,
        force_zero_delay: bool = False,
        protocol_marker: bool = True,
    ) -> None:
        self.server = ThreadingHTTPServer((host, port), _Handler)
        self.server.force_zero_delay = force_zero_delay  # type: ignore[attr-defined]
        self.server.protocol_marker = protocol_marker  # type: ignore[attr-defined]
        self.server.attempt_counts = {}  # type: ignore[attr-defined]
        self.server.attempt_lock = threading.Lock()  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def endpoint(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}/v1/chat/completions"

    def __enter__(self) -> "DeterministicServer":
        self.thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802 - HTTP method name
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        config = body.get("oicap_test", {})
        if getattr(self.server, "force_zero_delay", False):
            config = {
                "leading_empty": True,
                "ttft_ms": 0,
                "token_delay_ms": 0,
                "tokens": ["calibration", " token"],
                "prompt_tokens": 1,
            }
        statuses = config.get("status_sequence")
        if isinstance(statuses, list) and statuses:
            request_id = self.headers.get("X-OICAP-Request-ID", "anonymous")
            with self.server.attempt_lock:  # type: ignore[attr-defined]
                attempt = self.server.attempt_counts.get(request_id, 0)  # type: ignore[attr-defined]
                self.server.attempt_counts[request_id] = attempt + 1  # type: ignore[attr-defined]
            status = int(statuses[min(attempt, len(statuses) - 1)])
        else:
            status = int(config.get("status", 200))
        if status != 200:
            payload = json.dumps({"error": "injected"}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        _delay_ms(config.get("queue_ms", 0))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        if getattr(self.server, "protocol_marker", False):
            self.send_header(DETERMINISTIC_PROTOCOL_HEADER, DETERMINISTIC_PROTOCOL_ID)
        self.end_headers()
        try:
            if config.get("leading_empty", True):
                self._event({"choices": [{"delta": {"role": "assistant", "content": ""}}]})
            _delay_ms(config.get("ttft_ms", 0))
            for reasoning in config.get("reasoning_tokens", []):
                self._event(
                    {"choices": [{"delta": {"reasoning_content": str(reasoning)}}]}
                )
            tokens = config.get("tokens", ["hello", " world"])
            token_delay_ms = float(config.get("token_delay_ms", 0))
            for index, token in enumerate(tokens):
                if index:
                    _delay_ms(token_delay_ms)
                self._event({"choices": [{"delta": {"content": str(token)}}]})
            usage = {
                "prompt_tokens": int(config.get("prompt_tokens", 1)),
                "completion_tokens": len(tokens),
            }
            self._event({"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": usage})
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            # Expected when the timeout positive control closes the client socket.
            pass
        self.close_connection = True

    def _event(self, value: dict[str, Any]) -> None:
        payload = json.dumps(value, separators=(",", ":")).encode("utf-8")
        self.wfile.write(b"data: " + payload + b"\n\n")
        self.wfile.flush()

    def log_message(self, format: str, *args: object) -> None:
        return


def _delay_ms(value: object) -> None:
    delay = float(value) / 1000.0
    if delay > 0:
        time.sleep(delay)
