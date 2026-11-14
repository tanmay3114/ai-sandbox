import test from "node:test";
import assert from "node:assert/strict";
import { isRouteAllowed } from "../bff/server.ts";
import { AUDITED_BENCHMARK_METADATA, AUDITED_WORKLOADS, AUDITED_CONCURRENCY } from "../src/features/benchmarks/data/auditedBenchmark.ts";

test("BFF Security & Allowlist Enforcement", () => {
  // Allowlisted sandbox routes
  assert.equal(isRouteAllowed("GET", "/health"), true, "GET /health must be allowed");
  assert.equal(isRouteAllowed("GET", "/ready"), true, "GET /ready must be allowed");
  assert.equal(isRouteAllowed("GET", "/api/v1/sandboxes"), true, "GET /api/v1/sandboxes must be allowed");
  assert.equal(isRouteAllowed("POST", "/api/v1/sandboxes"), true, "POST /api/v1/sandboxes must be allowed");
  assert.equal(isRouteAllowed("GET", "/api/v1/sandboxes/sb_1234"), true, "GET sandbox by id allowed");
  assert.equal(isRouteAllowed("DELETE", "/api/v1/sandboxes/sb_1234"), true, "DELETE sandbox by id allowed");

  // Allowlisted workspace routes
  assert.equal(isRouteAllowed("GET", "/api/v1/sandboxes/sb_1234/files"), true, "GET workspace files allowed");
  assert.equal(isRouteAllowed("POST", "/api/v1/sandboxes/sb_1234/files"), true, "POST workspace files allowed");
  assert.equal(isRouteAllowed("DELETE", "/api/v1/sandboxes/sb_1234/files"), true, "DELETE workspace files allowed");
  assert.equal(isRouteAllowed("POST", "/api/v1/sandboxes/sb_1234/directories"), true, "POST directories allowed");

  // Allowlisted agent routes
  assert.equal(isRouteAllowed("POST", "/api/v1/sandboxes/sb_1234/agent/tasks"), true, "POST agent task allowed");
  assert.equal(isRouteAllowed("GET", "/api/v1/sandboxes/sb_1234/agent/tasks"), true, "GET agent tasks allowed");
  assert.equal(isRouteAllowed("GET", "/api/v1/sandboxes/sb_1234/agent/tasks/task_5678"), true, "GET agent task detail allowed");
  assert.equal(isRouteAllowed("POST", "/api/v1/sandboxes/sb_1234/agent/tasks/task_5678/cancel"), true, "POST cancel agent task allowed");

  // Unlisted or malicious routes MUST be rejected (anti-open-proxy)
  assert.equal(isRouteAllowed("POST", "/health"), false, "POST /health must be blocked");
  assert.equal(isRouteAllowed("GET", "/api/v1/admin/secrets"), false, "unlisted admin route must be blocked");
  assert.equal(isRouteAllowed("GET", "/etc/passwd"), false, "path traversal must be blocked");
  assert.equal(isRouteAllowed("POST", "/api/v1/sandboxes/sb_1234/unapproved_action"), false, "unlisted action must be blocked");
});

test("Static Audited Benchmark Invariants", () => {
  assert.equal(AUDITED_BENCHMARK_METADATA.total_samples, 106, "Benchmark must reflect exactly 106 verified samples");
  assert.equal(AUDITED_BENCHMARK_METADATA.docker_samples, 53, "Docker samples must equal 53");
  assert.equal(AUDITED_BENCHMARK_METADATA.qemu_samples, 53, "QEMU samples must equal 53");
  assert.equal(AUDITED_BENCHMARK_METADATA.run_id, "bench_audited_20261110_103626", "Run ID must match audited artifact");

  // Verify memory separation
  for (const wl of AUDITED_WORKLOADS) {
    assert.match(wl.docker.memory_layer, /cgroup/i, "Docker memory must be labeled as cgroup RSS");
    assert.match(wl.qemu.memory_layer, /host/i, "QEMU memory must be labeled as host process RSS");
    assert.notEqual(wl.docker.memory_layer, wl.qemu.memory_layer, "Memory layers must not be equated");
  }

  // Verify concurrency data
  assert.equal(AUDITED_CONCURRENCY.length, 2, "Concurrency 2 and 4 must be present");
});
