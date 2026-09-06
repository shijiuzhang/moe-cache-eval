import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import {
  DEPLOYMENT_CATALOGUE,
  emptyDraft,
  finalizedDraft,
  validateDraft,
} from "../web/intake-prototype/model.mjs";

function completeDraft() {
  const draft = emptyDraft();
  draft.project = {
    project_id: "deidentified-case",
    deployment_mode: "private_on_prem",
    buyer_role: "procurement acceptance",
    technical_role: "infrastructure operations",
    measurement_boundary: "Buyer client through contracted network and API ingress.",
  };
  draft.workload_classes = [{
    class_id: "knowledge_qa",
    weight_percent: 100,
    input_tokens: "500-4000",
    output_tokens: "100-800",
    source_policy: "buyer_local",
    session_semantics: "single_turn",
    think_time_ms: 0,
    streaming: "required",
    quality_rule: "Pinned post-hoc validator and private reference manifest.",
  }];
  draft.sla_gates = [{
    metric: "ttft_ms",
    workload_class: "knowledge_qa",
    statistic: "p95",
    comparator: "lte",
    threshold: 2000,
    unit: "ms",
    population: "successful quality-eligible requests",
    min_samples: 100,
    min_duration_s: 60,
    quality_eligible: true,
    authority: "client_observed",
  }];
  draft.deployment_requirements = Object.fromEntries(
    DEPLOYMENT_CATALOGUE.map(([key]) => [key, {
      requirement_state: "required",
      constraint: `bounded ${key} requirement`,
    }]),
  );
  draft.execution = {
    load_semantics: "closed_loop",
    max_load: 500,
    repeats: 3,
    site_window_minutes: 480,
    min_point_duration_s: 60,
    min_point_samples: 100,
    load_points: [100, 250, 500],
    max_retests: 1,
    mutable_paths: "batching parameters only; model and hardware immutable",
    preflight: {
      max_load_sustained: true,
      resource_recorded: true,
      onsite_same_path_calibration: true,
      buyer_controls_responder: true,
    },
  };
  return draft;
}

test("a complete procurement draft is ready only for human review", () => {
  const result = validateDraft(completeDraft());
  assert.equal(result.ready, true);
  assert.deepEqual(result.errors, []);
  const exported = finalizedDraft(completeDraft());
  assert.equal(exported.status, "READY_FOR_HUMAN_REVIEW");
  assert.match(exported.notice, /not a frozen contract/i);
});

test("bare TPS is rejected even when imported outside the dropdown", () => {
  const draft = completeDraft();
  draft.sla_gates[0].metric = "TPS";
  const result = validateDraft(draft);
  assert(result.errors.some(item => item.code === "BARE_TPS_REJECTED"));
});

test("a silent deployment catalogue field blocks review", () => {
  const draft = completeDraft();
  delete draft.deployment_requirements.quantization;
  const result = validateDraft(draft);
  assert(result.errors.some(item => item.code === "DEPLOYMENT_CATALOGUE_INCOMPLETE"));
});

test("weak memory-envelope prerequisites are visible, not treated as pass", () => {
  const draft = completeDraft();
  draft.deployment_requirements.parallelism = {
    requirement_state: "informational",
    constraint: "",
  };
  const result = validateDraft(draft);
  assert.equal(result.ready, true);
  assert(result.warnings.some(item => item.code === "MEMORY_ENVELOPE_UNAVAILABLE_BY_CONTRACT"));
  assert.equal(finalizedDraft(draft).derived.physical_memory_consistency, "UNAVAILABLE_BY_CONTRACT");
});

test("workload weights and site-time floor are enforced", () => {
  const draft = completeDraft();
  draft.workload_classes[0].weight_percent = 90;
  draft.execution.site_window_minutes = 5;
  const codes = validateDraft(draft).errors.map(item => item.code);
  assert(codes.includes("WORKLOAD_WEIGHT_SUM"));
  assert(codes.includes("SITE_WINDOW_BELOW_MEASUREMENT_FLOOR"));
});

test("per-token gates require authoritative token timestamps", () => {
  const draft = completeDraft();
  draft.sla_gates[0].metric = "per_request_decode_tokens_per_second";
  draft.sla_gates[0].authority = "server_usage";
  assert(validateDraft(draft).errors.some(item => item.code === "TOKEN_TIMING_AUTHORITY_REQUIRED"));
});

test("both local authoring surfaces have no remote assets, persistence, or clipboard egress", async () => {
  const paths = ["index.html", "expert.html", "buyer-app.mjs", "buyer-model.mjs", "app.mjs", "model.mjs"];
  const contents = await Promise.all(paths.map(path => readFile(new URL(`../web/intake-prototype/${path}`, import.meta.url), "utf8")));
  const joined = contents.join("\n");
  assert.doesNotMatch(joined, /(?:src|href)=["']https?:/i);
  assert.doesNotMatch(joined, /fetch\s*\(|XMLHttpRequest|WebSocket|sendBeacon/);
  assert.doesNotMatch(joined, /localStorage|sessionStorage|indexedDB|document\.cookie/);
  assert.doesNotMatch(joined, /clipboard|copy-json/);
  assert.match(joined, /PRIVATE-oicap-ac04-/);
});
