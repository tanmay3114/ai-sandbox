import { useState } from "react";
import {
  AlertCircle,
  PlaySquare,
  RefreshCw,
  Search,
} from "lucide-react";
import type { JobExecution } from "../types";
import { ExecutionRow } from "./ExecutionRow";

type StatusFilter = "ALL" | "COMPLETED" | "FAILED" | "TIMED_OUT";

interface ExecutionListProps {
  executions: JobExecution[] | undefined;
  isLoading: boolean;
  isError: boolean;
  onRefresh?: () => void;
  isRefreshing?: boolean;
  showSandboxId?: boolean;
  title?: string;
  subtitle?: string;
}

export function ExecutionList({
  executions,
  isLoading,
  isError,
  onRefresh,
  isRefreshing,
  showSandboxId = false,
  title = "Execution History",
  subtitle = "All code execution runs submitted to this persistent sandbox session.",
}: ExecutionListProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("ALL");
  const [expandedExecId, setExpandedExecId] = useState<string | null>(null);

  const filteredExecutions = (executions ?? []).filter((exec) => {
    // Search match
    const matchesSearch =
      !searchQuery.trim() ||
      exec.execution_id.toLowerCase().includes(searchQuery.trim().toLowerCase());

    // Status filter match
    let matchesStatus = true;
    if (statusFilter === "COMPLETED") {
      matchesStatus = exec.status === "completed";
    } else if (statusFilter === "FAILED") {
      matchesStatus = exec.status === "failed" || exec.status === "error";
    } else if (statusFilter === "TIMED_OUT") {
      matchesStatus = exec.status === "timed_out";
    }

    return matchesSearch && matchesStatus;
  });

  return (
    <div
      style={{
        backgroundColor: "var(--color-surface)",
        border: "1px solid var(--color-border-subtle)",
        borderRadius: 8,
        overflow: "hidden",
      }}
    >
      {/* Header & Controls */}
      <div
        style={{
          padding: "16px 20px",
          borderBottom: "1px solid var(--color-border-subtle)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 12,
        }}
      >
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <h3
              style={{
                margin: 0,
                fontSize: 14,
                fontWeight: 600,
                color: "var(--color-text-primary)",
              }}
            >
              {title}
            </h3>
            <span
              style={{
                fontSize: 11,
                color: "var(--color-text-muted)",
                padding: "2px 8px",
                borderRadius: 12,
                backgroundColor: "var(--color-surface-2)",
              }}
            >
              {executions?.length ?? 0} jobs
            </span>
          </div>
          {subtitle && (
            <p
              style={{
                margin: "2px 0 0",
                fontSize: 12,
                color: "var(--color-text-muted)",
              }}
            >
              {subtitle}
            </p>
          )}
        </div>

        {/* Filter and Refresh */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          {/* Search box */}
          <div
            style={{
              position: "relative",
              display: "flex",
              alignItems: "center",
            }}
          >
            <Search
              size={13}
              color="var(--color-text-muted)"
              style={{ position: "absolute", left: 10, pointerEvents: "none" }}
            />
            <input
              type="text"
              placeholder="Search by ID..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{
                padding: "6px 10px 6px 30px",
                fontSize: 12,
                borderRadius: 6,
                border: "1px solid var(--color-border)",
                backgroundColor: "var(--color-surface-2)",
                color: "var(--color-text-primary)",
                outline: "none",
                width: 160,
              }}
            />
          </div>

          {/* Status filter buttons */}
          <div
            style={{
              display: "flex",
              backgroundColor: "var(--color-surface-2)",
              borderRadius: 6,
              padding: 2,
              border: "1px solid var(--color-border-subtle)",
            }}
          >
            {(["ALL", "COMPLETED", "FAILED", "TIMED_OUT"] as StatusFilter[]).map(
              (st) => (
                <button
                  key={st}
                  onClick={() => setStatusFilter(st)}
                  style={{
                    border: "none",
                    background:
                      statusFilter === st ? "var(--color-surface)" : "transparent",
                    color:
                      statusFilter === st
                        ? "var(--color-text-primary)"
                        : "var(--color-text-muted)",
                    padding: "4px 8px",
                    fontSize: 11,
                    fontWeight: statusFilter === st ? 600 : 400,
                    borderRadius: 4,
                    cursor: "pointer",
                    boxShadow:
                      statusFilter === st
                        ? "0 1px 2px rgba(0,0,0,0.1)"
                        : "none",
                  }}
                >
                  {st}
                </button>
              ),
            )}
          </div>

          {/* Refresh button */}
          {onRefresh && (
            <button
              onClick={onRefresh}
              disabled={isRefreshing}
              title="Refresh execution history"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 5,
                padding: "6px 10px",
                borderRadius: 6,
                border: "1px solid var(--color-border)",
                backgroundColor: "var(--color-surface-2)",
                color: "var(--color-text-secondary)",
                fontSize: 12,
                cursor: isRefreshing ? "not-allowed" : "pointer",
              }}
            >
              <RefreshCw
                size={12}
                style={{
                  animation: isRefreshing ? "spin 1s linear infinite" : "none",
                }}
              />
              Refresh
            </button>
          )}
        </div>
      </div>

      {/* Loading state */}
      {isLoading && (
        <div
          style={{
            padding: "36px 20px",
            textAlign: "center",
            color: "var(--color-text-muted)",
            fontSize: 12,
          }}
        >
          Loading execution records from backend...
        </div>
      )}

      {/* Error state */}
      {isError && (
        <div
          style={{
            padding: "20px",
            color: "var(--color-danger)",
            fontSize: 12,
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <AlertCircle size={15} />
          Unable to load execution history. Please check backend connection.
        </div>
      )}

      {/* Empty state */}
      {!isLoading && !isError && filteredExecutions.length === 0 && (
        <div
          style={{
            padding: "48px 20px",
            textAlign: "center",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 8,
          }}
        >
          <PlaySquare size={32} color="var(--color-text-muted)" />
          <div
            style={{
              fontSize: 14,
              fontWeight: 500,
              color: "var(--color-text-secondary)",
            }}
          >
            {searchQuery || statusFilter !== "ALL"
              ? "No executions match the selected filters"
              : "No executions yet"}
          </div>
          <div
            style={{
              fontSize: 12,
              color: "var(--color-text-muted)",
              maxWidth: 360,
            }}
          >
            {searchQuery || statusFilter !== "ALL"
              ? "Try adjusting your search criteria or resetting filters."
              : "Enter Python code in the editor above and click Run Code to execute inside this ephemeral sandbox."}
          </div>
        </div>
      )}

      {/* Executions Table */}
      {!isLoading && !isError && filteredExecutions.length > 0 && (
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
                {[
                  "Execution ID",
                  ...(showSandboxId ? ["Sandbox"] : []),
                  "Status",
                  "Duration",
                  "Exit Code",
                  "Submitted",
                  "Actions",
                ].map((header) => (
                  <th
                    key={header}
                    style={{
                      textAlign: header === "Actions" ? "right" : "left",
                      padding: "10px 16px",
                      color: "var(--color-text-muted)",
                      fontSize: 11,
                      fontWeight: 500,
                      textTransform: "uppercase",
                      letterSpacing: "0.04em",
                      borderBottom: "1px solid var(--color-border-subtle)",
                      backgroundColor: "var(--color-surface-2)",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filteredExecutions.map((exec) => (
                <ExecutionRow
                  key={exec.execution_id}
                  execution={exec}
                  showSandboxId={showSandboxId}
                  isExpanded={expandedExecId === exec.execution_id}
                  onToggleExpand={() =>
                    setExpandedExecId(
                      expandedExecId === exec.execution_id
                        ? null
                        : exec.execution_id,
                    )
                  }
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
