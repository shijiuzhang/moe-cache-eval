import {
  STEPS,
  DEPLOYMENT_CATALOGUE,
  MEMORY_ENVELOPE_PREREQUISITES,
  emptyDraft,
  emptyGate,
  emptyWorkload,
  finalizedDraft,
  numberOrNull,
  parseLoadPoints,
  validateDraft,
} from "./model.mjs";

const form = document.querySelector("#intake-form");
const nav = document.querySelector("#step-nav");
const gateList = document.querySelector("#gate-list");
const workloadList = document.querySelector("#workload-list");
const deploymentList = document.querySelector("#deployment-list");
const validationSummary = document.querySelector("#validation-summary");
const jsonPreview = document.querySelector("#json-preview");
let currentStep = 0;

function option(value, label) {
  const node = document.createElement("option");
  node.value = value;
  node.textContent = label;
  return node;
}

function renderNav() {
  nav.replaceChildren();
  STEPS.forEach(([key, label], index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `nav-step${index === currentStep ? " active" : ""}`;
    button.dataset.step = key;
    button.innerHTML = `<b>${String(index + 1).padStart(2, "0")}</b><span>${label}</span>`;
    button.addEventListener("click", () => showStep(index));
    nav.append(button);
  });
}

function updateIndices(list) {
  [...list.children].forEach((card, index) => {
    card.querySelector(".item-index").textContent = String(index + 1).padStart(2, "0");
    card.querySelector(".remove-item").hidden = list.children.length === 1;
  });
}

function fillCard(card, value) {
  for (const control of card.querySelectorAll("[data-field]")) {
    const field = control.dataset.field;
    if (control.type === "checkbox") control.checked = Boolean(value[field]);
    else control.value = value[field] ?? "";
  }
}

function addCard(kind, value) {
  const isGate = kind === "gate";
  const list = isGate ? gateList : workloadList;
  const template = document.querySelector(isGate ? "#gate-template" : "#workload-template");
  const card = template.content.firstElementChild.cloneNode(true);
  fillCard(card, value ?? (isGate ? emptyGate() : emptyWorkload()));
  card.querySelector(".remove-item").addEventListener("click", () => {
    card.remove();
    updateIndices(list);
    refreshReadiness();
  });
  card.addEventListener("input", refreshReadiness);
  list.append(card);
  updateIndices(list);
}

function renderDeployment(requirements) {
  deploymentList.replaceChildren();
  for (const [key, label, description] of DEPLOYMENT_CATALOGUE) {
    const row = document.createElement("div");
    row.className = "requirement-row";
    row.dataset.key = key;
    const title = document.createElement("div");
    title.innerHTML = `<strong>${label}</strong><small>${description}</small>`;
    const state = document.createElement("select");
    state.className = "requirement-state";
    state.setAttribute("aria-label", `${label}要求状态`);
    state.append(option("", "请选择状态"));
    state.append(option("required", "required"));
    state.append(option("allowed_set", "allowed_set"));
    state.append(option("informational", "informational"));
    state.append(option("not_required", "not_required"));
    state.value = requirements[key]?.requirement_state ?? "";
    const constraint = document.createElement("input");
    constraint.className = "requirement-constraint";
    constraint.placeholder = "填写精确约束、集合边界或排除理由";
    constraint.value = requirements[key]?.constraint ?? "";
    const update = () => {
      const needsConstraint = ["required", "allowed_set"].includes(state.value);
      constraint.placeholder = needsConstraint ? "此状态必须填写可检验约束" : "可记录表态依据（不参与裁决）";
      updateMemoryEnvelopeWarning();
      refreshReadiness();
    };
    state.addEventListener("change", update);
    constraint.addEventListener("input", refreshReadiness);
    row.append(title, state, constraint);
    deploymentList.append(row);
    update();
  }
}

function value(name) {
  return form.elements.namedItem(name)?.value ?? "";
}

function checked(name) {
  return Boolean(form.elements.namedItem(name)?.checked);
}

function collectCards(list) {
  return [...list.children].map(card => {
    const record = {};
    for (const control of card.querySelectorAll("[data-field]")) {
      const field = control.dataset.field;
      if (control.type === "checkbox") record[field] = control.checked;
      else if (control.type === "number") record[field] = numberOrNull(control.value);
      else record[field] = control.value.trim();
    }
    return record;
  });
}

function collectDraft() {
  const deploymentRequirements = {};
  for (const row of deploymentList.children) {
    deploymentRequirements[row.dataset.key] = {
      requirement_state: row.querySelector(".requirement-state").value,
      constraint: row.querySelector(".requirement-constraint").value.trim(),
    };
  }
  return {
    ...emptyDraft(),
    project: {
      project_id: value("project_id").trim(),
      deployment_mode: value("deployment_mode"),
      buyer_role: value("buyer_role").trim(),
      technical_role: value("technical_role").trim(),
      measurement_boundary: value("measurement_boundary").trim(),
    },
    sla_gates: collectCards(gateList),
    workload_classes: collectCards(workloadList),
    deployment_requirements: deploymentRequirements,
    execution: {
      load_semantics: value("load_semantics"),
      max_load: numberOrNull(value("max_load")),
      repeats: numberOrNull(value("repeats")),
      site_window_minutes: numberOrNull(value("site_window_minutes")),
      min_point_duration_s: numberOrNull(value("min_point_duration_s")),
      min_point_samples: numberOrNull(value("min_point_samples")),
      load_points: parseLoadPoints(value("load_points")),
      max_retests: numberOrNull(value("max_retests")),
      mutable_paths: value("mutable_paths").trim(),
      preflight: {
        max_load_sustained: checked("preflight_max_load"),
        resource_recorded: checked("preflight_resource_record"),
        onsite_same_path_calibration: checked("onsite_same_path_calibration"),
        buyer_controls_responder: checked("buyer_controls_responder"),
      },
    },
  };
}

