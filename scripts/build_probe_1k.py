#!/usr/bin/env python3
"""Build the frozen Probe-1K corpus used by the MoE routing study.

The builder intentionally uses the Hugging Face dataset-server API instead of
`datasets`, so only selected rows are cached and no hidden preprocessing code is
executed. Every final record carries its source row, repository revision,
license note, pair relationships, and content hash.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import random
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from huggingface_hub import HfApi
from transformers import AutoTokenizer


SEED = 20260727
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
BBH_UPSTREAM_REVISION = "9ee07bd481feebf959a6b59d61ea57bdcf30964d"

EXPECTED_CATEGORY_COUNTS = {
    "natural_text": 160,
    "mmlu_pro": 160,
    "bbh": 160,
    "math": 120,
    "code": 100,
    "long_context": 60,
    "multilingual": 40,
    "control": 200,
}
EXPECTED_SPLIT_COUNTS = {
    "discovery": 600,
    "confirmatory": 200,
    "perturbation": 200,
}
ORIGINAL_CONFIRMATORY = {
    "natural_text": 40,
    "mmlu_pro": 40,
    "bbh": 40,
    "math": 30,
    "code": 25,
    "long_context": 15,
    "multilingual": 10,
}
CONTROL_SEEDS = {
    "mmlu_pro": 30,
    "bbh": 25,
    "math": 20,
    "long_context": 10,
    "multilingual": 15,
}

SOURCE_SPECS = {
    "Salesforce/wikitext": {
        "license": "cc-by-sa-3.0",
        "url": "https://huggingface.co/datasets/Salesforce/wikitext",
        "note": "Dataset card license; individual Wikipedia text remains attribution/share-alike.",
    },
    "ccdv/arxiv-summarization": {
        "license": "not_specified",
        "url": "https://huggingface.co/datasets/ccdv/arxiv-summarization",
        "note": "Dataset card does not declare a repository-wide license; preserve paper provenance.",
    },
    "common-pile/project_gutenberg": {
        "license": "public-domain-with-jurisdiction-caveat",
        "url": "https://huggingface.co/datasets/common-pile/project_gutenberg",
        "note": "Project Gutenberg texts are generally public domain in the US; status can vary by jurisdiction.",
    },
    "OpenAssistant/oasst2": {
        "license": "apache-2.0",
        "url": "https://huggingface.co/datasets/OpenAssistant/oasst2",
        "note": "Human-generated conversation trees; only reviewed, non-deleted, non-synthetic English paths are selected.",
    },
    "TIGER-Lab/MMLU-Pro": {
        "license": "mit",
        "url": "https://huggingface.co/datasets/TIGER-Lab/MMLU-Pro",
        "note": "Dataset card license.",
    },
    "lighteval/big_bench_hard": {
        "license": "mit",
        "url": "https://huggingface.co/datasets/lighteval/big_bench_hard",
        "note": "BIG-Bench Hard derivative; upstream BIG-Bench repository is MIT.",
    },
    "suzgunmirac/BIG-Bench-Hard": {
        "license": "mit",
        "url": "https://github.com/suzgunmirac/BIG-Bench-Hard",
        "note": "Pinned upstream fallback for word_sorting because the dataset-server endpoint returns HTTP 501.",
    },
    "openai/gsm8k": {
        "license": "mit",
        "url": "https://huggingface.co/datasets/openai/gsm8k",
        "note": "Dataset card license.",
    },
    "HuggingFaceH4/MATH-500": {
        "license": "not_specified",
        "url": "https://huggingface.co/datasets/HuggingFaceH4/MATH-500",
        "note": "Dataset card currently does not declare a license.",
    },
    "lighteval/code_generation_lite": {
        "license": "cc-as-declared-on-card",
        "url": "https://huggingface.co/datasets/lighteval/code_generation_lite",
        "note": "Dataset card declares `cc`; underlying contest statements can have platform-specific terms.",
    },
    "NVIDIA/RULER": {
        "license": "apache-2.0",
        "url": "https://github.com/NVIDIA/RULER",
        "note": "Locally generated synthetic data; generator commit and compatibility patch are recorded.",
    },
    "li-lab/MMLU-ProX": {
        "license": "mit",
        "url": "https://huggingface.co/datasets/li-lab/MMLU-ProX",
        "note": "EMNLP 2025 multilingual benchmark; English and Chinese are joined on shared question identifiers and checked fields.",
    },
}

BBH_CONFIGS = [
    "boolean_expressions",
    "causal_judgement",
    "date_understanding",
    "disambiguation_qa",
    "dyck_languages",
    "formal_fallacies",
    "geometric_shapes",
    "hyperbaton",
    "logical_deduction_five_objects",
    "logical_deduction_seven_objects",
    "logical_deduction_three_objects",
    "movie_recommendation",
    "multistep_arithmetic_two",
    "navigate",
    "object_counting",
    "penguins_in_a_table",
    "reasoning_about_colored_objects",
    "ruin_names",
    "salient_translation_error_detection",
    "snarks",
    "sports_understanding",
    "temporal_sequences",
    "tracking_shuffled_objects_five_objects",
    "tracking_shuffled_objects_seven_objects",
    "tracking_shuffled_objects_three_objects",
    "web_of_lies",
    "word_sorting",
]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", text).strip()


class DatasetServer:
    def __init__(self, cache_dir: Path, offline: bool = False) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.offline = offline
        self.last_network_request = 0.0

    def rows(
        self, dataset: str, config: str, split: str, offset: int, length: int
    ) -> dict[str, Any]:
        params = urllib.parse.urlencode(
            {
                "dataset": dataset,
                "config": config,
                "split": split,
                "offset": offset,
                "length": length,
            }
        )
        url = f"https://datasets-server.huggingface.co/rows?{params}"
        cache_path = self.cache_dir / f"{sha256_text(url)}.json"
        if cache_path.exists():
            with cache_path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        if self.offline:
            raise RuntimeError(f"Missing offline cache entry: {url}")

        last_error: Exception | None = None
        request = urllib.request.Request(
            url, headers={"User-Agent": "moe-hierarchy-lab-probe-builder/1.0"}
        )
        for attempt in range(6):
            try:
                elapsed = time.monotonic() - self.last_network_request
                if elapsed < 0.35:
                    time.sleep(0.35 - elapsed)
                self.last_network_request = time.monotonic()
                with urllib.request.urlopen(request, timeout=180) as response:
                    payload = json.load(response)
                tmp_path = cache_path.with_suffix(".tmp")
                tmp_path.write_text(canonical_json(payload), encoding="utf-8")
                os.replace(tmp_path, cache_path)
                return payload
            except urllib.error.HTTPError as error:
                last_error = error
                if error.code == 429:
                    retry_after = error.headers.get("Retry-After")
                    time.sleep(float(retry_after) if retry_after else 60.0)
                else:
                    time.sleep(min(2**attempt, 20))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                last_error = error
                time.sleep(min(2**attempt, 20))
        raise RuntimeError(f"Dataset-server request failed: {url}") from last_error

    def all_rows(
        self, dataset: str, config: str, split: str, page_size: int = 100
    ) -> list[dict[str, Any]]:
        first = self.rows(dataset, config, split, 0, page_size)
        rows = list(first["rows"])
        total = first["num_rows_total"]
        for offset in range(page_size, total, page_size):
            rows.extend(self.rows(dataset, config, split, offset, page_size)["rows"])
        return rows

    def url_json(self, url: str) -> Any:
        cache_path = self.cache_dir / f"{sha256_text(url)}.json"
        if cache_path.exists():
            return json.loads(cache_path.read_text(encoding="utf-8"))
        if self.offline:
            raise RuntimeError(f"Missing offline cache entry: {url}")
        request = urllib.request.Request(
            url, headers={"User-Agent": "moe-hierarchy-lab-probe-builder/1.0"}
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = json.load(response)
        tmp_path = cache_path.with_suffix(".tmp")
        tmp_path.write_text(canonical_json(payload), encoding="utf-8")
        os.replace(tmp_path, cache_path)
        return payload


@dataclass(frozen=True)
class SourceRef:
    dataset: str
    config: str
    split: str
    row_id: str | int


class ProbeBuilder:
    def __init__(
        self,
        api: DatasetServer,
        revisions: dict[str, str],
        ruler_dir: Path,
        ruler_revision: str,
    ) -> None:
        self.api = api
        self.revisions = revisions
        self.ruler_dir = ruler_dir
        self.ruler_revision = ruler_revision
        self.records: list[dict[str, Any]] = []

    def source(self, ref: SourceRef) -> dict[str, Any]:
        spec = SOURCE_SPECS[ref.dataset]
        revision = (
            self.ruler_revision
            if ref.dataset == "NVIDIA/RULER"
            else BBH_UPSTREAM_REVISION
            if ref.dataset == "suzgunmirac/BIG-Bench-Hard"
            else self.revisions[ref.dataset]
        )
        return {
            "dataset": ref.dataset,
            "config": ref.config,
            "split": ref.split,
            "row_id": ref.row_id,
            "revision": revision,
            "license": spec["license"],
            "url": spec["url"],
        }

    def add(
        self,
        *,
        record_id: str,
        text: str,
        prompt_text: str,
        category: str,
        domain: str,
        operation: str,
        language: str,
        source: SourceRef,
        reference_answer: str | list[str] | None = None,
        difficulty: str | None = None,
        format_name: str = "plain",
        metadata: dict[str, Any] | None = None,
        cross_lingual_pair_id: str | None = None,
    ) -> None:
        text = text.strip()
        prompt_text = prompt_text.strip()
        if not text or not prompt_text:
            raise ValueError(f"Empty text in {record_id}")
        self.records.append(
            {
                "id": record_id,
                "text": text,
                "prompt_text": prompt_text,
                "split": None,
                "category": category,
                "base_category": category,
                "domain": domain,
                "operation": operation,
                "language": language,
                "format": format_name,
                "difficulty": difficulty,
                "variant_type": "original",
                "pair_id": None,
                "pair_role": None,
                "cross_lingual_pair_id": cross_lingual_pair_id,
                "reference_answer": reference_answer,
                "source": self.source(source),
                "metadata": metadata or {},
            }
        )

    def natural_text(self) -> None:
        # Wikipedia: combine raw lines to restore paragraph-scale contexts.
        wiki_rows = self.api.all_rows(
            "Salesforce/wikitext", "wikitext-103-raw-v1", "validation"
        )
        chunks: list[tuple[int, str]] = []
        buffer: list[str] = []
        start = 0
        for item in wiki_rows:
            row_idx, line = item["row_idx"], item["row"]["text"].strip()
            if not line:
                continue
            if not buffer:
                start = row_idx
            buffer.append(line)
            joined = "\n".join(buffer)
            if len(joined) >= 1100:
                chunks.append((start, joined[:2600]))
                buffer = []
        rng = random.Random(SEED + 1)
        for index, (row_idx, text) in enumerate(rng.sample(chunks, 40)):
            self.add(
                record_id=f"p1k-natural-wikitext-{index:03d}",
                text=text,
                prompt_text=text,
                category="natural_text",
                domain="encyclopedic",
                operation="language_modeling",
                language="en",
                source=SourceRef(
                    "Salesforce/wikitext",
                    "wikitext-103-raw-v1",
                    "validation",
                    f"chunk-start-{row_idx}",
                ),
                metadata={"genre": "wikipedia", "construction": "consecutive_lines"},
            )

        # ArXiv abstracts: deterministic random offsets, rejecting tiny abstracts.
        first = self.api.rows(
            "ccdv/arxiv-summarization", "section", "test", 0, 1
        )
        total = first["num_rows_total"]
        page_size = 10
        offsets = list(range(0, total, page_size))
        random.Random(SEED + 2).shuffle(offsets)
        selected = []
        for offset in offsets:
            page = self.api.rows(
                "ccdv/arxiv-summarization", "section", "test", offset, page_size
            )
            for item in page["rows"]:
                abstract = item["row"]["abstract"].strip()
                if 500 <= len(abstract) <= 5000:
                    selected.append((item["row_idx"], abstract))
                    if len(selected) == 40:
                        break
            if len(selected) == 40:
                break
        for index, (row_idx, text) in enumerate(selected):
            self.add(
                record_id=f"p1k-natural-arxiv-{index:03d}",
                text=text,
                prompt_text=text,
                category="natural_text",
                domain="scientific",
                operation="language_modeling",
                language="en",
                source=SourceRef(
                    "ccdv/arxiv-summarization", "section", "test", row_idx
                ),
                metadata={"genre": "scientific_abstract"},
            )

        # Project Gutenberg: sample interior excerpts, away from boilerplate.
        first = self.api.rows(
            "common-pile/project_gutenberg", "default", "train", 0, 1
        )
        total = first["num_rows_total"]
        page_size = 5
        offsets = list(range(0, total, page_size))
        random.Random(SEED + 3).shuffle(offsets)
        selected = []
        seen = set()
        for offset in offsets:
            page = self.api.rows(
                "common-pile/project_gutenberg", "default", "train", offset, page_size
            )
            for item in page["rows"]:
                text = item["row"]["text"].strip()
                if len(text) < 4000:
                    continue
                center = len(text) // 2
                excerpt = text[max(0, center - 1000) : center + 1000].strip()
                digest = sha256_text(normalize_text(excerpt))
                if len(excerpt) >= 1400 and digest not in seen:
                    seen.add(digest)
                    selected.append(
                        (item["row_idx"], excerpt, item["row"].get("id"))
                    )
                if len(selected) == 40:
                    break
            if len(selected) == 40:
                break
        for index, (row_idx, text, book_id) in enumerate(selected):
            self.add(
                record_id=f"p1k-natural-gutenberg-{index:03d}",
                text=text,
                prompt_text=text,
                category="natural_text",
                domain="literary",
                operation="language_modeling",
                language="en",
                source=SourceRef(
                    "common-pile/project_gutenberg", "default", "train", row_idx
                ),
                metadata={
                    "genre": "literature",
                    "source_book_id": book_id,
                    "construction": "interior_excerpt",
                },
            )

        # OASST2 is depth-first ordered, so a page usually contains several
        # complete trees. Select reviewed English paths with at least two
        # user/assistant exchanges and conservative safety-label thresholds.
        first = self.api.rows(
            "OpenAssistant/oasst2", "default", "validation", 0, 1
        )
        page_size = 100
        page_offsets = list(range(0, first["num_rows_total"], page_size))
        random.Random(SEED + 4).shuffle(page_offsets)
        candidates: list[dict[str, Any]] = []
        seen_trees: set[str] = set()

        def safe_message(item: dict[str, Any]) -> bool:
            row = item["row"]
            if (
                row["lang"] != "en"
                or not row["review_result"]
                or row["deleted"]
                or row["synthetic"]
                or not row["text"].strip()
            ):
                return False
            detoxify = row.get("detoxify") or {}
            if any(
                float(detoxify.get(name, 0.0) or 0.0) > 0.10
                for name in (
                    "toxicity",
                    "severe_toxicity",
                    "obscene",
                    "identity_attack",
                    "insult",
                    "threat",
                    "sexual_explicit",
                )
            ):
                return False
            labels = row.get("labels") or {}
            label_values = dict(
                zip(
                    labels.get("name") or [],
                    labels.get("value") or [],
                    strict=False,
                )
            )
            return not any(
                float(label_values.get(name, 0.0) or 0.0) > 0.10
                for name in (
                    "spam",
                    "lang_mismatch",
                    "pii",
                    "not_appropriate",
                    "hate_speech",
                    "sexual_content",
                    "violence",
                )
            )

        def paths_from_page(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            valid = [item for item in items if safe_message(item)]
            by_id = {item["row"]["message_id"]: item for item in valid}
            children: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for item in valid:
                parent_id = item["row"]["parent_id"]
                if parent_id in by_id:
                    children[parent_id].append(item)

            def best_path(item: dict[str, Any], visited: set[str]) -> list[dict[str, Any]]:
                row = item["row"]
                message_id = row["message_id"]
                if message_id in visited:
                    return [item]
                expected_role = "assistant" if row["role"] == "prompter" else "prompter"
                branches = [
                    child
                    for child in children.get(message_id, [])
                    if child["row"]["role"] == expected_role
                ]
                branches.sort(
                    key=lambda child: (
                        child["row"]["rank"] is None,
                        child["row"]["rank"]
                        if child["row"]["rank"] is not None
                        else 10_000,
                        child["row"]["message_id"],
                    )
                )
                if not branches:
                    return [item]
                continuations = [
                    best_path(child, visited | {message_id}) for child in branches
                ]
                continuation = max(
                    continuations,
                    key=lambda path: (
                        len(path),
                        -sum(
                            node["row"]["rank"] or 0
                            for node in path
                            if node["row"]["role"] == "assistant"
                        ),
                    ),
                )
                return [item, *continuation]

            page_candidates = []
            roots = [
                item
                for item in valid
                if item["row"]["parent_id"] is None
                and item["row"]["role"] == "prompter"
            ]
            for root in sorted(roots, key=lambda item: item["row"]["message_id"]):
                path = best_path(root, set())[:6]
                if len(path) % 2:
                    path = path[:-1]
                if len(path) < 4:
                    continue
                text = "\n".join(
                    (
                        "User: " if node["row"]["role"] == "prompter" else "Assistant: "
                    )
                    + node["row"]["text"].strip()
                    for node in path
                )
                if 250 <= len(text) <= 6000:
                    page_candidates.append(
                        {
                            "tree_id": root["row"]["message_tree_id"],
                            "text": text,
                            "path": path,
                        }
                    )
            return page_candidates

        for offset in page_offsets:
            page = self.api.rows(
                "OpenAssistant/oasst2",
                "default",
                "validation",
                offset,
                page_size,
            )["rows"]
            page_candidates = paths_from_page(page)
            random.Random(f"{SEED}:oasst2:{offset}").shuffle(page_candidates)
            for candidate in page_candidates:
                if candidate["tree_id"] not in seen_trees:
                    seen_trees.add(candidate["tree_id"])
                    candidates.append(candidate)
            if len(candidates) >= 40:
                break
        if len(candidates) < 40:
            raise RuntimeError(
                f"Could only construct {len(candidates)} safe OASST2 conversations"
            )

        for index, candidate in enumerate(candidates[:40]):
            path = candidate["path"]
            row_indices = [item["row_idx"] for item in path]
            message_ids = [item["row"]["message_id"] for item in path]
            self.add(
                record_id=f"p1k-natural-oasst2-{index:03d}",
                text=candidate["text"],
                prompt_text=candidate["text"],
                category="natural_text",
                domain="dialogue",
                operation="language_modeling",
                language="en",
                source=SourceRef(
                    "OpenAssistant/oasst2",
                    "default",
                    "validation",
                    f"tree:{candidate['tree_id']}",
                ),
                metadata={
                    "genre": "human_assistant_dialogue",
                    "message_tree_id": candidate["tree_id"],
                    "message_ids": message_ids,
                    "source_row_indices": row_indices,
                    "turn_count": len(path),
                    "construction": "reviewed_safe_longest_alternating_path",
                },
            )

    def mmlu_pro(self) -> None:
        rows = self.api.all_rows("TIGER-Lab/MMLU-Pro", "default", "test")
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in rows:
            groups[item["row"]["category"]].append(item)
        categories = sorted(groups)
        extras = set(random.Random(SEED + 10).sample(categories, 160 % len(categories)))
        for category in categories:
            quota = 160 // len(categories) + int(category in extras)
            chosen = random.Random(f"{SEED}:mmlu:{category}").sample(
                groups[category], quota
            )
            for item in chosen:
                row = item["row"]
                options = "\n".join(
                    f"{LETTERS[i]}. {option}" for i, option in enumerate(row["options"])
                )
                prompt = f"Question: {row['question'].strip()}\nOptions:\n{options}"
                reasoning = row.get("cot_content", "").strip()
                reference = f"Reference answer: {row['answer']}"
                if reasoning:
                    reference += f"\nReference reasoning:\n{reasoning}"
                self.add(
                    record_id=f"p1k-mmlu-pro-{int(row['question_id']):06d}",
                    text=f"{prompt}\n\n{reference}",
                    prompt_text=prompt,
                    category="mmlu_pro",
                    domain=category,
                    operation="knowledge_reasoning",
                    language="en",
                    source=SourceRef(
                        "TIGER-Lab/MMLU-Pro",
                        "default",
                        "test",
                        item["row_idx"],
                    ),
                    reference_answer=row["answer"],
                    difficulty="unspecified",
                    format_name="multiple_choice_with_reasoning",
                    metadata={
                        "question_id": row["question_id"],
                        "answer_index": row["answer_index"],
                        "source_subset": row.get("src"),
                    },
                )

    @staticmethod
    def bbh_operation(config: str) -> str:
        if "temporal" in config or "date_" in config:
            return "temporal_reasoning"
        if any(x in config for x in ("tracking_", "navigate", "geometric")):
            return "spatial_state_tracking"
        if any(x in config for x in ("arithmetic", "counting")):
            return "quantitative_reasoning"
        if any(
            x in config
            for x in (
                "boolean",
                "dyck",
                "fallacies",
                "logical_deduction",
                "web_of_lies",
                "word_sorting",
            )
        ):
            return "symbolic_deduction"
        if "causal" in config:
            return "causal_reasoning"
        if any(
            x in config
            for x in (
                "disambiguation",
                "hyperbaton",
                "ruin_names",
                "salient_translation",
                "snarks",
            )
        ):
            return "language_pragmatics"
        return "commonsense_reasoning"

    def bbh(self) -> None:
        extra_configs = set(
            random.Random(SEED + 20).sample(BBH_CONFIGS, 160 % len(BBH_CONFIGS))
        )
        for config in BBH_CONFIGS:
            quota = 160 // len(BBH_CONFIGS) + int(config in extra_configs)
            if config == "word_sorting":
                url = (
                    "https://raw.githubusercontent.com/"
                    "suzgunmirac/BIG-Bench-Hard/"
                    f"{BBH_UPSTREAM_REVISION}/bbh/word_sorting.json"
                )
                examples = self.api.url_json(url)["examples"]
                rows = [
                    {"row_idx": index, "row": {"id": index, **row}}
                    for index, row in enumerate(examples)
                ]
                source_dataset = "suzgunmirac/BIG-Bench-Hard"
                source_split = "bbh/word_sorting.json"
            else:
                rows = self.api.rows(
                    "lighteval/big_bench_hard", config, "train", 0, 100
                )["rows"]
                source_dataset = "lighteval/big_bench_hard"
                source_split = "train"
            chosen = random.Random(f"{SEED}:bbh:{config}").sample(rows, quota)
            for item in chosen:
                row = item["row"]
                prompt = f"Question:\n{row['input'].strip()}"
                target = str(row["target"]).strip()
                self.add(
                    record_id=f"p1k-bbh-{config}-{int(item['row_idx']):03d}",
                    text=f"{prompt}\n\nReference answer: {target}",
                    prompt_text=prompt,
                    category="bbh",
                    domain=config,
                    operation=self.bbh_operation(config),
                    language="en",
                    source=SourceRef(
                        source_dataset,
                        config,
                        source_split,
                        item["row_idx"],
                    ),
                    reference_answer=target,
                    format_name="task_with_reference",
                    metadata={"upstream_id": row.get("id")},
                )

    def math(self) -> None:
        gsm_rows = self.api.all_rows("openai/gsm8k", "main", "test")
        for item in random.Random(SEED + 30).sample(gsm_rows, 60):
            row = item["row"]
            prompt = f"Problem:\n{row['question'].strip()}"
            solution = row["answer"].strip()
            final = solution.rsplit("####", 1)[-1].strip()
            self.add(
                record_id=f"p1k-math-gsm8k-{int(item['row_idx']):04d}",
                text=f"{prompt}\n\nReference solution:\n{solution}",
                prompt_text=prompt,
                category="math",
                domain="grade_school_math",
                operation="quantitative_reasoning",
                language="en",
                source=SourceRef("openai/gsm8k", "main", "test", item["row_idx"]),
                reference_answer=final,
                difficulty="grade_school",
                format_name="problem_with_solution",
                metadata={"math_source": "gsm8k"},
            )

        math_rows = self.api.all_rows("HuggingFaceH4/MATH-500", "default", "test")
        for item in random.Random(SEED + 31).sample(math_rows, 60):
            row = item["row"]
            prompt = f"Problem:\n{row['problem'].strip()}"
            solution = row["solution"].strip()
            self.add(
                record_id=f"p1k-math-math500-{int(item['row_idx']):03d}",
                text=f"{prompt}\n\nReference solution:\n{solution}",
                prompt_text=prompt,
                category="math",
                domain=row["subject"],
                operation="symbolic_quantitative_reasoning",
                language="en",
                source=SourceRef(
                    "HuggingFaceH4/MATH-500",
                    "default",
                    "test",
                    item["row_idx"],
                ),
                reference_answer=str(row["answer"]),
                difficulty=str(row["level"]),
                format_name="problem_with_solution",
                metadata={
                    "math_source": "math_500",
                    "unique_id": row["unique_id"],
                },
            )

    def code(self) -> None:
        # The API also returns compressed private tests and a 100-row page can
        # exceed 500 MB. Freeze a 300-row candidate pool, immediately project
        # it to public statement metadata, and never retain private tests in
        # the in-memory or final corpus.
        rows = []
        retained_fields = (
            "question_title",
            "question_content",
            "platform",
            "question_id",
            "contest_id",
            "contest_date",
            "starter_code",
            "difficulty",
        )
        for offset in (0, 100, 200):
            payload = self.api.rows(
                "lighteval/code_generation_lite",
                "release_latest",
                "test",
                offset,
                100,
            )
            rows.extend(
                {
                    "row_idx": item["row_idx"],
                    "row": {
                        field: item["row"].get(field)
                        for field in retained_fields
                    },
                }
                for item in payload["rows"]
            )
            del payload
            gc.collect()
        random.Random(SEED + 40).shuffle(rows)
        quotas = {"easy": 34, "medium": 33, "hard": 33}
        groups: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
        for item in rows:
            row = item["row"]
            difficulty = str(row["difficulty"]).lower()
            if difficulty in quotas and len(groups[difficulty]) < quotas[difficulty]:
                groups[difficulty].append((item["row_idx"], row))
            if all(len(groups[key]) == value for key, value in quotas.items()):
                break
        if any(len(groups[key]) != value for key, value in quotas.items()):
            raise RuntimeError(f"Could not fill code difficulty quotas: {dict(map(lambda x: (x[0], len(x[1])), groups.items()))}")
        index = 0
        for difficulty in ("easy", "medium", "hard"):
            for row_idx, row in groups[difficulty]:
                starter = row.get("starter_code", "").strip()
                prompt = (
                    f"Programming problem: {row['question_title'].strip()}\n\n"
                    f"{row['question_content'].strip()}"
                )
                if starter:
                    prompt += f"\n\nStarter code:\n```text\n{starter}\n```"
                self.add(
                    record_id=f"p1k-code-{index:03d}-{row['question_id']}",
                    text=prompt,
                    prompt_text=prompt,
                    category="code",
                    domain="competitive_programming",
                    operation="algorithm_design",
                    language="en",
                    source=SourceRef(
                        "lighteval/code_generation_lite",
                        "release_latest",
                        "test",
                        row_idx,
                    ),
                    difficulty=difficulty,
                    format_name="programming_problem",
                    metadata={
                        "platform": row["platform"],
                        "question_id": row["question_id"],
                        "contest_id": row["contest_id"],
                        "contest_date": row["contest_date"],
                        "tests_intentionally_omitted": True,
                        "candidate_pool": "rows_0_through_299",
                    },
                )
                index += 1

    def long_context(self) -> None:
        operations = {
            "niah_single_1": "needle_retrieval",
            "vt": "variable_state_tracking",
            "cwe": "common_item_aggregation",
            "fwe": "frequency_aggregation",
        }
        for target_length in (2048, 4096, 8192):
            for task in ("niah_single_1", "vt", "cwe", "fwe"):
                path = (
                    self.ruler_dir
                    / str(target_length)
                    / task
                    / "validation.jsonl"
                )
                rows = [
                    json.loads(line)
                    for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
                if len(rows) != 5:
                    raise RuntimeError(f"Expected 5 RULER rows in {path}, got {len(rows)}")
                for row in rows:
                    prompt = row["input"].strip()
                    answer_prefix = row.get("answer_prefix", "").strip()
                    outputs = row["outputs"]
                    answer_text = (
                        ", ".join(map(str, outputs))
                        if isinstance(outputs, list)
                        else str(outputs)
                    )
                    reference = " ".join(x for x in (answer_prefix, answer_text) if x)
                    text = f"{prompt}\n\nReference answer: {reference}"
                    self.add(
                        record_id=(
                            f"p1k-long-{task}-{target_length}-"
                            f"{int(row['index']):02d}"
                        ),
                        text=text,
                        prompt_text=prompt,
                        category="long_context",
                        domain=task,
                        operation=operations[task],
                        language="en",
                        source=SourceRef(
                            "NVIDIA/RULER",
                            f"{task}@{target_length}",
                            "validation",
                            row["index"],
                        ),
                        reference_answer=outputs,
                        difficulty=f"target_{target_length}_tokens",
                        format_name="synthetic_long_context",
                        metadata={
                            "target_token_length": target_length,
                            "generator_reported_length": row.get("length"),
                            "answer_prefix": answer_prefix,
                            "phase_512_expected_truncation": target_length > 512,
                            "generator_seed": 7319 + target_length,
                        },
                    )

    def multilingual(self) -> None:
        first = self.api.rows("li-lab/MMLU-ProX", "zh", "test", 0, 1)
        total = first["num_rows_total"]
        page_size = 100
        offsets = list(range(0, total, page_size))
        random.Random(SEED + 50).shuffle(offsets)
        selected: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
        category_counts: Counter[str] = Counter()
        for offset in offsets:
            zh_page = self.api.rows(
                "li-lab/MMLU-ProX", "zh", "test", offset, page_size
            )["rows"]
            en_page = self.api.rows(
                "li-lab/MMLU-ProX", "en", "test", offset, page_size
            )["rows"]
            paired_page = list(zip(zh_page, en_page, strict=True))
            random.Random(f"{SEED}:multilingual:{offset}").shuffle(paired_page)
            for zh_item, en_item in paired_page:
                zh = zh_item["row"]
                en = en_item["row"]
                row_idx = zh_item["row_idx"]
                if category_counts[zh["category"]] >= 2:
                    continue
                if (
                    en["question_id"] != zh["question_id"]
                    or en["question_id_src"] != zh["question_id_src"]
                    or en["category"] != zh["category"]
                    or en["src"] != zh["src"]
                    or en["answer"] != zh["answer"]
                    or en["answer_index"] != zh["answer_index"]
                    or en_item["row_idx"] != row_idx
                ):
                    raise RuntimeError(f"MMLU-ProX alignment mismatch at row {row_idx}")
                category_counts[zh["category"]] += 1
                selected.append((row_idx, en, zh))
                if len(selected) == 20:
                    break
            if len(selected) == 20:
                break

        for pair_index, (row_idx, en, zh) in enumerate(selected):
            pair_id = f"xl-mmlu-prox-{row_idx:05d}"
            en_choices = [
                en[f"option_{i}"] for i in range(10) if en.get(f"option_{i}") is not None
            ]
            en_options = "\n".join(
                f"{LETTERS[i]}. {choice}" for i, choice in enumerate(en_choices)
            )
            en_prompt = f"Question: {en['question'].strip()}\nOptions:\n{en_options}"
            answer = en["answer"]
            self.add(
                record_id=f"p1k-multilingual-en-{pair_index:02d}",
                text=f"{en_prompt}\n\nReference answer: {answer}",
                prompt_text=en_prompt,
                category="multilingual",
                domain=en["category"],
                operation="cross_lingual_knowledge_reasoning",
                language="en",
                source=SourceRef("li-lab/MMLU-ProX", "en", "test", row_idx),
                reference_answer=answer,
                format_name="multiple_choice_parallel",
                cross_lingual_pair_id=pair_id,
                metadata={
                    "parallel_language": "zh-CN",
                    "question_id": en["question_id"],
                    "question_id_src": en["question_id_src"],
                    "upstream_src": en["src"],
                },
            )
            zh_choices = [
                zh[f"option_{i}"] for i in range(10) if zh.get(f"option_{i}") is not None
            ]
            zh_options = "\n".join(
                f"{LETTERS[i]}. {choice}" for i, choice in enumerate(zh_choices)
            )
            zh_prompt = f"问题：{zh['question'].strip()}\n选项：\n{zh_options}"
            self.add(
                record_id=f"p1k-multilingual-zh-{pair_index:02d}",
                text=f"{zh_prompt}\n\n参考答案：{zh['answer']}",
                prompt_text=zh_prompt,
                category="multilingual",
                domain=zh["category"],
                operation="cross_lingual_knowledge_reasoning",
                language="zh-CN",
                source=SourceRef("li-lab/MMLU-ProX", "zh", "test", row_idx),
                reference_answer=zh["answer"],
                format_name="multiple_choice_parallel",
                cross_lingual_pair_id=pair_id,
                metadata={
                    "parallel_language": "en",
                    "question_id": zh["question_id"],
                    "question_id_src": zh["question_id_src"],
                    "upstream_src": zh["src"],
                },
            )

    def assign_original_splits(self) -> None:
        by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in self.records:
            by_category[record["category"]].append(record)
        for category, records in by_category.items():
            rng = random.Random(f"{SEED}:split:{category}")
            rng.shuffle(records)
            confirm = ORIGINAL_CONFIRMATORY[category]
            for index, record in enumerate(records):
                record["split"] = (
                    "confirmatory" if index < confirm else "discovery"
                )

    def controls(self) -> None:
        originals_by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in self.records:
            originals_by_category[record["category"]].append(record)
        controls: list[dict[str, Any]] = []
        for category, quota in CONTROL_SEEDS.items():
            candidates = originals_by_category[category]
            seeds = random.Random(f"{SEED}:controls:{category}").sample(
                candidates, quota
            )
            for original in seeds:
                pair_id = f"perturb-{original['id']}"
                original["pair_id"] = pair_id
                original["pair_role"] = "original"

                prompt_only = deepcopy(original)
                prompt_only.update(
                    {
                        "id": f"{original['id']}--prompt-only",
                        "text": original["prompt_text"],
                        "split": "perturbation",
                        "category": "control",
                        "base_category": category,
                        "variant_type": "prompt_only",
                        "pair_id": pair_id,
                        "pair_role": "control",
                    }
                )
                prompt_only["metadata"] = {
                    **prompt_only["metadata"],
                    "control_operation": "remove_reference_answer_and_reasoning",
                    "parent_id": original["id"],
                }
                controls.append(prompt_only)

                format_variant = deepcopy(original)
                reference = original["text"][len(original["prompt_text"]) :].strip()
                xml_text = (
                    f'<probe category="{category}" operation="{original["operation"]}">\n'
                    f"<task>\n{original['prompt_text']}\n</task>"
                )
                if reference:
                    xml_text += f"\n<reference>\n{reference}\n</reference>"
                xml_text += "\n</probe>"
                format_variant.update(
                    {
                        "id": f"{original['id']}--xml-format",
                        "text": xml_text,
                        "split": "perturbation",
                        "category": "control",
                        "base_category": category,
                        "format": "xml_surface_variant",
                        "variant_type": "format_variant",
                        "pair_id": pair_id,
                        "pair_role": "control",
                    }
                )
                format_variant["metadata"] = {
                    **format_variant["metadata"],
                    "control_operation": "information_preserving_xml_reframe",
                    "parent_id": original["id"],
                }
                controls.append(format_variant)
        self.records.extend(controls)


def resolve_revisions(cache_dir: Path, offline: bool) -> dict[str, str]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / "source_revisions.json"
    if path.exists():
        revisions = json.loads(path.read_text(encoding="utf-8"))
    else:
        revisions = {}
    non_hf_sources = {"NVIDIA/RULER", "suzgunmirac/BIG-Bench-Hard"}
    hf_sources = set(SOURCE_SPECS) - non_hf_sources
    revisions = {
        name: revision
        for name, revision in revisions.items()
        if name in hf_sources
    }
    missing = [
        name
        for name in SOURCE_SPECS
        if name not in non_hf_sources and name not in revisions
    ]
    if missing and offline:
        raise RuntimeError(f"Missing cached revisions: {missing}")
    if missing:
        api = HfApi()
        for name in missing:
            revisions[name] = api.dataset_info(name).sha
    path.write_text(canonical_json(revisions) + "\n", encoding="utf-8")
    return revisions


def git_revision(repo: Path) -> str:
    head = repo / ".git" / "HEAD"
    if not head.exists():
        return "unknown"
    value = head.read_text(encoding="utf-8").strip()
    if value.startswith("ref: "):
        ref_path = repo / ".git" / value[5:]
        if ref_path.exists():
            return ref_path.read_text(encoding="utf-8").strip()
    return value


def token_bin(length: int) -> str:
    if length <= 128:
        return "0001-0128"
    if length <= 512:
        return "0129-0512"
    if length <= 2048:
        return "0513-2048"
    if length <= 4096:
        return "2049-4096"
    if length <= 8192:
        return "4097-8192"
    return "8193+"


def add_derived_fields(
    records: list[dict[str, Any]], skip_token_audit: bool
) -> dict[str, Any]:
    tokenizer_specs = {
        "granite": "ibm-granite/granite-3.1-3b-a800m-base",
        "olmoe": "allenai/OLMoE-1B-7B-0125",
    }
    tokenizers = {}
    if not skip_token_audit:
        for key, model in tokenizer_specs.items():
            tokenizers[key] = AutoTokenizer.from_pretrained(
                model, local_files_only=True, trust_remote_code=True
            )

    tokenizer_revisions = {}
    for record in records:
        record["content_sha256"] = sha256_text(record["text"])
        record["normalized_content_sha256"] = sha256_text(
            normalize_text(record["text"])
        )
        record["char_length"] = len(record["text"])
        record["word_count"] = len(re.findall(r"\S+", record["text"]))
        record["token_lengths"] = {}
        record["token_length_bins"] = {}
        record["truncated_at_512"] = {}
        for key, tokenizer in tokenizers.items():
            length = len(tokenizer(record["text"], add_special_tokens=True)["input_ids"])
            record["token_lengths"][key] = length
            record["token_length_bins"][key] = token_bin(length)
            record["truncated_at_512"][key] = length > 512
            tokenizer_revisions[key] = getattr(tokenizer, "name_or_path", tokenizer_specs[key])
    return {
        "tokenizer_models": tokenizer_specs,
        "tokenizer_resolution": tokenizer_revisions,
        "token_audit_skipped": skip_token_audit,
    }


def duplicate_groups(records: list[dict[str, Any]], field: str) -> list[list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for record in records:
        groups[record[field]].append(record["id"])
    return [ids for ids in groups.values() if len(ids) > 1]


def counter(records: Iterable[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(str(record[key]) for record in records).items()))


def audit(records: list[dict[str, Any]], token_meta: dict[str, Any]) -> dict[str, Any]:
    category_counts = counter(records, "category")
    split_counts = counter(records, "split")
    ids = [record["id"] for record in records]
    pair_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record["pair_id"]:
            pair_groups[record["pair_id"]].append(record)
    invalid_pairs = {}
    for pair_id, group in pair_groups.items():
        roles = Counter(record["pair_role"] for record in group)
        variants = {record["variant_type"] for record in group}
        if len(group) != 3 or roles != {"original": 1, "control": 2} or variants != {
            "original",
            "prompt_only",
            "format_variant",
        }:
            invalid_pairs[pair_id] = [record["id"] for record in group]

    cross_pairs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record["cross_lingual_pair_id"] and record["variant_type"] == "original":
            cross_pairs[record["cross_lingual_pair_id"]].append(record)
    invalid_cross_pairs = {
        pair_id: [record["id"] for record in group]
        for pair_id, group in cross_pairs.items()
        if len(group) != 2 or {record["language"] for record in group} != {"en", "zh-CN"}
    }

    source_counts = Counter(
        record["source"]["dataset"] for record in records if record["variant_type"] == "original"
    )
    length_bins = {}
    for tokenizer in ("granite", "olmoe"):
        if records and tokenizer in records[0]["token_length_bins"]:
            length_bins[tokenizer] = dict(
                sorted(
                    Counter(
                        record["token_length_bins"][tokenizer] for record in records
                    ).items()
                )
            )

    checks = {
        "total_is_1000": len(records) == 1000,
        "unique_ids": len(set(ids)) == len(ids),
        "category_quotas": category_counts == EXPECTED_CATEGORY_COUNTS,
        "split_quotas": split_counts == EXPECTED_SPLIT_COUNTS,
        "exact_text_unique": not duplicate_groups(records, "content_sha256"),
        "normalized_text_unique": not duplicate_groups(
            records, "normalized_content_sha256"
        ),
        "control_pair_integrity": not invalid_pairs and len(pair_groups) == 100,
        "cross_lingual_pair_integrity": not invalid_cross_pairs
        and len(cross_pairs) == 20,
        "all_sources_revisioned": all(
            bool(record["source"]["revision"]) for record in records
        ),
        "all_sources_licensed_or_flagged": all(
            bool(record["source"]["license"]) for record in records
        ),
    }
    return {
        "schema_version": "probe-1k-v1.1",
        "seed": SEED,
        "checks": checks,
        "all_checks_pass": all(checks.values()),
        "counts": {
            "total": len(records),
            "category": category_counts,
            "split": split_counts,
            "base_category": counter(records, "base_category"),
            "language": counter(records, "language"),
            "variant_type": counter(records, "variant_type"),
            "original_source": dict(sorted(source_counts.items())),
            "token_length_bins": length_bins,
        },
        "duplicate_groups": {
            "exact": duplicate_groups(records, "content_sha256"),
            "normalized": duplicate_groups(records, "normalized_content_sha256"),
        },
        "invalid_control_pairs": invalid_pairs,
        "invalid_cross_lingual_pairs": invalid_cross_pairs,
        "token_audit": token_meta,
        "license_notes": SOURCE_SPECS,
    }


def write_outputs(
    output_dir: Path,
    records: list[dict[str, Any]],
    report: dict[str, Any],
    revisions: dict[str, str],
    ruler_revision: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    records.sort(key=lambda record: record["id"])
    jsonl_path = output_dir / "probe_1k.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(canonical_json(record) + "\n")
    report["artifact"] = {
        "path": str(jsonl_path),
        "sha256": hashlib.sha256(jsonl_path.read_bytes()).hexdigest(),
        "bytes": jsonl_path.stat().st_size,
    }
    builder_path = Path(__file__).resolve()
    ruler_patch_path = Path(
        "vendor/RULER/scripts/data/synthetic/common_words_extraction.py"
    )
    report["builder"] = {
        "path": str(builder_path),
        "sha256": hashlib.sha256(builder_path.read_bytes()).hexdigest(),
        "seed": SEED,
        "ruler_compatibility_patch_path": str(ruler_patch_path),
        "ruler_compatibility_patch_sha256": hashlib.sha256(
            ruler_patch_path.read_bytes()
        ).hexdigest(),
        "code_candidate_pool": {
            "dataset": "lighteval/code_generation_lite",
            "config": "release_latest",
            "split": "test",
            "rows": "0-299",
            "reason": "Project away very large private-test fields before stratified sampling.",
        },
    }
    used_sources = {
        record["source"]["dataset"]
        for record in records
        if record["variant_type"] == "original"
    }
    all_revisions = {
        **revisions,
        "NVIDIA/RULER": ruler_revision,
        "suzgunmirac/BIG-Bench-Hard": BBH_UPSTREAM_REVISION,
    }
    report["source_revisions"] = {
        name: all_revisions[name] for name in sorted(used_sources)
    }
    (output_dir / "audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    schema = {
        "schema_version": "probe-1k-v1.1",
        "required_fields": [
            "id",
            "text",
            "prompt_text",
            "split",
            "category",
            "base_category",
            "domain",
            "operation",
            "language",
            "format",
            "difficulty",
            "variant_type",
            "pair_id",
            "pair_role",
            "cross_lingual_pair_id",
            "reference_answer",
            "source",
            "metadata",
            "content_sha256",
            "normalized_content_sha256",
            "char_length",
            "word_count",
            "token_lengths",
            "token_length_bins",
            "truncated_at_512",
        ],
        "source_required_fields": [
            "dataset",
            "config",
            "split",
            "row_id",
            "revision",
            "license",
            "url",
        ],
    }
    (output_dir / "schema.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("data/probe_1k")
    )
    parser.add_argument(
        "--cache-dir", type=Path, default=Path(".cache/probe_builder")
    )
    parser.add_argument(
        "--ruler-dir", type=Path, default=Path("data/probe_1k_work/ruler")
    )
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--skip-token-audit", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    revisions = resolve_revisions(args.cache_dir, args.offline)
    ruler_repo = Path("vendor/RULER")
    ruler_revision = git_revision(ruler_repo)
    api = DatasetServer(args.cache_dir / "rows", offline=args.offline)
    builder = ProbeBuilder(api, revisions, args.ruler_dir, ruler_revision)

    stages = [
        ("natural_text", builder.natural_text),
        ("mmlu_pro", builder.mmlu_pro),
        ("bbh", builder.bbh),
        ("math", builder.math),
        ("code", builder.code),
        ("long_context", builder.long_context),
        ("multilingual", builder.multilingual),
    ]
    for name, stage in stages:
        print(f"[build] {name}", flush=True)
        before = len(builder.records)
        stage()
        print(f"[build] {name}: +{len(builder.records) - before}", flush=True)

    if len(builder.records) != 800:
        raise RuntimeError(f"Expected 800 originals, got {len(builder.records)}")
    builder.assign_original_splits()
    builder.controls()
    token_meta = add_derived_fields(builder.records, args.skip_token_audit)
    report = audit(builder.records, token_meta)
    write_outputs(
        args.output_dir,
        builder.records,
        report,
        revisions,
        ruler_revision,
    )
    if not report["all_checks_pass"]:
        raise RuntimeError(
            "Probe-1K audit failed: "
            + canonical_json(
                {key: value for key, value in report["checks"].items() if not value}
            )
        )
    print(
        f"[done] {len(builder.records)} records; "
        f"sha256={report['artifact']['sha256']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
