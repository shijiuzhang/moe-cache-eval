#!/usr/bin/env python3
"""Assemble the paper Markdown without shortening its body and run Pandoc.

The source sections remain authoritative. This script removes only repeated
draft labels/title furniture, then concatenates every section and the related-
work appendix. It deliberately performs no prose compression.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / "paper"
SECTION_NAMES = [
    (1, "abstract_intro"),
    (2, "evaluation_model"),
    (3, "experimental_setup"),
    (4, "axis1_replay_semantics"),
    (5, "axis2_workload_contamination"),
    (6, "axis3_operating_regimes"),
    (7, "gap_decomposition"),
    (8, "scoped_negative_results"),
    (9, "what_survives"),
    (10, "benchmarking_recommendations"),
    (11, "limitations"),
    (12, "related_work"),
    (13, "artifacts_conclusion"),
]
APPENDIX_NAME = "APPENDIX_RELATED_WORK_AUDIT.md"


def section_paths(paper_dir: Path):
    return [paper_dir / f"{i:02d}_{name}.md" for i, name in SECTION_NAMES]

TEXT_MATH = {
    "ρ": r"$\rho$",
    "≈": "approximately ",
    "→": r"$\rightarrow$",
    "↓": r"$\downarrow$",
    "≥": r"$\geq$",
    "≤": r"$\leq$",
    "∈": r"$\in$",
    "∩": r"$\cap$",
    "⋃": r"$\bigcup$",
    "⌊": r"$\lfloor$",
    "⌋": r"$\rfloor$",
}
CODE_ASCII = {
    "ρ": "rho",
    "≈": "~=",
    "→": "->",
    "↓": "down",
    "≥": ">=",
    "≤": "<=",
    "∈": "in",
    "∩": "intersect",
    "⋃": "union",
    "⌊": "floor(",
    "⌋": ")",
}


def clean_section(path: Path, first: bool = False) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    title_lines_removed = 0
    in_draft_label = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("*Draft v"):
            in_draft_label = not stripped.endswith(".*")
            continue
        if in_draft_label:
            if stripped.endswith(".*"):
                in_draft_label = False
            continue
        if first and title_lines_removed < 2 and line.startswith("#"):
            title_lines_removed += 1
            continue
        if first and line.strip() == "---" and not out:
            continue
        out.append(line)
    text = "\n".join(out).strip()
    return text + "\n"


def replace_symbols(text: str) -> str:
    """Keep mathematical Unicode out of text/code fonts in the TeX build."""
    text = text.replace("10⁻⁵", r"$10^{-5}$")
    converted: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            converted.append(line)
            continue
        parts = [line] if in_fence else line.split("`")
        for index, part in enumerate(parts):
            mapping = CODE_ASCII if in_fence or index % 2 == 1 else TEXT_MATH
            for source, target in mapping.items():
                part = part.replace(source, target)
            parts[index] = part
        converted.append("".join(parts) if in_fence else "`".join(parts))
    return "\n".join(converted) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-pandoc", action="store_true")
    parser.add_argument(
        "--paper-dir",
        default=None,
        help="Directory holding the section files (default: paper/). "
             "Use e.g. paper/v2 to build a variant without touching the default.",
    )
    args = parser.parse_args()

    paper_dir = Path(args.paper_dir).resolve() if args.paper_dir else PAPER
    sections = section_paths(paper_dir)
    appendix = paper_dir / APPENDIX_NAME
    missing = [str(p) for p in [*sections, appendix] if not p.exists()]
    if missing:
        raise SystemExit(f"missing manuscript sections: {missing}")

    assembled = [clean_section(path, first=(idx == 0)) for idx, path in enumerate(sections)]
    assembled.append(clean_section(appendix))
    extra = paper_dir / "APPENDIX_B_SUPPLEMENTARY.md"
    if extra.exists():
        assembled.append(clean_section(extra))
    source = paper_dir / "manuscript_source.md"
    source.write_text(replace_symbols("\n\n".join(assembled)), encoding="utf-8")

    if args.no_pandoc:
        return

    subprocess.run(
        [
            "pandoc",
            str(paper_dir / "manuscript.yaml" if (paper_dir / "manuscript.yaml").exists() else PAPER / "manuscript.yaml"),
            str(source),
            "--from=markdown+pipe_tables+strikeout+tex_math_dollars",
            "--standalone",
            "--citeproc",
            "--resource-path=.",
            "--output",
            str(paper_dir / "manuscript.tex"),
        ],
        cwd=ROOT,
        check=True,
    )


if __name__ == "__main__":
    main()
