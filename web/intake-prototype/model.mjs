export const STEPS = [
  ["project", "项目边界"],
  ["sla", "SLA 门槛"],
  ["workload", "负载画像"],
  ["deployment", "交付配置"],
  ["execution", "执行与重测"],
  ["review", "检查导出"],
];

export const DEPLOYMENT_CATALOGUE = [
  ["model_identity", "模型身份", "系列、精确版本与权重哈希"],
  ["tokenizer_and_chat_template", "Tokenizer 与对话模板", "标识符及版本"],
  ["quantization", "量化", "算法、位宽、组大小与校准标识"],
  ["serving_engine", "推理引擎", "产品、版本或 commit"],
  ["container_and_runtime", "容器与运行时", "镜像摘要与运行时"],
  ["launch_configuration", "启动配置", "命令与影响裁决的环境变量"],
  ["endpoint_boundary", "服务入口边界", "路径、模型别名与监听端口归属"],
  ["external_dependencies", "外部依赖", "允许的网络出口与远程服务"],
  ["accelerator_topology", "加速器拓扑", "型号、数量、显存、互联与功耗模式"],
  ["host_platform", "主机平台", "CPU、内存、NUMA、操作系统与存储"],
  ["parallelism", "并行策略", "张量、流水线、数据或专家并行"],
  ["memory_and_offload", "内存与卸载", "权重位置、KV cache 与 offload"],
  ["decoding_acceleration", "解码加速", "投机解码或其他机制"],
  ["batching_scheduling_admission", "批处理、调度与准入", "序列/批次上限、队列、缓存、去重与准入"],
];

export const MEMORY_ENVELOPE_PREREQUISITES = new Set([
  "model_identity",
  "quantization",
  "serving_engine",
  "accelerator_topology",
  "parallelism",
  "memory_and_offload",
]);

const CURRENT_DRAFT_SCHEMA = "oicap-ac04-intake-draft/0.1";

export function emptyDraft() {
  return {
    schema: CURRENT_DRAFT_SCHEMA,
    status: "DRAFT",
    notice: "AC04 authoring prototype only; not a frozen contract, test pack, or verdict.",
    project: {
      project_id: "",
      deployment_mode: "private_on_prem",
      buyer_role: "",
      technical_role: "",
      measurement_boundary: "",
    },
    sla_gates: [emptyGate()],
    workload_classes: [emptyWorkload()],
    deployment_requirements: Object.fromEntries(
      DEPLOYMENT_CATALOGUE.map(([key]) => [key, { requirement_state: "", constraint: "" }]),
    ),
    execution: {
      load_semantics: "closed_loop",
      max_load: null,
      repeats: 3,
      site_window_minutes: null,
      min_point_duration_s: 60,
      min_point_samples: 100,
      load_points: [],
      max_retests: 1,
      mutable_paths: "",
      preflight: {
        max_load_sustained: false,
        resource_recorded: false,
        onsite_same_path_calibration: false,
        buyer_controls_responder: false,
      },
    },
  };
}

export function emptyGate() {
  return {
    metric: "",
    workload_class: "",
    statistic: "p95",
    comparator: "lte",
    threshold: null,
    unit: "",
    population: "",
    min_samples: 100,
    min_duration_s: 60,
    quality_eligible: false,
    authority: "client_observed",
  };
}

export function emptyWorkload() {
  return {
    class_id: "",
    weight_percent: null,
    input_tokens: "",
    output_tokens: "",
    source_policy: "oicap_standard",
    session_semantics: "single_turn",
    think_time_ms: 0,
    streaming: "required",
    quality_rule: "",
  };
}

export function parseLoadPoints(value) {
  if (Array.isArray(value)) return value.map(Number).filter(Number.isFinite);
  return String(value ?? "")
    .split(/[,，\s]+/)
    .filter(Boolean)
    .map(Number)
    .filter(Number.isFinite);
}

