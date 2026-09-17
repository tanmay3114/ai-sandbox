import { useState } from "react";
import {
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  Check,
  Clock,
  Container,
  Copy,
  ExternalLink,
  Info,
  Layers,
  Terminal,
} from "lucide-react";
import { Link } from "react-router-dom";
import { formatDate, formatDuration } from "@/lib/utils";
import type { JobExecution } from "../types";
import { StatusBadge } from "./ExecutionOutput";

interface ExecutionDetailProps {
  execution: JobExecution;
  onRefresh?: () => void;
  isRefreshing?: boolean;
}

export function ExecutionDetail({
  execution,
  onRefresh,
  isRefreshing,
}: ExecutionDetailProps) {
  const [copiedExecutionId, setCopiedExecutionId] = useState(false);
  const [copiedSandboxId, setCopiedSandboxId] = useState(false);
  const [copiedStdout, setCopiedStdout] = useState(false);
  const [copiedStderr, setCopiedStderr] = useState(false);

  const handleCopy = (
    text: string,
    type: "execution_id" | "sandbox_id" | "stdout" | "stderr",
  ) => {
    navigator.clipboard.writeText(text);
    if (type === "execution_id") {
      setCopiedExecutionId(true);
      setTimeout(() => setCopiedExecutionId(false), 1500);
    } else if (type === "sandbox_id") {
      setCopiedSandboxId(true);
      setTimeout(() => setCopiedSandboxId(false), 1500);
    } else if (type === "stdout") {
      setCopiedStdout(true);
      setTimeout(() => setCopiedStdout(false), 1500);
    } else {
      setCopiedStderr(true);
      setTimeout(() => setCopiedStderr(false), 1500);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* Header Banner */}
      <div
        style={{
          backgroundColor: "var(--color-surface)",
          border: "1px solid var(--color-border-subtle)",
          borderRadius: 8,
          padding: "20px 24px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 16,
        }}
      >
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
            <span
              style={{
                fontFamily: "monospace",
                fontSize: 18,
                fontWeight: 700,
                color: "var(--color-text-primary)",
              }}
            >
              {execution.execution_id}
            </span>
            <button
              onClick={() => handleCopy(execution.execution_id, "execution_id")}
              title="Copy Execution ID"
              style={{
                background: "none",
                border: "none",
                color: copiedExecutionId ? "var(--color-success)" : "var(--color-text-muted)",
                cursor: "pointer",
                padding: 4,
                borderRadius: 4,
                display: "flex",
              }}
            >
              {copiedExecutionId ? <Check size={14} /> : <Copy size={14} />}
            </button>
            <StatusBadge status={execution.status} />
          </div>

          <div
            style={{
              fontSize: 12,
              color: "var(--color-text-muted)",
              display: "flex",
              alignItems: "center",
              gap: 8,
              flexWrap: "wrap",
            }}
          >
            <span>
              Submitted on {formatDate(execution.submitted_at)}
            </span>
          </div>
        </div>

        {onRefresh && (
          <button
            onClick={onRefresh}
            disabled={isRefreshing}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "7px 12px",
              borderRadius: 6,
              border: "1px solid var(--color-border)",
              backgroundColor: "var(--color-surface-2)",
              color: "var(--color-text-secondary)",
              fontSize: 12,
              cursor: isRefreshing ? "not-allowed" : "pointer",
            }}
          >
            <Clock
              size={13}
              style={{
                animation: isRefreshing ? "spin 1s linear infinite" : "none",
              }}
            />
            Refresh Details
          </button>
        )}
      </div>

      {/* Execution Hierarchy & Lineage: Execution ID → Sandbox ID */}
      <div
        style={{
          backgroundColor: "var(--color-surface)",
          border: "1px solid var(--color-border-subtle)",
          borderRadius: 8,
          padding: "16px 20px",
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        <div
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: "var(--color-text-muted)",
            textTransform: "uppercase",
            letterSpacing: "0.05em",
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <Layers size={13} color="var(--color-accent)" />
          Execution Lineage
        </div>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            flexWrap: "wrap",
          }}
        >
          {/* Execution Node */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              backgroundColor: "var(--color-surface-2)",
              border: "1px solid var(--color-border)",
              borderRadius: 6,
              padding: "10px 14px",
              minWidth: 260,
              flex: "1 1 auto",
            }}
          >
            <Terminal size={16} color="var(--color-accent)" style={{ flexShrink: 0 }} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                style={{
                  fontSize: 10,
                  fontWeight: 600,
                  color: "var(--color-text-muted)",
                  textTransform: "uppercase",
                  letterSpacing: "0.04em",
                  marginBottom: 2,
                }}
              >
                Execution ID
              </div>
              <div
                style={{
                  fontFamily: "monospace",
                  fontSize: 13,
                  fontWeight: 600,
                  color: "var(--color-text-primary)",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
                title={execution.execution_id}
              >
                {execution.execution_id}
              </div>
            </div>
            <button
              onClick={() => handleCopy(execution.execution_id, "execution_id")}
              title="Copy Execution ID"
              style={{
                background: "none",
                border: "none",
                color: copiedExecutionId ? "var(--color-success)" : "var(--color-text-muted)",
                cursor: "pointer",
                padding: 4,
                borderRadius: 4,
                display: "flex",
                flexShrink: 0,
              }}
            >
              {copiedExecutionId ? <Check size={14} /> : <Copy size={14} />}
            </button>
          </div>

          {/* Directed Relationship Indicator: Execution ID → Sandbox ID */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "0 4px",
              flexShrink: 0,
            }}
          >
            <ArrowRight size={20} color="var(--color-accent)" />
            <span
              style={{
                fontSize: 11,
                fontWeight: 600,
                color: "var(--color-text-secondary)",
                textTransform: "uppercase",
                letterSpacing: "0.04em",
              }}
            >
              scoped to
            </span>
          </div>

          {/* Parent Sandbox Node */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              backgroundColor: "var(--color-surface-2)",
              border: "1px solid var(--color-border)",
              borderRadius: 6,
              padding: "10px 14px",
              minWidth: 260,
              flex: "1 1 auto",
            }}
          >
            <Container size={16} color="var(--color-accent)" style={{ flexShrink: 0 }} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                style={{
                  fontSize: 10,
                  fontWeight: 600,
                  color: "var(--color-text-muted)",
                  textTransform: "uppercase",
                  letterSpacing: "0.04em",
                  marginBottom: 2,
                }}
              >
                Sandbox ID
              </div>
              <Link
                to={`/dashboard/sandboxes/${execution.sandbox_id}`}
                title="Navigate to Parent Sandbox"
                style={{
                  fontFamily: "monospace",
                  fontSize: 13,
                  fontWeight: 600,
                  color: "var(--color-accent)",
                  textDecoration: "none",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 4,
                  maxWidth: "100%",
                }}
              >
                <span
                  style={{
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {execution.sandbox_id}
                </span>
                <ExternalLink size={12} style={{ flexShrink: 0 }} />
              </Link>
            </div>
            <button
              onClick={() => handleCopy(execution.sandbox_id, "sandbox_id")}
              title="Copy Sandbox ID"
              style={{
                background: "none",
                border: "none",
                color: copiedSandboxId ? "var(--color-success)" : "var(--color-text-muted)",
                cursor: "pointer",
                padding: 4,
                borderRadius: 4,
                display: "flex",
                flexShrink: 0,
              }}
            >
              {copiedSandboxId ? <Check size={14} /> : <Copy size={14} />}
            </button>
          </div>
        </div>
      </div>

      {/* Ephemeral Container Informational Indicator */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          gap: 12,
          backgroundColor: "var(--color-info-subtle)",
          border: "1px solid var(--color-border)",
          borderRadius: 8,
          padding: "12px 16px",
        }}
      >
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            width: 26,
            height: 26,
            borderRadius: 6,
            backgroundColor: "var(--color-surface-2)",
            color: "var(--color-info)",
            flexShrink: 0,
            marginTop: 1,
          }}
        >
          <Info size={15} />
        </div>
        <div style={{ fontSize: 12, lineHeight: 1.5, color: "var(--color-text-secondary)" }}>
          <span
            style={{
              fontWeight: 600,
              color: "var(--color-text-primary)",
              marginRight: 6,
            }}
          >
            Ephemeral Container:
          </span>
          Executions use ephemeral containers which are destroyed after result collection. Each execution runs inside a single-use, isolated Docker environment; no persistent container ID is retained.
        </div>
      </div>

      {/* Metadata Cards Grid */}
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
            padding: "16px 18px",
          }}
        >
          <div
            style={{
              fontSize: 11,
              color: "var(--color-text-muted)",
              marginBottom: 4,
              textTransform: "uppercase",
              letterSpacing: "0.04em",
            }}
          >
            Duration
          </div>
          <div
            style={{
              fontSize: 18,
              fontWeight: 700,
              fontFamily: "monospace",
              color: "var(--color-text-primary)",
            }}
          >
            {formatDuration(execution.duration_ms)}
          </div>
          <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 2 }}>
            Total execution elapsed
          </div>
        </div>

        <div
          style={{
            backgroundColor: "var(--color-surface)",
            border: "1px solid var(--color-border-subtle)",
            borderRadius: 8,
            padding: "16px 18px",
          }}
        >
          <div
            style={{
              fontSize: 11,
              color: "var(--color-text-muted)",
              marginBottom: 4,
              textTransform: "uppercase",
              letterSpacing: "0.04em",
            }}
          >
            Process Exit Code
          </div>
          <div
            style={{
              fontSize: 18,
              fontWeight: 700,
              fontFamily: "monospace",
              color:
                execution.exit_code === 0
                  ? "var(--color-success)"
                  : execution.exit_code !== null
                  ? "var(--color-danger)"
                  : "var(--color-text-muted)",
            }}
          >
            {execution.exit_code !== null ? execution.exit_code : "—"}
          </div>
          <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 2 }}>
            {execution.exit_code === 0
              ? "Successful termination"
              : execution.exit_code !== null
              ? "Non-zero exit"
              : "No exit code returned"}
          </div>
        </div>

        <div
          style={{
            backgroundColor: "var(--color-surface)",
            border: "1px solid var(--color-border-subtle)",
            borderRadius: 8,
            padding: "16px 18px",
          }}
        >
          <div
            style={{
              fontSize: 11,
              color: "var(--color-text-muted)",
              marginBottom: 4,
              textTransform: "uppercase",
              letterSpacing: "0.04em",
            }}
          >
            Started At
          </div>
          <div style={{ fontSize: 13, fontWeight: 600, color: "var(--color-text-primary)" }}>
            {execution.started_at ? formatDate(execution.started_at) : "—"}
          </div>
          <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 2 }}>
            Container dispatch time
          </div>
        </div>

        <div
          style={{
            backgroundColor: "var(--color-surface)",
            border: "1px solid var(--color-border-subtle)",
            borderRadius: 8,
            padding: "16px 18px",
          }}
        >
          <div
            style={{
              fontSize: 11,
              color: "var(--color-text-muted)",
              marginBottom: 4,
              textTransform: "uppercase",
              letterSpacing: "0.04em",
            }}
          >
            Completed At
          </div>
          <div style={{ fontSize: 13, fontWeight: 600, color: "var(--color-text-primary)" }}>
            {execution.completed_at ? formatDate(execution.completed_at) : "—"}
          </div>
          <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 2 }}>
            Result collected & destroyed
          </div>
        </div>
      </div>

      {/* Diagnostic Error Message */}
      {execution.error_message && (
        <div
          style={{
            backgroundColor: "var(--color-danger-subtle)",
            border: "1px solid var(--color-danger)",
            borderRadius: 8,
            padding: "14px 18px",
            color: "var(--color-danger)",
            fontSize: 13,
            display: "flex",
            alignItems: "flex-start",
            gap: 10,
          }}
        >
          <AlertTriangle size={18} style={{ marginTop: 1, flexShrink: 0 }} />
          <div>
            <div style={{ fontWeight: 600, marginBottom: 2 }}>Execution Diagnostics</div>
            <div>{execution.error_message}</div>
          </div>
        </div>
      )}

      {/* STDOUT Terminal Block */}
      <div
        style={{
          backgroundColor: "var(--color-surface)",
          border: "1px solid var(--color-border-subtle)",
          borderRadius: 8,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "12px 18px",
            backgroundColor: "var(--color-surface-2)",
            borderBottom: "1px solid var(--color-border-subtle)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Terminal size={15} color="var(--color-accent)" />
            <span style={{ fontSize: 12, fontWeight: 600, color: "var(--color-text-primary)" }}>
              Standard Output (STDOUT)
            </span>
            {execution.stdout_truncated && (
              <span
                style={{
                  fontSize: 10,
                  padding: "1px 6px",
                  borderRadius: 3,
                  backgroundColor: "var(--color-warning-subtle)",
                  color: "var(--color-warning)",
                  fontWeight: 600,
                }}
              >
                TRUNCATED
              </span>
            )}
          </div>

          {execution.stdout && (
            <button
              onClick={() => handleCopy(execution.stdout, "stdout")}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
                background: "none",
                border: "none",
                color: copiedStdout ? "var(--color-success)" : "var(--color-text-muted)",
                fontSize: 11,
                cursor: "pointer",
                padding: 2,
              }}
            >
              {copiedStdout ? <Check size={12} /> : <Copy size={12} />}
              <span>{copiedStdout ? "Copied" : "Copy"}</span>
            </button>
          )}
        </div>
        <pre
          style={{
            margin: 0,
            padding: "14px 18px",
            backgroundColor: "var(--color-background)",
            fontFamily: "monospace",
            fontSize: 12,
            lineHeight: 1.5,
            color: execution.stdout ? "var(--color-text-primary)" : "var(--color-text-muted)",
            maxHeight: 320,
            overflowY: "auto",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {execution.stdout ? execution.stdout : "(no standard output was captured)"}
        </pre>
      </div>

      {/* STDERR Terminal Block */}
      <div
        style={{
          backgroundColor: "var(--color-surface)",
          border: "1px solid",
          borderColor: execution.stderr ? "var(--color-danger)" : "var(--color-border-subtle)",
          borderRadius: 8,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "12px 18px",
            backgroundColor: "var(--color-surface-2)",
            borderBottom: "1px solid var(--color-border-subtle)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <AlertCircle
              size={15}
              color={execution.stderr ? "var(--color-danger)" : "var(--color-text-muted)"}
            />
            <span
              style={{
                fontSize: 12,
                fontWeight: 600,
                color: execution.stderr ? "var(--color-danger)" : "var(--color-text-primary)",
              }}
            >
              Standard Error (STDERR)
            </span>
            {execution.stderr_truncated && (
              <span
                style={{
                  fontSize: 10,
                  padding: "1px 6px",
                  borderRadius: 3,
                  backgroundColor: "var(--color-danger-subtle)",
                  color: "var(--color-danger)",
                  fontWeight: 600,
                }}
              >
                TRUNCATED
              </span>
            )}
          </div>

          {execution.stderr && (
            <button
              onClick={() => handleCopy(execution.stderr, "stderr")}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
                background: "none",
                border: "none",
                color: copiedStderr ? "var(--color-success)" : "var(--color-text-muted)",
                fontSize: 11,
                cursor: "pointer",
                padding: 2,
              }}
            >
              {copiedStderr ? <Check size={12} /> : <Copy size={12} />}
              <span>{copiedStderr ? "Copied" : "Copy"}</span>
            </button>
          )}
        </div>
        <pre
          style={{
            margin: 0,
            padding: "14px 18px",
            backgroundColor: "var(--color-background)",
            fontFamily: "monospace",
            fontSize: 12,
            lineHeight: 1.5,
            color: execution.stderr ? "var(--color-danger)" : "var(--color-text-muted)",
            maxHeight: 240,
            overflowY: "auto",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {execution.stderr ? execution.stderr : "No errors"}
        </pre>
      </div>
    </div>
  );
}
