export const BUYER_STEPS = [
  ["project", "项目背景"], ["load", "使用高峰"], ["experience", "体验与稳定"],
  ["evidence", "证据与处理"], ["review", "检查导出"],
];

export const BUYER_REQUIREMENT_FIELDS = [
  "project.business_outcome",
  "project.use_cases",
  "peak_use.peak_users",
  "peak_use.interaction_pattern",
  "peak_use.requests_per_minute",
  "peak_use.input_size",
  "experience.first_response_required",
  "experience.first_response_seconds",
  "experience.first_response_reliability",
  "experience.stability_hours",
  "experience.recovery_expectation",
  "experience.quality_expectation",
];

export function emptyBuyerIntake() {
  return {
    schema: "oicap-buyer-intake/0.1",
    status: "DRAFT",
    notice: "Business-intent intake only; not a frozen contract, test pack, or verdict.",
    project: { project_id: "", buyer_role: "", use_cases: [], business_outcome: "" },
    peak_use: { peak_users_known: "", peak_users: null, interaction_pattern: "", requests_per_minute: null, input_size: "" },
    experience: { first_response_required: "", first_response_seconds: null, first_response_reliability: "", stability_hours: null, recovery_expectation: "", risks: [], quality_expectation: "" },
    evidence_and_process: { supplier_evidence: [], fail_transition: "", site_window_hours: null, retest_changes: "" },
  };
}

const positive = value => typeof value === "number" && Number.isFinite(value) && value > 0;
const arrivalRatePlanFor = draft => draft.peak_use?.interaction_pattern === "known_request_rate";

function retainedRequirementFields(draft) {
  const retained = [];
  if (draft.project?.business_outcome?.trim()) retained.push("project.business_outcome");
  if (draft.project?.use_cases?.length) retained.push("project.use_cases");
  if (draft.peak_use?.peak_users_known === "known" && positive(draft.peak_use.peak_users)) retained.push("peak_use.peak_users");
  if (draft.peak_use?.interaction_pattern && draft.peak_use.interaction_pattern !== "unknown") retained.push("peak_use.interaction_pattern");
  if (positive(draft.peak_use?.requests_per_minute)) retained.push("peak_use.requests_per_minute");
  if (draft.peak_use?.input_size && draft.peak_use.input_size !== "unknown") retained.push("peak_use.input_size");
  if (draft.experience?.first_response_required === "yes") {
    retained.push("experience.first_response_required");
    if (positive(draft.experience.first_response_seconds)) retained.push("experience.first_response_seconds");
    if (draft.experience.first_response_reliability) retained.push("experience.first_response_reliability");
  }
  if (positive(draft.experience?.stability_hours)) retained.push("experience.stability_hours");
  if (draft.experience?.recovery_expectation) retained.push("experience.recovery_expectation");
  if (draft.experience?.quality_expectation?.trim()) retained.push("experience.quality_expectation");
  return retained;
}

export function checkRequirementCoverage(retainedFields, tasks) {
  const obligations = Object.fromEntries(retainedFields.map(field => [
    field,
    tasks.filter(item => item.source_fields?.includes(field)).map(item => item.code),
  ]));
  return {
    retained_fields: retainedFields,
    obligations,
    uncovered_fields: retainedFields.filter(field => obligations[field].length === 0),
  };
}

function validateCrossFieldConsistency(draft, { error, task }) {
  const firstResponseRequired = draft.experience?.first_response_required;
  const hasFirstResponseSeconds = draft.experience?.first_response_seconds !== null
    && draft.experience?.first_response_seconds !== undefined;
  const hasFirstResponseReliability = Boolean(draft.experience?.first_response_reliability);

  if (["no", "unclear"].includes(firstResponseRequired)
      && (hasFirstResponseSeconds || hasFirstResponseReliability)) {
    error(
      "experience",
      "FIRST_RESPONSE_SUBORDINATE_FIELDS_NOT_ALLOWED",
      "已选择合同不承诺或尚不清楚开始显示回答时间，不能同时保留秒数或达标频率；请先确认主答案。",
    );
  }

  const hasPeakUsers = draft.peak_use?.peak_users !== null && draft.peak_use?.peak_users !== undefined;
  if (draft.peak_use?.peak_users_known !== "known" && hasPeakUsers) {
    error("load", "PEAK_USERS_SUBORDINATE_FIELD_NOT_ALLOWED", "未选择‘我知道大致人数’时不能保留人数；请确认主答案或清空人数。");
  }

  const stabilityHours = draft.experience?.stability_hours;
  const siteWindowHours = draft.evidence_and_process?.site_window_hours;
  if (positive(stabilityHours) && positive(siteWindowHours) && stabilityHours > siteWindowHours) {
    task(
      "procurement",
      "SITE_WINDOW_BELOW_MEASUREMENT_FLOOR",
      `已声明的 ${stabilityHours} 小时连续稳定性要求超过 ${siteWindowHours} 小时现场窗口；冻结前必须选择分阶段观察方案或修改要求，不能在现场静默删减覆盖。`,
      true,
    );
  }
}

