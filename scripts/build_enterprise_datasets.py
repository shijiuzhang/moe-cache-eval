#!/usr/bin/env python3
"""Build public and fully synthetic enterprise probes for MoE routing research.

The two frozen artifacts are deliberately separated:

* EnterpriseProxy-1K is a balanced, English-language aggregation of five
  public benchmarks with fixed upstream revisions and explicit provenance.
* SyntheticEnterprise-1K contains 200 deterministic, bilingual workflows for
  a fictional company.  Each workflow has five cumulative turns, executable
  or exact ground truth, and no real company data or external model output.

The generated JSONL remains compatible with ``collect_routes.py`` through its
``id`` and ``text`` fields while adding workflow and evaluation metadata.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable

from build_probe_1k import (
    DatasetServer,
    add_derived_fields,
    canonical_json,
    duplicate_groups,
    normalize_text,
    sha256_text,
)


ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache" / "enterprise_builder"
SEED = 20260727
SCHEMA_VERSION = "enterprise-probes-v1.0"

PUBLIC_REVISIONS = {
    "zai-org/LongBench": "5e628be450b7e67fb7ae6e201bd6d8f7056f7672",
    "xlang-ai/Spider2": "01a4c67c1e3f6ab9032716b050a927abbb245f65",
    "gorilla-llm/Berkeley-Function-Calling-Leaderboard": (
        "61fc0608cfd831fcfbbaa676ebdfef0ed963eeda"
    ),
    "princeton-nlp/SWE-bench_Lite": "6ec7bb89b9342f664a54a6e0a6ea6501d3437cc2",
    "nguha/legalbench": "daec8237410aa23e3faf4bc41ad8b3a7e1696826",
}

SOURCE_MANIFEST = {
    "zai-org/LongBench": {
        "license": "public-domain-us-gov; benchmark-wrapper-mit",
        "url": "https://huggingface.co/datasets/zai-org/LongBench",
        "usage": "evaluation-and-research",
        "note": (
            "Only GovReport examples are used. The underlying reports are US "
            "federal government works; provenance and LongBench revision are retained."
        ),
    },
    "xlang-ai/Spider2": {
        "license": "mit",
        "url": "https://github.com/xlang-ai/Spider2",
        "usage": "evaluation-and-research",
        "note": "Only public Spider 2.0 Lite question metadata is redistributed.",
    },
    "gorilla-llm/Berkeley-Function-Calling-Leaderboard": {
        "license": "apache-2.0",
        "url": (
            "https://huggingface.co/datasets/"
            "gorilla-llm/Berkeley-Function-Calling-Leaderboard"
        ),
        "usage": "evaluation-and-research",
        "note": "Official dataset-card license; includes single- and multi-turn cases.",
    },
    "princeton-nlp/SWE-bench_Lite": {
        "license": "mit-benchmark; upstream-repository-licenses-vary",
        "url": "https://huggingface.co/datasets/princeton-nlp/SWE-bench_Lite",
        "usage": "evaluation-only",
        "note": (
            "Benchmark code/data is MIT. Problem statements and patches originate "
            "from public repositories and retain repository identifiers."
        ),
    },
    "nguha/legalbench": {
        "license": "cc-by-4.0-dataset-card",
        "url": "https://huggingface.co/datasets/nguha/legalbench",
        "usage": "evaluation-and-research",
        "note": (
            "Only ContractNLI-derived configurations are used. The task-level "
            "provenance is retained because LegalBench aggregates upstream tasks."
        ),
    },
    "moe-hierarchy-lab/SyntheticEnterprise-1K": {
        "license": "cc-by-4.0",
        "url": "local:moe-hierarchy-lab/scripts/build_enterprise_datasets.py",
        "usage": "research-and-commercial",
        "note": (
            "Deterministically generated from code and arithmetic only. No real "
            "company data, private logs, user prompts, or external model output."
        ),
    },
}

CONTRACT_CONFIGS = [
    "contract_nli_confidentiality_of_agreement",
    "contract_nli_explicit_identification",
    "contract_nli_limited_use",
    "contract_nli_no_licensing",
    "contract_nli_notice_on_compelled_disclosure",
    "contract_nli_permissible_copy",
    "contract_nli_return_of_confidential_information",
    "contract_nli_sharing_with_employees",
    "contract_nli_sharing_with_third-parties",
    "contract_nli_survival_of_obligations",
]

CONTRACT_HYPOTHESES = {
    "contract_nli_confidentiality_of_agreement": (
        "The agreement itself is treated as confidential information."
    ),
    "contract_nli_explicit_identification": (
        "Confidential information must be explicitly identified as confidential."
    ),
    "contract_nli_limited_use": (
        "Confidential information may be used only for the stated purpose."
    ),
    "contract_nli_no_licensing": (
        "Disclosure does not grant a license to intellectual property."
    ),
    "contract_nli_notice_on_compelled_disclosure": (
        "The recipient must notify the discloser before compelled disclosure."
    ),
    "contract_nli_permissible_copy": (
        "The recipient may make copies of confidential information."
    ),
    "contract_nli_return_of_confidential_information": (
        "Confidential information must be returned or destroyed on request."
    ),
    "contract_nli_sharing_with_employees": (
        "Confidential information may be shared with employees."
    ),
    "contract_nli_sharing_with_third-parties": (
        "Confidential information may be shared with third parties."
    ),
    "contract_nli_survival_of_obligations": (
        "Confidentiality obligations survive termination of the agreement."
    ),
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def source_ref(
    dataset: str,
    *,
    config: str,
    split: str,
    row_id: str | int,
) -> dict[str, Any]:
    spec = SOURCE_MANIFEST[dataset]
    return {
        "dataset": dataset,
        "config": config,
        "split": split,
        "row_id": row_id,
        "revision": PUBLIC_REVISIONS.get(dataset, "generator-v1-seed-20260727"),
        "license": spec["license"],
        "url": spec["url"],
        "usage": spec["usage"],
    }


def make_record(
    *,
    record_id: str,
    dataset_name: str,
    text: str,
    prompt_text: str,
    category: str,
    domain: str,
    operation: str,
    language: str,
    source: dict[str, Any],
    reference_answer: Any,
    evaluator: dict[str, Any],
    workflow_id: str | None = None,
    turn_index: int = 0,
    turn_count: int = 1,
    department: str = "cross_functional",
    system: str = "none",
    risk_tier: str = "medium",
    provenance_type: str = "public_benchmark",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "dataset_name": dataset_name,
        "id": record_id,
        "text": text.strip(),
        "prompt_text": prompt_text.strip(),
        "split": None,
        "category": category,
        "base_category": category,
        "domain": domain,
        "operation": operation,
        "language": language,
        "format": "cumulative_chat" if turn_count > 1 else "task_with_reference",
        "difficulty": None,
        "variant_type": "original",
        "pair_id": None,
        "pair_role": None,
        "cross_lingual_pair_id": None,
        "workflow_id": workflow_id or record_id,
        "session_id": workflow_id or record_id,
        "turn_index": turn_index,
        "turn_count": turn_count,
        "department": department,
        "system": system,
        "risk_tier": risk_tier,
        "provenance_type": provenance_type,
        "reference_answer": reference_answer,
        "evaluator": evaluator,
        "source": source,
        "metadata": metadata or {},
    }


def stratified_take(
    rows: Iterable[dict[str, Any]],
    key: Callable[[dict[str, Any]], str],
    count: int,
    seed: int,
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[key(row)].append(row)
    rng = random.Random(seed)
    for values in groups.values():
        rng.shuffle(values)
    names = sorted(groups)
    output: list[dict[str, Any]] = []
    cursor = 0
    while len(output) < count:
        name = names[cursor % len(names)]
        if groups[name]:
            output.append(groups[name].pop())
        cursor += 1
        if cursor > count * max(10, len(names)) and len(output) < count:
            raise RuntimeError("Insufficient rows for stratified sample")
    return output


def assign_public_splits(records: list[dict[str, Any]]) -> None:
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_category[record["category"]].append(record)
    for category, values in by_category.items():
        values.sort(key=lambda row: sha256_text(f"{SEED}:{category}:{row['id']}"))
        for index, record in enumerate(values):
            record["split"] = "discovery" if index < 140 else "confirmatory"


def build_public(api: DatasetServer) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    # 200 public US government reports: long-document summarization/RAG proxy.
    for index, row in enumerate(read_jsonl(CACHE / "gov_report.jsonl")):
        prompt = (
            "Task: Prepare an evidence-grounded executive summary of the following "
            "public government report. Preserve quantitative findings, risks, and "
            "recommendations. Do not invent facts.\n\n"
            f"Document:\n{row['context']}"
        )
        answer = row["answers"][0]
        records.append(
            make_record(
                record_id=f"ent-public-doc-{index:03d}",
                dataset_name="EnterpriseProxy-1K",
                text=f"{prompt}\n\nReference executive summary:\n{answer}",
                prompt_text=prompt,
                category="document_rag",
                domain="public_government_report",
                operation="long_document_summarization",
                language="en",
                source=source_ref(
                    "zai-org/LongBench",
                    config="gov_report",
                    split="test",
                    row_id=row.get("_id", index),
                ),
                reference_answer=answer,
                evaluator={"type": "reference_summary", "metric": "rouge_and_factuality"},
                department="strategy",
                system="document_management",
                risk_tier="medium",
                metadata={
                    "upstream_length": row.get("length"),
                    "upstream_dataset": row.get("dataset"),
                    "document_is_public": True,
                },
            )
        )

    # 200 enterprise analytics questions, balanced over database families.
    spider_rows = stratified_take(
        read_jsonl(CACHE / "spider2-lite.jsonl"),
        key=lambda row: str(row["db"]),
        count=200,
        seed=SEED + 10,
    )
    for index, row in enumerate(spider_rows):
        prompt = (
            "You are a data analyst. Translate the business question into a correct, "
            "efficient query for the specified database. Inspect the referenced schema "
            "documentation when available and state any assumptions.\n\n"
            f"Database: {row['db']}\n"
            f"Schema reference: {row.get('external_knowledge') or 'none'}\n"
            f"Business question: {row['question']}"
        )
        records.append(
            make_record(
                record_id=f"ent-public-sql-{index:03d}",
                dataset_name="EnterpriseProxy-1K",
                text=prompt,
                prompt_text=prompt,
                category="structured_analytics",
                domain=str(row["db"]),
                operation="text_to_sql",
                language="en",
                source=source_ref(
                    "xlang-ai/Spider2",
                    config="spider2-lite",
                    split="test",
                    row_id=row["instance_id"],
                ),
                reference_answer=None,
                evaluator={
                    "type": "external_execution",
                    "metric": "execution_accuracy",
                    "ground_truth_not_redistributed": True,
                },
                department="finance_and_operations",
                system="data_warehouse",
                risk_tier="high",
                metadata={
                    "instance_id": row["instance_id"],
                    "external_knowledge": row.get("external_knowledge"),
                },
            )
        )

    # 100 single-turn + 100 multi-turn tool-use cases with official ground truth.
    simple = read_jsonl(CACHE / "bfcl-simple.jsonl")[:100]
    simple_answers = {
        row["id"]: row["ground_truth"]
        for row in read_jsonl(CACHE / "bfcl-simple-answers.jsonl")
    }
    multi = read_jsonl(CACHE / "bfcl-multi-turn.jsonl")[:100]
    multi_answers = {
        row["id"]: row["ground_truth"]
        for row in read_jsonl(CACHE / "bfcl-multi-turn-answers.jsonl")
    }
    for index, row in enumerate(simple + multi):
        is_multi = row["id"].startswith("multi_turn")
        if is_multi:
            user_turns = [
                turn[0]["content"] for turn in row["question"] if turn
            ]
            prompt = (
                "Select and call the available tools to complete the workflow. "
                "Preserve state across turns and do not call unrelated tools.\n\n"
                f"Initial state:\n{canonical_json(row.get('initial_config', {}))}\n\n"
                + "\n".join(
                    f"User turn {turn_index + 1}: {content}"
                    for turn_index, content in enumerate(user_turns)
                )
                + f"\n\nAvailable tool classes: {', '.join(row.get('involved_classes', []))}"
            )
            answer = multi_answers[row["id"]]
            operation = "multi_turn_tool_use"
        else:
            question = row["question"][0][0]["content"]
            prompt = (
                "Choose the appropriate function and return a valid function call.\n\n"
                f"Functions:\n{canonical_json(row['function'])}\n\n"
                f"User request: {question}"
            )
            answer = simple_answers[row["id"]]
            operation = "single_turn_function_call"
        text = f"{prompt}\n\nReference tool calls:\n{canonical_json(answer)}"
        records.append(
            make_record(
                record_id=f"ent-public-agent-{index:03d}",
                dataset_name="EnterpriseProxy-1K",
                text=text,
                prompt_text=prompt,
                category="tool_agent",
                domain="function_calling",
                operation=operation,
                language="en",
                source=source_ref(
                    "gorilla-llm/Berkeley-Function-Calling-Leaderboard",
                    config="multi_turn_base" if is_multi else "simple",
                    split="test",
                    row_id=row["id"],
                ),
                reference_answer=answer,
                evaluator={"type": "bfcl_ast", "metric": "function_call_accuracy"},
                workflow_id=f"bfcl-{row['id']}",
                turn_count=len(row["question"]) if is_multi else 1,
                department="cross_functional",
                system="enterprise_tools",
                risk_tier="high",
                metadata={
                    "bfcl_id": row["id"],
                    "multi_turn": is_multi,
                    "available_path": row.get("path"),
                },
            )
        )

    # 200 public software-maintenance issues, balanced by repository.
    swe_payload = api.rows(
        "princeton-nlp/SWE-bench_Lite", "default", "test", 0, 100
    )
    swe_rows = list(swe_payload["rows"])
    for offset in (100, 200):
        swe_rows.extend(
            api.rows(
                "princeton-nlp/SWE-bench_Lite",
                "default",
                "test",
                offset,
                100,
            )["rows"]
        )
    selected_swe = stratified_take(
        [item["row"] | {"_row_idx": item["row_idx"]} for item in swe_rows],
        key=lambda row: str(row["repo"]),
        count=200,
        seed=SEED + 20,
    )
    for index, row in enumerate(selected_swe):
        prompt = (
            "Act as a software-maintenance engineer. Diagnose the issue and propose "
            "a minimal patch that preserves existing behavior and passes the tests.\n\n"
            f"Repository: {row['repo']}\nVersion: {row['version']}\n"
            f"Issue:\n{row['problem_statement']}"
        )
        if row.get("hints_text"):
            prompt += f"\n\nMaintainer hints:\n{row['hints_text']}"
        answer = row["patch"]
        records.append(
            make_record(
                record_id=f"ent-public-swe-{index:03d}",
                dataset_name="EnterpriseProxy-1K",
                text=f"{prompt}\n\nReference patch:\n{answer}",
                prompt_text=prompt,
                category="software_engineering",
                domain=str(row["repo"]),
                operation="issue_resolution",
                language="en",
                source=source_ref(
                    "princeton-nlp/SWE-bench_Lite",
                    config="default",
                    split="test",
                    row_id=row["instance_id"],
                ),
                reference_answer=answer,
                evaluator={"type": "unit_tests", "metric": "resolved"},
                department="information_technology",
                system="source_control",
                risk_tier="high",
                metadata={
                    "instance_id": row["instance_id"],
                    "base_commit": row["base_commit"],
                    "created_at": row["created_at"],
                    "upstream_row_idx": row["_row_idx"],
                },
            )
        )

    # 200 ContractNLI cases: ten compliance concepts x twenty clauses.
    legal_index = 0
    for config_index, config in enumerate(CONTRACT_CONFIGS):
        payload = api.rows("nguha/legalbench", config, "test", 0, 100)
        candidates = [item["row"] | {"_row_idx": item["row_idx"]} for item in payload["rows"]]
        rng = random.Random(SEED + 100 + config_index)
        rng.shuffle(candidates)
        for row in candidates[:20]:
            hypothesis = CONTRACT_HYPOTHESES[config]
            prompt = (
                "Review the contract clause for the stated compliance proposition. "
                "Answer Yes, No, or Not Mentioned, then cite the decisive phrase.\n\n"
                f"Proposition: {hypothesis}\n"
                f"Contract clause:\n{row['text']}"
            )
            answer = row["answer"]
            records.append(
                make_record(
                    record_id=f"ent-public-legal-{legal_index:03d}",
                    dataset_name="EnterpriseProxy-1K",
                    text=f"{prompt}\n\nReference label: {answer}",
                    prompt_text=prompt,
                    category="legal_compliance",
                    domain=config.removeprefix("contract_nli_"),
                    operation="contract_entailment",
                    language="en",
                    source=source_ref(
                        "nguha/legalbench",
                        config=config,
                        split="test",
                        row_id=row["_row_idx"],
                    ),
                    reference_answer=answer,
                    evaluator={"type": "exact_label", "labels": ["Yes", "No", "Not Mentioned"]},
                    department="legal",
                    system="contract_management",
                    risk_tier="critical",
                    metadata={"document_name": row.get("document_name")},
                )
            )
            legal_index += 1

    assign_public_splits(records)
    return records


def money(value: float) -> str:
    return f"{value:.2f}"


def synthetic_procurement(i: int, zh: bool) -> dict[str, Any]:
    qty = 80 + i * 3
    price_a = 42.5 + i
    price_b = price_a - 1.8
    discount = 0.04 + (i % 3) * 0.01
    total_a = qty * price_a * (1 - discount)
    total_b = qty * price_b
    threshold = 4000 + (i % 4) * 500
    if zh:
        context = (
            f"供应商A报价：物料PX-{i:03d}，数量{qty}，单价{price_a:.2f}元，"
            f"整单折扣{discount:.0%}。供应商B单价{price_b:.2f}元，无折扣。"
            f"采购政策：净额超过{threshold}元需要采购经理审批，超过7000元还需财务审批。"
        )
        turns = [
            (f"计算供应商A的折后总价。", f"{money(total_a)}元", "numeric"),
            ("供应商B的总价是多少，哪家更低？", f"B为{money(total_b)}元；" + ("B更低" if total_b < total_a else "A更低"), "numeric"),
            ("按照政策需要哪些审批？", "采购经理" + ("和财务" if min(total_a, total_b) > 7000 else ""), "rule"),
            ("生成简短采购建议，必须说明价格依据。", f"建议选择{'B' if total_b < total_a else 'A'}，其净价更低；应按门槛完成审批。", "semantic"),
            ("列出下单前必须归档的材料。", "两份报价、比价记录、审批记录和采购订单。", "set"),
        ]
    else:
        context = (
            f"Supplier A quotes item PX-{i:03d}, quantity {qty}, unit price "
            f"{price_a:.2f}, order discount {discount:.0%}. Supplier B quotes "
            f"{price_b:.2f} per unit without discount. Policy: net value above "
            f"{threshold} requires procurement-manager approval; above 7000 also "
            "requires finance approval."
        )
        turns = [
            ("Calculate Supplier A's discounted total.", money(total_a), "numeric"),
            ("What is Supplier B's total and which is lower?", f"B total {money(total_b)}; {'B' if total_b < total_a else 'A'} is lower.", "numeric"),
            ("Which approvals are required by policy?", "Procurement manager" + (" and finance" if min(total_a, total_b) > 7000 else ""), "rule"),
            ("Draft a short sourcing recommendation with the price basis.", f"Select Supplier {'B' if total_b < total_a else 'A'} because its net price is lower; complete the required approvals.", "semantic"),
            ("List the records that must be archived before ordering.", "Both quotes, bid comparison, approval record, and purchase order.", "set"),
        ]
    return {
        "context": context,
        "department": "procurement",
        "system": "ERP-PROC",
        "risk": "high",
        "turns": turns,
    }


def synthetic_finance(i: int, zh: bool) -> dict[str, Any]:
    invoiced = 12000 + i * 137
    paid = 7000 + i * 83
    credit = 350 + (i % 5) * 25
    outstanding = invoiced - paid - credit
    due_days = 10 + i % 25
    tax = round(outstanding * 0.06, 2)
    if zh:
        context = (
            f"ERP应收记录：客户C-{i:03d}，已开票{invoiced:.2f}元，"
            f"已收款{paid:.2f}元，贷项{credit:.2f}元，逾期{due_days}天。"
            "公司规则：逾期超过20天升级给信用经理；调整分录必须包含客户、金额、税额和原因。"
        )
        turns = [
            ("计算未结应收余额。", f"{outstanding:.2f}元", "numeric"),
            ("是否需要升级给信用经理？", "是" if due_days > 20 else "否", "exact"),
            ("按6%计算余额对应税额。", f"{tax:.2f}元", "numeric"),
            ("生成调整分录JSON草案，原因为reconciliation。", canonical_json({"customer": f"C-{i:03d}", "amount": round(outstanding, 2), "tax": tax, "reason": "reconciliation"}), "json"),
            ("写一段管理摘要。", f"客户C-{i:03d}未结余额{outstanding:.2f}元，逾期{due_days}天，" + ("需要信用经理跟进。" if due_days > 20 else "暂按常规催收。"), "semantic"),
        ]
    else:
        context = (
            f"ERP receivables: customer C-{i:03d}, invoiced {invoiced:.2f}, "
            f"paid {paid:.2f}, credit memo {credit:.2f}, overdue {due_days} days. "
            "Policy: escalate beyond 20 overdue days; adjustment entries require "
            "customer, amount, tax, and reason."
        )
        turns = [
            ("Calculate the outstanding receivable.", f"{outstanding:.2f}", "numeric"),
            ("Does this require credit-manager escalation?", "Yes" if due_days > 20 else "No", "exact"),
            ("Calculate tax on the balance at 6%.", f"{tax:.2f}", "numeric"),
            ("Create an adjustment-entry JSON draft with reason reconciliation.", canonical_json({"customer": f"C-{i:03d}", "amount": round(outstanding, 2), "tax": tax, "reason": "reconciliation"}), "json"),
            ("Write a one-paragraph management summary.", f"Customer C-{i:03d} has {outstanding:.2f} outstanding for {due_days} overdue days; " + ("credit-manager follow-up is required." if due_days > 20 else "standard collection applies."), "semantic"),
        ]
    return {"context": context, "department": "finance", "system": "ERP-FIN", "risk": "critical", "turns": turns}


def synthetic_operations(i: int, zh: bool) -> dict[str, Any]:
    pressure = 7.8 + (i % 6) * 0.45
    temp = 165 + (i % 7) * 6
    vibration = 3.2 + (i % 5) * 0.8
    alarms = []
    if pressure > 9.0:
        alarms.append("pressure")
    if temp > 190:
        alarms.append("temperature")
    if vibration > 5.0:
        alarms.append("vibration")
    severity = "high" if len(alarms) >= 2 else "medium" if alarms else "normal"
    if zh:
        context = (
            f"DCS快照：反应器R-{i:02d}压力{pressure:.2f}MPa、温度{temp}°C、"
            f"振动{vibration:.2f}mm/s。报警阈值：压力>9.0、温度>190、振动>5.0。"
            "SOP：两个及以上报警为高风险，操作员应先降负荷、确认冷却和联锁，不得直接旁路联锁。"
        )
        turns = [
            ("哪些参数越过报警阈值？", "、".join(alarms) if alarms else "无", "set"),
            ("按SOP判定风险等级。", severity, "exact"),
            ("计算压力超过阈值的幅度，没有超限则为0。", f"{max(0, pressure - 9.0):.2f}MPa", "numeric"),
            ("给出允许的首要处置步骤。", "降负荷，确认冷却和联锁；不得旁路联锁。", "rule"),
            ("生成交接班摘要。", f"R-{i:02d}风险等级{severity}，报警项：" + ("、".join(alarms) if alarms else "无") + "。按SOP持续监视。", "semantic"),
        ]
    else:
        context = (
            f"DCS snapshot: reactor R-{i:02d}, pressure {pressure:.2f} MPa, "
            f"temperature {temp} C, vibration {vibration:.2f} mm/s. Alarm limits: "
            "pressure >9.0, temperature >190, vibration >5.0. SOP: two or more "
            "alarms are high risk; first reduce load and verify cooling/interlocks. "
            "Never bypass an interlock."
        )
        turns = [
            ("Which parameters cross their alarm limits?", ", ".join(alarms) if alarms else "none", "set"),
            ("Classify risk under the SOP.", severity, "exact"),
            ("Calculate pressure exceedance, or zero if within limit.", f"{max(0, pressure - 9.0):.2f} MPa", "numeric"),
            ("Give the permitted first response.", "Reduce load and verify cooling and interlocks; do not bypass an interlock.", "rule"),
            ("Create a shift-handover summary.", f"R-{i:02d} is {severity} risk; alarms: " + (", ".join(alarms) if alarms else "none") + ". Continue SOP monitoring.", "semantic"),
        ]
    return {"context": context, "department": "operations", "system": "DCS-OPS", "risk": "critical", "turns": turns}


def synthetic_engineering(i: int, zh: bool) -> dict[str, Any]:
    old_cost = 18.0 + i * 0.4
    new_cost = old_cost + (-1 if i % 2 else 1) * (1.2 + (i % 3) * 0.3)
    qty = 12 + i % 8
    delta = (new_cost - old_cost) * qty
    compatible = i % 3 != 0
    if zh:
        context = (
            f"BOM：组件A-{i:03d}当前版本R2，候选版本R3；每台用量{qty}。"
            f"R2单价{old_cost:.2f}元，R3单价{new_cost:.2f}元。"
            f"接口兼容性验证结果：{'通过' if compatible else '未通过'}。"
            "ECR规则：接口未通过不得批准；成本增加超过20元需成本工程师会签。"
        )
        turns = [
            ("计算每台设备的成本变化。", f"{delta:+.2f}元", "numeric"),
            ("接口是否兼容？", "是" if compatible else "否", "exact"),
            ("ECR能否直接批准？", "否" if not compatible or delta > 20 else "是", "rule"),
            ("列出需要的会签或补充动作。", ("重新完成接口验证；" if not compatible else "") + ("成本工程师会签。" if delta > 20 else "无需成本会签。"), "set"),
            ("生成工程变更摘要。", f"A-{i:03d}拟由R2升级R3，每台成本变化{delta:+.2f}元，接口{'兼容' if compatible else '不兼容'}。", "semantic"),
        ]
    else:
        context = (
            f"BOM: component A-{i:03d}, current revision R2, candidate R3, "
            f"quantity per unit {qty}. R2 costs {old_cost:.2f}; R3 costs "
            f"{new_cost:.2f}. Interface validation: {'passed' if compatible else 'failed'}. "
            "ECR policy: failed compatibility blocks approval; a cost increase above "
            "20 requires a cost-engineer co-sign."
        )
        turns = [
            ("Calculate the cost change per finished unit.", f"{delta:+.2f}", "numeric"),
            ("Is the interface compatible?", "Yes" if compatible else "No", "exact"),
            ("Can the ECR be approved immediately?", "No" if not compatible or delta > 20 else "Yes", "rule"),
            ("List required co-signs or corrective actions.", ("Repeat interface validation; " if not compatible else "") + ("cost-engineer co-sign." if delta > 20 else "no cost co-sign."), "set"),
            ("Create an engineering-change summary.", f"Change A-{i:03d} from R2 to R3; cost delta {delta:+.2f} per unit; interface {'compatible' if compatible else 'incompatible'}.", "semantic"),
        ]
    return {"context": context, "department": "engineering", "system": "PLM-BOM", "risk": "high", "turns": turns}


def synthetic_legal(i: int, zh: bool) -> dict[str, Any]:
    notice = 20 + (i % 4) * 10
    cap = 100000 + i * 5000
    law = ["Singapore", "England", "New York"][i % 3]
    third_party = i % 2 == 0
    if zh:
        context = (
            f"合同LC-{i:03d}：便利终止需提前{notice}日书面通知；责任上限{cap}元；"
            f"适用法律为{law}；未经书面同意{'可以' if third_party else '不得'}向第三方披露。"
        )
        turns = [
            ("提取终止通知期限。", f"{notice}日", "exact"),
            ("责任上限是多少？", f"{cap}元", "exact"),
            ("能否未经同意向第三方披露？", "能" if third_party else "不能", "exact"),
            ("如果今天发出通知，最早何时终止？只需给出计算规则。", f"通知送达日加{notice}日。", "rule"),
            ("生成合同风险摘要。", f"适用{law}法律，责任上限{cap}元，第三方披露{'允许' if third_party else '受限'}，终止需提前{notice}日。", "semantic"),
        ]
    else:
        context = (
            f"Contract LC-{i:03d}: termination for convenience requires {notice} "
            f"days written notice; liability is capped at {cap}; governing law is "
            f"{law}; disclosure to third parties without written consent is "
            f"{'permitted' if third_party else 'prohibited'}."
        )
        turns = [
            ("Extract the termination notice period.", f"{notice} days", "exact"),
            ("What is the liability cap?", str(cap), "exact"),
            ("May information be disclosed to a third party without consent?", "Yes" if third_party else "No", "exact"),
            ("If notice is issued today, state the earliest-termination calculation rule.", f"Date of receipt plus {notice} days.", "rule"),
            ("Create a contract-risk summary.", f"{law} law; liability cap {cap}; third-party disclosure {'permitted' if third_party else 'restricted'}; {notice}-day notice.", "semantic"),
        ]
    return {"context": context, "department": "legal", "system": "CLM-LEGAL", "risk": "critical", "turns": turns}


def synthetic_it(i: int, zh: bool) -> dict[str, Any]:
    service = ["inventory-api", "document-index", "erp-gateway"][i % 3]
    code = [401, 429, 503][i % 3]
    cause = {401: "expired service token", 429: "rate limit exceeded", 503: "upstream unavailable"}[code]
    if zh:
        context = (
            f"工单IT-{i:03d}：服务{service}返回HTTP {code}。日志包含"
            f"`request_id=req-{i:04d}`和`cause={cause}`。工具："
            "`get_service_status(service)`、`rotate_token(service)`、"
            "`adjust_rate_limit(service)`、`restart_service(service)`。"
            "变更规则：先诊断，只有401可轮换令牌，429只能调整限流，503先检查上游。"
        )
        action = {401: "rotate_token", 429: "adjust_rate_limit", 503: "get_service_status"}[code]
        turns = [
            ("识别故障原因。", cause, "exact"),
            ("给出第一步允许调用的工具。", action, "exact"),
            ("生成该工具的JSON调用。", canonical_json({"name": action, "arguments": {"service": service}}), "json"),
            ("是否应当立即重启服务？", "否", "rule"),
            ("生成工单更新摘要。", f"{service}发生HTTP {code}，原因{cause}；按规则执行{action}并观察。", "semantic"),
        ]
    else:
        context = (
            f"Ticket IT-{i:03d}: service {service} returns HTTP {code}. Log fields: "
            f"`request_id=req-{i:04d}`, `cause={cause}`. Tools: "
            "`get_service_status(service)`, `rotate_token(service)`, "
            "`adjust_rate_limit(service)`, `restart_service(service)`. Change rule: "
            "diagnose first; only 401 permits token rotation, 429 permits rate-limit "
            "adjustment, and 503 requires upstream status inspection first."
        )
        action = {401: "rotate_token", 429: "adjust_rate_limit", 503: "get_service_status"}[code]
        turns = [
            ("Identify the fault cause.", cause, "exact"),
            ("Name the first permitted tool.", action, "exact"),
            ("Generate the tool call as JSON.", canonical_json({"name": action, "arguments": {"service": service}}), "json"),
            ("Should the service be restarted immediately?", "No", "rule"),
            ("Write a ticket update.", f"{service} returned HTTP {code} due to {cause}; execute {action} and monitor.", "semantic"),
        ]
    return {"context": context, "department": "information_technology", "system": "ITSM", "risk": "high", "turns": turns}


def synthetic_hr(i: int, zh: bool) -> dict[str, Any]:
    balance = 8 + i % 10
    requested = 3 + i % 8
    manager_required = requested >= 5
    remaining = balance - requested
    if zh:
        context = (
            f"员工E-{i:03d}年假余额{balance}天，申请{requested}天。政策：不得批准超过余额的申请；"
            "连续5天及以上需部门经理审批；健康诊断信息仅HR可查看，不得向直属经理披露。"
        )
        turns = [
            ("余额是否足够？", "是" if remaining >= 0 else "否", "exact"),
            ("批准后剩余多少天？", f"{remaining}天" if remaining >= 0 else "不可批准", "numeric"),
            ("是否需要部门经理审批？", "是" if manager_required else "否", "exact"),
            ("经理要求查看健康诊断，能否提供？", "不能，健康诊断仅HR可查看。", "rule"),
            ("生成给员工的处理回复。", ("申请可进入审批，" if remaining >= 0 else "申请超过余额，不能批准，") + ("需要部门经理审批。" if manager_required and remaining >= 0 else "HR将按政策处理。"), "semantic"),
        ]
    else:
        context = (
            f"Employee E-{i:03d} has {balance} leave days and requests {requested}. "
            "Policy: never approve more than the balance; five or more consecutive "
            "days require department-manager approval; medical diagnosis is HR-only "
            "and must not be disclosed to the line manager."
        )
        turns = [
            ("Is the leave balance sufficient?", "Yes" if remaining >= 0 else "No", "exact"),
            ("What balance remains after approval?", str(remaining) if remaining >= 0 else "Cannot approve", "numeric"),
            ("Is department-manager approval required?", "Yes" if manager_required else "No", "exact"),
            ("The manager asks for the diagnosis. Can it be disclosed?", "No. Medical diagnosis is HR-only.", "rule"),
            ("Draft a response to the employee.", ("The request may proceed; " if remaining >= 0 else "The request exceeds the balance; ") + ("manager approval is required." if manager_required and remaining >= 0 else "HR will process it under policy."), "semantic"),
        ]
    return {"context": context, "department": "human_resources", "system": "HRIS", "risk": "critical", "turns": turns}


def synthetic_security(i: int, zh: bool) -> dict[str, Any]:
    failed = 4 + i % 9
    privileged = i % 3 == 0
    foreign = i % 2 == 0
    severity = "critical" if privileged and foreign and failed >= 8 else "high" if privileged or failed >= 8 else "medium"
    action = "disable_account" if severity == "critical" else "force_mfa" if severity == "high" else "open_investigation"
    if zh:
        context = (
            f"安全事件SEC-{i:03d}：账户U-{i:03d}失败登录{failed}次，"
            f"{'来自境外地址' if foreign else '来自常用地址'}，"
            f"{'具有特权' if privileged else '普通账户'}。规则：境外+特权+失败≥8为critical；"
            "特权或失败≥8为high；其余medium。critical禁用账户，high强制MFA，medium立案调查。"
        )
        turns = [
            ("按规则判定严重级别。", severity, "exact"),
            ("给出规定的首要处置动作。", action, "exact"),
            ("生成处置工具调用JSON。", canonical_json({"name": action, "arguments": {"account": f"U-{i:03d}"}}), "json"),
            ("列出支持该判定的证据。", f"失败{failed}次、{'境外' if foreign else '常用'}地址、{'特权' if privileged else '普通'}账户。", "set"),
            ("生成事件摘要。", f"SEC-{i:03d}判定为{severity}，对U-{i:03d}执行{action}并保全登录证据。", "semantic"),
        ]
    else:
        context = (
            f"Security event SEC-{i:03d}: account U-{i:03d}, {failed} failed "
            f"logins, {'foreign' if foreign else 'usual'} source, "
            f"{'privileged' if privileged else 'standard'} account. Rule: foreign + "
            "privileged + failures >=8 is critical; privileged or failures >=8 is "
            "high; otherwise medium. Critical disables the account, high forces MFA, "
            "and medium opens an investigation."
        )
        turns = [
            ("Classify severity under the rule.", severity, "exact"),
            ("Give the required first response.", action, "exact"),
            ("Generate the response tool call as JSON.", canonical_json({"name": action, "arguments": {"account": f"U-{i:03d}"}}), "json"),
            ("List evidence supporting the classification.", f"{failed} failures, {'foreign' if foreign else 'usual'} source, {'privileged' if privileged else 'standard'} account.", "set"),
            ("Create an incident summary.", f"SEC-{i:03d} is {severity}; apply {action} to U-{i:03d} and preserve login evidence.", "semantic"),
        ]
    return {"context": context, "department": "security", "system": "SIEM-IAM", "risk": "critical", "turns": turns}


SYNTHETIC_BUILDERS: list[tuple[str, Callable[[int, bool], dict[str, Any]]]] = [
    ("procurement_workflow", synthetic_procurement),
    ("finance_erp", synthetic_finance),
    ("operations_dcs", synthetic_operations),
    ("engineering_change", synthetic_engineering),
    ("legal_contract", synthetic_legal),
    ("it_service_agent", synthetic_it),
    ("hr_policy", synthetic_hr),
    ("security_incident", synthetic_security),
]


def render_cumulative_prompt(
    *,
    language: str,
    company_context: str,
    history: list[tuple[str, str]],
    question: str,
) -> str:
    if language == "zh-CN":
        header = (
            "系统：你是“北辰集成工业集团”的内网助手。这是一家完全虚构的企业。"
            "只能依据给定记录回答；遵守权限、审批和安全规则。\n\n"
            f"当前业务记录：\n{company_context}"
        )
        history_text = "\n".join(
            f"用户：{q}\n助手：{a}" for q, a in history
        )
        return f"{header}\n\n{history_text + chr(10) if history_text else ''}用户：{question}\n助手："
    header = (
        "System: You are the on-premise assistant for Northstar Integrated "
        "Industries, a wholly fictional company. Answer only from the supplied "
        "records and follow all approval, access, and safety rules.\n\n"
        f"Current business record:\n{company_context}"
    )
    history_text = "\n".join(f"User: {q}\nAssistant: {a}" for q, a in history)
    return f"{header}\n\n{history_text + chr(10) if history_text else ''}User: {question}\nAssistant:"


def build_synthetic() -> list[dict[str, Any]]:
    workflows: list[tuple[str, str, dict[str, Any], str]] = []
    for category_index, (category, builder) in enumerate(SYNTHETIC_BUILDERS):
        for local_index in range(25):
            global_index = category_index * 25 + local_index
            zh = global_index % 2 == 0
            language = "zh-CN" if zh else "en"
            workflow_id = f"syn-{category_index:02d}-{local_index:03d}"
            workflows.append(
                (workflow_id, category, builder(local_index, zh), language)
            )

    shuffled_ids = [item[0] for item in workflows]
    random.Random(SEED + 500).shuffle(shuffled_ids)
    discovery_ids = set(shuffled_ids[:150])

    records: list[dict[str, Any]] = []
    for workflow_id, category, workflow, language in workflows:
        history: list[tuple[str, str]] = []
        for turn_index, (question, answer, evaluator_type) in enumerate(workflow["turns"]):
            prompt = render_cumulative_prompt(
                language=language,
                company_context=workflow["context"],
                history=history,
                question=question,
            )
            record = make_record(
                record_id=f"{workflow_id}-t{turn_index + 1}",
                dataset_name="SyntheticEnterprise-1K",
                text=f"{prompt} {answer}",
                prompt_text=prompt,
                category=category,
                domain=workflow["department"],
                operation=f"workflow_turn_{turn_index + 1}",
                language=language,
                source=source_ref(
                    "moe-hierarchy-lab/SyntheticEnterprise-1K",
                    config=category,
                    split="generated",
                    row_id=f"{workflow_id}:{turn_index + 1}",
                ),
                reference_answer=answer,
                evaluator={"type": evaluator_type},
                workflow_id=workflow_id,
                turn_index=turn_index,
                turn_count=5,
                department=workflow["department"],
                system=workflow["system"],
                risk_tier=workflow["risk"],
                provenance_type="deterministic_synthetic",
                metadata={
                    "fictional_company": True,
                    "contains_real_company_data": False,
                    "generation_method": "deterministic_templates_and_arithmetic",
                },
            )
            record["split"] = (
                "discovery" if workflow_id in discovery_ids else "confirmatory"
            )
            records.append(record)
            history.append((question, answer))
    return records


def count(records: Iterable[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(str(record[key]) for record in records).items()))


def derive_and_audit(
    records: list[dict[str, Any]],
    *,
    dataset_name: str,
    expected_categories: dict[str, int],
    expected_splits: dict[str, int],
    skip_token_audit: bool,
) -> dict[str, Any]:
    token_meta = add_derived_fields(records, skip_token_audit)
    ids = [record["id"] for record in records]
    workflows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        workflows[record["workflow_id"]].append(record)
    synthetic = dataset_name == "SyntheticEnterprise-1K"
    workflow_integrity = True
    if synthetic:
        workflow_integrity = (
            len(workflows) == 200
            and all(
                len(group) == 5
                and sorted(record["turn_index"] for record in group)
                == list(range(5))
                and len({record["split"] for record in group}) == 1
                for group in workflows.values()
            )
        )
    checks = {
        "total_is_1000": len(records) == 1000,
        "unique_ids": len(ids) == len(set(ids)),
        "category_quotas": count(records, "category") == expected_categories,
        "split_quotas": count(records, "split") == expected_splits,
        "exact_text_unique": not duplicate_groups(records, "content_sha256"),
        "normalized_text_unique": not duplicate_groups(
            records, "normalized_content_sha256"
        ),
        "all_sources_revisioned": all(record["source"]["revision"] for record in records),
        "all_sources_licensed": all(record["source"]["license"] for record in records),
        "all_evaluators_present": all(record["evaluator"]["type"] for record in records),
        "workflow_integrity": workflow_integrity,
        "no_real_company_data_claim": (
            all(
                record["metadata"].get("contains_real_company_data") is False
                for record in records
            )
            if synthetic
            else True
        ),
    }
    length_bins: dict[str, dict[str, int]] = {}
    for tokenizer in ("granite", "olmoe"):
        if records and tokenizer in records[0]["token_length_bins"]:
            length_bins[tokenizer] = dict(
                sorted(
                    Counter(
                        record["token_length_bins"][tokenizer] for record in records
                    ).items()
                )
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "dataset_name": dataset_name,
        "seed": SEED,
        "checks": checks,
        "all_checks_pass": all(checks.values()),
        "counts": {
            "total": len(records),
            "category": count(records, "category"),
            "split": count(records, "split"),
            "language": count(records, "language"),
            "department": count(records, "department"),
            "system": count(records, "system"),
            "risk_tier": count(records, "risk_tier"),
            "provenance_type": count(records, "provenance_type"),
            "sources": dict(
                sorted(Counter(record["source"]["dataset"] for record in records).items())
            ),
            "workflows": len(workflows),
            "token_length_bins": length_bins,
        },
        "duplicate_groups": {
            "exact": duplicate_groups(records, "content_sha256"),
            "normalized": duplicate_groups(records, "normalized_content_sha256"),
        },
        "token_audit": token_meta,
        "source_manifest": {
            source: SOURCE_MANIFEST[source]
            for source in sorted({record["source"]["dataset"] for record in records})
        },
    }


REQUIRED_FIELDS = [
    "schema_version",
    "dataset_name",
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
    "workflow_id",
    "session_id",
    "turn_index",
    "turn_count",
    "department",
    "system",
    "risk_tier",
    "provenance_type",
    "reference_answer",
    "evaluator",
    "source",
    "metadata",
    "content_sha256",
    "normalized_content_sha256",
    "char_length",
    "word_count",
    "token_lengths",
    "token_length_bins",
    "truncated_at_512",
]


def write_dataset(
    output_dir: Path,
    filename: str,
    records: list[dict[str, Any]],
    audit: dict[str, Any],
    readme: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    records.sort(key=lambda record: record["id"])
    jsonl_path = output_dir / filename
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(canonical_json(record) + "\n")
    audit["artifact"] = {
        "path": str(jsonl_path.relative_to(ROOT)),
        "sha256": hashlib.sha256(jsonl_path.read_bytes()).hexdigest(),
        "bytes": jsonl_path.stat().st_size,
    }
    builder_path = Path(__file__).resolve()
    audit["builder"] = {
        "path": str(builder_path.relative_to(ROOT)),
        "sha256": hashlib.sha256(builder_path.read_bytes()).hexdigest(),
        "seed": SEED,
    }
    (output_dir / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    schema = {
        "schema_version": SCHEMA_VERSION,
        "required_fields": REQUIRED_FIELDS,
        "source_required_fields": [
            "dataset",
            "config",
            "split",
            "row_id",
            "revision",
            "license",
            "url",
            "usage",
        ],
        "evaluator_required_fields": ["type"],
    }
    (output_dir / "schema.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "SOURCE_MANIFEST.json").write_text(
        json.dumps(audit["source_manifest"], ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "README.md").write_text(readme.strip() + "\n", encoding="utf-8")


PUBLIC_README = """# EnterpriseProxy-1K v1.0

