#!/usr/bin/env python3
"""Build ControllerProbe-D1: a diversity-controlled decode probe set.

Motivation
----------
Every existing probe pool in this repository wraps each workload category in a
single fixed instruction template.  Under raw continuation the model echoes the
shared template tail before it produces category-specific content, so the first
tens of decode tokens are near-identical across concurrent requests.  Any
per-step expert union measured over a short decode window then reports template
alignment rather than workload structure.

D1 keeps the same six archetypes and the same public sources, but:

1.  Twelve structurally distinct prompt *forms*, each ending in a different
    kind of line (question / data / skeleton / constraint / mid-sentence /
    speaker tag / table header / deliverable name ...), crossed with two
    instruction languages.  No two `diverse` records inside one
    (archetype, split) share a (form, language) pair.
2.  Eight task framings per archetype, so the *content* the model must produce
    diverges, not only the wrapper.
3.  Five payload rendering styles and, for the industrial archetypes, six
    different source families with genuinely different record shapes.
4.  A matched-pair `single_template` control: the same source records rendered
    with one fixed legacy-style template.  This turns the template artifact
    into a measurable quantity instead of an argument.
5.  Per-record collection directives (`target_new_tokens`,
    `arrival_offset_steps`, `requires_chat_template`) so the collector can
    break cohort position lock and run past the boilerplate region.

The record schema is a superset of `data/controller_probe_v0_1_3/schema.json`,
so the existing collection and conversion pipeline reads it unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

SCHEMA_VERSION = "controller-probe-d1"
BUILD_SEED = "controller-probe-d1-20260801"

ARCHETYPES = (
    "document_rag",
    "tool_agent",
    "erp_structured_analytics",
    "office_legal",
    "dcs_process_diagnostics",
    "equipment_maintenance_bom",
)

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"

# ---------------------------------------------------------------------------
# deterministic helpers
# ---------------------------------------------------------------------------


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_rank(seed: str, key: str) -> int:
    """Deterministic ordering key independent of insertion order."""
    return int(sha256_text(f"{seed}|{key}")[:16], 16)


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


# A single fixed truncation marker would become the shared final line of every
# form whose tail is the data block, reintroducing exactly the tail collision
# this probe set exists to avoid.
TRUNCATION_NOTICES = (
    "[record truncated]",
    "[... remainder of record omitted]",
    "[excerpt ends here]",
    "[record continues beyond this excerpt]",
    "[truncated for review]",
    "[end of supplied extract]",
)


def clip(text: str, limit: int, notice_idx: int = 0) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    pivot = max(cut.rfind("\n"), cut.rfind(". "), cut.rfind("。"))
    if pivot > limit * 0.6:
        cut = cut[: pivot + 1]
    notice = TRUNCATION_NOTICES[notice_idx % len(TRUNCATION_NOTICES)]
    return cut.rstrip() + "\n" + notice


def num(value: Any, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int,)):
        return str(value)
    if isinstance(value, float):
        if value != value:  # NaN
            return "n/a"
        return f"{value:.{digits}g}"
    return str(value)


# ---------------------------------------------------------------------------
# payload rendering styles
# ---------------------------------------------------------------------------


def style_bullets(pairs: Sequence[tuple[str, Any]]) -> str:
    return "\n".join(f"- {k}: {num(v)}" for k, v in pairs)


def style_key_value(pairs: Sequence[tuple[str, Any]]) -> str:
    width = max((len(k) for k, _ in pairs), default=0)
    return "\n".join(f"{k.ljust(width)} = {num(v)}" for k, v in pairs)


def style_markdown_table(pairs: Sequence[tuple[str, Any]]) -> str:
    head = "| field | value |\n|---|---|"
    body = "\n".join(f"| {k} | {num(v)} |" for k, v in pairs)
    return f"{head}\n{body}"


def style_compact_json(pairs: Sequence[tuple[str, Any]]) -> str:
    return json.dumps({k: v for k, v in pairs}, ensure_ascii=False, sort_keys=False)


def style_prose(pairs: Sequence[tuple[str, Any]]) -> str:
    return "; ".join(f"{k} {num(v)}" for k, v in pairs) + "."


PAYLOAD_STYLES: tuple[tuple[str, Callable[[Sequence[tuple[str, Any]]], str]], ...] = (
    ("bullets", style_bullets),
    ("key_value", style_key_value),
    ("markdown_table", style_markdown_table),
    ("compact_json", style_compact_json),
    ("prose", style_prose),
)


# ---------------------------------------------------------------------------
# prompt forms -- each ends with a structurally different final line
# ---------------------------------------------------------------------------

FORM_IDS = (
    "f01_spec_data_question",
    "f02_data_first_bare",
    "f03_question_first",
    "f04_dialogue_turn",
    "f05_terse_imperative",
    "f06_output_skeleton",
    "f07_constraint_last",
    "f08_continuation_stem",
    "f09_ticket_email",
    "f10_paired_comparison",
    "f11_table_request",
    "f12_role_brief",
)


# Role lines are composed from the task persona plus a scope rule, so the
# opening sentence varies with the task rather than being frozen per archetype.
ROLE_SHAPES = (
    ("你现在的身份是{persona}。{scope}", "You are acting as {article} {persona_l}. {scope}"),
    ("{persona}视角。{scope}", "From the perspective of {article} {persona_l}: {scope}"),
    ("以{persona}的身份处理下面的材料。{scope}", "Handle the material below as {article} {persona_l}. {scope}"),
    ("{scope}当前处理人：{persona}。", "{scope} Handled by: {persona_l}."),
    ("岗位：{persona}。{scope}", "Position: {persona_l}. {scope}"),
    ("{scope}本次由{persona}负责。", "{scope} This item is owned by {article} {persona_l}."),
)

LABEL_SUFFIXES = (
    ("", ""),
    ("（原始字段）", " (raw fields)"),
    ("（节选）", " (excerpt)"),
    ("（整理后）", " (normalised)"),
)


def compose_role(shape_idx: int, lang: str, persona: str, scope: str) -> str:
    zh, en = ROLE_SHAPES[shape_idx % len(ROLE_SHAPES)]
    if lang == "zh-CN":
        return zh.format(persona=persona, scope=scope)
    lowered = persona[0].lower() + persona[1:]
    article = "an" if lowered[0] in "aeiou" else "a"
    return en.format(persona_l=lowered, scope=scope, article=article)


def render_form(form_id: str, lang: str, ctx: dict[str, str]) -> str:
    """Compose one prompt.  ``ctx`` carries language-resolved fragments."""
    role = ctx["role"]
    label = ctx["data_label"]
    data = ctx["data"]
    question = ctx["question"]
    zh = lang == "zh-CN"

    if form_id == "f01_spec_data_question":
        return f"{role}\n\n{label}:\n{data}\n\n{question}"
    if form_id == "f02_data_first_bare":
        return f"{label}:\n{data}\n\n{question}"
    if form_id == "f03_question_first":
        lead = "先读下面的记录再回答。" if zh else "Read the record below before answering."
        return f"{question}\n\n{lead}\n\n{label}:\n{data}"
    if form_id == "f04_dialogue_turn":
        a = "值班工程师" if zh else "Duty engineer"
        b = "助手" if zh else "Assistant"
        return f"{role}\n\n{label}:\n{data}\n\n{a}：{question}\n{b}："
    if form_id == "f05_terse_imperative":
        return f"{ctx['terse']}\n{data}"
    if form_id == "f06_output_skeleton":
        return f"{role}\n\n{label}:\n{data}\n\n{question}\n\n{ctx['skeleton']}"
    if form_id == "f07_constraint_last":
        return f"{role}\n\n{label}:\n{data}\n\n{question}\n\n{ctx['constraint']}"
    if form_id == "f08_continuation_stem":
        return f"{label}:\n{data}\n\n{ctx['stem']}"
    if form_id == "f09_ticket_email":
        if zh:
            header = (
                f"发件人：{ctx['sender']}\n收件人：{ctx['audience']}\n"
                f"主题：{ctx['subject']}\n优先级：{ctx['priority']}"
            )
        else:
            header = (
                f"From: {ctx['sender']}\nTo: {ctx['audience']}\n"
                f"Subject: {ctx['subject']}\nPriority: {ctx['priority']}"
            )
        return f"{header}\n\n{label}:\n{data}\n\n{question}"
    if form_id == "f10_paired_comparison":
        left = "记录 A" if zh else "Record A"
        right = "记录 B" if zh else "Record B"
        tail = "差异：" if zh else "Differences:"
        return (
            f"{role}\n\n{left}:\n{data}\n\n{right}:\n{ctx['data_b']}\n\n"
            f"{question}\n\n{tail}"
        )
    if form_id == "f11_table_request":
        return f"{role}\n\n{label}:\n{data}\n\n{question}\n\n{ctx['table_header']}"
    if form_id == "f12_role_brief":
        if zh:
            brief = (
                f"角色：{ctx['persona']}\n受众：{ctx['audience']}\n"
                f"交付物：{ctx['deliverable']}\n约束：{ctx['constraint']}"
            )
        else:
            brief = (
                f"Role: {ctx['persona']}\nAudience: {ctx['audience']}\n"
                f"Deliverable: {ctx['deliverable']}\nConstraint: {ctx['constraint']}"
            )
        return f"{brief}\n\n{label}:\n{data}"
    raise KeyError(form_id)


# forms whose final line is *not* natural-language instruction text; recorded so
# the audit can report how much of the set is protected against tail echo.
NON_INSTRUCTION_TAIL_FORMS = frozenset(
    {
        "f03_question_first",
        "f04_dialogue_turn",
        "f05_terse_imperative",
        "f06_output_skeleton",
        "f08_continuation_stem",
        "f10_paired_comparison",
        "f11_table_request",
        "f12_role_brief",
    }
)


# ---------------------------------------------------------------------------
# archetype task framings
# ---------------------------------------------------------------------------
# Each entry supplies eight task framings.  Fields are (zh, en) pairs.

TaskSpec = dict[str, tuple[str, str]]


def T(**kwargs: tuple[str, str]) -> TaskSpec:
    return dict(kwargs)


ARCHETYPE_TASKS: dict[str, tuple[TaskSpec, ...]] = {
    "document_rag": (
        T(
            task_type=("summarize_findings", "summarize_findings"),
            question=(
                "用不超过八句话概括本报告的主要发现，保留所有量化结论。",
                "Summarise the report's principal findings in at most eight sentences and keep every quantitative result.",
            ),
            terse=("概括要点，保留数字。", "Summarise the key points; keep the numbers."),
            skeleton=(
                "发现 1：\n发现 2：\n发现 3：\n量化证据：",
                "Finding 1:\nFinding 2:\nFinding 3:\nQuantitative evidence:",
            ),
            constraint=(
                "只允许引用文中出现过的数字，不得外推。",
                "Cite only figures that appear in the text; do not extrapolate.",
            ),
            stem=(
                "本报告最重要的三项发现依次是，第一，",
                "The three most important findings of this report are, first,",
            ),
            table_header=(
                "| 发现 | 证据段落 | 数值 |\n|---|---|---|",
                "| finding | supporting passage | value |\n|---|---|---|",
            ),
            persona=("政策研究分析师", "Policy research analyst"),
            deliverable=("要点纪要", "Findings memo"),
        ),
        T(
            task_type=("extract_recommendations", "extract_recommendations"),
            question=(
                "抽取报告中所有给出的建议，并标注每条建议的责任主体。",
                "Extract every recommendation the report makes and attribute each one to its responsible party.",
            ),
            terse=("列出全部建议及责任方。", "List all recommendations and their owners."),
            skeleton=(
                "建议：\n责任主体：\n依据段落：",
                "Recommendation:\nResponsible party:\nSupporting passage:",
            ),
            constraint=(
                "报告未指明责任主体的，写“未指明”，不要推测。",
                "Where the report names no owner, write 'unspecified'; do not guess.",
            ),
            stem=(
                "报告提出的第一条建议是",
                "The first recommendation the report makes is",
            ),
            table_header=(
                "| 建议 | 责任主体 | 时限 |\n|---|---|---|",
                "| recommendation | owner | deadline |\n|---|---|---|",
            ),
            persona=("合规审阅人", "Compliance reviewer"),
            deliverable=("建议清单", "Recommendation register"),
        ),
        T(
            task_type=("risk_triage", "risk_triage"),
            question=(
                "识别报告中描述的风险，按严重程度排序并说明排序依据。",
                "Identify the risks described in the report, rank them by severity and justify the ranking.",
            ),
            terse=("按严重度排序风险。", "Rank the described risks by severity."),
            skeleton=(
                "高：\n中：\n低：\n排序依据：",
                "High:\nMedium:\nLow:\nRanking rationale:",
            ),
            constraint=(
                "严重度必须以文中证据支撑，不得引入外部知识。",
                "Every severity call must rest on evidence in the text; no outside knowledge.",
            ),
            stem=(
                "在本报告描述的风险中，最严重的一项是",
                "Among the risks this report describes, the most severe is",
            ),
            table_header=(
                "| 风险 | 严重度 | 证据 |\n|---|---|---|",
                "| risk | severity | evidence |\n|---|---|---|",
            ),
            persona=("风险管理负责人", "Risk manager"),
            deliverable=("风险排序表", "Risk ranking"),
        ),
        T(
            task_type=("answer_scoped_question", "answer_scoped_question"),
            question=(
                "报告对成本与预算的表述是什么？只依据原文回答。",
                "What does the report say about costs and budget? Answer from the text only.",
            ),
            terse=("回答成本相关内容。", "Report what is said about cost."),
            skeleton=(
                "结论：\n引用原文：\n不确定之处：",
                "Answer:\nQuoted passage:\nRemaining uncertainty:",
            ),
            constraint=(
                "若报告未提及，直接回答“报告未提及”。",
                "If the report does not address it, answer 'not addressed'.",
            ),
            stem=(
                "关于成本，报告指出",
                "On the question of cost, the report states",
            ),
            table_header=(
                "| 问题 | 原文依据 | 结论 |\n|---|---|---|",
                "| question | passage | answer |\n|---|---|---|",
            ),
            persona=("预算审查员", "Budget examiner"),
            deliverable=("问询答复", "Query response"),
        ),
        T(
            task_type=("draft_executive_brief", "draft_executive_brief"),
            question=(
                "为管理层写一份三段式简报：背景、结论、待决事项。",
                "Draft a three-paragraph executive brief: background, conclusion, open decisions.",
            ),
            terse=("写三段式管理层简报。", "Write a three-paragraph executive brief."),
            skeleton=(
                "背景：\n结论：\n待决事项：",
                "Background:\nConclusion:\nOpen decisions:",
            ),
            constraint=(
                "全文不得超过两百字，且不得使用项目符号。",
                "Stay under 200 words and do not use bullet points.",
            ),
            stem=(
                "背景。本报告处理的核心问题是",
                "Background. The core question this report addresses is",
            ),
            table_header=(
                "| 段落 | 内容要点 |\n|---|---|",
                "| section | content |\n|---|---|",
            ),
            persona=("幕僚长", "Chief of staff"),
            deliverable=("管理层简报", "Executive brief"),
        ),
        T(
            task_type=("identify_evidence_gaps", "identify_evidence_gaps"),
            question=(
                "指出报告结论中证据不足或依赖假设的部分。",
                "Point out where the report's conclusions rest on thin evidence or stated assumptions.",
            ),
            terse=("找出证据薄弱处。", "Locate the weakly evidenced claims."),
            skeleton=(
                "结论：\n所依赖的假设：\n缺失的证据：",
                "Claim:\nAssumption relied on:\nMissing evidence:",
            ),
            constraint=(
                "只标注报告自身承认或明显缺失的证据缺口。",
                "Flag only gaps the report concedes or that are plainly absent.",
            ),
            stem=(
                "报告中证据最薄弱的一处结论是",
                "The most weakly evidenced conclusion in the report is",
            ),
            table_header=(
                "| 结论 | 依赖假设 | 缺失证据 |\n|---|---|---|",
                "| claim | assumption | missing evidence |\n|---|---|---|",
            ),
            persona=("同行评审专家", "Peer reviewer"),
            deliverable=("证据缺口说明", "Evidence gap note"),
        ),
        T(
            task_type=("timeline_reconstruction", "timeline_reconstruction"),
            question=(
                "按时间顺序重建报告中提到的关键事件。",
                "Reconstruct, in chronological order, the key events the report mentions.",
            ),
            terse=("按时间线重排关键事件。", "Order the key events chronologically."),
            skeleton=(
                "时间：\n事件：\n出处：",
                "Date:\nEvent:\nSource passage:",
            ),
            constraint=(
                "时间不明确的事件放在末尾并标注“时间不详”。",
                "Place undated events last and mark them 'date unknown'.",
            ),
            stem=(
                "最早发生的事件是",
                "The earliest event described is",
            ),
            table_header=(
                "| 时间 | 事件 | 出处 |\n|---|---|---|",
                "| date | event | passage |\n|---|---|---|",
            ),
            persona=("档案研究员", "Archival researcher"),
            deliverable=("事件时间线", "Event timeline"),
        ),
        T(
            task_type=("stakeholder_impact", "stakeholder_impact"),
            question=(
                "分析报告结论对各利益相关方的影响差异。",
                "Analyse how the report's conclusions land differently for each stakeholder group.",
            ),
            terse=("分析各方受影响差异。", "Contrast the impact by stakeholder."),
            skeleton=(
                "利益相关方：\n受影响方式：\n证据：",
                "Stakeholder:\nHow affected:\nEvidence:",
            ),
            constraint=(
                "只讨论报告中显式出现的利益相关方。",
                "Discuss only stakeholders the report names explicitly.",
            ),
            stem=(
                "受影响最直接的一方是",
                "The group affected most directly is",
            ),
            table_header=(
                "| 利益相关方 | 影响 | 证据 |\n|---|---|---|",
                "| stakeholder | impact | evidence |\n|---|---|---|",
            ),
            persona=("公共事务顾问", "Public affairs adviser"),
            deliverable=("影响分析", "Impact analysis"),
        ),
    ),
    "tool_agent": (
        T(
            task_type=("select_single_call", "select_single_call"),
            question=(
                "选择正确的函数并给出完整的调用参数。",
                "Choose the correct function and give the complete call with arguments.",
            ),
            terse=("给出函数调用。", "Emit the function call."),
            skeleton=(
                "函数名：\n参数：\n理由：",
                "Function:\nArguments:\nReason:",
            ),
            constraint=(
                "参数必须严格符合声明的类型，缺失参数不得臆造。",
                "Arguments must match the declared types; do not invent missing ones.",
            ),
            stem=(
                "需要调用的函数是",
                "The function that must be called is",
            ),
            table_header=(
                "| 参数 | 取值 | 来源 |\n|---|---|---|",
                "| argument | value | source |\n|---|---|---|",
            ),
            persona=("集成工程师", "Integration engineer"),
            deliverable=("调用规格", "Call specification"),
        ),
        T(
            task_type=("plan_multi_step", "plan_multi_step"),
            question=(
                "规划完成该请求所需的工具调用顺序，并说明每步的前置条件。",
                "Plan the sequence of tool calls needed and state each step's precondition.",
            ),
            terse=("列出调用顺序。", "List the call sequence."),
            skeleton=(
                "步骤 1：\n前置条件：\n步骤 2：\n前置条件：",
                "Step 1:\nPrecondition:\nStep 2:\nPrecondition:",
            ),
            constraint=(
                "不得调用未在清单中声明的工具。",
                "Do not call any tool absent from the declared list.",
            ),
            stem=(
                "第一步应当调用",
                "The first call should be",
            ),
            table_header=(
                "| 序号 | 工具 | 前置条件 |\n|---|---|---|",
                "| # | tool | precondition |\n|---|---|---|",
            ),
            persona=("自动化编排者", "Automation orchestrator"),
            deliverable=("执行计划", "Execution plan"),
        ),
        T(
            task_type=("validate_arguments", "validate_arguments"),
            question=(
                "检查请求中的参数是否足以完成调用，指出缺失或类型不符之处。",
                "Check whether the request supplies enough arguments; flag anything missing or mistyped.",
            ),
            terse=("校验参数完整性。", "Validate argument completeness."),
            skeleton=(
                "缺失参数：\n类型不符：\n可安全调用：是/否",
                "Missing:\nType mismatch:\nSafe to call: yes/no",
            ),
            constraint=(
                "任何一项必填参数缺失即判定为不可调用。",
                "A single missing required argument makes the call invalid.",
            ),
            stem=(
                "参数校验的结论是",
                "The argument validation result is",
            ),
            table_header=(
                "| 参数 | 必填 | 是否提供 |\n|---|---|---|",
                "| argument | required | supplied |\n|---|---|---|",
            ),
            persona=("接口测试工程师", "API test engineer"),
            deliverable=("校验报告", "Validation report"),
        ),
        T(
            task_type=("choose_between_tools", "choose_between_tools"),
            question=(
                "在可用工具中说明为何选择其中一个而排除其余。",
                "Explain why one of the available tools fits and the others do not.",
            ),
            terse=("说明工具取舍。", "Justify the tool choice."),
            skeleton=(
                "选中：\n排除及原因：",
                "Selected:\nRejected and why:",
            ),
            constraint=(
                "排除理由必须引用工具声明中的具体字段。",
                "Each rejection must cite a specific field of the tool declaration.",
            ),
            stem=(
                "最合适的工具是",
                "The most appropriate tool is",
            ),
            table_header=(
                "| 工具 | 是否选用 | 原因 |\n|---|---|---|",
                "| tool | selected | reason |\n|---|---|---|",
            ),
            persona=("解决方案架构师", "Solution architect"),
            deliverable=("选型说明", "Selection rationale"),
        ),
        T(
            task_type=("state_tracking", "state_tracking"),
            question=(
                "根据当前状态判断下一次调用后系统状态会如何变化。",
                "Given the current state, describe how it changes after the next call.",
            ),
            terse=("推演状态变化。", "Trace the state transition."),
            skeleton=(
                "调用前：\n调用：\n调用后：",
                "Before:\nCall:\nAfter:",
            ),
            constraint=(
                "只描述状态中显式存在的字段。",
                "Describe only fields that exist explicitly in the state.",
            ),
            stem=(
                "执行该调用后，状态中发生变化的字段是",
                "After that call, the state fields that change are",
            ),
            table_header=(
                "| 字段 | 调用前 | 调用后 |\n|---|---|---|",
                "| field | before | after |\n|---|---|---|",
            ),
            persona=("运行时调试者", "Runtime debugger"),
            deliverable=("状态推演", "State trace"),
        ),
        T(
            task_type=("failure_handling", "failure_handling"),
            question=(
                "若该调用返回错误，说明应如何重试或降级。",
                "If the call returns an error, describe the retry or fallback path.",
            ),
            terse=("给出失败处理路径。", "Give the failure-handling path."),
            skeleton=(
                "错误类型：\n重试策略：\n降级方案：",
                "Error class:\nRetry policy:\nFallback:",
            ),
            constraint=(
                "降级方案不得调用清单之外的工具。",
                "The fallback may not use tools outside the declared list.",
            ),
            stem=(
                "该调用最可能的失败模式是",
                "The most likely failure mode of this call is",
            ),
            table_header=(
                "| 错误 | 处理 | 重试次数 |\n|---|---|---|",
                "| error | handling | retries |\n|---|---|---|",
            ),
            persona=("可靠性工程师", "Reliability engineer"),
            deliverable=("容错方案", "Fault-handling plan"),
        ),
        T(
            task_type=("summarize_capability", "summarize_capability"),
            question=(
                "用业务语言说明这些工具合起来能完成什么，不能完成什么。",
                "In business terms, state what these tools together can and cannot do.",
            ),
            terse=("说明工具集能力边界。", "State the toolset's capability boundary."),
            skeleton=(
                "可完成：\n不可完成：\n依据：",
                "Can do:\nCannot do:\nBasis:",
            ),
            constraint=(
                "能力判断必须逐条对应工具声明。",
                "Every capability claim must map to a declared tool.",
            ),
            stem=(
                "这组工具能够完成的核心工作是",
                "The core thing this toolset can accomplish is",
            ),
            table_header=(
                "| 能力 | 支持的工具 |\n|---|---|",
                "| capability | supporting tool |\n|---|---|",
            ),
            persona=("产品经理", "Product manager"),
            deliverable=("能力说明", "Capability note"),
        ),
        T(
            task_type=("permission_check", "permission_check"),
            question=(
                "判断执行该请求是否需要额外授权，并说明理由。",
                "Decide whether executing this request needs extra authorisation, and why.",
            ),
            terse=("判断是否需要授权。", "Decide if authorisation is needed."),
            skeleton=(
                "需要授权：是/否\n涉及的操作：\n理由：",
                "Authorisation needed: yes/no\nOperations involved:\nReason:",
            ),
            constraint=(
                "任何写操作一律视为需要授权。",
                "Treat every write operation as requiring authorisation.",
            ),
            stem=(
                "该请求涉及的敏感操作是",
                "The sensitive operation in this request is",
            ),
            table_header=(
                "| 操作 | 读/写 | 需授权 |\n|---|---|---|",
                "| operation | read/write | needs auth |\n|---|---|---|",
            ),
            persona=("安全审核员", "Security reviewer"),
            deliverable=("授权判定", "Authorisation ruling"),
        ),
    ),
    "erp_structured_analytics": (
        T(
            task_type=("translate_to_query", "translate_to_query"),
            question=(
                "把该业务问题翻译成一条可执行查询，并说明所做的假设。",
                "Translate the business question into one executable query and state your assumptions.",
            ),
            terse=("写出查询语句。", "Write the query."),
            skeleton=(
                "查询：\n假设：\n所用字段：",
                "Query:\nAssumptions:\nColumns used:",
            ),
            constraint=(
                "只允许使用架构中出现的表和列。",
                "Use only tables and columns present in the schema.",
            ),
            stem=(
                "回答这个问题需要的主表是",
                "The primary table needed to answer this is",
            ),
            table_header=(
                "| 表 | 列 | 用途 |\n|---|---|---|",
                "| table | column | purpose |\n|---|---|---|",
            ),
            persona=("数据分析师", "Data analyst"),
            deliverable=("查询方案", "Query plan"),
        ),
        T(
            task_type=("identify_join_path", "identify_join_path"),
            question=(
                "指出连接这些表所需的键路径，并标出可能产生重复行的连接。",
                "Identify the key path joining these tables and mark any join that can fan out rows.",
            ),
            terse=("给出连接路径。", "Give the join path."),
            skeleton=(
                "连接顺序：\n连接键：\n扇出风险：",
                "Join order:\nJoin keys:\nFan-out risk:",
            ),
            constraint=(
                "无法从架构确认的外键关系必须标为“待确认”。",
                "Any foreign key you cannot confirm from the schema must be marked 'unconfirmed'.",
            ),
            stem=(
                "连接路径的起点应当是",
                "The join path should start from",
            ),
            table_header=(
                "| 左表 | 右表 | 连接键 |\n|---|---|---|",
                "| left | right | key |\n|---|---|---|",
            ),
            persona=("数据仓库工程师", "Warehouse engineer"),
            deliverable=("连接路径说明", "Join path note"),
        ),
        T(
            task_type=("data_quality_flags", "data_quality_flags"),
            question=(
                "指出该记录中会影响统计口径的数据质量问题。",
                "Point out the data-quality issues in this record that would distort an aggregate.",
            ),
            terse=("列出数据质量问题。", "List the data-quality issues."),
            skeleton=(
                "问题：\n影响的指标：\n建议处理：",
                "Issue:\nMetric affected:\nSuggested handling:",
            ),
            constraint=(
                "空值和默认值必须分别讨论，不得合并。",
                "Treat nulls and default values separately; do not merge them.",
            ),
            stem=(
                "最需要注意的数据质量问题是",
                "The data-quality issue that matters most here is",
            ),
            table_header=(
                "| 字段 | 问题 | 影响 |\n|---|---|---|",
                "| field | issue | impact |\n|---|---|---|",
            ),
            persona=("数据治理专员", "Data governance officer"),
            deliverable=("质量问题清单", "Quality issue list"),
        ),
        T(
            task_type=("explain_entity", "explain_entity"),
            question=(
                "向不熟悉该系统的业务人员解释这条记录代表什么。",
                "Explain to a business user unfamiliar with the system what this record represents.",
            ),
            terse=("解释这条记录。", "Explain this record."),
            skeleton=(
                "记录类型：\n业务含义：\n关键字段：",
                "Record type:\nBusiness meaning:\nKey fields:",
            ),
            constraint=(
                "不得使用系统内部字段名以外的推测性术语。",
                "Do not introduce terminology beyond the field names shown.",
            ),
            stem=(
                "这条记录描述的是",
                "This record describes",
            ),
            table_header=(
                "| 字段 | 含义 |\n|---|---|",
                "| field | meaning |\n|---|---|",
            ),
            persona=("业务顾问", "Business consultant"),
            deliverable=("记录说明", "Record explainer"),
        ),
        T(
            task_type=("derive_metric", "derive_metric"),
            question=(
                "根据可用字段推导一个可用于月度看板的指标，并写出计算式。",
                "Derive one metric suitable for a monthly dashboard and write out its formula.",
            ),
            terse=("推导一个指标。", "Derive one metric."),
            skeleton=(
                "指标名：\n计算式：\n口径说明：",
                "Metric:\nFormula:\nDefinition notes:",
            ),
            constraint=(
                "计算式只能引用已给出的字段。",
                "The formula may reference only the fields supplied.",
            ),
            stem=(
                "可以直接从这些字段计算的指标是",
                "A metric computable directly from these fields is",
            ),
            table_header=(
                "| 指标 | 计算式 | 依赖字段 |\n|---|---|---|",
                "| metric | formula | fields |\n|---|---|---|",
            ),
            persona=("经营分析岗", "Business analyst"),
            deliverable=("指标定义", "Metric definition"),
        ),
        T(
            task_type=("reconcile_discrepancy", "reconcile_discrepancy"),
            question=(
                "若该记录与总账不一致，列出需要核对的字段与顺序。",
                "If this record disagrees with the ledger, list the fields to reconcile and in what order.",
            ),
            terse=("给出对账顺序。", "Give the reconciliation order."),
            skeleton=(
                "核对顺序：\n每步依据：\n升级条件：",
                "Order:\nBasis per step:\nEscalation trigger:",
            ),
            constraint=(
                "不得假设存在未在记录中出现的科目。",
                "Do not assume accounts that are not present in the record.",
            ),
            stem=(
                "对账应当首先核对的字段是",
                "Reconciliation should begin with the field",
            ),
            table_header=(
                "| 顺序 | 字段 | 依据 |\n|---|---|---|",
                "| order | field | basis |\n|---|---|---|",
            ),
            persona=("财务稽核", "Financial auditor"),
            deliverable=("对账步骤", "Reconciliation steps"),
        ),
        T(
            task_type=("access_scope", "access_scope"),
            question=(
                "判断哪些字段属于敏感信息，不应出现在部门级报表中。",
                "Decide which fields are sensitive and must not appear in a department-level report.",
            ),
            terse=("标注敏感字段。", "Mark the sensitive fields."),
            skeleton=(
                "敏感字段：\n可公开字段：\n判定依据：",
                "Sensitive:\nShareable:\nBasis:",
            ),
            constraint=(
                "有疑问的字段一律按敏感处理。",
                "When in doubt, classify the field as sensitive.",
            ),
            stem=(
                "其中最需要限制访问的字段是",
                "The field most in need of access restriction is",
            ),
            table_header=(
                "| 字段 | 敏感度 | 依据 |\n|---|---|---|",
                "| field | sensitivity | basis |\n|---|---|---|",
            ),
            persona=("信息安全专员", "Information security officer"),
            deliverable=("字段分级", "Field classification"),
        ),
        T(
            task_type=("estimate_query_cost", "estimate_query_cost"),
            question=(
                "估计回答该问题的查询代价，并指出可能的优化点。",
                "Estimate the cost of the query answering this question and name the optimisation levers.",
            ),
            terse=("估计查询代价。", "Estimate the query cost."),
            skeleton=(
                "主要代价来源：\n估计量级：\n优化点：",
                "Main cost driver:\nOrder of magnitude:\nOptimisation:",
            ),
            constraint=(
                "没有统计信息时必须写明估计所依赖的假设。",
                "Absent statistics, state explicitly which assumptions the estimate rests on.",
            ),
            stem=(
                "该查询最主要的代价来自",
                "The dominant cost of this query comes from",
            ),
            table_header=(
                "| 环节 | 代价 | 优化 |\n|---|---|---|",
                "| stage | cost | optimisation |\n|---|---|---|",
            ),
            persona=("查询优化工程师", "Query optimisation engineer"),
            deliverable=("代价评估", "Cost assessment"),
        ),
    ),
    "office_legal": (
        T(
            task_type=("clause_proposition", "clause_proposition"),
            question=(
                "该条款是否支持所述命题？回答支持、不支持或未提及，并引用关键措辞。",
                "Does the clause support the proposition? Answer supported, not supported, or not mentioned, and quote the decisive wording.",
            ),
            terse=("判断命题是否成立。", "Rule on the proposition."),
            skeleton=(
                "判定：\n关键措辞：\n理由：",
                "Ruling:\nDecisive wording:\nReason:",
            ),
            constraint=(
                "判定必须落在三个选项之一，不得给出中间态。",
                "The ruling must be one of the three options; no intermediate answer.",
            ),
            stem=(
                "就该命题而言，条款的措辞表明",
                "On this proposition, the wording of the clause indicates",
            ),
            table_header=(
                "| 命题 | 判定 | 措辞 |\n|---|---|---|",
                "| proposition | ruling | wording |\n|---|---|---|",
            ),
            persona=("合同审查律师", "Contract review counsel"),
            deliverable=("条款判定", "Clause ruling"),
        ),
        T(
            task_type=("obligation_extraction", "obligation_extraction"),
            question=(
                "抽取条款为各方设定的义务，并注明触发条件。",
                "Extract the obligations the clause places on each party and note their triggers.",
            ),
            terse=("列出各方义务。", "List each party's obligations."),
            skeleton=(
                "义务方：\n义务内容：\n触发条件：",
                "Obligor:\nObligation:\nTrigger:",
            ),
            constraint=(
                "未明确约定期限的义务标为“未约定期限”。",
                "Mark obligations without a stated deadline as 'no deadline specified'.",
            ),
            stem=(
                "条款为接收方设定的主要义务是",
                "The principal obligation the clause places on the receiving party is",
            ),
            table_header=(
                "| 义务方 | 义务 | 触发条件 |\n|---|---|---|",
                "| obligor | obligation | trigger |\n|---|---|---|",
            ),
            persona=("法务经理", "Legal operations manager"),
            deliverable=("义务清单", "Obligation register"),
        ),
        T(
            task_type=("exception_scope", "exception_scope"),
            question=(
                "指出条款中的例外情形及其适用范围。",
                "Identify the exceptions in the clause and the scope in which they apply.",
            ),
            terse=("列出例外情形。", "List the carve-outs."),
            skeleton=(
                "例外情形：\n适用范围：\n限制：",
                "Exception:\nScope:\nLimitation:",
            ),
            constraint=(
                "不得把一般性表述当作例外。",
                "Do not treat general language as an exception.",
            ),
            stem=(
                "条款中最宽泛的一项例外是",
                "The broadest exception in the clause is",
            ),
            table_header=(
                "| 例外 | 范围 | 限制 |\n|---|---|---|",
                "| exception | scope | limitation |\n|---|---|---|",
            ),
            persona=("交易律师", "Transactional lawyer"),
            deliverable=("例外分析", "Carve-out analysis"),
        ),
        T(
            task_type=("counterparty_risk", "counterparty_risk"),
            question=(
                "从接收方角度评估该条款带来的主要风险。",
                "Assess the principal risk this clause creates for the receiving party.",
            ),
            terse=("评估接收方风险。", "Assess the recipient's risk."),
            skeleton=(
                "风险：\n触发场景：\n缓释建议：",
                "Risk:\nTrigger scenario:\nMitigation:",
            ),
            constraint=(
                "缓释建议必须是条款文本允许的操作。",
                "Every mitigation must be permitted by the clause text.",
            ),
            stem=(
                "对接收方而言，最不利的安排是",
                "The arrangement least favourable to the recipient is",
            ),
            table_header=(
                "| 风险 | 触发 | 缓释 |\n|---|---|---|",
                "| risk | trigger | mitigation |\n|---|---|---|",
            ),
            persona=("并购法律顾问", "M&A counsel"),
            deliverable=("风险备忘", "Risk memo"),
        ),
        T(
            task_type=("plain_language_rewrite", "plain_language_rewrite"),
            question=(
                "把该条款改写成非法律人员能理解的表述，不改变含义。",
                "Rewrite the clause in plain language for a non-lawyer without changing its meaning.",
            ),
            terse=("改写为通俗表述。", "Rewrite in plain language."),
            skeleton=(
                "通俗表述：\n保留的限定：\n省略的措辞：",
                "Plain version:\nQualifiers kept:\nWording omitted:",
            ),
            constraint=(
                "不得省略任何限定词和期限。",
                "Do not drop any qualifier or time limit.",
            ),
            stem=(
                "用通俗语言说，这一条的意思是",
                "In plain language, this clause means",
            ),
            table_header=(
                "| 原措辞 | 通俗表述 |\n|---|---|",
                "| original wording | plain rendering |\n|---|---|",
            ),
            persona=("企业内训讲师", "Corporate trainer"),
            deliverable=("通俗释义", "Plain-language note"),
        ),
        T(
            task_type=("negotiation_position", "negotiation_position"),
            question=(
                "给出对该条款的两条谈判修改建议，并说明各自的让步空间。",
                "Propose two negotiated amendments to this clause and state the concession room in each.",
            ),
            terse=("提出谈判修改建议。", "Propose negotiated amendments."),
            skeleton=(
                "建议一：\n让步空间：\n建议二：\n让步空间：",
                "Proposal 1:\nConcession room:\nProposal 2:\nConcession room:",
            ),
            constraint=(
                "建议不得改变条款的适用法律。",
                "No proposal may change the governing law of the clause.",
            ),
            stem=(
                "首先应当争取修改的是",
                "The first point to push back on is",
            ),
            table_header=(
                "| 建议 | 修改点 | 让步空间 |\n|---|---|---|",
                "| proposal | change | concession room |\n|---|---|---|",
            ),
            persona=("商务谈判代表", "Commercial negotiator"),
            deliverable=("谈判要点", "Negotiation points"),
        ),
        T(
            task_type=("compliance_checklist", "compliance_checklist"),
            question=(
                "把该条款转化为内部合规检查清单。",
                "Turn this clause into an internal compliance checklist.",
            ),
            terse=("转成合规检查项。", "Convert into compliance checks."),
            skeleton=(
                "检查项：\n责任部门：\n检查频率：",
                "Check:\nOwning department:\nFrequency:",
            ),
            constraint=(
                "每一项检查都必须能被客观验证。",
                "Every check must be objectively verifiable.",
            ),
            stem=(
                "第一项需要落实的检查是",
                "The first check to put in place is",
            ),
            table_header=(
                "| 检查项 | 责任部门 | 频率 |\n|---|---|---|",
                "| check | owner | frequency |\n|---|---|---|",
            ),
            persona=("内控专员", "Internal control officer"),
            deliverable=("检查清单", "Checklist"),
        ),
        T(
            task_type=("term_definition_audit", "term_definition_audit"),
            question=(
                "检查条款中使用但未定义的术语。",
                "Audit the clause for terms it uses but never defines.",
            ),
            terse=("找出未定义术语。", "Find the undefined terms."),
            skeleton=(
                "未定义术语：\n出现位置：\n潜在歧义：",
                "Undefined term:\nWhere used:\nPotential ambiguity:",
            ),
            constraint=(
                "通用词汇不计入未定义术语。",
                "Do not count ordinary vocabulary as undefined terms.",
            ),
            stem=(
                "条款中歧义最大的未定义术语是",
                "The undefined term carrying the most ambiguity is",
            ),
            table_header=(
                "| 术语 | 位置 | 歧义 |\n|---|---|---|",
                "| term | location | ambiguity |\n|---|---|---|",
            ),
            persona=("条款起草人", "Clause drafter"),
            deliverable=("术语审查", "Terminology audit"),
        ),
    ),
    "dcs_process_diagnostics": (
        T(
            task_type=("interval_summary", "interval_summary"),
            question=(
                "概括该时间区间的运行状态，并指出变化最明显的三个信号。",
                "Summarise the operating state over this interval and name the three signals that moved most.",
            ),
            terse=("概括运行区间。", "Summarise the operating interval."),
            skeleton=(
                "运行状态：\n变化最大的信号：\n证据：",
                "State:\nMost-changed signals:\nEvidence:",
            ),
            constraint=(
                "不得推断未记录的根因。",
                "Do not infer a root cause that is not recorded.",
            ),
            stem=(
                "该区间内变化最剧烈的信号是",
                "The signal that moved most over this interval is",
            ),
            table_header=(
                "| 信号 | 起值 | 末值 | 变化 |\n|---|---|---|---|",
                "| signal | first | last | change |\n|---|---|---|---|",
            ),
            persona=("工艺工程师", "Process engineer"),
            deliverable=("区间小结", "Interval summary"),
        ),
        T(
            task_type=("anomaly_localisation", "anomaly_localisation"),
            question=(
                "指出哪些信号的取值偏离了其自身区间统计，并说明偏离方式。",
                "Identify which signals deviate from their own interval statistics and how.",
            ),
            terse=("定位异常信号。", "Localise the anomalous signals."),
            skeleton=(
                "异常信号：\n偏离方式：\n量级：",
                "Signal:\nDeviation type:\nMagnitude:",
            ),
            constraint=(
                "只依据给出的统计量判断，不得引入外部阈值。",
                "Judge only from the statistics given; do not import external thresholds.",
            ),
            stem=(
                "偏离最明显的信号是",
                "The signal deviating most clearly is",
            ),
            table_header=(
                "| 信号 | 偏离方式 | 量级 |\n|---|---|---|",
                "| signal | deviation | magnitude |\n|---|---|---|",
            ),
            persona=("在线监测工程师", "Condition monitoring engineer"),
            deliverable=("异常定位", "Anomaly localisation"),
        ),
        T(
            task_type=("operator_handoff", "operator_handoff"),
            question=(
                "写一段交接班说明，包含受影响单元、当前状态和需要盯守的信号。",
                "Write a shift handover note covering the affected unit, current state and signals to watch.",
            ),
            terse=("写交接班说明。", "Write the shift handover."),
            skeleton=(
                "受影响单元：\n当前状态：\n需盯守信号：\n未决事项：",
                "Affected unit:\nCurrent state:\nSignals to watch:\nOpen items:",
            ),
            constraint=(
                "交接内容不得包含未在记录中出现的结论。",
                "The handover may not contain conclusions absent from the record.",
            ),
            stem=(
                "交班时最需要提醒下一班的是",
                "The most important thing to flag to the next shift is",
            ),
            table_header=(
                "| 单元 | 状态 | 盯守项 |\n|---|---|---|",
                "| unit | state | watch item |\n|---|---|---|",
            ),
            persona=("中控室班长", "Control room supervisor"),
            deliverable=("交接班记录", "Handover record"),
        ),
        T(
            task_type=("alarm_triage", "alarm_triage"),
            question=(
                "对该报警定级，并说明确认与处置的先后顺序。",
                "Assign a severity to this alarm and state the order of acknowledgement and response.",
            ),
            terse=("给报警定级。", "Triage this alarm."),
            skeleton=(
                "等级：\n确认动作：\n处置顺序：",
                "Severity:\nAcknowledgement:\nResponse order:",
            ),
            constraint=(
                "定级只能依据记录中的等级与状态字段。",
                "Base the severity solely on the level and state fields in the record.",
            ),
            stem=(
                "该报警应当定级为",
                "This alarm should be classified as",
            ),
            table_header=(
                "| 报警 | 等级 | 处置 |\n|---|---|---|",
                "| alarm | severity | response |\n|---|---|---|",
            ),
            persona=("报警管理工程师", "Alarm management engineer"),
            deliverable=("报警分级", "Alarm triage"),
        ),
        T(
            task_type=("signal_correlation", "signal_correlation"),
            question=(
                "指出哪些信号看起来同向变化，哪些反向，并说明依据。",
                "State which signals appear to move together, which move oppositely, and on what basis.",
            ),
            terse=("分析信号相关性。", "Analyse signal co-movement."),
            skeleton=(
                "同向组：\n反向组：\n判断依据：",
                "Co-moving:\nCounter-moving:\nBasis:",
            ),
            constraint=(
                "相关不等于因果，结论中必须写明这一限制。",
                "Correlation is not causation; state that limitation explicitly.",
            ),
            stem=(
                "看起来同向变化的一组信号是",
                "One group of signals that appears to move together is",
            ),
            table_header=(
                "| 信号组 | 方向 | 依据 |\n|---|---|---|",
                "| group | direction | basis |\n|---|---|---|",
            ),
            persona=("工艺数据分析师", "Process data analyst"),
            deliverable=("相关性说明", "Co-movement note"),
        ),
        T(
            task_type=("label_verification", "label_verification"),
            question=(
                "记录给出的状态标签与信号表现是否一致？说明支持与不支持的证据。",
                "Is the recorded state label consistent with the signal behaviour? Give supporting and contradicting evidence.",
            ),
            terse=("核对状态标签。", "Verify the state label."),
            skeleton=(
                "标签：\n支持证据：\n不支持证据：\n结论：",
                "Label:\nSupporting:\nContradicting:\nVerdict:",
            ),
            constraint=(
                "不得修改上游标签，只能给出一致性判断。",
                "Do not revise the upstream label; only judge consistency.",
            ),
            stem=(
                "就标签一致性而言，最值得注意的是",
                "On label consistency, the point most worth noting is",
            ),
            table_header=(
                "| 证据 | 支持/反对 | 信号 |\n|---|---|---|",
                "| evidence | for/against | signal |\n|---|---|---|",
            ),
            persona=("数据标注审核", "Label quality reviewer"),
            deliverable=("一致性判断", "Consistency verdict"),
        ),
        T(
            task_type=("instrument_health", "instrument_health"),
            question=(
                "从缺测和恒定读数判断可能存在问题的仪表。",
                "From missing and flat readings, identify instruments that may be faulty.",
            ),
            terse=("判断仪表健康。", "Assess instrument health."),
            skeleton=(
                "可疑仪表：\n症状：\n建议核查：",
                "Suspect instrument:\nSymptom:\nSuggested check:",
            ),
            constraint=(
                "恒定读数不一定是故障，必须说明替代解释。",
                "A flat reading is not necessarily a fault; give the alternative explanation.",
            ),
            stem=(
                "最可能存在问题的仪表是",
                "The instrument most likely to be faulty is",
            ),
            table_header=(
                "| 仪表 | 症状 | 建议 |\n|---|---|---|",
                "| instrument | symptom | action |\n|---|---|---|",
            ),
            persona=("仪表维护工程师", "Instrumentation engineer"),
            deliverable=("仪表核查建议", "Instrument check list"),
        ),
        T(
            task_type=("regime_comparison", "regime_comparison"),
            question=(
                "比较两段运行记录，指出统计上差异最大的信号。",
                "Compare the two operating records and identify the signals differing most.",
            ),
            terse=("比较两段运行。", "Compare the two runs."),
            skeleton=(
                "差异最大信号：\n差异方向：\n可能含义：",
                "Largest difference:\nDirection:\nPossible meaning:",
            ),
            constraint=(
                "比较必须基于同名信号，缺一侧的信号不参与比较。",
                "Compare only signals present on both sides; skip one-sided signals.",
            ),
            stem=(
                "两段记录之间差异最大的信号是",
                "The signal differing most between the two records is",
            ),
            table_header=(
                "| 信号 | A 均值 | B 均值 | 差 |\n|---|---|---|---|",
                "| signal | mean A | mean B | delta |\n|---|---|---|---|",
            ),
            persona=("工况对比分析师", "Regime comparison analyst"),
            deliverable=("对比结论", "Comparison note"),
        ),
    ),
    "equipment_maintenance_bom": (
        T(
            task_type=("maintenance_intake", "maintenance_intake"),
            question=(
                "把该记录整理成一条维修工单摘要，并列出还需补充的信息。",
                "Turn this record into a maintenance work-order summary and list what information is still missing.",
            ),
            terse=("整理成维修工单。", "Draft the work order."),
            skeleton=(
                "设备：\n现象：\n需补充信息：",
                "Asset:\nSymptom:\nMissing information:",
            ),
            constraint=(
                "缺失字段必须逐项列出，不得用占位值填充。",
                "List every missing field; never fill it with a placeholder.",
            ),
            stem=(
                "这条记录能确定的设备信息是",
                "The asset information this record establishes is",
            ),
            table_header=(
                "| 字段 | 取值 | 是否缺失 |\n|---|---|---|",
                "| field | value | missing |\n|---|---|---|",
            ),
            persona=("设备管理员", "Maintenance planner"),
            deliverable=("工单摘要", "Work-order summary"),
        ),
        T(
            task_type=("alarm_frequency_read", "alarm_frequency_read"),
            question=(
                "从这段报警历史判断哪台设备最需要优先检修。",
                "From this alarm history, decide which machine needs attention first.",
            ),
            terse=("判断优先检修对象。", "Pick the machine to service first."),
            skeleton=(
                "优先设备：\n依据：\n次优先：",
                "First:\nBasis:\nSecond:",
            ),
            constraint=(
                "只依据出现次数和时间分布，不得引入设备价值判断。",
                "Use only counts and timing; do not weigh asset value.",
            ),
            stem=(
                "报警最集中的设备是",
                "The machine with the densest alarms is",
            ),
            table_header=(
                "| 设备 | 报警次数 | 时间跨度 |\n|---|---|---|",
                "| machine | alarm count | span |\n|---|---|---|",
            ),
            persona=("可靠性工程师", "Reliability engineer"),
            deliverable=("检修优先级", "Service priority"),
        ),
        T(
            task_type=("bom_field_reading", "bom_field_reading"),
            question=(
                "说明这条物料/工序记录在制造流程中的作用。",
                "Explain what role this material or routing record plays in the manufacturing flow.",
            ),
            terse=("解释该物料记录。", "Explain this BOM record."),
            skeleton=(
                "记录类型：\n流程位置：\n关联字段：",
                "Record type:\nPosition in flow:\nRelated fields:",
            ),
            constraint=(
                "不得假设记录之外的上下游工序。",
                "Do not assume upstream or downstream steps beyond the record.",
            ),
            stem=(
                "这条记录在制造流程中的位置是",
                "In the manufacturing flow, this record sits at",
            ),
            table_header=(
                "| 字段 | 含义 | 流程作用 |\n|---|---|---|",
                "| field | meaning | role |\n|---|---|---|",
            ),
            persona=("工艺规划员", "Manufacturing planner"),
            deliverable=("记录释义", "Record explainer"),
        ),
        T(
            task_type=("spare_part_inference", "spare_part_inference"),
            question=(
                "根据该记录推断可能需要准备的备件类别，并说明不确定性。",
                "Infer which spare-part categories may be needed and state the uncertainty.",
            ),
            terse=("推断备件类别。", "Infer the spare-part categories."),
            skeleton=(
                "备件类别：\n推断依据：\n不确定性：",
                "Category:\nBasis:\nUncertainty:",
            ),
            constraint=(
                "记录信息不足以推断时必须直接说明。",
                "If the record is insufficient, say so directly.",
            ),
            stem=(
                "从这条记录可以合理推断需要准备的是",
                "What can reasonably be inferred as needed is",
            ),
            table_header=(
                "| 备件类别 | 依据 | 置信度 |\n|---|---|---|",
                "| category | basis | confidence |\n|---|---|---|",
            ),
            persona=("备件计划员", "Spare parts planner"),
            deliverable=("备件建议", "Spare parts note"),
        ),
        T(
            task_type=("downtime_impact", "downtime_impact"),
            question=(
                "评估该事件对产线可用性的影响，并说明评估依赖的假设。",
                "Assess the impact of this event on line availability and state the assumptions used.",
            ),
            terse=("评估停机影响。", "Assess the downtime impact."),
            skeleton=(
                "影响范围：\n估计时长：\n所依赖假设：",
                "Scope:\nEstimated duration:\nAssumptions:",
            ),
            constraint=(
                "记录中没有时长信息时不得给出具体数字。",
                "Give no numeric duration if the record contains none.",
            ),
            stem=(
                "该事件对产线的直接影响是",
                "The direct effect of this event on the line is",
            ),
            table_header=(
                "| 影响项 | 程度 | 假设 |\n|---|---|---|",
                "| impact | severity | assumption |\n|---|---|---|",
            ),
            persona=("生产计划员", "Production planner"),
            deliverable=("影响评估", "Impact assessment"),
        ),
        T(
            task_type=("failure_code_mapping", "failure_code_mapping"),
            question=(
                "把该报警代码映射到标准故障类别，并说明映射的不确定性。",
                "Map this alarm code onto a standard failure category and state the mapping uncertainty.",
            ),
            terse=("映射故障类别。", "Map to a failure category."),
            skeleton=(
                "代码：\n映射类别：\n不确定性：",
                "Code:\nMapped category:\nUncertainty:",
            ),
            constraint=(
                "缺少代码手册时必须说明映射是推测性的。",
                "Without a code book, state that the mapping is conjectural.",
            ),
            stem=(
                "该代码最可能对应的故障类别是",
                "The failure category this code most likely denotes is",
            ),
            table_header=(
                "| 代码 | 类别 | 置信度 |\n|---|---|---|",
                "| code | category | confidence |\n|---|---|---|",
            ),
            persona=("维修技术员", "Maintenance technician"),
            deliverable=("代码映射", "Code mapping"),
        ),
        T(
            task_type=("inspection_plan", "inspection_plan"),
            question=(
                "为该设备制定一次针对性点检的检查项。",
                "Define the checks for one targeted inspection of this asset.",
            ),
            terse=("制定点检项。", "Define the inspection checks."),
            skeleton=(
                "检查项：\n所需工具：\n判定标准：",
                "Check:\nTool needed:\nPass criterion:",
            ),
            constraint=(
                "每项检查都必须能在停机窗口内完成。",
                "Every check must fit inside a single downtime window.",
            ),
            stem=(
                "首先应当检查的部位是",
                "The first thing to inspect is",
            ),
            table_header=(
                "| 检查项 | 工具 | 判定标准 |\n|---|---|---|",
                "| check | tool | criterion |\n|---|---|---|",
            ),
            persona=("点检员", "Inspection technician"),
            deliverable=("点检表", "Inspection sheet"),
        ),
        T(
            task_type=("record_completeness", "record_completeness"),
            question=(
                "评估该记录是否足以支撑一次维修决策，指出关键缺口。",
                "Judge whether this record suffices for a maintenance decision and name the critical gaps.",
            ),
            terse=("评估记录完整性。", "Assess record completeness."),
            skeleton=(
                "是否充分：\n关键缺口：\n补采建议：",
                "Sufficient:\nCritical gaps:\nCollection advice:",
            ),
            constraint=(
                "只要缺少设备标识或时间戳即判定为不充分。",
                "Judge insufficient if either asset identity or timestamp is absent.",
            ),
            stem=(
                "这条记录最关键的缺口是",
                "The most critical gap in this record is",
            ),
            table_header=(
                "| 必需字段 | 是否具备 |\n|---|---|",
                "| required field | present |\n|---|---|",
            ),
            persona=("维修数据管理员", "Maintenance data steward"),
            deliverable=("完整性评估", "Completeness assessment"),
        ),
    ),
}

# per-archetype framing that does not vary by task
ARCHETYPE_FRAMING = {
    "document_rag": {
        "role": (
            "你在处理一份公开政府报告，只能依据文中内容作答。",
            "You are working with a public government report and may rely only on its text.",
        ),
        "data_label": ("报告正文", "Report text"),
        "sender": ("研究支持组", "Research support"),
        "audience": ("政策委员会", "Policy committee"),
        "subject": ("公开报告阅读请求", "Public report review request"),
        "priority": ("普通", "Normal"),
    },
    "tool_agent": {
        "role": (
            "你是一个只能通过声明的工具与外部系统交互的助手。",
            "You are an assistant that may reach external systems only through the declared tools.",
        ),
        "data_label": ("可用工具与请求", "Available tools and request"),
        "sender": ("自动化平台", "Automation platform"),
        "audience": ("集成值班", "Integration on-call"),
        "subject": ("工具编排请求", "Tool orchestration request"),
        "priority": ("较高", "High"),
    },
    "erp_structured_analytics": {
        "role": (
            "你在企业 ERP 与数据仓库环境中工作，只能使用给出的架构与记录。",
            "You work inside an enterprise ERP and warehouse environment and may use only the schema and records given.",
        ),
        "data_label": ("数据记录", "Data record"),
        "sender": ("经营分析室", "Business analytics"),
        "audience": ("财务共享中心", "Finance shared services"),
        "subject": ("取数与口径确认", "Data pull and definition check"),
        "priority": ("普通", "Normal"),
    },
    "office_legal": {
        "role": (
            "你在审阅一份合同条款，只能依据条款文本作答。",
            "You are reviewing a contract clause and may rely only on the clause text.",
        ),
        "data_label": ("条款与命题", "Clause and proposition"),
        "sender": ("法务共享中心", "Legal shared services"),
        "audience": ("业务单元负责人", "Business unit lead"),
        "subject": ("条款审阅请求", "Clause review request"),
        "priority": ("较高", "High"),
    },
    "dcs_process_diagnostics": {
        "role": (
            "你在读取一段来自公开工业基准的过程记录，不得虚构未记录的测点或结论。",
            "You are reading a process record from a public industrial benchmark; do not invent measurements or conclusions.",
        ),
        "data_label": ("过程记录", "Process record"),
        "sender": ("中控室", "Control room"),
        "audience": ("工艺值班工程师", "Duty process engineer"),
        "subject": ("运行区间复核", "Operating interval review"),
        "priority": ("紧急", "Urgent"),
    },
    "equipment_maintenance_bom": {
        "role": (
            "你在处理一条来自公开工业基准的设备或物料记录，只能使用记录中的字段。",
            "You are handling an equipment or material record from a public industrial benchmark; use only its fields.",
        ),
        "data_label": ("设备/物料记录", "Equipment / material record"),
        "sender": ("设备科", "Maintenance department"),
        "audience": ("车间主管", "Shop floor supervisor"),
        "subject": ("设备记录处理", "Equipment record handling"),
        "priority": ("普通", "Normal"),
    },
}

# The legacy-style fixed template used by the matched-pair control arm.  It
# deliberately reproduces the failure mode: one instruction, always first,
# always ending with the same constraint sentence.
CONTROL_TEMPLATE = {
    "document_rag": (
        "Task: Prepare an evidence-grounded executive summary of the following "
        "public government report. Preserve quantitative findings, risks, and "
        "recommendations. Do not invent facts."
    ),
    "tool_agent": (
        "Select and call the available tools to complete the workflow. Preserve "
        "state across turns and do not call unrelated tools."
    ),
    "erp_structured_analytics": (
        "You are a data analyst. Translate the business question into a correct, "
        "efficient answer for the specified system. State any assumptions and do "
        "not invent columns."
    ),
    "office_legal": (
        "Review the contract clause for the stated compliance proposition. Answer "
        "Yes, No, or Not Mentioned, then cite the decisive phrase."
    ),
    "dcs_process_diagnostics": (
        "You are an industrial process-operations assistant. Use only the public "
        "benchmark record below; do not invent causes or missing measurements."
    ),
    "equipment_maintenance_bom": (
        "You are a maintenance intake assistant. Use only the fields supplied and "
        "do not mention fields that are not present."
    ),
}

CONTROL_TAIL = {
    "document_rag": "Produce the summary now. Do not use markdown.",
    "tool_agent": "Produce the tool calls now. Do not use markdown.",
    "erp_structured_analytics": "Produce the answer now. Do not use markdown.",
    "office_legal": "Produce the ruling now. Do not use markdown.",
    "dcs_process_diagnostics": "Produce the operator note now. Do not use markdown.",
    "equipment_maintenance_bom": "Produce the intake note now. Do not use markdown.",
}


# ---------------------------------------------------------------------------
# source loading and payload extraction
# ---------------------------------------------------------------------------

SIGNAL_RANKERS: tuple[tuple[str, Callable[[dict], float]], ...] = (
    (
        "normalised_range",
        lambda s: abs((s.get("max") or 0) - (s.get("min") or 0))
        / (abs(s.get("mean") or 0) + 1e-9),
    ),
    ("absolute_drift", lambda s: abs((s.get("last") or 0) - (s.get("first") or 0))),
    ("span", lambda s: abs((s.get("max") or 0) - (s.get("min") or 0))),
    ("null_density", lambda s: float(s.get("null_count") or 0)),
    ("mean_magnitude", lambda s: abs(s.get("mean") or 0)),
    ("terminal_value", lambda s: abs(s.get("last") or 0)),
)

SIGNAL_FIELD_SETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("first_last", ("first", "last")),
    ("min_max_mean", ("min", "max", "mean")),
    ("full", ("first", "last", "min", "max", "mean")),
    ("range_nulls", ("min", "max", "null_count")),
    ("mean_only", ("mean", "count")),
)

SIGNAL_COUNTS = (4, 6, 8, 10, 12, 16)


PAYLOAD_DUP_CEILING = 0.30


def payload_signature(pool: SourcePool) -> str:
    """A cheap textual view of a candidate's payload, used for dedup only."""
    if pool.renderer == "enterprise_body":
        return pool.raw["body"][:4000]
    return json.dumps(
        pool.raw.get("payload", {}), ensure_ascii=False, sort_keys=True
    )[:4000]


