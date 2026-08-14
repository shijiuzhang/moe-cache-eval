#!/usr/bin/env python3
"""Generate one real M1 evidence bundle for cross-platform CI verification."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from oicap.calibration import calibrate, load_calibration
from oicap.contracts import load_contracts
from oicap.evidence import write_bundle
from oicap.runner import execute_load_point
from oicap.test_server import DeterministicServer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    contracts = load_contracts(args.benchmark)
    asyncio.run(calibrate(contracts, args.calibration))
    reference = load_calibration(args.calibration, contracts.measurement_identity)
    with DeterministicServer() as server:
        result = asyncio.run(execute_load_point(contracts, server.endpoint))
        write_bundle(
            args.output,
            contracts,
            result,
            server.endpoint,
            reference,
            invocation=["oicap", "run", "<benchmark>", "--endpoint", "<ci-local>"],
        )


if __name__ == "__main__":
    main()
