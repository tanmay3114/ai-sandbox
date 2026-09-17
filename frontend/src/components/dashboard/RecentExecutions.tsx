import type { ExecutionStatus } from "@/types";
import { formatDate, formatDuration } from "@/lib/utils";

interface DemoExecution {
  id: string;
  sandbox_id: string;
  status: ExecutionStatus;
  submitted_at: string;
  duration_ms: number | null;
  runtime: string;
}

function StatusBadge({ status }: { status: ExecutionStatus }) {
  const config: Record<ExecutionStatus, { label: string; color: string; bg: string }> =
    {
      completed: {
        label: "Completed",
        color: "var(--color-success)",
        bg: "var(--color-success-subtle)",
      },
      failed: {
        label: "Failed",
        color: "var(--color-danger)",
        bg: "var(--color-danger-subtle)",
      },
      timed_out: {
        label: "Timed Out",
        color: "var(--color-warning)",
        bg: "var(--color-warning-subtle)",
      },
      error: {
        label: "Error",
        color: "var(--color-danger)",
        bg: "var(--color-danger-subtle)",
      },
    };

  const c = config[status];
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "2px 8px",
        borderRadius: 4,
        fontSize: 11,
        fontWeight: 500,
        color: c.color,
        backgroundColor: c.bg,
        letterSpacing: "0.01em",
      }}
    >
      {c.label}
    </span>
  );
}

// Demo executions — clearly marked as demo data
const DEMO_EXECUTIONS: DemoExecution[] = [
  {
    id: "a1b2c3d4",
    sandbox_id: "sb-001",
    status: "completed",
    submitted_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
    duration_ms: 1243,
    runtime: "python",
  },
  {
    id: "e5f6g7h8",
    sandbox_id: "sb-002",
    status: "completed",
    submitted_at: new Date(Date.now() - 15 * 60 * 1000).toISOString(),
    duration_ms: 872,
    runtime: "python",
  },
  {
    id: "i9j0k1l2",
    sandbox_id: "sb-003",
    status: "failed",
    submitted_at: new Date(Date.now() - 32 * 60 * 1000).toISOString(),
    duration_ms: 5012,
    runtime: "python",
  },
  {
    id: "m3n4o5p6",
    sandbox_id: "sb-001",
    status: "timed_out",
    submitted_at: new Date(Date.now() - 68 * 60 * 1000).toISOString(),
    duration_ms: 5000,
    runtime: "python",
  },
  {
    id: "q7r8s9t0",
    sandbox_id: "sb-004",
    status: "completed",
    submitted_at: new Date(Date.now() - 120 * 60 * 1000).toISOString(),
    duration_ms: 330,
    runtime: "python",
  },
];

export function RecentExecutions() {
  return (
    <div
      style={{
        backgroundColor: "var(--color-surface)",
        border: "1px solid var(--color-border-subtle)",
        borderRadius: 8,
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "14px 20px",
          borderBottom: "1px solid var(--color-border-subtle)",
        }}
      >
        <span
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: "var(--color-text-primary)",
          }}
        >
          Recent Executions
        </span>
        <span
          style={{
            fontSize: 10,
            color: "var(--color-text-muted)",
            padding: "2px 6px",
            borderRadius: 4,
            border: "1px solid var(--color-border)",
            letterSpacing: "0.04em",
          }}
        >
          DEMO
        </span>
      </div>

      {/* Table */}
      <div style={{ overflowX: "auto" }}>
        <table
          style={{
            width: "100%",
            borderCollapse: "collapse",
            fontSize: 12,
          }}
        >
          <thead>
            <tr>
              {["Execution ID", "Sandbox", "Runtime", "Status", "Duration", "Submitted"].map(
                (col) => (
                  <th
                    key={col}
                    style={{
                      textAlign: "left",
                      padding: "8px 16px",
                      color: "var(--color-text-muted)",
                      fontWeight: 500,
                      fontSize: 11,
                      letterSpacing: "0.04em",
                      textTransform: "uppercase",
                      borderBottom: "1px solid var(--color-border-subtle)",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {col}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {DEMO_EXECUTIONS.map((exec, i) => (
              <tr
                key={exec.id}
                style={{
                  borderBottom:
                    i < DEMO_EXECUTIONS.length - 1
                      ? "1px solid var(--color-border-subtle)"
                      : undefined,
                }}
              >
                <td
                  style={{
                    padding: "10px 16px",
                    color: "var(--color-accent)",
                    fontFamily: "monospace",
                    fontSize: 11,
                  }}
                >
                  {exec.id}
                </td>
                <td
                  style={{
                    padding: "10px 16px",
                    color: "var(--color-text-secondary)",
                    fontFamily: "monospace",
                    fontSize: 11,
                  }}
                >
                  {exec.sandbox_id}
                </td>
                <td
                  style={{
                    padding: "10px 16px",
                    color: "var(--color-text-secondary)",
                  }}
                >
                  {exec.runtime}
                </td>
                <td style={{ padding: "10px 16px" }}>
                  <StatusBadge status={exec.status} />
                </td>
                <td
                  style={{
                    padding: "10px 16px",
                    color: "var(--color-text-secondary)",
                    fontFamily: "monospace",
                    fontSize: 11,
                  }}
                >
                  {formatDuration(exec.duration_ms)}
                </td>
                <td
                  style={{
                    padding: "10px 16px",
                    color: "var(--color-text-muted)",
                    whiteSpace: "nowrap",
                  }}
                >
                  {formatDate(exec.submitted_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Footer note */}
      <div
        style={{
          padding: "10px 20px",
          fontSize: 11,
          color: "var(--color-text-muted)",
          borderTop: "1px solid var(--color-border-subtle)",
        }}
      >
        Demo data · Connect backend for live execution history
      </div>
    </div>
  );
}
