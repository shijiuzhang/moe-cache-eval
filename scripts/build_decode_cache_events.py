#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moe_controller.convert import convert_decode_trace


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build FCFS union-deduplicated decode cache events."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--batch-size", type=int, required=True)
    parser.add_argument(
        "--queue-order",
        choices=("source", "category_round_robin"),
        default="category_round_robin",
    )
    parser.add_argument(
        "--category-field",
        default="workload_archetype",
    )
    parser.add_argument(
        "--include-category",
        action="append",
        dest="include_categories",
        help="Only include this workload category; repeat as needed.",
    )
    parser.add_argument(
        "--include-request-id-file",
        type=Path,
        help="UTF-8 file containing one source request ID per line.",
    )
    parser.add_argument(
        "--requests-per-category",
        type=int,
        help="Deterministically retain at most this many requests per category.",
    )
    parser.add_argument(
        "--arrival-offset-field",
        help=(
            "Dot-separated path inside source metadata, e.g. "
            "collection.arrival_offset_steps."
        ),
    )
    parser.add_argument(
        "--arrival-offset-map",
        type=Path,
        help="JSON object mapping source request ID to an arrival step.",
    )
    parser.add_argument("--skip-source-checksums", action="store_true")
    args = parser.parse_args()
    output = convert_decode_trace(
        args.source,
        args.output,
        batch_size=args.batch_size,
        queue_order=args.queue_order,
        category_field=args.category_field,
        include_categories=(
            tuple(args.include_categories)
            if args.include_categories
            else None
        ),
        include_request_ids=(
            tuple(
                line.strip()
                for line in args.include_request_id_file.read_text(
                    encoding="utf-8"
                ).splitlines()
                if line.strip()
            )
            if args.include_request_id_file
            else None
        ),
        requests_per_category=args.requests_per_category,
        arrival_offset_field=args.arrival_offset_field,
        arrival_offset_map=(
            {
                str(key): int(value)
                for key, value in json.loads(
                    args.arrival_offset_map.read_text(encoding="utf-8")
                ).items()
            }
            if args.arrival_offset_map
            else None
        ),
        verify_source_checksums=not args.skip_source_checksums,
    )
    print(output)


if __name__ == "__main__":
    main()
