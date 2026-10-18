"""Rebuild-stable digests for safetensors files (DEVIATIONS D-003).

safetensors writes its metadata keys in a per-process random order, so the raw
file hash of identical content takes one of two values.  The content digest
below covers the parsed header and every payload byte, and is stable.
"""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path


def safetensors_content(path: Path) -> tuple[dict, str]:
    """Return the parsed header and the SHA-256 of the tensor payload."""
    data = Path(path).read_bytes()
    header_length = struct.unpack("<Q", data[:8])[0]
    header = json.loads(data[8 : 8 + header_length])
    return header, hashlib.sha256(data[8 + header_length :]).hexdigest()


def content_digest(path: Path) -> str:
    """SHA-256 over the canonical header JSON followed by the payload digest."""
    header, payload = safetensors_content(path)
    canonical = json.dumps(header, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256((canonical + "\n" + payload).encode("utf-8")).hexdigest()


def content_equal(left: Path, right: Path) -> bool:
    return safetensors_content(left) == safetensors_content(right)
