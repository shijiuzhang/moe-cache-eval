#!/usr/bin/env python3
"""Create a machine-readable attribution ledger from frozen source manifests."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTERPRISE = ROOT / "data/enterprise_proxy_1k/SOURCE_MANIFEST.json"
INDUSTRIAL = ROOT / "data/industrial_public/SOURCE_MANIFEST.json"
OUTPUT = ROOT / "paper/artifact_attributions.csv"

D1_ENTERPRISE = {
    "gorilla-llm/Berkeley-Function-Calling-Leaderboard",
    "nguha/legalbench",
    "xlang-ai/Spider2",
    "zai-org/LongBench",
}
D1_INDUSTRIAL = {"hai_23_05", "pronto", "packaging_alarms", "petrobras_3w", "ofbiz_manufacturing"}


def main() -> None:
    enterprise = json.loads(ENTERPRISE.read_text(encoding="utf-8"))
    industrial_manifest = json.loads(INDUSTRIAL.read_text(encoding="utf-8"))
    rows: list[dict[str, str]] = []
    for source_id in sorted(D1_ENTERPRISE):
        item = enterprise[source_id]
        rows.append({
            "source_id": source_id,
            "title": source_id,
            "url": item["url"],
            "revision": "see ControllerProbe-D1 source manifest/hash",
            "license": item["license"],
            "redistribution": item["usage"],
            "required_notice": item["note"],
            "controller_probe_d1": "yes",
        })
    indexed = {item["id"]: item for item in industrial_manifest["sources"]}
    for source_id in sorted(D1_INDUSTRIAL):
        item = indexed[source_id]
        rows.append({
            "source_id": source_id,
            "title": item["title"],
            "url": item["official_url"],
            "revision": str(item.get("revision") or item.get("version") or ""),
            "license": str(item["license"].get("spdx") or "UNVERIFIED"),
            "redistribution": item["redistribution"],
            "required_notice": item["license"].get("note", ""),
            "controller_probe_d1": "yes",
        })
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
