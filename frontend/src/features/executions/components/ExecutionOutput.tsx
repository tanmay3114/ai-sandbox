import { useState } from "react";
import {
  AlertCircle,
  AlertTriangle,
  Check,
  CheckCircle2,
  Clock,
  Copy,
  ExternalLink,
  Terminal,
  XCircle,
} from "lucide-react";
import { Link } from "react-router-dom";
import { formatDuration } from "@/lib/utils";
import type { JobExecution, JobStatus } from "../types";

interface ExecutionOutputProps {
  execution: JobExecution | null;
  isPending?: boolean;
  error?: any;
}

export function StatusBadge({ status }: { status: JobStatus | string }) {
  const configs: Record<string, { label: string; color: string; bg: string; icon: any }> = {
    completed: {
      label: "COMPLETED",
      color: "var(--color-success)",
      bg: "var(--color-success-subtle)",
      icon: CheckCircle2,
    },
    failed: {
      label: "FAILED",
      color: "var(--color-danger)",
      bg: "var(--color-danger-subtle)",
      icon: XCircle,
    },
    timed_out: {
      label: "TIMED OUT",
      color: "var(--color-warning)",
      bg: "var(--color-warning-subtle)",
      icon: Clock,
    },
    error: {
      label: "ERROR",
      color: "var(--color-danger)",
      bg: "var(--color-danger-subtle)",
      icon: AlertCircle,
    },
    running: {
      label: "RUNNING",
      color: "#818cf8",
      bg: "#312e8133",
      icon: Clock,
    },
    queued: {
      label: "QUEUED",
      color: "#60a5fa",
      bg: "#1e3a5f33",
      icon: Clock,
    },
  };

  const c = configs[status.toLowerCase()] ?? {
    label: String(status).toUpperCase(),
    color: "#9ca3af",
    bg: "#1f293733",
    icon: Terminal,
  };
  const Icon = c.icon;

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        padding: "3px 10px",
        borderRadius: 4,
        fontSize: 11,
        fontWeight: 700,
        color: c.color,
        backgroundColor: c.bg,
        letterSpacing: "0.03em",
      }}
    >
      <Icon size={12} />
      {c.label}
    </span>
  );
}