export function numberOrNull(value) {
  if (value === "" || value === null || value === undefined) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function validateDraft(draft) {
  const errors = [];
  const warnings = [];
  const error = (step, code, message) => errors.push({ step, code, message });
  const warning = (step, code, message) => warnings.push({ step, code, message });

  if (!draft.project?.project_id?.trim()) error("project", "PROJECT_ID_REQUIRED", "需要一个脱敏的演练代号。");
  if (!draft.project?.buyer_role?.trim()) error("project", "BUYER_ROLE_REQUIRED", "需要记录甲方验收负责人角色。");
  if (!draft.project?.technical_role?.trim()) error("project", "TECHNICAL_ROLE_REQUIRED", "需要记录技术见证角色。");
  if (!draft.project?.measurement_boundary?.trim()) error("project", "MEASUREMENT_BOUNDARY_REQUIRED", "必须冻结 SUT 与甲方器具的测量边界。");

  if (!Array.isArray(draft.sla_gates) || draft.sla_gates.length === 0) {
    error("sla", "SLA_GATE_REQUIRED", "至少需要一条 SLA 门槛。");
  }
  const classIds = new Set((draft.workload_classes ?? []).map(item => item.class_id?.trim()).filter(Boolean));
  (draft.sla_gates ?? []).forEach((gate, index) => {
    const n = index + 1;
    if (!gate.metric) error("sla", "GATE_METRIC_REQUIRED", `门槛 ${n} 缺少指标。`);
    if (/^tps$/i.test(gate.metric?.trim() ?? "")) error("sla", "BARE_TPS_REJECTED", `门槛 ${n} 使用了含义不明的 TPS。`);
    if (!gate.workload_class?.trim()) error("sla", "GATE_CLASS_REQUIRED", `门槛 ${n} 缺少业务类别。`);
    else if (!classIds.has(gate.workload_class.trim())) error("sla", "GATE_CLASS_UNKNOWN", `门槛 ${n} 引用的业务类别尚未定义。`);
    if (!gate.population?.trim()) error("sla", "GATE_POPULATION_REQUIRED", `门槛 ${n} 缺少统计总体。`);
    if (!gate.unit?.trim()) error("sla", "GATE_UNIT_REQUIRED", `门槛 ${n} 缺少单位。`);
    if (numberOrNull(gate.threshold) === null) error("sla", "GATE_THRESHOLD_REQUIRED", `门槛 ${n} 缺少数值阈值。`);
    if (!(numberOrNull(gate.min_samples) > 0)) error("sla", "GATE_SAMPLE_REQUIRED", `门槛 ${n} 的最低样本数必须大于零。`);
    if (!(numberOrNull(gate.min_duration_s) > 0)) error("sla", "GATE_DURATION_REQUIRED", `门槛 ${n} 的最低持续时间必须大于零。`);
    if ((gate.metric === "per_request_decode_tokens_per_second" || gate.metric === "itl_ms") && gate.authority !== "authoritative_token_timestamps") {
      error("sla", "TOKEN_TIMING_AUTHORITY_REQUIRED", `门槛 ${n} 需要权威逐 token 时间戳，不能用 SSE 分块间隔代替。`);
    }
  });

  if (!Array.isArray(draft.workload_classes) || draft.workload_classes.length === 0) {
    error("workload", "WORKLOAD_CLASS_REQUIRED", "至少需要一个业务类别。");
  }
  const seenClasses = new Set();
  let totalWeight = 0;
  (draft.workload_classes ?? []).forEach((item, index) => {
    const n = index + 1;
    const id = item.class_id?.trim();
    if (!id) error("workload", "WORKLOAD_ID_REQUIRED", `业务类别 ${n} 缺少代号。`);
    else if (seenClasses.has(id)) error("workload", "WORKLOAD_ID_DUPLICATE", `业务类别代号 ${id} 重复。`);
    else seenClasses.add(id);
    const weight = numberOrNull(item.weight_percent);
    if (weight === null || weight <= 0) error("workload", "WORKLOAD_WEIGHT_INVALID", `业务类别 ${n} 的占比必须大于零。`);
    else totalWeight += weight;
    if (!item.input_tokens?.trim()) error("workload", "INPUT_DISTRIBUTION_REQUIRED", `业务类别 ${n} 缺少输入 token 分布。`);
    if (!item.output_tokens?.trim()) error("workload", "OUTPUT_DISTRIBUTION_REQUIRED", `业务类别 ${n} 缺少请求输出 token 分布。`);
    if (!item.quality_rule?.trim()) error("workload", "QUALITY_RULE_REQUIRED", `业务类别 ${n} 缺少质量规则。`);
  });
  if ((draft.workload_classes ?? []).length && Math.abs(totalWeight - 100) > 0.001) {
    error("workload", "WORKLOAD_WEIGHT_SUM", `业务类别占比合计必须为 100%，当前为 ${totalWeight}%。`);
  }

  const missingCatalogue = [];
  const unavailableMemoryInputs = [];
  for (const [key, label] of DEPLOYMENT_CATALOGUE) {
    const requirement = draft.deployment_requirements?.[key];
    if (!requirement || !["required", "allowed_set", "not_required", "informational"].includes(requirement.requirement_state)) {
      missingCatalogue.push(label);
      continue;
    }
    if (["required", "allowed_set"].includes(requirement.requirement_state) && !requirement.constraint?.trim()) {
      error("deployment", "DEPLOYMENT_CONSTRAINT_REQUIRED", `${label} 选择 ${requirement.requirement_state} 后必须填写约束。`);
    }
    if (MEMORY_ENVELOPE_PREREQUISITES.has(key) && !["required", "allowed_set"].includes(requirement.requirement_state)) {
      unavailableMemoryInputs.push(label);
    }
  }
  if (missingCatalogue.length) error("deployment", "DEPLOYMENT_CATALOGUE_INCOMPLETE", `14 项目录尚有 ${missingCatalogue.length} 项未明确表态：${missingCatalogue.join("、")}。`);
  if (unavailableMemoryInputs.length) warning("deployment", "MEMORY_ENVELOPE_UNAVAILABLE_BY_CONTRACT", `物理显存一致性检查将因合同前置不足而不可用：${unavailableMemoryInputs.join("、")}。这不等于通过。`);

  const execution = draft.execution ?? {};
  const maxLoad = numberOrNull(execution.max_load);
  const points = parseLoadPoints(execution.load_points);
  if (!(maxLoad > 0)) error("execution", "MAX_LOAD_REQUIRED", "最大计划负载必须大于零。");
  if (!points.length || points.some(point => point <= 0)) error("execution", "LOAD_POINTS_REQUIRED", "至少需要一个大于零的负载点。");
  if (maxLoad > 0 && points.length && Math.max(...points) !== maxLoad) warning("execution", "MAX_LOAD_NOT_SCANNED", "负载点中的最大值与最大计划负载不一致。");
  const repeats = numberOrNull(execution.repeats);
  if (!(repeats >= 2)) error("execution", "REPEATS_TOO_LOW", "独立重复次数至少为 2，才能让不一致可见。");
  const minDuration = numberOrNull(execution.min_point_duration_s);
  const siteWindow = numberOrNull(execution.site_window_minutes);
  if (!(minDuration > 0)) error("execution", "POINT_DURATION_REQUIRED", "单点最低时长必须大于零。");
  if (!(numberOrNull(execution.min_point_samples) > 0)) error("execution", "POINT_SAMPLES_REQUIRED", "单点最低成功样本数必须大于零。");
  if (!(siteWindow > 0)) error("execution", "SITE_WINDOW_REQUIRED", "必须声明现场可用时间窗口。");
  if (points.length && repeats > 0 && minDuration > 0 && siteWindow > 0) {
    const measurementFloorMinutes = points.length * repeats * minDuration / 60;
    if (measurementFloorMinutes > siteWindow) error("execution", "SITE_WINDOW_BELOW_MEASUREMENT_FLOOR", `仅正式负载点的最低测量时间已为 ${measurementFloorMinutes.toFixed(1)} 分钟，超过现场窗口；尚未计入标定、重置、质量检查和上传。`);
    else if (measurementFloorMinutes > siteWindow * 0.6) warning("execution", "SITE_WINDOW_LOW_RESERVE", `正式负载点最低需要 ${measurementFloorMinutes.toFixed(1)} 分钟，现场窗口留给标定、重置、质量检查和上传的余量偏小。`);
  }
  const preflight = execution.preflight ?? {};
  if (!preflight.max_load_sustained) error("execution", "PREFLIGHT_SUSTAINED_LOAD_REQUIRED", "出发前自检必须按最大负载持续配速，瞬时峰值不算通过。");
  if (!preflight.resource_recorded) error("execution", "PREFLIGHT_RESOURCE_RECORD_REQUIRED", "出发前自检必须记录客户端资源。");
  if (!preflight.onsite_same_path_calibration) error("execution", "ONSITE_CALIBRATION_REQUIRED", "正式测量前必须在现场真实路径重新标定。");
  if (!preflight.buyer_controls_responder) error("execution", "RESPONDER_CONTROL_REQUIRED", "甲方必须控制并校验包内锁定的标定应答器。");
  if (!execution.mutable_paths?.trim()) warning("execution", "RETEST_MUTABILITY_UNDECLARED", "尚未说明重测时允许修改哪些配置；这会在 FAIL 后产生争议。");

  return { errors, warnings, ready: errors.length === 0 };
}

export function finalizedDraft(draft) {
  const copy = JSON.parse(JSON.stringify(draft));
  const validation = validateDraft(copy);
  copy.schema = CURRENT_DRAFT_SCHEMA;
  copy.status = validation.ready ? "READY_FOR_HUMAN_REVIEW" : "DRAFT_WITH_ERRORS";
  copy.notice = "AC04 authoring prototype only; not a frozen contract, test pack, or verdict.";
  copy.validation = {
    checked_at: new Date().toISOString(),
    error_count: validation.errors.length,
    warning_count: validation.warnings.length,
    errors: validation.errors,
    warnings: validation.warnings,
  };
  copy.derived = {
    load_point_count: parseLoadPoints(copy.execution?.load_points).length,
    measurement_floor_minutes:
      parseLoadPoints(copy.execution?.load_points).length *
      (numberOrNull(copy.execution?.repeats) ?? 0) *
      (numberOrNull(copy.execution?.min_point_duration_s) ?? 0) / 60,
    physical_memory_consistency:
      validation.warnings.some(item => item.code === "MEMORY_ENVELOPE_UNAVAILABLE_BY_CONTRACT")
        ? "UNAVAILABLE_BY_CONTRACT"
        : "PREREQUISITES_DECLARED_NOT_YET_OBSERVED",
  };
  return copy;
}