function refreshReadiness() {
  const validation = validateDraft(collectDraft());
  const label = document.querySelector("#readiness-label");
  if (validation.ready) label.textContent = validation.warnings.length ? `可人工评审 · ${validation.warnings.length} 条警告` : "可进入人工评审";
  else label.textContent = `${validation.errors.length} 项待补充`;
  if (currentStep === STEPS.length - 1) renderReview();
}

function updateMemoryEnvelopeWarning() {
  const missing = [];
  for (const row of deploymentList.children) {
    if (!MEMORY_ENVELOPE_PREREQUISITES.has(row.dataset.key)) continue;
    const state = row.querySelector(".requirement-state").value;
    if (!["required", "allowed_set"].includes(state)) {
      const label = DEPLOYMENT_CATALOGUE.find(([key]) => key === row.dataset.key)?.[1];
      missing.push(label);
    }
  }
  const box = document.querySelector("#memory-envelope-warning");
  box.hidden = missing.length === 0;
  box.innerHTML = missing.length
    ? `<strong>物理显存一致性检查当前不可用</strong><span>以下合同前置未被有界约束：${missing.join("、")}。这不是 PASS，冻结前必须明确接受失去的保障。</span>`
    : "";
}

function renderReview() {
  const draft = finalizedDraft(collectDraft());
  const { errors, warnings } = draft.validation;
  validationSummary.replaceChildren();
  if (!errors.length && !warnings.length) {
    validationSummary.innerHTML = '<div class="validation-item success"><strong>结构检查通过。</strong> 草案可以交给采购、技术和保密角色共同复核；它仍未冻结，也尚未生成测试包。</div>';
  } else {
    for (const item of errors) {
      const node = document.createElement("div");
      node.className = "validation-item error";
      node.textContent = `错误 · ${STEPS.find(([key]) => key === item.step)?.[1] ?? item.step} · ${item.message}`;
      validationSummary.append(node);
    }
    for (const item of warnings) {
      const node = document.createElement("div");
      node.className = "validation-item warning";
      node.textContent = `警告 · ${STEPS.find(([key]) => key === item.step)?.[1] ?? item.step} · ${item.message}`;
      validationSummary.append(node);
    }
  }
  jsonPreview.textContent = JSON.stringify(draft, null, 2);
  return draft;
}

function showStep(index) {
  currentStep = Math.max(0, Math.min(index, STEPS.length - 1));
  document.querySelectorAll(".step").forEach((section, sectionIndex) => {
    section.hidden = sectionIndex !== currentStep;
  });
  document.querySelector("#previous-step").disabled = currentStep === 0;
  document.querySelector("#next-step").textContent = currentStep === STEPS.length - 1 ? "重新检查" : "下一步";
  document.querySelector("#progress-label").textContent = `第 ${currentStep + 1} / ${STEPS.length} 步`;
  document.querySelector("#progress-bar").style.width = `${((currentStep + 1) / STEPS.length) * 100}%`;
  renderNav();
  if (currentStep === STEPS.length - 1) renderReview();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function downloadDraft() {
  const draft = renderReview();
  const body = JSON.stringify(draft, null, 2);
  const blob = new Blob([body], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  const id = draft.project.project_id.replace(/[^a-zA-Z0-9_-]+/g, "-") || "untitled";
  anchor.href = url;
  anchor.download = `PRIVATE-oicap-ac04-${id}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
  document.querySelector("#local-status").textContent = "PRIVATE 草案已进入浏览器下载目录；请立即移至买方批准的私有位置";
}

function initialize() {
  const draft = emptyDraft();
  addCard("gate", draft.sla_gates[0]);
  addCard("workload", draft.workload_classes[0]);
  renderDeployment(draft.deployment_requirements);
  renderNav();
  showStep(0);

  document.querySelector("#add-gate").addEventListener("click", () => addCard("gate", emptyGate()));
  document.querySelector("#add-workload").addEventListener("click", () => addCard("workload", emptyWorkload()));
  document.querySelector("#previous-step").addEventListener("click", () => showStep(currentStep - 1));
  document.querySelector("#next-step").addEventListener("click", () => showStep(currentStep === STEPS.length - 1 ? currentStep : currentStep + 1));
  document.querySelector("#download-json").addEventListener("click", downloadDraft);
  document.querySelector("#clear-form").addEventListener("click", () => {
    if (!window.confirm("清空当前浏览器中的本次演练？页面没有自动保存，清空后无法恢复。")) return;
    window.location.reload();
  });
  form.addEventListener("input", refreshReadiness);
  form.addEventListener("change", refreshReadiness);
  refreshReadiness();
}

initialize();
