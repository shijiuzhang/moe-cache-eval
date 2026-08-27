from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from .calibration import calibrate, load_calibration
from .contracts import ContractError, load_contracts
from .evidence import verify_bundle, write_bundle
from .runner import execute_load_point


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="oicap")
    sub = root.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="validate and hash a benchmark contract")
    validate.add_argument("benchmark")

    calibration = sub.add_parser("calibrate", help="measure the local runner noise floor")
    calibration.add_argument("benchmark")
    calibration.add_argument("--output", required=True)

    run = sub.add_parser("run", help="record one load point without issuing an SLO verdict")
    run.add_argument("benchmark")
    run.add_argument("--endpoint", required=True)
    run.add_argument("--calibration", required=True)
    run.add_argument("--output", required=True)

    verify = sub.add_parser(
        "verify", help="check unsigned bundle internal consistency and recompute summaries"
    )
    verify.add_argument("bundle")
    verify.add_argument(
        "--calibration-source",
        help="independently check the referenced calibration bundle manifest",
    )
    return root


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    try:
        if args.command == "validate":
            contracts = load_contracts(args.benchmark)
            _print(
                {
                    "ok": True,
                    "contract_hashes": contracts.hashes,
                    "identity": contracts.identity,
                }
            )
        elif args.command == "calibrate":
            contracts = load_contracts(args.benchmark)
            output = asyncio.run(calibrate(contracts, args.output))
            record = json.loads((Path(output) / "calibration.json").read_text())
            valid = bool(record.get("valid"))
            _print(
                {
                    "ok": valid,
                    "command_completed": True,
                    "calibration_valid": valid,
                    "invalid_reasons": record.get("invalid_reasons", []),
                    "calibration_bundle": str(output),
                }
            )
            if not valid:
                raise SystemExit(2)
        elif args.command == "run":
            contracts = load_contracts(args.benchmark)
            calibration = load_calibration(args.calibration, contracts.measurement_identity)
            result = asyncio.run(
                execute_load_point(
                    contracts,
                    args.endpoint,
                    api_key=os.getenv("OICAP_API_KEY"),
                )
            )
            output = write_bundle(
                args.output,
                contracts,
                result,
                args.endpoint,
                calibration,
                invocation=_sanitized_invocation(args),
            )
            _print({"ok": True, "evidence_bundle": str(output)})
        elif args.command == "verify":
            result = verify_bundle(args.bundle, args.calibration_source)
            _print(result)
            if not result["ok"]:
                raise SystemExit(2)
    except (ContractError, ValueError, OSError) as exc:
        _print({"ok": False, "error": str(exc)}, stream=sys.stderr)
        raise SystemExit(2) from exc


def _print(value: object, stream: object | None = None) -> None:
    print(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2),
        file=stream if stream is not None else sys.stdout,
    )


def _sanitized_invocation(args: argparse.Namespace) -> list[str]:
    values = ["oicap", str(args.command)]
    if hasattr(args, "benchmark"):
        values.append("<benchmark>")
    if hasattr(args, "endpoint"):
        from .evidence import _redact_endpoint

        values.extend(["--endpoint", _redact_endpoint(str(args.endpoint))])
    if hasattr(args, "calibration"):
        values.extend(["--calibration", "<calibration-bundle>"])
    if hasattr(args, "output"):
        values.extend(["--output", "<output-bundle>"])
    return values