def strip_fixed_instruction(text: str) -> str:
    """Drop the frozen leading instruction paragraph of an EnterpriseProxy row."""
    parts = text.split("\n\n", 1)
    return parts[1].strip() if len(parts) == 2 else text.strip()


def drop_reference_block(text: str) -> str:
    """Remove trailing reference-answer blocks so the model must actually work."""
    for marker in (
        "\nReference executive summary:",
        "\nReference label:",
        "\nReference answer:",
        "\nReference tool calls:",
        "\nReference SQL:",
        "\nReference patch:",
    ):
        idx = text.find(marker)
        if idx != -1:
            text = text[:idx]
    return text.strip()


class SourcePool:
    """One candidate record with everything needed to render it."""

    def __init__(
        self,
        *,
        record_id: str,
        group_id: str,
        family: str,
        source_path: str,
        raw: dict,
        renderer: str,
    ) -> None:
        self.record_id = record_id
        self.group_id = group_id
        self.family = family
        self.source_path = source_path
        self.raw = raw
        self.renderer = renderer


def load_enterprise_pools() -> dict[str, list[SourcePool]]:
    path = DATA / "enterprise_proxy_1k" / "enterprise_proxy_1k.jsonl"
    rows = read_jsonl(path)
    mapping = {
        "document_rag": "document_rag",
        "tool_agent": "tool_agent",
        "legal_compliance": "office_legal",
        "structured_analytics": "erp_structured_analytics",
    }
    pools: dict[str, list[SourcePool]] = defaultdict(list)
    for row in rows:
        archetype = mapping.get(row["category"])
        if archetype is None:
            continue
        body = drop_reference_block(strip_fixed_instruction(row["text"]))
        if not body:
            continue
        pools[archetype].append(
            SourcePool(
                record_id=row["id"],
                group_id=str(row.get("session_id") or row["id"]),
                family=row["source"]["dataset"],
                source_path=str(path.relative_to(REPO)),
                raw={"body": body, "domain": row.get("domain"), "source": row["source"]},
                renderer="enterprise_body",
            )
        )
    return pools


