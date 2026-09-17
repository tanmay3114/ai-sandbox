import { useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronUp,
  Copy,
  ExternalLink,
} from "lucide-react";
import { Link } from "react-router-dom";
import { formatDate, formatDuration } from "@/lib/utils";
import type { JobExecution } from "../types";
import { StatusBadge } from "./ExecutionOutput";

interface ExecutionRowProps {
  execution: JobExecution;
  isExpanded?: boolean;
  onToggleExpand?: () => void;
  showSandboxId?: boolean;
}

export function ExecutionRow({
  execution,
  isExpanded = false,
  onToggleExpand,
  showSandboxId = false,
}: ExecutionRowProps) {
  const [copiedId, setCopiedId] = useState(false);

  const handleCopyId = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(execution.execution_id);
    setCopiedId(true);
    setTimeout(() => setCopiedId(false), 1500);
  };

  const colSpan = showSandboxId ? 7 : 6;

  return (
    <>
      <tr
        onClick={onToggleExpand}
        style={{
          borderBottom: "1px solid var(--color-border-subtle)",
          cursor: onToggleExpand ? "pointer" : "default",
          backgroundColor: isExpanded
            ? "var(--color-surface-2)"
            : "transparent",
          transition: "background-color 0.1s ease",
        }}
      >
        {/* Execution ID */}
        <td
          style={{
            padding: "12px 16px",
            fontFamily: "monospace",
            fontSize: 11,
            whiteSpace: "nowrap",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ color: "var(--color-accent)" }}>
              {execution.execution_id.slice(0, 8)}...
              {execution.execution_id.slice(-4)}
            </span>
            <button
              onClick={handleCopyId}
              title="Copy Execution ID"
              style={{
                background: "none",
                border: "none",
                color: copiedId
                  ? "var(--color-success)"
                  : "var(--color-text-muted)",
                cursor: "pointer",
                padding: 2,
                borderRadius: 3,
                display: "inline-flex",
              }}
            >
              {copiedId ? <Check size={12} /> : <Copy size={12} />}
            </button>
          </div>
        </td>

        {/* Sandbox ID (Optional) */}
        {showSandboxId && (
          <td
            style={{
              padding: "12px 16px",
              fontFamily: "monospace",
              fontSize: 11,
              color: "var(--color-text-secondary)",
              whiteSpace: "nowrap",
            }}
          >
            <Link
              to={`/dashboard/sandboxes/${execution.sandbox_id}`}
              onClick={(e) => e.stopPropagation()}
              style={{ color: "inherit", textDecoration: "none" }}
            >
              {execution.sandbox_id.slice(0, 8)}...
            </Link>
          </td>
        )}

        {/* Status */}
        <td style={{ padding: "12px 16px", whiteSpace: "nowrap" }}>
          <StatusBadge status={execution.status} />
        </td>

        {/* Duration */}
        <td
          style={{
            padding: "12px 16px",
            fontFamily: "monospace",
            fontSize: 12,
            color: "var(--color-text-secondary)",
            whiteSpace: "nowrap",
          }}
        >
          {formatDuration(execution.duration_ms)}
        </td>

        {/* Exit Code */}
        <td
          style={{
            padding: "12px 16px",
            fontFamily: "monospace",
            fontSize: 12,
            color:
              execution.exit_code === 0
                ? "var(--color-success)"
                : execution.exit_code !== null
                ? "var(--color-danger)"
                : "var(--color-text-muted)",
            whiteSpace: "nowrap",
          }}
        >
          {execution.exit_code !== null ? execution.exit_code : "—"}
        </td>

        {/* Submitted Time */}
        <td
          style={{
            padding: "12px 16px",
            color: "var(--color-text-muted)",
            fontSize: 11,
            whiteSpace: "nowrap",
          }}
        >
          {formatDate(execution.submitted_at)}
        </td>

        {/* Actions */}
        <td
          style={{
            padding: "12px 16px",
            textAlign: "right",
            whiteSpace: "nowrap",
          }}
        >
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 10,
              justifyContent: "flex-end",
            }}
          >
            <Link
              to={`/dashboard/executions/${execution.execution_id}?sandboxId=${execution.sandbox_id}`}
              onClick={(e) => e.stopPropagation()}
              title="Open full execution details"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
                color: "var(--color-accent)",
                fontSize: 11,
                fontWeight: 600,
                textDecoration: "none",
              }}
            >
              <span>Inspect</span>
              <ExternalLink size={11} />
            </Link>

            {onToggleExpand && (
              <span style={{ color: "var(--color-text-muted)" }}>
                {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
              </span>
            )}
          </div>
        </td>
      </tr>

      {/* Expanded Inline Preview */}
      {isExpanded && (
        <tr
          style={{
            backgroundColor: "var(--color-surface-2)",
            borderBottom: "1px solid var(--color-border-subtle)",
          }}
        >
          <td colSpan={colSpan} style={{ padding: "14px 20px" }}>
            {execution.error_message && (
              <div
                style={{
                  padding: "8px 12px",
                  borderRadius: 4,
                  backgroundColor: "var(--color-danger-subtle)",
                  color: "var(--color-danger)",
                  fontSize: 12,
                  marginBottom: 10,
                }}
              >
                {execution.error_message}
              </div>
            )}

            <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 10 }}>
              {/* Stdout preview */}
              <div>
                <div
                  style={{
                    fontSize: 10,
                    fontWeight: 700,
                    color: "var(--color-text-muted)",
                    marginBottom: 4,
                    textTransform: "uppercase",
                  }}
                >
                  Stdout {execution.stdout_truncated && "(truncated)"}
                </div>
                <pre
                  style={{
                    margin: 0,
                    padding: "8px 12px",
                    backgroundColor: "var(--color-background)",
                    border: "1px solid var(--color-border)",
                    borderRadius: 4,
                    fontFamily: "monospace",
                    fontSize: 11,
                    color: execution.stdout
                      ? "var(--color-text-primary)"
                      : "var(--color-text-muted)",
                    maxHeight: 140,
                    overflowY: "auto",
                    whiteSpace: "pre-wrap",
                  }}
                >
                  {execution.stdout || "(empty stdout)"}
                </pre>
              </div>

              {/* Stderr preview if present */}
              {execution.stderr && (
                <div>
                  <div
                    style={{
                      fontSize: 10,
                      fontWeight: 700,
                      color: "var(--color-danger)",
                      marginBottom: 4,
                      textTransform: "uppercase",
                    }}
                  >
                    Stderr {execution.stderr_truncated && "(truncated)"}
                  </div>
                  <pre
                    style={{
                      margin: 0,
                      padding: "8px 12px",
                      backgroundColor: "var(--color-background)",
                      border: "1px solid var(--color-danger)",
                      borderRadius: 4,
                      fontFamily: "monospace",
                      fontSize: 11,
                      color: "var(--color-danger)",
                      maxHeight: 140,
                      overflowY: "auto",
                      whiteSpace: "pre-wrap",
                    }}
                  >
                    {execution.stderr}
                  </pre>
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
