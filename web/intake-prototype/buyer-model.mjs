export const BUYER_STEPS = [
  ["project", "项目背景"], ["load", "使用高峰"], ["experience", "体验与稳定"],
  ["evidence", "证据与处理"], ["review", "检查导出"],
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

export function validateBuyerIntake(draft) {
  const errors = [];
  const tasks = [];
  const error = (step, code, message) => errors.push({ step, code, message });
  const task = (owner, code, message, blocks_freeze = true) => tasks.push({ owner, code, message, blocks_freeze });

  if (!draft.project?.project_id?.trim()) error("project", "PROJECT_ID_REQUIRED", "请填写脱敏项目代号。");
  if (!draft.project?.buyer_role) error("project", "BUYER_ROLE_REQUIRED", "请选择你的角色。");
  if (!draft.project?.use_cases?.length) error("project", "USE_CASE_REQUIRED", "至少选择一个业务用途。");
  if (!draft.project?.business_outcome?.trim()) task("procurement", "BUSINESS_OUTCOME_CLARIFICATION", "需要用业务语言确认什么结果才算交付成功。", true);

  if (!draft.peak_use?.peak_users_known) error("load", "PEAK_USERS_KNOWLEDGE_REQUIRED", "请选择是否知道高峰同时在线人数。");
  if (draft.peak_use?.peak_users_known === "known" && !positive(draft.peak_use.peak_users)) error("load", "PEAK_USERS_REQUIRED", "已选择知道高峰人数，请填写人数。");
  if (draft.peak_use?.peak_users_known === "unknown") task("business_owner", "PEAK_USERS_UNRESOLVED", "高峰同时在线人数需要业务负责人确认。", true);
  if (!draft.peak_use?.interaction_pattern) error("load", "INTERACTION_PATTERN_REQUIRED", "请选择最接近的高峰使用方式。");
  if (draft.peak_use?.interaction_pattern === "unknown") task("technical_reviewer", "ARRIVAL_SEMANTICS_UNRESOLVED", "需要通过访谈或历史日志确定用户请求节奏。", true);
  if (draft.peak_use?.interaction_pattern === "known_request_rate" && !positive(draft.peak_use.requests_per_minute)) error("load", "REQUEST_RATE_REQUIRED", "选择已有请求量后，请填写每分钟请求数。");
  if (!draft.peak_use?.input_size || draft.peak_use.input_size === "unknown") task("workload_reviewer", "INPUT_DISTRIBUTION_UNRESOLVED", "需要把业务内容长度转换成可见、可确认的测试分布。", true);

  if (!draft.experience?.first_response_required) error("experience", "FIRST_RESPONSE_REQUIREMENT_REQUIRED", "请选择合同是否承诺开始显示回答的时间。");
  if (draft.experience?.first_response_required === "yes" && !positive(draft.experience.first_response_seconds)) error("experience", "FIRST_RESPONSE_TARGET_REQUIRED", "已要求快速开始回答，请填写可接受的秒数。");
  if (draft.experience?.first_response_required === "yes" && !draft.experience.first_response_reliability) error("experience", "FIRST_RESPONSE_RELIABILITY_REQUIRED", "请选择该体验要求允许多大偶发波动。");
  if (draft.experience?.first_response_reliability === "unclear") task("procurement", "LATENCY_RELIABILITY_TRANSLATION", "合同没有说明体验要求适用于每次、大多数还是几乎所有请求。", true);
  if (draft.experience?.first_response_required === "unclear") task("procurement", "FIRST_RESPONSE_PROMISE_UNRESOLVED", "需要确认合同是否包含开始显示回答的体验承诺。", true);
  if (!positive(draft.experience?.stability_hours)) error("experience", "STABILITY_WINDOW_REQUIRED", "请填写至少连续稳定运行的小时数。");
  if (!draft.experience?.recovery_expectation) error("experience", "RECOVERY_EXPECTATION_REQUIRED", "请选择服务中断后的恢复要求。");
  if (!draft.experience?.quality_expectation?.trim()) task("business_owner", "QUALITY_RULE_UNRESOLVED", "需要业务负责人说明什么回答才算可用。", true);
  if (draft.experience?.risks?.includes("concurrency")) task("oicap_compiler", "CONCURRENCY_SWEEP_REQUIRED", "根据冻结的高峰使用方式生成并发/到达率扫描和持续时间。", false);
  if (draft.experience?.risks?.includes("stability")) task("oicap_compiler", "SOAK_PLAN_REQUIRED", "生成持续稳定性阶段并定义服务退出、重启、超时和错误统计。", false);
  if (draft.experience?.risks?.includes("oom")) task("technical_reviewer", "OOM_EVIDENCE_PLAN_REQUIRED", "只有进程、系统或设备证据能确认 OOM；黑盒中断只能标为与资源耗尽一致。", true);

  const evidence = draft.evidence_and_process?.supplier_evidence ?? [];
  if (!evidence.length) task("procurement", "SUPPLIER_EVIDENCE_UNRESOLVED", "需要明确乙方能提供哪些报告、清单或现场检查条件，或明确确实没有。", true);
  if (evidence.includes("none_or_unknown") && evidence.length > 1) error("evidence", "SUPPLIER_EVIDENCE_CONTRADICTORY", "不能同时选择已有具体证据和‘没有或不清楚’。");
  if (evidence.length === 1 && evidence[0] === "none_or_unknown") task("technical_reviewer", "SUPPLIER_EVIDENCE_ABSENT", "当前没有可依赖的乙方证据；现场证据计划必须从零建立。", true);
  if (evidence.includes("supplier_report")) task("evidence_reviewer", "SUPPLIER_REPORT_PROVENANCE_ONLY", "乙方环境报告作为有来源的输入保存，不直接产生买方现场 PASS。", false);
  if (evidence.includes("hardware_inventory")) task("technical_reviewer", "RUNTIME_BINDING_REQUIRED", "硬件清单需通过现场观察与服务进程绑定，清单本身不证明实际承载请求。", true);
  if (!draft.evidence_and_process?.fail_transition) error("evidence", "FAIL_TRANSITION_REQUIRED", "请选择技术测试 FAIL 后的既有处理方式。");
  if (["renegotiate", "unknown"].includes(draft.evidence_and_process?.fail_transition)) task("procurement", "FAIL_TRANSITION_UNRESOLVED", "正式采购前需要在合同中预先确定整改、重测或拒收的技术状态转换。", true);
  if (!positive(draft.evidence_and_process?.site_window_hours)) error("evidence", "SITE_WINDOW_REQUIRED", "请填写现场可用于验收的时间。");
  if (!draft.evidence_and_process?.retest_changes || draft.evidence_and_process.retest_changes === "unspecified") task("procurement", "RETEST_MUTABILITY_UNRESOLVED", "必须在看到测试结果前冻结重测允许改变的配置。", true);

  return { errors, tasks, ready_for_translation: errors.length === 0 };
}

export function finalizeBuyerIntake(draft) {
  const out = JSON.parse(JSON.stringify(draft));
  const result = validateBuyerIntake(out);
  out.status = result.ready_for_translation ? "READY_FOR_TECHNICAL_TRANSLATION" : "DRAFT_WITH_ERRORS";
  out.validation = { checked_at: new Date().toISOString(), error_count: result.errors.length, errors: result.errors };
  out.technical_translation_tasks = result.tasks;
  out.handoff = {
    procurement_intent_recorded: result.ready_for_translation,
    technical_contract_frozen: false,
    test_pack_compiled: false,
    verdict_available: false,
  };
  return out;
}