def load_industrial_pools() -> dict[str, list[SourcePool]]:
    base = DATA / "industrial_public" / "derived"
    spec = (
        ("dcs_process_diagnostics", "hai_window", base / "hai_23_05" / "cases_s1_100_windows.jsonl", "signal_summary"),
        ("dcs_process_diagnostics", "hai_episode", base / "hai_23_05" / "cases_s2_100_episodes.jsonl", "signal_summary"),
        ("dcs_process_diagnostics", "petrobras_point", base / "petrobras_3w" / "cases_s0_100_points.jsonl", "signals_flat"),
        ("dcs_process_diagnostics", "petrobras_window", base / "petrobras_3w" / "cases_s1_100_windows.jsonl", "signal_summary"),
        ("dcs_process_diagnostics", "petrobras_pair", base / "petrobras_3w" / "cases_s3_50_comparisons.jsonl", "mean_comparison"),
        ("dcs_process_diagnostics", "pronto_alarm", base / "pronto" / "sample_100_events.jsonl", "alarm_event"),
        ("equipment_maintenance_bom", "ofbiz_entity", base / "ofbiz_manufacturing" / "sample_100_entities.jsonl", "erp_entity"),
    )
    pools: dict[str, list[SourcePool]] = defaultdict(list)
    for archetype, family, path, renderer in spec:
        if not path.exists():
            continue
        for row in read_jsonl(path):
            pools[archetype].append(
                SourcePool(
                    record_id=row["id"],
                    group_id=str(
                        row.get("group_id")
                        or (row.get("context") or {}).get("sequence_id")
                        or row["id"]
                    ),
                    family=family,
                    source_path=str(path.relative_to(REPO)),
                    raw=row,
                    renderer=renderer,
                )
            )

    # Packaging alarms are one short row each and therefore near-identical.
    # Bundle them into per-machine alarm histories so the payload carries real
    # structure (counts, codes, timing) instead of three fields.
    alarm_path = base / "packaging_alarms" / "sample_100_events.jsonl"
    if alarm_path.exists():
        by_machine: dict[str, list[dict]] = defaultdict(list)
        for row in read_jsonl(alarm_path):
            raw = (row.get("payload") or {}).get("raw_fields") or {}
            by_machine[str(raw.get("serial") or "unknown")].append(row)
        for serial, rows in sorted(by_machine.items()):
            rows.sort(key=lambda r: str((r["payload"]["raw_fields"]).get("timestamp")))
            for chunk_start in range(0, len(rows), 6):
                chunk = rows[chunk_start : chunk_start + 6]
                if len(chunk) < 3:
                    continue
                pools["equipment_maintenance_bom"].append(
                    SourcePool(
                        record_id=f"packaging_alarms:machine-{serial}:{chunk[0]['id']}",
                        group_id=f"packaging_alarms:machine-{serial}",
                        family="packaging_alarm_history",
                        source_path=str(alarm_path.relative_to(REPO)),
                        raw={"machine": serial, "events": chunk},
                        renderer="alarm_history",
                    )
                )
    return pools


