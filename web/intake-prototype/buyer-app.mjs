import { BUYER_STEPS, emptyBuyerIntake, finalizeBuyerIntake, validateBuyerIntake } from "./buyer-model.mjs";

const form = document.querySelector("#buyer-form");
const nav = document.querySelector("#buyer-step-nav");
let currentStep = 0;
const value = name => form.elements.namedItem(name)?.value ?? "";
const number = name => value(name) === "" ? null : Number(value(name));
const selected = name => [...form.querySelectorAll(`[name="${name}"]:checked`)].map(node => node.value);

function collect() {
  return {
    ...emptyBuyerIntake(),
    project: { project_id: value("project_id").trim(), buyer_role: value("buyer_role"), use_cases: selected("use_case"), business_outcome: value("business_outcome").trim() },
    peak_use: { peak_users_known: value("peak_users_known"), peak_users: number("peak_users"), interaction_pattern: value("interaction_pattern"), requests_per_minute: number("requests_per_minute"), input_size: value("input_size") },
    experience: { first_response_required: value("first_response_required"), first_response_seconds: number("first_response_seconds"), first_response_reliability: value("first_response_reliability"), stability_hours: number("stability_hours"), recovery_expectation: value("recovery_expectation"), risks: selected("risk"), quality_expectation: value("quality_expectation").trim() },
    evidence_and_process: { supplier_evidence: selected("supplier_evidence"), fail_transition: value("fail_transition"), site_window_hours: number("site_window_hours"), retest_changes: value("retest_changes") },
  };
}

function renderNav() {
  nav.replaceChildren();
  BUYER_STEPS.forEach(([key, label], index) => {
    const button = document.createElement("button");
    button.type = "button"; button.className = `nav-step${index === currentStep ? " active" : ""}`;
    button.innerHTML = `<b>${String(index + 1).padStart(2, "0")}</b><span>${label}</span>`;
    button.addEventListener("click", () => show(index)); nav.append(button);
  });
}

function renderReview() {
  const draft = finalizeBuyerIntake(collect());
  const box = document.querySelector("#buyer-validation-summary"); box.replaceChildren();
  if (!draft.validation.errors.length) box.innerHTML = `<div class="validation-item success"><strong>采购信息已可交给技术人员转换。</strong> 当前产生 ${draft.technical_translation_tasks.length} 项显式确认任务；它们不会被静默默认。</div>`;
  for (const item of draft.validation.errors) { const node = document.createElement("div"); node.className = "validation-item error"; node.textContent = `需要补充 · ${item.message}`; box.append(node); }
  for (const item of draft.technical_translation_tasks) { const node = document.createElement("div"); node.className = "validation-item warning"; node.textContent = `${item.buyer_emphasis ? "买方重点 · " : ""}${item.owner} · ${item.message}${item.blocks_freeze ? "（冻结前必须解决）" : ""}`; box.append(node); }
  document.querySelector("#buyer-json-preview").textContent = JSON.stringify(draft, null, 2); return draft;
}

function refresh() {
  const result = validateBuyerIntake(collect());
  document.querySelector("#buyer-readiness-label").textContent = result.errors.length ? `${result.errors.length} 项业务信息待补充` : `${result.tasks.length} 项交给技术转换`;
  if (currentStep === BUYER_STEPS.length - 1) renderReview();
}

function show(index) {
  currentStep = Math.max(0, Math.min(index, BUYER_STEPS.length - 1));
  document.querySelectorAll("[data-buyer-step]").forEach((section, i) => { section.hidden = i !== currentStep; });
  document.querySelector("#buyer-previous-step").disabled = currentStep === 0;
  document.querySelector("#buyer-next-step").textContent = currentStep === BUYER_STEPS.length - 1 ? "重新检查" : "下一步";
  document.querySelector("#buyer-progress-label").textContent = `第 ${currentStep + 1} / ${BUYER_STEPS.length} 步`;
  document.querySelector("#buyer-progress-bar").style.width = `${(currentStep + 1) / BUYER_STEPS.length * 100}%`;
  renderNav(); if (currentStep === BUYER_STEPS.length - 1) renderReview(); window.scrollTo({ top: 0, behavior: "smooth" });
}

function download() {
  const draft = renderReview(); const blob = new Blob([JSON.stringify(draft, null, 2)], { type: "application/json" }); const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a"); const id = draft.project.project_id.replace(/[^a-zA-Z0-9_-]+/g, "-") || "untitled";
  anchor.href = url; anchor.download = `PRIVATE-oicap-buyer-intake-${id}.json`; anchor.click(); URL.revokeObjectURL(url);
  document.querySelector("#buyer-local-status").textContent = "PRIVATE 草案已下载；请立即移至买方批准的私有位置";
}

document.querySelector("#buyer-previous-step").addEventListener("click", () => show(currentStep - 1));
document.querySelector("#buyer-next-step").addEventListener("click", () => show(currentStep === BUYER_STEPS.length - 1 ? currentStep : currentStep + 1));
document.querySelector("#buyer-download-json").addEventListener("click", download);
document.querySelector("#buyer-clear-form").addEventListener("click", () => { if (window.confirm("清空本次采购需求录入？页面没有自动保存。")) window.location.reload(); });
form.addEventListener("input", refresh); form.addEventListener("change", refresh); show(0); refresh();