面向MoE路由研究的公开企业代理集，共1000条，五类各200条：

| 类别 | 来源 | 条数 |
|---|---|---:|
| 长文档总结/RAG | LongBench GovReport | 200 |
| 结构化分析 | Spider 2.0 Lite | 200 |
| 工具与Agent | BFCL v3 | 200 |
| 软件工程 | SWE-bench Lite | 200 |
| 合同合规 | LegalBench ContractNLI | 200 |

数据采用 discovery / confirmatory = 700 / 300 的分层冻结划分。它是科研
代理基准，不声称代表任一具体企业的真实任务比例。逐来源版本、许可和
再分发边界见 `SOURCE_MANIFEST.json`。没有使用本项目研究者所在公司的
数据、日志、文档或激活记录。

`text` 可直接交给现有 `collect_routes.py`；`prompt_text` 排除参考答案。
"""

SYNTHETIC_README = """# SyntheticEnterprise-1K v1.0

完全虚构、确定性生成的企业内部工作流集：

- 虚拟企业：北辰集成工业集团 / Northstar Integrated Industries；
- 8类业务，各25个工作流；
- 每个工作流5轮，合计200个会话、1000次模型调用；
- 中文与英文各500条；
- 每一轮使用累积会话上下文；
- 全部答案来自规则、算术或确定性JSON构造；
- 不含真实公司数据、私人日志、用户prompt或外部模型生成内容。

