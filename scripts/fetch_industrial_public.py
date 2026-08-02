#!/usr/bin/env python3
"""Fetch frozen, publication-eligible IndustrialPublic upstream sources.

The script deliberately refuses license-hold sources and never uses mirrors.
Direct downloads use curl's resume support; Git repositories are sparse
checkouts pinned to the commits in SOURCE_MANIFEST.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "industrial_public"
MANIFEST_PATH = DATA_DIR / "SOURCE_MANIFEST.json"
GIT = ["git", "-c", "http.proxy=", "-c", "https.proxy="]


def load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def digest(path: Path, algorithm: str) -> str:
    hasher = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def checksum_ok(path: Path, expected: str | None) -> bool:
    if not path.is_file():
        return False
    if expected is None:
        return True
    algorithm, value = expected.split(":", 1)
    return digest(path, algorithm) == value


def run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    printable = " ".join(command)
    print(f"+ {printable}", flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def fetch_direct(source: dict[str, Any], destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for item in source["retrieval"]["files"]:
        target = destination / item["name"]
        expected_size = item.get("size")
        expected_checksum = item.get("checksum")
        if (
            target.is_file()
            and (expected_size is None or target.stat().st_size == expected_size)
            and checksum_ok(target, expected_checksum)
        ):
            print(f"verified, skipping: {target}")
            continue
        run(
            [
                "curl",
                "--location",
                "--fail",
                "--retry",
                "5",
                "--retry-delay",
                "2",
                "--continue-at",
                "-",
                "--output",
                str(target),
                item["url"],
            ]
        )
        if expected_size is not None and target.stat().st_size != expected_size:
            raise RuntimeError(
                f"size mismatch for {target}: "
                f"{target.stat().st_size} != {expected_size}"
            )
        if not checksum_ok(target, expected_checksum):
            raise RuntimeError(f"checksum mismatch for {target}")


def assert_safe_existing_repo(destination: Path, repo_url: str) -> None:
    if not destination.exists():
        return
    if not (destination / ".git").is_dir():
        raise RuntimeError(
            f"refusing to overwrite non-Git directory: {destination}"
        )
    actual = subprocess.check_output(
        ["git", "remote", "get-url", "origin"],
        cwd=destination,
        text=True,
    ).strip()
    normalized = {actual.removesuffix(".git"), repo_url.removesuffix(".git")}
    if len(normalized) != 1:
        raise RuntimeError(
            f"origin mismatch for {destination}: {actual} != {repo_url}"
        )


def clone_sparse(
    source: dict[str, Any],
    destination: Path,
    *,
    use_lfs: bool,
) -> None:
    retrieval = source["retrieval"]
    repo_url = retrieval["repo_url"]
    assert_safe_existing_repo(destination, repo_url)
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        if use_lfs:
            environment["GIT_LFS_SKIP_SMUDGE"] = "1"
        run(
            [
                *GIT,
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                "--single-branch",
                "--branch",
                retrieval["branch"],
                repo_url,
                str(destination),
            ],
            env=environment,
        )
    run([*GIT, "sparse-checkout", "init", "--cone"], cwd=destination)
    run(
        [
            *GIT,
            "sparse-checkout",
            "set",
            "--skip-checks",
            *retrieval["paths"],
        ],
        cwd=destination,
    )
    run(
        [*GIT, "checkout", "--detach", source["revision"]],
        cwd=destination,
    )
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=destination, text=True
    ).strip()
    if head != source["revision"]:
        raise RuntimeError(f"revision mismatch for {source['id']}: {head}")
    if use_lfs:
        if shutil.which("git-lfs") is None:
            raise RuntimeError(
                "git-lfs is required for HAI. Install it with "
                "`brew install git-lfs`, then rerun this source."
            )
        run([*GIT, "lfs", "install", "--local"], cwd=destination)
        run(
            [
                *GIT,
                "lfs",
                "pull",
                f"--include={retrieval['lfs_include']}",
                "--exclude=",
            ],
            cwd=destination,
        )


def fetch_source(source: dict[str, Any]) -> None:
    if not source["publication_eligible"]:
        raise RuntimeError(
            f"{source['id']} is blocked by its publication/license gate"
        )
    if source["access"] != "automatic":
        raise RuntimeError(
            f"{source['id']} requires {source['access']}; "
            "follow the manifest instructions"
        )
    destination = DATA_DIR / source["local_path"]
    kind = source["retrieval"]["kind"]
    print(f"\n[{source['id']}] -> {destination}", flush=True)
    if kind == "direct_files":
        fetch_direct(source, destination)
    elif kind == "git_sparse":
        clone_sparse(source, destination, use_lfs=False)
    elif kind == "git_lfs_sparse":
        clone_sparse(source, destination, use_lfs=True)
    else:
        raise RuntimeError(f"unsupported retrieval kind: {kind}")


def print_sources(sources: list[dict[str, Any]]) -> None:
    print(
        "source_id\tpublication\taccess\tlicense\tversion",
    )
    for source in sources:
        license_spec = source["license"]
        print(
            f"{source['id']}\t{source['publication_eligible']}\t"
            f"{source['access']}\t"
            f"{license_spec.get('spdx') or 'UNVERIFIED'}\t"
            f"{source['version']}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="*", help="source ids to fetch")
    parser.add_argument(
        "--eligible",
        action="store_true",
        help="fetch all automatic, publication-eligible sources",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list source gates without downloading",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = load_manifest()
    sources = manifest["sources"]
    by_id = {source["id"]: source for source in sources}
    if args.list:
        print_sources(sources)
        return 0
    selected = list(args.sources)
    if args.eligible:
        selected.extend(
            source["id"]
            for source in sources
            if source["publication_eligible"]
            and source["access"] == "automatic"
        )
    selected = list(dict.fromkeys(selected))
    if not selected:
        print("No sources selected. Use --list, --eligible, or source ids.")
        return 2
    unknown = sorted(set(selected) - set(by_id))
    if unknown:
        raise SystemExit(f"unknown source ids: {', '.join(unknown)}")
    failures: list[str] = []
    for source_id in selected:
        try:
            fetch_source(by_id[source_id])
        except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
            failures.append(source_id)
            print(f"ERROR [{source_id}]: {error}", file=sys.stderr)
    if failures:
        print(f"Failed sources: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
