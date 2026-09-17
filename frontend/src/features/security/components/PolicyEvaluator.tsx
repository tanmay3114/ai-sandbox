import { useState } from "react";
import {
  CheckCircle2,
  Play,
  Shield,
  ShieldAlert,
} from "lucide-react";
import { useEvaluatePolicy } from "../hooks/useSecurity";
import type {
  RequestedPolicyPayload,
  SecurityAuditRecord,
  SecurityEvaluationResponse,
} from "../types";

interface PresetOption {
  label: string;
  badge: "SAFE" | "CLAMP" | "REJECT";
  badgeColor: string;
  badgeBg: string;
  payload: RequestedPolicyPayload;
  description: string;
}

const PRESETS: PresetOption[] = [
  {
    label: "Safe Tuned Resources",
    badge: "SAFE",
    badgeColor: "var(--color-success)",
    badgeBg: "var(--color-success-subtle)",
    payload: {
      runtime: "python",
      timeout_seconds: 3.0,
      memory_limit: "128m",
      cpu_limit: 0.4,
      pids_limit: 20,
    },
    description: "Parameters within platform quotas. Evaluated as 'allowed'.",
  },
  {
    label: "Excessive Memory & Timeout",
    badge: "CLAMP",
    badgeColor: "var(--color-warning)",
    badgeBg: "var(--color-warning-subtle)",
    payload: {
      timeout_seconds: 60.0,
      memory_limit: "1024m",
      cpu_limit: 2.0,
      pids_limit: 100,
    },
    description: "Exceeds limits (1024m, 60s). Engine safely clamps to 256m and 5.0s.",
  },
  {
    label: "Reject Privileged Execution",
    badge: "REJECT",
    badgeColor: "var(--color-danger)",
    badgeBg: "var(--color-danger-subtle)",
    payload: {
      privileged: true,
    },
    description: "Attempting privileged container. Engine raises HTTP 400 violation.",
  },
  {
    label: "Reject Network Access",
    badge: "REJECT",
    badgeColor: "var(--color-danger)",
    badgeBg: "var(--color-danger-subtle)",
    payload: {
      network_mode: "bridge",
    },
    description: "Attempting network connection. Engine raises HTTP 400 violation.",
  },
  {
    label: "Reject Host Mounts",
    badge: "REJECT",
    badgeColor: "var(--color-danger)",
    badgeBg: "var(--color-danger-subtle)",
    payload: {
      volumes: { "/etc": { bind: "/host_etc" } },
    },
    description: "Attempting host volume bind. Engine raises HTTP 400 violation.",
  },
  {
    label: "Reject Arbitrary Image",
    badge: "REJECT",
    badgeColor: "var(--color-danger)",
    badgeBg: "var(--color-danger-subtle)",
    payload: {
      image: "alpine:latest",
    },
    description: "Attempting unverified image. Engine raises HTTP 400 violation.",
  },
];

