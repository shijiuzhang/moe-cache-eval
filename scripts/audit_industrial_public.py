#!/usr/bin/env python3
"""Inventory locally acquired IndustrialPublic files and verify frozen inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "industrial_public"
MANIFEST_PATH = DATA_DIR / "SOURCE_MANIFEST.json"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
DEFAULT_OUTPUT = SNAPSHOT_DIR / "local_snapshot.json"


def digest(path: Path, algorithm: str = "sha256") -> str:
    hasher = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def git_head(path: Path) -> str | None:
    if not (path / ".git").is_dir():
        return None
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=path, text=True
    ).strip()


def is_lfs_pointer(path: Path) -> bool:
    if path.stat().st_size > 1024:
        return False
    try:
        prefix = path.read_bytes()[:200]
    except OSError:
        return False
    return prefix.startswith(b"version https://git-lfs.github.com/spec/v1")


def inventory_source(source: dict[str, Any]) -> dict[str, Any]:
    directory = DATA_DIR / source["local_path"]
    if not directory.is_dir():
        return {
            "source_id": source["id"],
            "status": "not_present",
            "path": source["local_path"],
            "file_count": 0,
            "total_bytes": 0,
            "files": [],
        }
    paths = sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(directory).parts
    )
    files = []
    pointer_count = 0
    for path in paths:
        relative = path.relative_to(directory).as_posix()
        pointer = is_lfs_pointer(path)
        pointer_count += int(pointer)
        files.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "sha256": digest(path),
                "git_lfs_pointer": pointer,
            }
        )
    expected_revision = source.get("revision")
    actual_revision = git_head(directory)
    revision_ok = (
        actual_revision is None
        or expected_revision is None
        or actual_revision == expected_revision
    )
    direct_checks = []
    if source["retrieval"]["kind"] == "direct_files":
        by_name = {item["path"]: item for item in files}
        for expected in source["retrieval"]["files"]:
            actual = by_name.get(expected["name"])
            expected_checksum = expected.get("checksum")
            checksum_ok = None
            if actual is not None and expected_checksum is not None:
                algorithm, value = expected_checksum.split(":", 1)
                checksum_ok = digest(
                    directory / expected["name"], algorithm
                ) == value
            direct_checks.append(
                {
                    "name": expected["name"],
                    "present": actual is not None,
                    "size_ok": (
                        None
                        if actual is None or expected.get("size") is None
                        else actual["size"] == expected["size"]
                    ),
                    "checksum_ok": checksum_ok,
                }
            )
    complete = bool(paths) and revision_ok and pointer_count == 0
    if direct_checks:
        complete = complete and all(
            check["present"]
            and check["size_ok"] is not False
            and check["checksum_ok"] is not False
            for check in direct_checks
        )
    return {
        "source_id": source["id"],
        "status": "verified" if complete else "incomplete",
        "path": source["local_path"],
        "expected_revision": expected_revision,
        "actual_revision": actual_revision,
        "revision_ok": revision_ok,
        "file_count": len(files),
        "total_bytes": sum(item["size"] for item in files),
        "git_lfs_pointer_count": pointer_count,
        "direct_file_checks": direct_checks,
        "files": files,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="snapshot JSON path",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    sources = [
        inventory_source(source) for source in manifest["sources"]
    ]
    snapshot = {
        "snapshot_version": "industrial-public-local-snapshot-v0.1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "manifest_sha256": digest(MANIFEST_PATH),
        "summary": {
            "verified": sum(row["status"] == "verified" for row in sources),
            "incomplete": sum(
                row["status"] == "incomplete" for row in sources
            ),
            "not_present": sum(
                row["status"] == "not_present" for row in sources
            ),
            "total_bytes": sum(row["total_bytes"] for row in sources),
        },
        "sources": sources,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(snapshot["summary"], indent=2))
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