export function validateBuyerIntake(draft) {
  const errors = [];
  const tasks = [];
  const error = (step, code, message) => errors.push({ step, code, message });
  const task = (owner, code, message, blocks_freeze = true, buyer_emphasis = false, source_fields = [], details = undefined) => {
    const item = { owner, code, message, blocks_freeze, buyer_emphasis, source_fields };
    if (details !== undefined) item.details = details;
    tasks.push(item);
  };
  const risks = draft.experience?.risks ?? [];

  if (!draft.project?.project_id?.trim()) error("project", "PROJECT_ID_REQUIRED", "请填写脱敏项目代号。");
  if (!draft.project?.buyer_role) error("project", "BUYER_ROLE_REQUIRED", "请选择你的角色。");
  if (!draft.project?.use_cases?.length) error("project", "USE_CASE_REQUIRED", "至少选择一个业务用途。");
  if (!draft.project?.business_outcome?.trim()) task("procurement", "BUSINESS_OUTCOME_CLARIFICATION", "需要用业务语言确认什么结果才算交付成功。", true);
  else task("technical_reviewer", "BUSINESS_OUTCOME_TRANSLATION_REQUIRED", "把买方成功标准转换为可复核的候选验收要求，并返回买方确认。", false, false, ["project.business_outcome"]);

  if (!draft.peak_use?.peak_users_known) error("load", "PEAK_USERS_KNOWLEDGE_REQUIRED", "请选择是否知道高峰同时在线人数。");
  if (draft.peak_use?.peak_users_known === "known" && !positive(draft.peak_use.peak_users)) error("load", "PEAK_USERS_REQUIRED", "已选择知道高峰人数，请填写人数。");
  if (draft.peak_use?.peak_users_known === "unknown") task("business_owner", "PEAK_USERS_UNRESOLVED", "高峰同时在线人数需要业务负责人确认。", true);
  if (!draft.peak_use?.interaction_pattern) error("load", "INTERACTION_PATTERN_REQUIRED", "请选择最接近的高峰使用方式。");
  if (draft.peak_use?.interaction_pattern === "unknown") task("technical_reviewer", "ARRIVAL_SEMANTICS_UNRESOLVED", "需要通过访谈或历史日志确定用户请求节奏。", true);
  const requestsPerMinutePresent = draft.peak_use?.requests_per_minute !== null && draft.peak_use?.requests_per_minute !== undefined;
  if (draft.peak_use?.interaction_pattern === "known_request_rate" && !requestsPerMinutePresent) error("load", "REQUEST_RATE_REQUIRED", "选择已有请求量后，请填写每分钟请求数。");
  else if (requestsPerMinutePresent && !positive(draft.peak_use.requests_per_minute)) error("load", "REQUEST_RATE_REQUIRED", "已填写高峰请求量时，每分钟请求数必须大于零。");
  if (!draft.peak_use?.input_size || draft.peak_use.input_size === "unknown") task("workload_reviewer", "INPUT_DISTRIBUTION_UNRESOLVED", "需要把业务内容长度转换成可见、可确认的测试分布。", true, false, draft.project?.use_cases?.length ? ["project.use_cases"] : []);
  if (draft.project?.use_cases?.length && draft.peak_use?.input_size && draft.peak_use.input_size !== "unknown") {
    task("workload_reviewer", "WORKLOAD_PROFILE_REQUIRED", "根据已声明的业务用途和内容长度编译候选工作负载分布，并返回买方确认。", false, false, ["project.use_cases", "peak_use.input_size"]);
  }

  if (!draft.experience?.first_response_required) error("experience", "FIRST_RESPONSE_REQUIREMENT_REQUIRED", "请选择合同是否承诺开始显示回答的时间。");
  if (draft.experience?.first_response_required === "yes" && !positive(draft.experience.first_response_seconds)) error("experience", "FIRST_RESPONSE_TARGET_REQUIRED", "已要求快速开始回答，请填写可接受的秒数。");
  if (draft.experience?.first_response_required === "yes" && !draft.experience.first_response_reliability) error("experience", "FIRST_RESPONSE_RELIABILITY_REQUIRED", "请选择该体验要求允许多大偶发波动。");
  if (draft.experience?.first_response_required === "yes" && draft.experience?.first_response_reliability === "unclear") task("procurement", "LATENCY_RELIABILITY_TRANSLATION", "合同没有说明体验要求适用于每次、大多数还是几乎所有请求。", true);
  if (draft.experience?.first_response_required === "unclear") task("procurement", "FIRST_RESPONSE_PROMISE_UNRESOLVED", "需要确认合同是否包含开始显示回答的体验承诺。", true);
  if (draft.experience?.first_response_required === "yes" && positive(draft.experience.first_response_seconds) && draft.experience.first_response_reliability) {
    task("oicap_compiler", "FIRST_RESPONSE_GATE_REQUIRED", "把开始显示回答的秒数和达标频率转换为明确总体、统计量与阈值的 TTFT gate。", false, false, ["experience.first_response_required", "experience.first_response_seconds", "experience.first_response_reliability"]);
  }
  if (!positive(draft.experience?.stability_hours)) error("experience", "STABILITY_WINDOW_REQUIRED", "请填写至少连续稳定运行的小时数。");
  if (!draft.experience?.recovery_expectation) error("experience", "RECOVERY_EXPECTATION_REQUIRED", "请选择服务中断后的恢复要求。");
  if (!draft.experience?.quality_expectation?.trim()) task("business_owner", "QUALITY_RULE_UNRESOLVED", "需要业务负责人说明什么回答才算可用。", true, risks.includes("quality"));
  else task("quality_reviewer", "QUALITY_GATE_REQUIRED", "把买方可用性描述转换为带独立阳性对照的正式质量 gate，并返回买方确认。", false, risks.includes("quality"), ["experience.quality_expectation"]);

  // Plan obligations come from declared requirements. The buyer's stated
  // worries only raise their emphasis; leaving a worry unticked must never
  // remove a contractual load, stability, or recovery test.
  const peakUsersResolved = draft.peak_use?.peak_users_known === "known" && positive(draft.peak_use.peak_users);
  const interactionResolved = Boolean(draft.peak_use?.interaction_pattern) && draft.peak_use.interaction_pattern !== "unknown";
  const arrivalRatePlan = arrivalRatePlanFor(draft);
  if (peakUsersResolved || interactionResolved) {
    task(
      "oicap_compiler",
      arrivalRatePlan ? "ARRIVAL_RATE_PLAN_REQUIRED" : "CONCURRENCY_SWEEP_REQUIRED",
      arrivalRatePlan
        ? "根据冻结的请求量和使用方式生成到达率扫描和持续时间。"
        : "根据冻结的高峰人数和使用方式生成并发扫描和持续时间。",
      false,
      risks.includes("concurrency"),
      [
        ...(peakUsersResolved ? ["peak_use.peak_users"] : []),
        ...(interactionResolved ? ["peak_use.interaction_pattern"] : []),
        ...(arrivalRatePlan && positive(draft.peak_use?.requests_per_minute) ? ["peak_use.requests_per_minute"] : []),
      ],
    );
  }
  if (positive(draft.peak_use?.requests_per_minute) && (peakUsersResolved || !arrivalRatePlanFor(draft))) {
    const cycleSeconds = peakUsersResolved
      ? draft.peak_use.peak_users * 60 / draft.peak_use.requests_per_minute
      : null;
    task(
      "technical_reviewer",
      "LOAD_MODEL_TRANSLATION_REQUIRED",
      cycleSeconds === null
        ? "已填写到达率但缺少可用于交叉核对的有效高峰人数；技术复核必须选择一种正式负载模型。"
        : `高峰人数和到达率共同给出每用户平均 ${cycleSeconds.toFixed(3)} 秒的请求周期（服务时间 + 思考时间）；技术复核必须确认口径、冻结一种负载模型，并把另一数值保留为一致性检查。`,
      true,
      risks.includes("concurrency"),
      ["peak_use.requests_per_minute", ...(peakUsersResolved ? ["peak_use.peak_users"] : [])],
      cycleSeconds === null ? undefined : {
        mean_request_cycle_seconds: cycleSeconds,
        formula: "peak_users * 60 / requests_per_minute",
        interpretation: "service_time_plus_think_time; requires technical review",
      },
    );
  }
  if (positive(draft.experience?.stability_hours)) {
    task("oicap_compiler", "SOAK_PLAN_REQUIRED", "根据已声明的连续稳定运行时长生成 soak 阶段，并定义服务退出、重启、超时和错误统计。", false, risks.includes("stability"), ["experience.stability_hours"]);
  }
  if (draft.experience?.recovery_expectation) {
    if (draft.experience.recovery_expectation === "unclear") {
      task("procurement", "RECOVERY_EXPECTATION_UNRESOLVED", "合同没有说清服务中断后的恢复要求，需要在冻结测试计划前确认。", true);
    }
    task("oicap_compiler", "RECOVERY_OBSERVATION_PLAN_REQUIRED", "根据已声明的恢复要求生成中断、重启或恢复观察计划。", false, risks.includes("errors"), ["experience.recovery_expectation"]);
  }
  if (risks.includes("oom")) task("technical_reviewer", "OOM_EVIDENCE_PLAN_REQUIRED", "只有进程、系统或设备证据能确认 OOM；黑盒中断只能标为与资源耗尽一致。", true, true);

  const evidence = draft.evidence_and_process?.supplier_evidence ?? [];
  if (!evidence.length) task("procurement", "SUPPLIER_EVIDENCE_UNRESOLVED", "需要明确乙方能提供哪些报告、清单或现场检查条件，或明确确实没有。", true);
  if (evidence.includes("none_or_unknown") && evidence.length > 1) error("evidence", "SUPPLIER_EVIDENCE_CONTRADICTORY", "不能同时选择已有具体证据和‘没有或不清楚’。");
  if (evidence.length === 1 && evidence[0] === "none_or_unknown") task("technical_reviewer", "SUPPLIER_EVIDENCE_ABSENT", "当前没有可依赖的乙方证据；现场证据计划必须从零建立。", true);
  if (evidence.includes("supplier_report")) task("evidence_reviewer", "SUPPLIER_REPORT_PROVENANCE_ONLY", "乙方环境报告作为有来源的输入保存，不直接产生买方现场 PASS。", false);
  if (evidence.includes("hardware_inventory")) task("technical_reviewer", "RUNTIME_BINDING_REQUIRED", "硬件清单需通过现场观察与服务进程绑定，清单本身不证明实际承载请求。", true, risks.includes("wrong_deployment"));
  if (!draft.evidence_and_process?.fail_transition) error("evidence", "FAIL_TRANSITION_REQUIRED", "请选择技术测试 FAIL 后的既有处理方式。");
  if (["renegotiate", "unknown"].includes(draft.evidence_and_process?.fail_transition)) task("procurement", "FAIL_TRANSITION_UNRESOLVED", "正式采购前需要在合同中预先确定整改、重测或拒收的技术状态转换。", true);
  if (!positive(draft.evidence_and_process?.site_window_hours)) error("evidence", "SITE_WINDOW_REQUIRED", "请填写现场可用于验收的时间。");
  if (!draft.evidence_and_process?.retest_changes || draft.evidence_and_process.retest_changes === "unspecified") task("procurement", "RETEST_MUTABILITY_UNRESOLVED", "必须在看到测试结果前冻结重测允许改变的配置。", true);

  validateCrossFieldConsistency(draft, { error, task });

  const retainedRequirements = retainedRequirementFields(draft);
  const requirementCoverage = checkRequirementCoverage(retainedRequirements, tasks);
  if (requirementCoverage.uncovered_fields.length) {
    error("review", "RETAINED_REQUIREMENT_WITHOUT_OBLIGATION", `以下已保留要求没有对应编译义务：${requirementCoverage.uncovered_fields.join(", ")}`);
  }

  return { errors, tasks, requirement_coverage: requirementCoverage, ready_for_translation: errors.length === 0 };
}

export function finalizeBuyerIntake(draft) {
  const out = JSON.parse(JSON.stringify(draft));
  const result = validateBuyerIntake(out);
  out.status = result.ready_for_translation ? "READY_FOR_TECHNICAL_TRANSLATION" : "DRAFT_WITH_ERRORS";
  out.validation = { checked_at: new Date().toISOString(), error_count: result.errors.length, errors: result.errors, requirement_coverage: result.requirement_coverage };
  out.technical_translation_tasks = result.tasks;
  out.handoff = {
    procurement_intent_recorded: result.ready_for_translation,
    technical_contract_frozen: false,
    test_pack_compiled: false,
    verdict_available: false,
  };
  return out;
}
