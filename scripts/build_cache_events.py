#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moe_controller.convert import convert_prefill_trace


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert frozen MoE router traces into cache event traces."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--prefill-chunk-size",
        type=int,
        default=128,
        help="Tokens grouped into one prefill forward cycle (default: 128).",
    )
    parser.add_argument(
        "--skip-source-checksums",
        action="store_true",
        help="Skip verification of the frozen input shards.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = convert_prefill_trace(
        args.source,
        args.output,
        prefill_chunk_size=args.prefill_chunk_size,
        verify_source_checksums=not args.skip_source_checksums,
    )
    print(output)


if __name__ == "__main__":
    main()