工作流级 discovery / confirmatory = 150 / 50，对应调用数750 / 250。
内容以 CC BY 4.0 发布。`text` 可直接交给现有路由采集器。
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--skip-token-audit", action="store_true")
    parser.add_argument(
        "--cache-dir", type=Path, default=CACHE / "http"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    api = DatasetServer(args.cache_dir, offline=args.offline)

    public_records = build_public(api)
    public_categories = {
        "document_rag": 200,
        "structured_analytics": 200,
        "tool_agent": 200,
        "software_engineering": 200,
        "legal_compliance": 200,
    }
    public_audit = derive_and_audit(
        public_records,
        dataset_name="EnterpriseProxy-1K",
        expected_categories=public_categories,
        expected_splits={"discovery": 700, "confirmatory": 300},
        skip_token_audit=args.skip_token_audit,
    )
    if not public_audit["all_checks_pass"]:
        raise RuntimeError(
            "EnterpriseProxy audit failed: "
            + canonical_json(
                {key: value for key, value in public_audit["checks"].items() if not value}
            )
        )
    write_dataset(
        ROOT / "data" / "enterprise_proxy_1k",
        "enterprise_proxy_1k.jsonl",
        public_records,
        public_audit,
        PUBLIC_README,
    )

    synthetic_records = build_synthetic()
    synthetic_categories = {name: 125 for name, _ in SYNTHETIC_BUILDERS}
    synthetic_audit = derive_and_audit(
        synthetic_records,
        dataset_name="SyntheticEnterprise-1K",
        expected_categories=synthetic_categories,
        expected_splits={"discovery": 750, "confirmatory": 250},
        skip_token_audit=args.skip_token_audit,
    )
    if not synthetic_audit["all_checks_pass"]:
        raise RuntimeError(
            "SyntheticEnterprise audit failed: "
            + canonical_json(
                {
                    key: value
                    for key, value in synthetic_audit["checks"].items()
                    if not value
                }
            )
        )
    write_dataset(
        ROOT / "data" / "synthetic_enterprise_1k",
        "synthetic_enterprise_1k.jsonl",
        synthetic_records,
        synthetic_audit,
        SYNTHETIC_README,
    )

    print(
        canonical_json(
            {
                "enterprise_proxy": public_audit["counts"],
                "synthetic_enterprise": synthetic_audit["counts"],
            }
        )
    )


if __name__ == "__main__":
    main()