export function PolicyEvaluator() {
  const [selectedPreset, setSelectedPreset] = useState<PresetOption>(PRESETS[0]);
  const [lastEvaluation, setLastEvaluation] = useState<SecurityEvaluationResponse | null>(null);
  const [lastError, setLastError] = useState<{
    error: string;
    message: string;
    details?: Record<string, any>;
  } | null>(null);
  const [auditLog, setAuditLog] = useState<SecurityAuditRecord[]>([]);

  const { mutate: evaluate, isPending } = useEvaluatePolicy();

  const handleRunEvaluation = (preset: PresetOption) => {
    setLastEvaluation(null);
    setLastError(null);

    evaluate(preset.payload, {
      onSuccess: (data) => {
        setLastEvaluation(data);
        if (data.audit) {
          setAuditLog((prev) => [data.audit, ...prev].slice(0, 10));
        }
      },
      onError: (err: any) => {
        const errorData = err.response?.data || {
          error: "SecurityPolicyViolationError",
          message: err.message || "Security policy invariant rejected the request",
          details: {},
        };
        setLastError(errorData);

        // Record simulated rejection audit record
        const rejectionRecord: SecurityAuditRecord = {
          timestamp: new Date().toISOString(),
          sandbox_id: "dry-run-evaluation",
          decision: "rejected",
          clamped_fields: [],
          violations: [errorData.details?.violation || "policy_violation"],
          requested_summary: preset.payload,
          effective_summary: { status: "REJECTED_BEFORE_DISPATCH" },
        };
        setAuditLog((prev) => [rejectionRecord, ...prev].slice(0, 10));
      },
    });
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* Evaluator Card */}
      <div
        style={{
          backgroundColor: "var(--color-surface)",
          border: "1px solid var(--color-border-subtle)",
          borderRadius: 8,
          padding: "20px 24px",
        }}
      >
        <div style={{ marginBottom: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
            <Shield size={18} color="var(--color-accent)" />
            <h3
              style={{
                margin: 0,
                fontSize: 16,
                fontWeight: 600,
                color: "var(--color-text-primary)",
              }}
            >
              Requested Policy vs. Effective Sandbox Policy
            </h3>
          </div>
          <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
            Select a simulation scenario to test how the authoritative backend SecurityPolicyEngine evaluates, clamps, or rejects requested parameters before any container is launched.
          </div>
        </div>

        {/* Preset Selectors */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
            gap: 10,
            marginBottom: 20,
          }}
        >
          {PRESETS.map((preset) => {
            const isSelected = selectedPreset.label === preset.label;
            return (
              <button
                key={preset.label}
                type="button"
                onClick={() => {
                  setSelectedPreset(preset);
                  handleRunEvaluation(preset);
                }}
                disabled={isPending}
                style={{
                  textAlign: "left",
                  padding: "12px 14px",
                  borderRadius: 6,
                  border: `1px solid ${
                    isSelected ? "var(--color-accent)" : "var(--color-border)"
                  }`,
                  backgroundColor: isSelected
                    ? "var(--color-surface-3)"
                    : "var(--color-surface-2)",
                  cursor: isPending ? "not-allowed" : "pointer",
                  transition: "all 0.15s ease",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    marginBottom: 6,
                  }}
                >
                  <span
                    style={{
                      fontSize: 13,
                      fontWeight: 600,
                      color: isSelected
                        ? "var(--color-text-primary)"
                        : "var(--color-text-secondary)",
                    }}
                  >
                    {preset.label}
                  </span>
                  <span
                    style={{
                      fontSize: 9,
                      fontWeight: 700,
                      padding: "1px 5px",
                      borderRadius: 3,
                      color: preset.badgeColor,
                      backgroundColor: preset.badgeBg,
                    }}
                  >
                    {preset.badge}
                  </span>
                </div>
                <div style={{ fontSize: 11, color: "var(--color-text-muted)", lineHeight: 1.3 }}>
                  {preset.description}
                </div>
              </button>
            );
          })}
        </div>

        {/* Action button */}
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
          <button
            type="button"
            onClick={() => handleRunEvaluation(selectedPreset)}
            disabled={isPending}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              padding: "9px 18px",
              borderRadius: 6,
              backgroundColor: "var(--color-accent)",
              border: "none",
              color: "#ffffff",
              fontSize: 13,
              fontWeight: 600,
              cursor: isPending ? "not-allowed" : "pointer",
              opacity: isPending ? 0.6 : 1,
            }}
          >
            <Play size={14} />
            {isPending ? "Evaluating against Backend..." : `Evaluate "${selectedPreset.label}"`}
          </button>
          <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
            Calls real backend <code style={{ color: "var(--color-text-secondary)" }}>POST /api/v1/security/evaluate</code>
          </span>
        </div>

        {/* Live Evaluation Result Display */}
        {lastEvaluation && (
          <div
            style={{
              backgroundColor: "var(--color-surface-2)",
              border: "1px solid var(--color-border)",
              borderRadius: 8,
              padding: "18px 20px",
              display: "flex",
              flexDirection: "column",
              gap: 16,
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                flexWrap: "wrap",
                gap: 8,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <CheckCircle2
                  size={18}
                  color={
                    lastEvaluation.status === "clamped"
                      ? "var(--color-warning)"
                      : "var(--color-success)"
                  }
                />
                <span style={{ fontSize: 14, fontWeight: 600, color: "var(--color-text-primary)" }}>
                  Backend Decision:
                </span>
                <span
                  style={{
                    fontSize: 12,
                    fontWeight: 700,
                    padding: "2px 8px",
                    borderRadius: 4,
                    color:
                      lastEvaluation.status === "clamped"
                        ? "var(--color-warning)"
                        : "var(--color-success)",
                    backgroundColor:
                      lastEvaluation.status === "clamped"
                        ? "var(--color-warning-subtle)"
                        : "var(--color-success-subtle)",
                    textTransform: "uppercase",
                  }}
                >
                  {lastEvaluation.status}
                </span>
              </div>

              {lastEvaluation.audit?.clamped_fields.length > 0 && (
                <span style={{ fontSize: 12, color: "var(--color-warning)" }}>
                  Clamped Fields: {lastEvaluation.audit.clamped_fields.join(", ")}
                </span>
              )}
            </div>

            {/* Side-by-side Requested vs Effective Comparison */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
                gap: 14,
              }}
            >
              {/* Requested Box */}
              <div
                style={{
                  backgroundColor: "var(--color-surface-3)",
                  borderRadius: 6,
                  padding: "14px",
                  border: "1px solid var(--color-border)",
                }}
              >
                <div
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    color: "var(--color-text-muted)",
                    textTransform: "uppercase",
                    letterSpacing: "0.04em",
                    marginBottom: 8,
                  }}
                >
                  Requested Parameters
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 12 }}>
                  {Object.entries(lastEvaluation.audit.requested_summary || {}).map(
                    ([key, val]) => (
                      <div
                        key={key}
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          fontFamily: "monospace",
                        }}
                      >
                        <span style={{ color: "var(--color-text-secondary)" }}>{key}:</span>
                        <span style={{ color: "var(--color-text-primary)", fontWeight: 600 }}>
                          {String(val)}
                        </span>
                      </div>
                    ),
                  )}
                </div>
              </div>

              {/* Effective Box */}
              <div
                style={{
                  backgroundColor: "var(--color-surface-3)",
                  borderRadius: 6,
                  padding: "14px",
                  border: "1px solid var(--color-border)",
                }}
              >
                <div
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    color: "var(--color-success)",
                    textTransform: "uppercase",
                    letterSpacing: "0.04em",
                    marginBottom: 8,
                  }}
                >
                  Effective Sandbox Policy
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 12 }}>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      fontFamily: "monospace",
                    }}
                  >
                    <span style={{ color: "var(--color-text-secondary)" }}>memory_limit:</span>
                    <span
                      style={{
                        color:
                          lastEvaluation.audit.clamped_fields.includes("memory_limit")
                            ? "var(--color-warning)"
                            : "var(--color-text-primary)",
                        fontWeight: 600,
                      }}
                    >
                      {lastEvaluation.effective.memory_limit}
                    </span>
                  </div>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      fontFamily: "monospace",
                    }}
                  >
                    <span style={{ color: "var(--color-text-secondary)" }}>timeout_seconds:</span>
                    <span
                      style={{
                        color:
                          lastEvaluation.audit.clamped_fields.includes("timeout_seconds")
                            ? "var(--color-warning)"
                            : "var(--color-text-primary)",
                        fontWeight: 600,
                      }}
                    >
                      {lastEvaluation.effective.timeout_seconds}s
                    </span>
                  </div>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      fontFamily: "monospace",
                    }}
                  >
                    <span style={{ color: "var(--color-text-secondary)" }}>pids_limit:</span>
                    <span style={{ color: "var(--color-text-primary)", fontWeight: 600 }}>
                      {lastEvaluation.effective.pids_limit}
                    </span>
                  </div>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      fontFamily: "monospace",
                    }}
                  >
                    <span style={{ color: "var(--color-text-secondary)" }}>network_mode:</span>
                    <span style={{ color: "var(--color-success)", fontWeight: 600 }}>
                      {lastEvaluation.effective.network_mode}
                    </span>
                  </div>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      fontFamily: "monospace",
                    }}
                  >
                    <span style={{ color: "var(--color-text-secondary)" }}>read_only:</span>
                    <span style={{ color: "var(--color-success)", fontWeight: 600 }}>
                      {String(lastEvaluation.effective.read_only)}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Invariant Rejection Alert Display */}
        {lastError && (
          <div
            style={{
              backgroundColor: "var(--color-danger-subtle)",
              border: "1px solid var(--color-danger)",
              borderRadius: 8,
              padding: "18px 20px",
              display: "flex",
              alignItems: "flex-start",
              gap: 12,
            }}
          >
            <ShieldAlert size={22} color="var(--color-danger)" style={{ marginTop: 2, flexShrink: 0 }} />
            <div>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  marginBottom: 4,
                }}
              >
                <span
                  style={{
                    fontSize: 14,
                    fontWeight: 700,
                    color: "var(--color-danger)",
                  }}
                >
                  HTTP 400 {lastError.error}
                </span>
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 700,
                    padding: "2px 6px",
                    borderRadius: 3,
                    backgroundColor: "var(--color-danger)",
                    color: "#ffffff",
                    letterSpacing: "0.04em",
                  }}
                >
                  REJECTED
                </span>
              </div>
              <div
                style={{
                  fontSize: 13,
                  color: "var(--color-text-primary)",
                  marginBottom: 6,
                  fontWeight: 500,
                }}
              >
                {lastError.message}
              </div>
              {lastError.details?.violation && (
                <div style={{ fontSize: 11, color: "var(--color-text-secondary)", fontFamily: "monospace" }}>
                  Violation code: <span style={{ color: "var(--color-danger)" }}>{lastError.details.violation}</span>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Security Decisions & Audit Stream */}
      <div
        style={{
          backgroundColor: "var(--color-surface)",
          border: "1px solid var(--color-border-subtle)",
          borderRadius: 8,
          padding: "20px 24px",
        }}
      >
        <div style={{ marginBottom: 16 }}>
          <h3
            style={{
              margin: "0 0 4px",
              fontSize: 16,
              fontWeight: 600,
              color: "var(--color-text-primary)",
            }}
          >
            Authoritative Security Decisions Audit Stream
          </h3>
          <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
            Real-time audit records produced by the backend SecurityPolicyEngine during this session
          </div>
        </div>

        {auditLog.length === 0 ? (
          <div
            style={{
              padding: "28px 16px",
              textAlign: "center",
              color: "var(--color-text-muted)",
              fontSize: 13,
              backgroundColor: "var(--color-surface-2)",
              borderRadius: 6,
            }}
          >
            No security decisions have been evaluated yet in this session. Click any simulation scenario above to evaluate against the backend.
          </div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table
              style={{
                width: "100%",
                borderCollapse: "collapse",
                fontSize: 12,
              }}
            >
              <thead>
                <tr
                  style={{
                    borderBottom: "1px solid var(--color-border)",
                    textAlign: "left",
                    color: "var(--color-text-muted)",
                  }}
                >
                  <th style={{ padding: "8px 12px", fontWeight: 600 }}>TIME</th>
                  <th style={{ padding: "8px 12px", fontWeight: 600 }}>DECISION</th>
                  <th style={{ padding: "8px 12px", fontWeight: 600 }}>REQUESTED SUMMARY</th>
                  <th style={{ padding: "8px 12px", fontWeight: 600 }}>EFFECTIVE SUMMARY</th>
                  <th style={{ padding: "8px 12px", fontWeight: 600 }}>CLAMPED / VIOLATIONS</th>
                </tr>
              </thead>
              <tbody>
                {auditLog.map((record, index) => {
                  const isRejected = record.decision === "rejected";
                  const isClamped = record.decision === "clamped";
                  const decisionColor = isRejected
                    ? "var(--color-danger)"
                    : isClamped
                    ? "var(--color-warning)"
                    : "var(--color-success)";
                  const decisionBg = isRejected
                    ? "var(--color-danger-subtle)"
                    : isClamped
                    ? "var(--color-warning-subtle)"
                    : "var(--color-success-subtle)";

                  return (
                    <tr
                      key={index}
                      style={{
                        borderBottom: "1px solid var(--color-border-subtle)",
                      }}
                    >
                      <td
                        style={{
                          padding: "10px 12px",
                          fontFamily: "monospace",
                          color: "var(--color-text-secondary)",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {new Date(record.timestamp).toLocaleTimeString()}
                      </td>
                      <td style={{ padding: "10px 12px" }}>
                        <span
                          style={{
                            fontSize: 10,
                            fontWeight: 700,
                            padding: "2px 7px",
                            borderRadius: 3,
                            color: decisionColor,
                            backgroundColor: decisionBg,
                            textTransform: "uppercase",
                          }}
                        >
                          {record.decision}
                        </span>
                      </td>
                      <td
                        style={{
                          padding: "10px 12px",
                          fontFamily: "monospace",
                          color: "var(--color-text-primary)",
                        }}
                      >
                        {JSON.stringify(record.requested_summary)}
                      </td>
                      <td
                        style={{
                          padding: "10px 12px",
                          fontFamily: "monospace",
                          color: "var(--color-text-secondary)",
                        }}
                      >
                        {JSON.stringify(record.effective_summary)}
                      </td>
                      <td
                        style={{
                          padding: "10px 12px",
                          color: isRejected
                            ? "var(--color-danger)"
                            : isClamped
                            ? "var(--color-warning)"
                            : "var(--color-text-muted)",
                        }}
                      >
                        {isRejected
                          ? record.violations.join(", ") || "rejected"
                          : record.clamped_fields.join(", ") || "none"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