# ---------------------------------------------------------------------------
# per-renderer data blocks
# ---------------------------------------------------------------------------


def render_data_block(
    pool: SourcePool,
    *,
    style_name: str,
    style_fn: Callable,
    ranker_idx: int,
    field_set_idx: int,
    count_idx: int,
    char_budget: int,
    lang: str,
    notice_idx: int = 0,
) -> tuple[str, dict]:
    """Return (data block, rendering descriptor)."""
    zh = lang == "zh-CN"
    desc: dict[str, Any] = {"payload_style": style_name}

    if pool.renderer == "enterprise_body":
        desc["payload_style"] = "verbatim_body"
        return clip(pool.raw["body"], char_budget, notice_idx), desc

    payload = pool.raw.get("payload", {})
    labels = pool.raw.get("labels") or {}

    if pool.renderer in {"signal_summary", "signals_flat", "mean_comparison"}:
        ranker_name, ranker = SIGNAL_RANKERS[ranker_idx % len(SIGNAL_RANKERS)]
        field_name, fields = SIGNAL_FIELD_SETS[field_set_idx % len(SIGNAL_FIELD_SETS)]
        top_n = SIGNAL_COUNTS[count_idx % len(SIGNAL_COUNTS)]
        desc.update(
            signal_ranker=ranker_name, field_set=field_name, signal_count=top_n
        )

        if pool.renderer == "signal_summary":
            summary = payload.get("signal_summary") or {}
            usable = {k: v for k, v in summary.items() if isinstance(v, dict)}
            ordered = sorted(
                usable.items(), key=lambda kv: (-ranker(kv[1]), kv[0])
            )[:top_n]
            pairs: list[tuple[str, Any]] = []
            for name, stats in ordered:
                for field in fields:
                    pairs.append((f"{name}.{field}", stats.get(field)))
        elif pool.renderer == "signals_flat":
            signals = payload.get("signals") or {}
            usable = {k: v for k, v in signals.items() if v is not None}
            ordered = sorted(
                usable.items(), key=lambda kv: (-abs(float(kv[1])), kv[0])
            )[:top_n]
            pairs = list(ordered)
        else:  # mean_comparison
            comp = payload.get("signal_mean_comparison") or {}
            ordered = sorted(
                comp.items(),
                key=lambda kv: (-abs(kv[1].get("delta_right_minus_left") or 0), kv[0]),
            )[:top_n]
            pairs = []
            for name, stats in ordered:
                pairs.append((f"{name}.A", stats.get("left_mean")))
                pairs.append((f"{name}.B", stats.get("right_mean")))
        header_pairs: list[tuple[str, Any]] = []
        if pool.raw.get("time"):
            t = pool.raw["time"]
            if isinstance(t, dict):
                header_pairs.append(
                    ("interval" if not zh else "区间",
                     f"{t.get('start')} -> {t.get('end')}")
                )
        if labels:
            header_pairs.append(
                ("label" if not zh else "上游标签",
                 ", ".join(f"{k}={v}" for k, v in labels.items() if v is not None))
            )
        header_pairs.append(("case_id" if not zh else "案例编号", pool.record_id))
        block = style_fn(header_pairs + pairs)
        return clip(block, char_budget, notice_idx), desc

    if pool.renderer == "alarm_event":
        alarm = (payload.get("alarm") or {}) if isinstance(payload, dict) else {}
        raw_fields = payload.get("raw_fields") or {}
        merged = {**raw_fields, **{k: v for k, v in alarm.items() if v is not None}}
        asset = pool.raw.get("asset") or {}
        domain = pool.raw.get("domain") or {}
        pairs = [
            ("event_id" if not zh else "事件编号", pool.record_id),
            ("asset" if not zh else "设备", asset.get("asset_id")),
            ("system" if not zh else "系统", domain.get("system")),
        ]
        pairs += [(k, v) for k, v in merged.items() if v is not None]
        return clip(style_fn(pairs), char_budget, notice_idx), desc

    if pool.renderer == "alarm_history":
        events = pool.raw["events"]
        codes = [str((e["payload"]["raw_fields"]).get("alarm")) for e in events]
        pairs = [
            ("machine" if not zh else "设备", f"machine-{pool.raw['machine']}"),
            ("event_count" if not zh else "事件数", len(events)),
            ("distinct_codes" if not zh else "不同代码数", len(set(codes))),
        ]
        for order, event in enumerate(events, start=1):
            raw_fields = event["payload"]["raw_fields"]
            pairs.append(
                (
                    f"event_{order}",
                    f"{raw_fields.get('timestamp')} code={raw_fields.get('alarm')}",
                )
            )
        return clip(style_fn(pairs), char_budget, notice_idx), desc

    if pool.renderer == "erp_entity":
        erp = payload.get("erp") or {}
        attrs = erp.get("attributes") or {}
        pairs = [
            ("entity" if not zh else "实体", erp.get("entity")),
            ("record_id" if not zh else "记录编号", pool.record_id),
        ]
        pairs += [(k, v) for k, v in attrs.items() if v is not None]
        return clip(style_fn(pairs), char_budget, notice_idx), desc

    raise KeyError(pool.renderer)


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

