import { useState } from "react";
import {
  Scale,
  ShieldAlert,
} from "lucide-react";
import {
  AUDITED_BENCHMARK_METADATA,
  AUDITED_WORKLOADS,
  AUDITED_CONCURRENCY,
} from "../data/auditedBenchmark";

export function BenchmarkPage() {
  const [activeTab, setActiveTab] = useState<"workloads" | "concurrency" | "provenance">("workloads");

  return (
    <div
      style={{
        maxWidth: 1100,
        margin: "0 auto",
        display: "flex",
        flexDirection: "column",
        gap: 20,
      }}
    >
      {/* Header Banner */}
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
          <div
            style={{
              width: 32,
              height: 32,
              borderRadius: 8,
              backgroundColor: "rgba(245, 158, 11, 0.15)",
              color: "#f59e0b",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <Scale size={18} />
          </div>
          <h1
            style={{
              fontSize: 20,
              fontWeight: 700,
              margin: 0,
              color: "var(--color-text-primary)",
            }}
          >
            Audited Performance Benchmarks
          </h1>
          <span
            style={{
              fontSize: 11,
              fontWeight: 700,
              padding: "2px 8px",
              borderRadius: 4,
              backgroundColor: "var(--color-warning-subtle)",
              color: "var(--color-warning)",
              border: "1px solid currentColor",
            }}
          >
            STATIC AUDITED DATA
          </span>
        </div>
        <p
          style={{
            fontSize: 13,
            color: "var(--color-text-muted)",
            margin: 0,
            maxWidth: 780,
            lineHeight: 1.5,
          }}
        >
          Comprehensive empirical comparison between the <strong>Docker Execution Backend</strong> (cgroup/namespace isolation) and the <strong>QEMU ARM64 MicroVM Backend</strong> (Apple Silicon HVF hypervisor isolation).
        </p>
      </div>

      {/* Mandatory Memory Boundary Disclosure Alert */}
      <div
        style={{
          padding: "14px 18px",
          borderRadius: 8,
          backgroundColor: "var(--color-surface)",
          border: "1px solid var(--color-warning)",
          display: "flex",
          alignItems: "flex-start",
          gap: 12,
        }}
      >
        <ShieldAlert size={20} color="var(--color-warning)" style={{ flexShrink: 0, marginTop: 2 }} />
        <div style={{ fontSize: 12, lineHeight: 1.6, color: "var(--color-text-secondary)" }}>
          <strong style={{ color: "var(--color-warning)", display: "block", marginBottom: 2 }}>
            Critical Methodological Caveat: Non-Equivalent Memory Accounting Layers
          </strong>
          <span>
            <strong>Docker Memory</strong> is sampled as Linux container cgroup RSS (<code>memory.current</code>). In fast sub-second runs, cgroup counters record only ephemeral container worker memory (~12–68 MB).
            In contrast, <strong>QEMU Memory</strong> is measured as the macOS host hypervisor process RSS (<code>ps -o rss= -p &lt;pid&gt;</code>), capturing the entire 256 MB guest physical RAM allocation plus QEMU engine overhead (~284–324 MB).
            <strong> These metrics are not direct equivalents.</strong>
          </span>
        </div>
      </div>

      {/* Metadata KPI Row */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
          gap: 12,
        }}
      >
        <div
          style={{
            backgroundColor: "var(--color-surface)",
            border: "1px solid var(--color-border-subtle)",
            borderRadius: 8,
            padding: "14px 16px",
          }}
        >
          <div style={{ fontSize: 11, color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: 4 }}>
            Total Audited Samples
          </div>
          <div style={{ fontSize: 18, fontWeight: 700, color: "var(--color-text-primary)" }}>
            {AUDITED_BENCHMARK_METADATA.total_samples} Executions
          </div>
          <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 2 }}>
            53 Docker · 53 QEMU MicroVMs
          </div>
        </div>

        <div
          style={{
            backgroundColor: "var(--color-surface)",
            border: "1px solid var(--color-border-subtle)",
            borderRadius: 8,
            padding: "14px 16px",
          }}
        >
          <div style={{ fontSize: 11, color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: 4 }}>
            Audited Environment
          </div>
          <div style={{ fontSize: 14, fontWeight: 600, color: "var(--color-text-primary)" }}>
            Apple M4 (Darwin 24.3)
          </div>
          <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 2 }}>
            32 GB RAM · HVF Hypervisor Framework
          </div>
        </div>

        <div
          style={{
            backgroundColor: "var(--color-surface)",
            border: "1px solid var(--color-border-subtle)",
            borderRadius: 8,
            padding: "14px 16px",
          }}
        >
          <div style={{ fontSize: 11, color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: 4 }}>
            Cleanup Teardown Success
          </div>
          <div style={{ fontSize: 18, fontWeight: 700, color: "var(--color-success)" }}>
            100% Verified
          </div>
          <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 2 }}>
            Zero lingering processes or volumes
          </div>
        </div>

        <div
          style={{
            backgroundColor: "var(--color-surface)",
            border: "1px solid var(--color-border-subtle)",
            borderRadius: 8,
            padding: "14px 16px",
          }}
        >
          <div style={{ fontSize: 11, color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: 4 }}>
            Benchmark Nature
          </div>
          <div style={{ fontSize: 14, fontWeight: 600, color: "var(--color-accent)" }}>
            Static / Historical Trace
          </div>
          <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 2 }}>
            Run ID: <code>bench_audited_20261110_103626</code>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", gap: 8, borderBottom: "1px solid var(--color-border-subtle)", paddingBottom: 2 }}>
        <button
          type="button"
          onClick={() => setActiveTab("workloads")}
          style={{
            padding: "8px 14px",
            border: "none",
            background: "none",
            borderBottom: activeTab === "workloads" ? "2px solid var(--color-accent)" : "2px solid transparent",
            color: activeTab === "workloads" ? "var(--color-accent)" : "var(--color-text-secondary)",
            fontWeight: activeTab === "workloads" ? 600 : 400,
            fontSize: 13,
            cursor: "pointer",
          }}
        >
          Sequential Workloads (Latency & Memory)
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("concurrency")}
          style={{
            padding: "8px 14px",
            border: "none",
            background: "none",
            borderBottom: activeTab === "concurrency" ? "2px solid var(--color-accent)" : "2px solid transparent",
            color: activeTab === "concurrency" ? "var(--color-accent)" : "var(--color-text-secondary)",
            fontWeight: activeTab === "concurrency" ? 600 : 400,
            fontSize: 13,
            cursor: "pointer",
          }}
        >
          Concurrency &amp; Throughput
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("provenance")}
          style={{
            padding: "8px 14px",
            border: "none",
            background: "none",
            borderBottom: activeTab === "provenance" ? "2px solid var(--color-accent)" : "2px solid transparent",
            color: activeTab === "provenance" ? "var(--color-accent)" : "var(--color-text-secondary)",
            fontWeight: activeTab === "provenance" ? 600 : 400,
            fontSize: 13,
            cursor: "pointer",
          }}
        >
          Methodology &amp; Provenance
        </button>
      </div>

      {/* Tab 1: Workloads Table */}
      {activeTab === "workloads" && (
        <div
          style={{
            backgroundColor: "var(--color-surface)",
            border: "1px solid var(--color-border-subtle)",
            borderRadius: 8,
            overflowX: "auto",
          }}
        >
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr style={{ backgroundColor: "var(--color-surface-2)", borderBottom: "1px solid var(--color-border)" }}>
                <th style={{ padding: "10px 14px", textAlign: "left" }}>Workload</th>
                <th style={{ padding: "10px 14px", textAlign: "center" }}>Samples</th>
                <th style={{ padding: "10px 14px", textAlign: "left" }}>Docker Duration (Mean / p50 / p95)</th>
                <th style={{ padding: "10px 14px", textAlign: "left" }}>QEMU Duration (Mean / p50 / p95)</th>
                <th style={{ padding: "10px 14px", textAlign: "left" }}>Startup Overhead</th>
                <th style={{ padding: "10px 14px", textAlign: "left" }}>Peak Memory (Separated Layers)</th>
              </tr>
            </thead>
            <tbody>
              {AUDITED_WORKLOADS.map((item) => {
                const diff = item.qemu.mean_ms - item.docker.mean_ms;
                const ratio = (item.qemu.mean_ms / item.docker.mean_ms).toFixed(2);

                return (
                  <tr key={item.workload} style={{ borderBottom: "1px solid var(--color-border-subtle)" }}>
                    <td style={{ padding: "12px 14px", verticalAlign: "top" }}>
                      <div style={{ fontWeight: 600, fontFamily: "monospace", color: "var(--color-text-primary)" }}>
                        {item.workload}
                      </div>
                      <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 2 }}>
                        {item.description}
                      </div>
                    </td>

                    <td style={{ padding: "12px 14px", textAlign: "center", verticalAlign: "top" }}>
                      {item.samplesPerBackend} / backend
                    </td>

                    <td style={{ padding: "12px 14px", verticalAlign: "top" }}>
                      <div style={{ fontWeight: 600, color: "var(--color-text-primary)" }}>
                        {item.docker.mean_ms} ms (mean)
                      </div>
                      <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
                        p50: {item.docker.median_ms} ms · p95: {item.docker.p95_ms} ms
                      </div>
                    </td>

                    <td style={{ padding: "12px 14px", verticalAlign: "top" }}>
                      <div style={{ fontWeight: 600, color: "var(--color-text-primary)" }}>
                        {item.qemu.mean_ms} ms (mean)
                      </div>
                      <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
                        p50: {item.qemu.median_ms} ms · p95: {item.qemu.p95_ms} ms
                      </div>
                      <div style={{ fontSize: 10, color: "var(--color-warning)", marginTop: 2 }}>
                        +{diff.toFixed(1)} ms ({ratio}x)
                      </div>
                    </td>

                    <td style={{ padding: "12px 14px", verticalAlign: "top" }}>
                      <div>Docker: <strong>{item.docker.startup_mean_ms} ms</strong></div>
                      <div style={{ marginTop: 2 }}>QEMU: <strong>{item.qemu.startup_mean_ms} ms</strong></div>
                    </td>

                    <td style={{ padding: "12px 14px", verticalAlign: "top" }}>
                      <div style={{ marginBottom: 4 }}>
                        <span style={{ color: "var(--color-text-muted)", fontSize: 10 }}>DOCKER (CGROUP): </span>
                        <strong>{item.docker.peak_memory_human}</strong>
                      </div>
                      <div>
                        <span style={{ color: "var(--color-text-muted)", fontSize: 10 }}>QEMU (HOST RSS): </span>
                        <strong>{item.qemu.peak_memory_human}</strong>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Tab 2: Concurrency */}
      {activeTab === "concurrency" && (
        <div
          style={{
            backgroundColor: "var(--color-surface)",
            border: "1px solid var(--color-border-subtle)",
            borderRadius: 8,
            padding: 20,
            display: "flex",
            flexDirection: "column",
            gap: 16,
          }}
        >
          <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
            Concurrent workload stress measurements across multiple worker threads:
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 16 }}>
            {AUDITED_CONCURRENCY.map((c) => (
              <div
                key={c.concurrency}
                style={{
                  backgroundColor: "var(--color-surface-2)",
                  border: "1px solid var(--color-border)",
                  borderRadius: 8,
                  padding: "16px 18px",
                }}
              >
                <div style={{ fontSize: 14, fontWeight: 700, color: "var(--color-text-primary)", marginBottom: 12 }}>
                  Concurrency Level = {c.concurrency} Threads
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: 10, fontSize: 12 }}>
                  <div style={{ padding: "8px 10px", backgroundColor: "var(--color-surface)", borderRadius: 6 }}>
                    <div style={{ fontWeight: 600, color: "var(--color-accent)", marginBottom: 2 }}>Docker Engine</div>
                    <div>Throughput: <strong>{c.docker.throughput_ops_sec} ops/sec</strong></div>
                    <div>Mean Latency: <strong>{c.docker.mean_ms} ms</strong> (p95: {c.docker.p95_ms} ms)</div>
                    <div style={{ fontSize: 10, color: "var(--color-text-muted)" }}>Samples: {c.docker.sample_count} runs</div>
                  </div>

                  <div style={{ padding: "8px 10px", backgroundColor: "var(--color-surface)", borderRadius: 6 }}>
                    <div style={{ fontWeight: 600, color: "#f59e0b", marginBottom: 2 }}>QEMU ARM64 MicroVM</div>
                    <div>Throughput: <strong>{c.qemu.throughput_ops_sec} ops/sec</strong></div>
                    <div>Mean Latency: <strong>{c.qemu.mean_ms} ms</strong> (p95: {c.qemu.p95_ms} ms)</div>
                    <div style={{ fontSize: 10, color: "var(--color-text-muted)" }}>Samples: {c.qemu.sample_count} runs</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Tab 3: Provenance & Methodology */}
      {activeTab === "provenance" && (
        <div
          style={{
            backgroundColor: "var(--color-surface)",
            border: "1px solid var(--color-border-subtle)",
            borderRadius: 8,
            padding: "20px 24px",
            display: "flex",
            flexDirection: "column",
            gap: 16,
            fontSize: 13,
            lineHeight: 1.6,
          }}
        >
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: "var(--color-text-primary)" }}>
            Benchmark Provenance &amp; Verification Methodology
          </h3>

          <div style={{ color: "var(--color-text-secondary)" }}>
            <p style={{ marginTop: 0 }}>
              The measurements displayed above originate from an audited benchmark run conducted on Apple Silicon under identical isolation constraints:
            </p>

            <ul style={{ paddingLeft: 20, margin: "8px 0" }}>
              <li><strong>Zero Ambient Containers:</strong> Every execution creates a fresh ephemeral execution environment with zero warm worker reuse.</li>
              <li><strong>Strict Air-gapping:</strong> Network isolation (<code>network_mode="none"</code> and <code>-nic none</code>) is verified on every run.</li>
              <li><strong>Air-tight Teardown:</strong> 100% of temporary overlays, sockets, and containers were verified unlinked upon completion.</li>
              <li><strong>Non-overlapping Phase Decomposition:</strong> Phase timers measure environment startup, workspace injection, workload execution, retrieval, and cleanup independently.</li>
            </ul>

            <h4 style={{ margin: "16px 0 6px", fontSize: 13, fontWeight: 600, color: "var(--color-text-primary)" }}>
              Architectural Takeaway
            </h4>
            <p style={{ margin: 0 }}>
              Docker delivers fast execution turnaround (~120–140 ms total wall clock) optimal for rapid developer workflows, while QEMU provides hardware-enforced hypervisor microVM boundaries (~430–460 ms total wall clock) suited for multi-tenant or untrusted AI agent execution.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
