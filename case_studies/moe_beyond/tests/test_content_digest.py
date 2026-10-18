"""Product-driven tests for the rebuild-stable safetensors digest (D-003)."""

from __future__ import annotations

import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

CASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CASE_DIR))

from content_digest import content_digest, content_equal  # noqa: E402


def _safetensors_bytes(header: str, payload: bytes) -> bytes:
    raw = header.encode("utf-8")
    return struct.pack("<Q", len(raw)) + raw + payload


TENSOR = '"a":{"dtype":"F32","shape":[2],"data_offsets":[0,8]}'
PAYLOAD = struct.pack("<2f", 1.0, -0.0)


class ContentDigestTests(unittest.TestCase):
    def _write(self, tmp: str, name: str, header: str, payload: bytes) -> Path:
        path = Path(tmp) / name
        path.write_bytes(_safetensors_bytes(header, payload))
        return path

    def test_metadata_key_order_does_not_change_the_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            one = self._write(tmp, "1", '{"__metadata__":{"schema":"s","schema_version":"1"},' + TENSOR + "}", PAYLOAD)
            two = self._write(tmp, "2", '{"__metadata__":{"schema_version":"1","schema":"s"},' + TENSOR + "}", PAYLOAD)
            self.assertNotEqual(one.read_bytes(), two.read_bytes())
            self.assertTrue(content_equal(one, two))
            self.assertEqual(content_digest(one), content_digest(two))

    def test_any_payload_byte_or_header_field_changes_the_digest(self) -> None:
        header = '{"__metadata__":{"schema":"s"},' + TENSOR + "}"
        with tempfile.TemporaryDirectory() as tmp:
            base = self._write(tmp, "base", header, PAYLOAD)
            # +0.0 instead of -0.0: numerically equal, one byte different.
            signed_zero = self._write(tmp, "zero", header, struct.pack("<2f", 1.0, 0.0))
            other_meta = self._write(tmp, "meta", header.replace('"s"', '"t"'), PAYLOAD)
            self.assertFalse(content_equal(base, signed_zero))
            self.assertNotEqual(content_digest(base), content_digest(signed_zero))
            self.assertNotEqual(content_digest(base), content_digest(other_meta))


if __name__ == "__main__":
    unittest.main()