CHAR_BUDGETS = (700, 1600, 3600, 8000, 16000)
TARGET_NEW_TOKENS = (192, 256, 320, 384, 448, 512)


def assign_split(seed: str, group_id: str) -> str:
    return "discovery" if stable_rank(seed, group_id) % 2 == 0 else "confirmatory"


def build(
    *,
    diverse_per_cell: int,
    control_per_cell: int,
    out_dir: Path,
) -> dict:
    pools = load_enterprise_pools()
    for archetype, items in load_industrial_pools().items():
        pools[archetype].extend(items)

    records: list[dict] = []
    per_cell_report: dict[str, dict[str, Any]] = {}

    for archetype in ARCHETYPES:
        candidates = pools.get(archetype, [])
        if not candidates:
            raise RuntimeError(f"No source records for archetype {archetype}.")

        # group-aware split, then deterministic ordering inside each split
        buckets: dict[str, list[SourcePool]] = {"discovery": [], "confirmatory": []}
        for cand in candidates:
            buckets[assign_split(BUILD_SEED, cand.group_id)].append(cand)

        tasks = ARCHETYPE_TASKS[archetype]
        framing = ARCHETYPE_FRAMING[archetype]

        for split, bucket in buckets.items():
            # interleave families so consecutive picks differ in record shape
            by_family: dict[str, list[SourcePool]] = defaultdict(list)
            for cand in bucket:
                by_family[cand.family].append(cand)
            for family in by_family:
                by_family[family].sort(
                    key=lambda c: stable_rank(BUILD_SEED + family, c.record_id)
                )
            families = sorted(by_family)
            ordered: list[SourcePool] = []
            accepted_grams: list[set[str]] = []
            rejected = 0
            cursor = 0
            # Round-robin across families, rejecting any candidate whose payload
            # is a near-duplicate of one already accepted.  legalbench clauses
            # and single-line alarm rows repeat heavily upstream; without this
            # filter the "diverse" arm inherits their redundancy.
            while len(ordered) < diverse_per_cell and any(by_family.values()):
                family = families[cursor % len(families)]
                cursor += 1
                if not by_family[family]:
                    continue
                cand = by_family[family].pop(0)
                grams = ngrams(payload_signature(cand))
                if any(
                    jaccard(grams, prev) > PAYLOAD_DUP_CEILING
                    for prev in accepted_grams
                ):
                    rejected += 1
                    continue
                ordered.append(cand)
                accepted_grams.append(grams)
            if len(ordered) < diverse_per_cell:
                raise RuntimeError(
                    f"{archetype}/{split}: only {len(ordered)} source records "
                    f"available, need {diverse_per_cell}."
                )

            # (form, language) grid -- every diverse record in this cell is unique
            combos = [
                (form, lang)
                for form in FORM_IDS
                for lang in ("zh-CN", "en")
            ]
            if diverse_per_cell > len(combos):
                raise RuntimeError(
                    "diverse_per_cell exceeds the number of (form, language) pairs."
                )

            cell_records: list[dict] = []
            for index, pool in enumerate(ordered):
                form_id, lang = combos[index % len(combos)]
                task = tasks[(index + FORM_IDS.index(form_id)) % len(tasks)]
                style_name, style_fn = PAYLOAD_STYLES[
                    (index * 3 + ARCHETYPES.index(archetype)) % len(PAYLOAD_STYLES)
                ]
                char_budget = CHAR_BUDGETS[(index + 1) % len(CHAR_BUDGETS)]
                li = 0 if lang == "zh-CN" else 1

                data_block, desc = render_data_block(
                    pool,
                    style_name=style_name,
                    style_fn=style_fn,
                    ranker_idx=index,
                    field_set_idx=index // 2,
                    count_idx=index // 3,
                    char_budget=char_budget,
                    lang=lang,
                    notice_idx=index,
                )

                ctx = {
                    "role": compose_role(
                        index + FORM_IDS.index(form_id),
                        lang,
                        task["persona"][li],
                        framing["role"][li],
                    ),
                    "data_label": framing["data_label"][li]
                    + LABEL_SUFFIXES[(index + li) % len(LABEL_SUFFIXES)][li],
                    "data": data_block,
                    "question": task["question"][li],
                    "terse": task["terse"][li],
                    "skeleton": task["skeleton"][li],
                    "constraint": task["constraint"][li],
                    "stem": task["stem"][li],
                    "table_header": task["table_header"][li],
                    "persona": task["persona"][li],
                    "deliverable": task["deliverable"][li],
                    "audience": framing["audience"][li],
                    "sender": framing["sender"][li],
                    "subject": framing["subject"][li],
                    "priority": framing["priority"][li],
                }
                if form_id == "f10_paired_comparison":
                    partner = ordered[(index + 1) % len(ordered)]
                    partner_block, _ = render_data_block(
                        partner,
                        style_name=style_name,
                        style_fn=style_fn,
                        ranker_idx=index + 1,
                        field_set_idx=index // 2,
                        count_idx=index // 3,
                        char_budget=max(400, char_budget // 2),
                        lang=lang,
                        notice_idx=index + 1,
                    )
                    ctx["data"] = clip(data_block, max(400, char_budget // 2), index + 3)
                    ctx["data_b"] = partner_block

                prompt = render_form(form_id, lang, ctx)
                record = make_record(
                    archetype=archetype,
                    split=split,
                    pool=pool,
                    prompt=prompt,
                    form_id=form_id,
                    lang=lang,
                    task=task,
                    render_variant="diverse",
                    descriptor=desc,
                    index=index,
                    char_budget=char_budget,
                )
                cell_records.append(record)

            # matched-pair single-template control on the first `control_per_cell`
            # source records of this cell
            for index, pool in enumerate(ordered[:control_per_cell]):
                data_block, desc = render_data_block(
                    pool,
                    style_name="bullets",
                    style_fn=style_bullets,
                    ranker_idx=0,
                    field_set_idx=0,
                    count_idx=1,
                    char_budget=CHAR_BUDGETS[1],
                    lang="en",
                )
                prompt = (
                    f"{CONTROL_TEMPLATE[archetype]}\n\n"
                    f"{ARCHETYPE_FRAMING[archetype]['data_label'][1]}:\n{data_block}\n\n"
                    f"{CONTROL_TAIL[archetype]}"
                )
                record = make_record(
                    archetype=archetype,
                    split=split,
                    pool=pool,
                    prompt=prompt,
                    form_id="control_fixed_template",
                    lang="en",
                    task=ARCHETYPE_TASKS[archetype][0],
                    render_variant="single_template",
                    descriptor=desc,
                    index=index,
                    char_budget=CHAR_BUDGETS[1],
                )
                record["pair_id"] = cell_records[index]["id"]
                cell_records[index]["pair_id"] = record["id"]
                cell_records.append(record)

            per_cell_report[f"{archetype}/{split}"] = {
                "diverse": diverse_per_cell,
                "single_template": control_per_cell,
                "source_families": sorted({p.family for p in ordered}),
            }
            records.extend(cell_records)

    records.sort(key=lambda r: r["id"])
    return write_outputs(records, per_cell_report, out_dir)


def make_record(
    *,
    archetype: str,
    split: str,
    pool: SourcePool,
    prompt: str,
    form_id: str,
    lang: str,
    task: TaskSpec,
    render_variant: str,
    descriptor: dict,
    index: int,
    char_budget: int,
) -> dict:
    digest = sha256_text(prompt)
    rid = f"cpd1-{archetype[:4]}-{split[:4]}-{render_variant[:3]}-{digest[:10]}"
    arrival = stable_rank(BUILD_SEED + "arrival", rid) % 24
    target_tokens = TARGET_NEW_TOKENS[
        stable_rank(BUILD_SEED + "gen", rid) % len(TARGET_NEW_TOKENS)
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "id": rid,
        "workload_archetype": archetype,
        "task_type": task["task_type"][1],
        "prompt_text": prompt,
        "text": prompt,
        "reference_continuation": None,
        "expected_phase": "prefill",
        "phase_scope": "prompt_only",
        "split": split,
        "group_id": pool.group_id,
        "session_id": pool.record_id,
        "turn_index": 0,
        "language": lang,
        "instruction_language": lang,
        "payload_language": "en",
        "source_family": pool.family,
        "source_record_ids": [pool.record_id],
        "selection_index": index,
        "content_sha256": digest,
        # ---- diversity control dimensions -------------------------------
        "render_variant": render_variant,
        "prompt_form": form_id,
        "prompt_tail_kind": (
            "non_instruction"
            if form_id in NON_INSTRUCTION_TAIL_FORMS
            else "instruction"
        ),
        "payload_render": descriptor,
        "prompt_char_budget": char_budget,
        "prompt_char_length": len(prompt),
        "prompt_final_line": prompt.rsplit("\n", 1)[-1][:120],
        "pair_id": None,
        # ---- collection directives --------------------------------------
        "collection": {
            "requires_chat_template": True,
            "target_new_tokens": target_tokens,
            "arrival_offset_steps": arrival,
            "note": (
                "Apply the model chat template; do not feed prompt_text as a raw "
                "continuation. Stagger admission by arrival_offset_steps so "
                "concurrent requests are not position-locked."
            ),
        },
        "provenance": {
            "provenance_type": "public_benchmark_rewrapped",
            "contains_private_data": False,
            "source_artifact": pool.source_path,
            "source_record_id": pool.record_id,
            "renderer": pool.renderer,
            "builder": "build_controller_probe_d1.py",
            "builder_seed": BUILD_SEED,
        },
    }


# ---------------------------------------------------------------------------
# diversity audit
# ---------------------------------------------------------------------------


def ngrams(text: str, n: int = 5) -> set[str]:
    tokens = text.split()
    if len(tokens) < n:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def audit(records: Sequence[dict]) -> dict:
    by_cell: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for record in records:
        by_cell[
            (record["workload_archetype"], record["split"], record["render_variant"])
        ].append(record)

    cells = {}
    for (archetype, split, variant), rows in sorted(by_cell.items()):
        heads = {r["prompt_text"][:70] for r in rows}
        tails = {r["prompt_final_line"] for r in rows}
        forms = {r["prompt_form"] for r in rows}
        langs = {r["language"] for r in rows}
        tasks = {r["task_type"] for r in rows}
        families = {r["source_family"] for r in rows}
        grams = [ngrams(r["prompt_text"]) for r in rows]
        sims = [
            jaccard(grams[i], grams[j])
            for i in range(len(grams))
            for j in range(i + 1, len(grams))
        ]
        sims.sort()
        cells[f"{archetype}/{split}/{variant}"] = {
            "records": len(rows),
            "distinct_prompt_heads_70char": len(heads),
            "distinct_prompt_final_lines": len(tails),
            "distinct_forms": len(forms),
            "distinct_task_types": len(tasks),
            "distinct_source_families": len(families),
            "languages": sorted(langs),
            "pairwise_5gram_jaccard_mean": round(
                sum(sims) / len(sims), 5
            ) if sims else 0.0,
            "pairwise_5gram_jaccard_p95": round(
                sims[int(0.95 * (len(sims) - 1))], 5
            ) if sims else 0.0,
            "pairwise_5gram_jaccard_max": round(max(sims), 5) if sims else 0.0,
            "non_instruction_tail_fraction": round(
                sum(1 for r in rows if r["prompt_tail_kind"] == "non_instruction")
                / len(rows),
                4,
            ),
            "char_length_min": min(r["prompt_char_length"] for r in rows),
            "char_length_median": sorted(
                r["prompt_char_length"] for r in rows
            )[len(rows) // 2],
            "char_length_max": max(r["prompt_char_length"] for r in rows),
        }

    diverse = [c for k, c in cells.items() if k.endswith("/diverse")]
    control = [c for k, c in cells.items() if k.endswith("/single_template")]

    def agg(items: list[dict], field: str) -> float:
        return round(sum(i[field] for i in items) / len(items), 5) if items else 0.0

    return {
        "cells": cells,
        "summary": {
            "diverse_mean_pairwise_5gram_jaccard": agg(
                diverse, "pairwise_5gram_jaccard_mean"
            ),
            "diverse_max_pairwise_5gram_jaccard": round(
                max((c["pairwise_5gram_jaccard_max"] for c in diverse), default=0.0), 5
            ),
            "control_mean_pairwise_5gram_jaccard": agg(
                control, "pairwise_5gram_jaccard_mean"
            ),
            "diverse_mean_distinct_heads": agg(diverse, "distinct_prompt_heads_70char"),
            "control_mean_distinct_heads": agg(control, "distinct_prompt_heads_70char"),
        },
    }


def write_outputs(
    records: list[dict], per_cell_report: dict, out_dir: Path
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / "controller_probe_d1.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    # The existing collector filters on split and archetype but has no notion of
    # a render variant, so ship each arm as its own file too.  Running the two
    # arms is then a matter of pointing --input at a different path.
    variant_paths = {}
    for variant in ("diverse", "single_template"):
        subset = [r for r in records if r["render_variant"] == variant]
        path = out_dir / f"controller_probe_d1_{variant}.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for record in subset:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        variant_paths[variant] = {
            "path": path.name,
            "records": len(subset),
            "sha256": sha256_file(path),
            "per_archetype_per_split": len(subset) // (len(ARCHETYPES) * 2),
        }

    audit_report = audit(records)
    (out_dir / "audit.json").write_text(
        json.dumps(audit_report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    source_files = sorted(
        {
            REPO / r["provenance"]["source_artifact"]
            for r in records
        }
    )
    manifest = {
        "schema_version": "controller-probe-d1-manifest",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "builder": "scripts/build_controller_probe_d1.py",
        "builder_seed": BUILD_SEED,
        "records": len(records),
        "purpose": (
            "Diversity-controlled replacement probe for decode-phase MoE cache "
            "measurement. Isolates workload structure from prompt-template echo."
        ),
        "counts_by_cell": per_cell_report,
        "counts_by_variant": {
            variant: sum(1 for r in records if r["render_variant"] == variant)
            for variant in ("diverse", "single_template")
        },
        "counts_by_archetype": {
            archetype: sum(1 for r in records if r["workload_archetype"] == archetype)
            for archetype in ARCHETYPES
        },
        "counts_by_split": {
            split: sum(1 for r in records if r["split"] == split)
            for split in ("discovery", "confirmatory")
        },
        "sources": {
            str(path.relative_to(REPO)): {
                "sha256": sha256_file(path),
                "records": sum(1 for _ in path.open(encoding="utf-8")),
            }
            for path in source_files
            if path.exists()
        },
        "split_policy": (
            "group-aware: split assigned by sha256(seed|group_id) parity, so no "
            "source group appears in both splits"
        ),
        "audit_summary": audit_report["summary"],
        "artifacts": {
            "records": {
                "path": jsonl_path.name,
                "sha256": sha256_file(jsonl_path),
                "bytes": jsonl_path.stat().st_size,
            },
            "variants": variant_paths,
        },
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diverse-per-cell", type=int, default=24)
    parser.add_argument("--control-per-cell", type=int, default=12)
    parser.add_argument(
        "--output", type=Path, default=DATA / "controller_probe_d1"
    )
    args = parser.parse_args()
    manifest = build(
        diverse_per_cell=args.diverse_per_cell,
        control_per_cell=args.control_per_cell,
        out_dir=args.output,
    )
    print(json.dumps(manifest["audit_summary"], ensure_ascii=False, indent=2))
    print(f"records={manifest['records']} -> {args.output}")


if __name__ == "__main__":
    main()
