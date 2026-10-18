"""Mechanical enforcement of the pre-registration (PREREG section 0).

Standard library only, so that the third-party harness can import it from its
own isolated environment.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

CASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CASE_DIR.parents[1]
THIRD_PARTY_ROOT = REPO_ROOT / "third_party" / "moe-beyond"


class PreregistrationError(RuntimeError):
    pass


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_lock(case_dir: Path = CASE_DIR) -> dict[str, str]:
    lock = case_dir / "PREREG.lock"
    if not lock.is_file():
        raise PreregistrationError("PREREG.lock is missing; analyses may not run.")
    values: dict[str, str] = {}
    for line in lock.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        key, _, value = line.partition(":")
        values[key.strip()] = value.strip()
    return values


def verify_prereg(case_dir: Path = CASE_DIR) -> dict[str, str]:
    """Refuse unless PREREG.md and INPUTS.sha256 match the lock exactly."""
    lock = read_lock(case_dir)
    prereg_sha = sha256_path(case_dir / "PREREG.md")
    if prereg_sha != lock.get("prereg_sha256"):
        raise PreregistrationError(
            f"PREREG.md hash {prereg_sha} does not match the lock."
        )
    inputs_sha = sha256_path(case_dir / "INPUTS.sha256")
    if inputs_sha != lock.get("inputs_manifest_sha256"):
        raise PreregistrationError(
            f"INPUTS.sha256 hash {inputs_sha} does not match the lock."
        )
    return lock


def frozen_input_hashes(case_dir: Path = CASE_DIR) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for line in (case_dir / "INPUTS.sha256").read_text(encoding="utf-8").splitlines():
        digest, _, relative = line.partition("  ")
        hashes[relative] = digest
    return hashes


def verify_third_party_files(
    relative_paths: list[str],
    *,
    third_party_root: Path = THIRD_PARTY_ROOT,
    case_dir: Path = CASE_DIR,
) -> dict[str, str]:
    """Check each used third-party file against the frozen list; return hashes."""
    frozen = frozen_input_hashes(case_dir)
    observed: dict[str, str] = {}
    for relative in relative_paths:
        if relative not in frozen:
            raise PreregistrationError(f"{relative} is not in INPUTS.sha256.")
        digest = sha256_path(third_party_root / relative)
        if digest != frozen[relative]:
            raise PreregistrationError(f"{relative} hash {digest} differs from the frozen list.")
        observed[relative] = digest
    return observed


def inputs_record(lock: dict[str, str], extra: dict[str, str] | None = None) -> dict:
    """The ``inputs`` block written into every result JSON."""
    return {
        "prereg_sha256": lock["prereg_sha256"],
        "prereg_commit": lock["prereg_commit"],
        "inputs_manifest_sha256": lock["inputs_manifest_sha256"],
        "third_party_commit": lock["third_party_commit"],
        "files": dict(sorted((extra or {}).items())),
    }
