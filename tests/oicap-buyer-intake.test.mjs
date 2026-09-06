import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { emptyBuyerIntake, finalizeBuyerIntake, validateBuyerIntake } from "../web/intake-prototype/buyer-model.mjs";

function completeBuyerIntake() {
  const draft = emptyBuyerIntake();
  draft.project = { project_id: "case-01", buyer_role: "procurement", use_cases: ["knowledge_qa"], business_outcome: "Peak users receive stable, timely answers." };
  draft.peak_use = { peak_users_known: "known", peak_users: 100, interaction_pattern: "active_chat", requests_per_minute: null, input_size: "mixed" };
  draft.experience = { first_response_required: "yes", first_response_seconds: 2, first_response_reliability: "almost_all", stability_hours: 8, recovery_expectation: "no_interruption", risks: ["concurrency", "stability", "oom"], quality_expectation: "Business reviewers approve representative answers." };
  draft.evidence_and_process = { supplier_evidence: ["supplier_report", "hardware_inventory"], fail_transition: "remediate_retest", site_window_hours: 8, retest_changes: "same_model_hardware" };
  return draft;
}

test("buyer intake stops at technical translation rather than claiming freeze", () => {
  const result = finalizeBuyerIntake(completeBuyerIntake());
  assert.equal(result.status, "READY_FOR_TECHNICAL_TRANSLATION");
  assert.equal(result.handoff.technical_contract_frozen, false);
  assert.equal(result.handoff.test_pack_compiled, false);
  assert.equal(result.handoff.verdict_available, false);
});

test("unknown usage creates a named blocking translation task instead of a guessed default", () => {
  const draft = completeBuyerIntake();
  draft.peak_use.interaction_pattern = "unknown";
  const result = validateBuyerIntake(draft);
  assert(result.tasks.some(item => item.code === "ARRIVAL_SEMANTICS_UNRESOLVED" && item.blocks_freeze));
});

test("buyer procurement facts have no preselected defaults", () => {
  const result = validateBuyerIntake(emptyBuyerIntake());
  const codes = result.errors.map(item => item.code);
  assert(codes.includes("PEAK_USERS_KNOWLEDGE_REQUIRED"));
  assert(codes.includes("FIRST_RESPONSE_REQUIREMENT_REQUIRED"));
});

test("supplier report and inventory are evidence inputs, not automatic proof", () => {
  const result = validateBuyerIntake(completeBuyerIntake());
  assert(result.tasks.some(item => item.code === "SUPPLIER_REPORT_PROVENANCE_ONLY"));
  assert(result.tasks.some(item => item.code === "RUNTIME_BINDING_REQUIRED" && item.blocks_freeze));
});

test("OOM concern requires confirming evidence and is not inferred from black-box failure", () => {
  const result = validateBuyerIntake(completeBuyerIntake());
  const task = result.tasks.find(item => item.code === "OOM_EVIDENCE_PLAN_REQUIRED");
  assert(task?.blocks_freeze);
  assert.equal(task?.buyer_emphasis, true);
  assert.match(task.message, /只有.*证据能确认 OOM/);
});

test("declared load and stability requirements create plans even when only OOM is a stated worry", () => {
  const draft = completeBuyerIntake();
  draft.peak_use.peak_users = 500;
  draft.experience.stability_hours = 720;
  draft.experience.risks = ["oom"];

  const result = finalizeBuyerIntake(draft);
  const byCode = new Map(result.technical_translation_tasks.map(item => [item.code, item]));

  assert.equal(result.status, "READY_FOR_TECHNICAL_TRANSLATION");
  assert(byCode.has("CONCURRENCY_SWEEP_REQUIRED"));
  assert(byCode.has("SOAK_PLAN_REQUIRED"));
  assert(byCode.has("RECOVERY_OBSERVATION_PLAN_REQUIRED"));
  assert.equal(byCode.get("CONCURRENCY_SWEEP_REQUIRED").buyer_emphasis, false);
  assert.equal(byCode.get("SOAK_PLAN_REQUIRED").buyer_emphasis, false);
  assert.equal(byCode.get("OOM_EVIDENCE_PLAN_REQUIRED").buyer_emphasis, true);
});

test("buyer worries raise plan emphasis without determining whether the plan exists", () => {
  const draft = completeBuyerIntake();
  draft.experience.risks = ["concurrency", "stability"];
  const result = validateBuyerIntake(draft);
  const byCode = new Map(result.tasks.map(item => [item.code, item]));
  assert.equal(byCode.get("CONCURRENCY_SWEEP_REQUIRED").buyer_emphasis, true);
  assert.equal(byCode.get("SOAK_PLAN_REQUIRED").buyer_emphasis, true);
});

test("post-failure renegotiation is exposed as a freeze-blocking procurement task", () => {
  const draft = completeBuyerIntake();
  draft.evidence_and_process.fail_transition = "renegotiate";
  const result = validateBuyerIntake(draft);
  assert(result.tasks.some(item => item.code === "FAIL_TRANSITION_UNRESOLVED" && item.blocks_freeze));
});

test("default buyer page does not ask procurement to author expert measurement fields", async () => {
  const html = await readFile(new URL("../web/intake-prototype/index.html", import.meta.url), "utf8");
  assert.doesNotMatch(html, /统计总体|时间戳权威|并行策略|scan point|p95|p99/i);
  assert.match(html, /不需要懂压测术语/);
  assert.match(html, /技术合同工作台/);
});

for (const [htmlName, appName] of [["index.html", "buyer-app.mjs"], ["expert.html", "app.mjs"]]) {
  test(`${appName} has no dangling literal id selectors`, async () => {
    const html = await readFile(new URL(`../web/intake-prototype/${htmlName}`, import.meta.url), "utf8");
    const app = await readFile(new URL(`../web/intake-prototype/${appName}`, import.meta.url), "utf8");
    const ids = new Set([...html.matchAll(/\bid=["']([^"']+)["']/g)].map(match => match[1]));
    const selectors = [...app.matchAll(/querySelector\(["']#([^"']+)["']\)/g)].map(match => match[1]);
    assert(selectors.length > 0);
    assert.deepEqual(selectors.filter(id => !ids.has(id)), []);
  });
}