export function ExecutionOutput({
  execution,
  isPending,
  error,
}: ExecutionOutputProps) {
  const [copiedStdout, setCopiedStdout] = useState(false);
  const [copiedStderr, setCopiedStderr] = useState(false);

  const handleCopy = (text: string, isStdout: boolean) => {
    navigator.clipboard.writeText(text);
    if (isStdout) {
      setCopiedStdout(true);
      setTimeout(() => setCopiedStdout(false), 1500);
    } else {
      setCopiedStderr(true);
      setTimeout(() => setCopiedStderr(false), 1500);
    }
  };

  if (isPending) {
    return (
      <div
        style={{
          backgroundColor: "var(--color-surface)",
          border: "1px solid var(--color-border-subtle)",
          borderRadius: 8,
          padding: "32px 24px",
          textAlign: "center",
          color: "var(--color-text-muted)",
        }}
      >
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 10,
            fontSize: 14,
            fontWeight: 500,
            color: "var(--color-text-secondary)",
          }}
        >
          <div
            style={{
              width: 16,
              height: 16,
              borderRadius: "50%",
              border: "2px solid var(--color-accent)",
              borderTopColor: "transparent",
              animation: "spin 1s linear infinite",
            }}
          />
          Executing code inside ephemeral container...
        </div>
      </div>
    );
  }

  if (error) {
    const errorMsg =
      error?.response?.data?.message ||
      error?.response?.data?.detail ||
      error?.message ||
      "Execution request failed";

    return (
      <div
        style={{
          backgroundColor: "var(--color-surface)",
          border: "1px solid var(--color-danger)",
          borderRadius: 8,
          padding: "16px 20px",
          color: "var(--color-danger)",
          fontSize: 13,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
          <AlertCircle size={16} />
          <strong>Execution Error</strong>
        </div>
        <div>{typeof errorMsg === "string" ? errorMsg : "Request could not be processed"}</div>
      </div>
    );
  }

  if (!execution) {
    return null;
  }

  return (
    <div
      style={{
        backgroundColor: "var(--color-surface)",
        border: "1px solid var(--color-border-subtle)",
        borderRadius: 8,
        overflow: "hidden",
      }}
    >
      {/* Result Header Bar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "14px 20px",
          backgroundColor: "var(--color-surface-2)",
          borderBottom: "1px solid var(--color-border-subtle)",
          flexWrap: "wrap",
          gap: 12,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <span
            style={{
              fontSize: 13,
              fontWeight: 700,
              color: "var(--color-text-primary)",
            }}
          >
            Execution Result
          </span>
          <StatusBadge status={execution.status} />
          {execution.duration_ms !== null && (
            <span
              style={{
                fontFamily: "monospace",
                fontSize: 12,
                color: "var(--color-text-secondary)",
                padding: "2px 8px",
                borderRadius: 4,
                backgroundColor: "var(--color-surface)",
                border: "1px solid var(--color-border-subtle)",
              }}
            >
              Duration: {formatDuration(execution.duration_ms)}
            </span>
          )}
          {execution.exit_code !== null && (
            <span
              style={{
                fontFamily: "monospace",
                fontSize: 12,
                color:
                  execution.exit_code === 0
                    ? "var(--color-success)"
                    : "var(--color-danger)",
                padding: "2px 8px",
                borderRadius: 4,
                backgroundColor: "var(--color-surface)",
                border: "1px solid var(--color-border-subtle)",
              }}
            >
              Exit code: {execution.exit_code}
            </span>
          )}
        </div>

        {/* Link to dedicated execution detail page */}
        <div>
          <Link
            to={`/dashboard/executions/${execution.execution_id}?sandboxId=${execution.sandbox_id}`}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 5,
              fontSize: 12,
              color: "var(--color-accent)",
              textDecoration: "none",
              fontWeight: 500,
            }}
          >
            <span>Inspect Details</span>
            <ExternalLink size={12} />
          </Link>
        </div>
      </div>

      {/* Diagnostic Error Message banner */}
      {execution.error_message && (
        <div
          style={{
            margin: "14px 20px 0",
            padding: "10px 14px",
            backgroundColor: "var(--color-danger-subtle)",
            border: "1px solid var(--color-danger)",
            borderRadius: 6,
            color: "var(--color-danger)",
            fontSize: 12,
            display: "flex",
            alignItems: "flex-start",
            gap: 8,
          }}
        >
          <AlertTriangle size={15} style={{ marginTop: 1, flexShrink: 0 }} />
          <div>{execution.error_message}</div>
        </div>
      )}

      {/* Output Terminal Section */}
      <div style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: 16 }}>
        {/* STDOUT */}
        <div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: 6,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                  color: "var(--color-text-muted)",
                }}
              >
                STDOUT
              </span>
              {execution.stdout_truncated && (
                <span
                  style={{
                    fontSize: 10,
                    padding: "1px 5px",
                    borderRadius: 3,
                    backgroundColor: "var(--color-warning-subtle)",
                    color: "var(--color-warning)",
                  }}
                >
                  TRUNCATED
                </span>
              )}
            </div>
            {execution.stdout && (
              <button
                onClick={() => handleCopy(execution.stdout, true)}
                title="Copy standard output"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 4,
                  background: "none",
                  border: "none",
                  color: copiedStdout
                    ? "var(--color-success)"
                    : "var(--color-text-muted)",
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
              padding: "12px 14px",
              backgroundColor: "var(--color-background)",
              border: "1px solid var(--color-border)",
              borderRadius: 6,
              fontFamily: "monospace",
              fontSize: 12,
              lineHeight: 1.5,
              color: execution.stdout ? "var(--color-text-primary)" : "var(--color-text-muted)",
              maxHeight: 220,
              overflowY: "auto",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}
          >
            {execution.stdout ? execution.stdout : "(empty stdout)"}
          </pre>
        </div>

        {/* STDERR */}
        <div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: 6,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                  color: execution.stderr ? "var(--color-danger)" : "var(--color-text-muted)",
                }}
              >
                STDERR
              </span>
              {execution.stderr_truncated && (
                <span
                  style={{
                    fontSize: 10,
                    padding: "1px 5px",
                    borderRadius: 3,
                    backgroundColor: "var(--color-danger-subtle)",
                    color: "var(--color-danger)",
                  }}
                >
                  TRUNCATED
                </span>
              )}
            </div>
            {execution.stderr && (
              <button
                onClick={() => handleCopy(execution.stderr, false)}
                title="Copy standard error"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 4,
                  background: "none",
                  border: "none",
                  color: copiedStderr
                    ? "var(--color-success)"
                    : "var(--color-text-muted)",
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
              padding: "12px 14px",
              backgroundColor: "var(--color-background)",
              border: "1px solid",
              borderColor: execution.stderr ? "var(--color-danger)" : "var(--color-border)",
              borderRadius: 6,
              fontFamily: "monospace",
              fontSize: 12,
              lineHeight: 1.5,
              color: execution.stderr ? "var(--color-danger)" : "var(--color-text-muted)",
              maxHeight: 180,
              overflowY: "auto",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}
          >
            {execution.stderr ? execution.stderr : "No errors"}
          </pre>
        </div>
      </div>
    </div>
  );
}
