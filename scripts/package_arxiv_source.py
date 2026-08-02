#!/usr/bin/env python3
"""Build a self-contained arXiv source directory from generated outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / "paper"


def copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--paper-dir",
        type=Path,
        default=PAPER,
        help="Directory containing manuscript.tex (default: paper/).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Destination directory (default: <paper-dir>/arxiv_source).",
    )
    args = parser.parse_args()
    paper_dir = args.paper_dir.resolve()
    dest = (args.output or (paper_dir / "arxiv_source")).resolve()

    if dest.exists():
        for child in sorted(dest.rglob("*"), reverse=True):
            if child.is_file() or child.is_symlink():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
    dest.mkdir(parents=True, exist_ok=True)
    copy(paper_dir / "manuscript.tex", dest / "manuscript.tex")
    copy(PAPER / "references.bib", dest / "references.bib")
    for figure in sorted((PAPER / "figures").glob("*.pdf")):
        copy(figure, dest / "figures" / figure.name)
    (dest / "00README.XXX").write_text(
        "Main file: manuscript.tex\nPreferred compiler: XeLaTeX\n"
        "The bibliography has already been rendered into manuscript.tex by Pandoc citeproc; "
        "references.bib is included for auditability.\n",
        encoding="utf-8",
    )
    manifest = {}
    for path in sorted(p for p in dest.rglob("*") if p.is_file()):
        manifest[str(path.relative_to(dest))] = {
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    (dest / "source-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
