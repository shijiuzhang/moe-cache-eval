from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ChunkObservation:
    received_ns: int
    kind: str
    content: str = ""


@dataclass
class RequestObservation:
    request_id: str
    workload_class: str
    phase: str
    t_scheduled_ns: int
    t_submit_ns: int
    t_send_start_ns: int | None = None
    t_first_byte_ns: int | None = None
    t_first_chunk_ns: int | None = None
    t_first_token_ns: int | None = None
    t_complete_ns: int | None = None
    t_error_ns: int | None = None
    status_code: int | None = None
    success: bool = False
    timed_out: bool = False
    censored: bool = False
    error_type: str | None = None
    error_message: str | None = None
    attempts: int = 1
    attempt_history: list[dict[str, Any]] = field(default_factory=list)
    request_body: dict[str, Any] = field(default_factory=dict)
    response_text: str = ""
    chunks: list[ChunkObservation] = field(default_factory=list)
    token_timestamps_ns: list[int] = field(default_factory=list)
    input_tokens: int | None = None
    output_tokens: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RequestObservation":
        copy = dict(value)
        copy["chunks"] = [ChunkObservation(**item) for item in copy.get("chunks", [])]
        return cls(**copy)
