import { useState } from "react";
import {
  History,
  PlaySquare,
  RefreshCw,
  Search,
  Bot,
} from "lucide-react";
import { useSandboxes } from "@/features/sandboxes/hooks/useSandboxes";
import { useSandboxExecutions } from "@/features/executions/hooks/useExecutions";
import { useSandboxAgentTasks } from "@/lib/api/queries";
import type { SandboxDetail } from "@/features/sandboxes/types";
import type { JobExecution } from "@/features/executions/types";
import type { AgentTaskResponse } from "@/types";

export function HistoryPage() {
  const [activeTab, setActiveTab] = useState<"all" | "executions" | "agent">("all");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [selectedSandboxId, setSelectedSandboxId] = useState<string>("");
  const [expandedItem, setExpandedItem] = useState<string | null>(null);

  // Fetch all sandboxes
  const {
    data: sandboxes,
    isLoading: isSandboxesLoading,
    refetch: refetchSandboxes,
  } = useSandboxes();

  // Active sandbox ID fallback
  const effectiveSandboxId =
    selectedSandboxId ||
    (sandboxes && sandboxes.length > 0 ? sandboxes[0].sandbox_id : "");

  // Fetch sandbox executions
  const {
    data: executions,
    isLoading: isExecsLoading,
    refetch: refetchExecs,
    isFetching: isExecsFetching,
  } = useSandboxExecutions(effectiveSandboxId || undefined);

  // Fetch sandbox agent tasks
  const {
    data: agentTasksResponse,
    isLoading: isAgentLoading,
    refetch: refetchAgentTasks,
    isFetching: isAgentFetching,
  } = useSandboxAgentTasks(effectiveSandboxId || "");

  const handleRefresh = () => {
    refetchSandboxes();
    refetchExecs();
    refetchAgentTasks();
  };

  const isRefreshing = isExecsFetching || isAgentFetching;

  // Normalized unified history record
  interface HistoryItem {
    id: string;
    type: "execution" | "agent_task";
    status: string;
    title: string;
    timestamp: string;
    durationMs?: number | null;
    rawExecution?: JobExecution;
    rawAgentTask?: AgentTaskResponse;
  }

  const execItems: HistoryItem[] = (executions ?? []).map((e: JobExecution) => ({
    id: e.execution_id,
    type: "execution",
    status: e.status,
    title: `Code Execution (#${e.execution_id.slice(0, 8)})`,
    timestamp: e.submitted_at || e.started_at || new Date().toISOString(),
    durationMs: e.duration_ms,
    rawExecution: e,
  }));

  const agentItems: HistoryItem[] = (agentTasksResponse?.tasks ?? []).map((t: AgentTaskResponse) => ({
    id: t.task_id,
    type: "agent_task",
    status: t.status,
    title: t.task_description,
    timestamp: t.created_at,
    durationMs: null,
    rawAgentTask: t,
  }));

  // Combine and sort newest first
  const allItems: HistoryItem[] = [...execItems, ...agentItems].sort(
    (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
  );

  // Filter items
  const filteredItems = allItems.filter((item) => {
    if (activeTab === "executions" && item.type !== "execution") return false;
    if (activeTab === "agent" && item.type !== "agent_task") return false;

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const matchId = item.id.toLowerCase().includes(q);
      const matchTitle = item.title.toLowerCase().includes(q);
      const matchStatus = item.status.toLowerCase().includes(q);
      if (!matchId && !matchTitle && !matchStatus) return false;
    }

    return true;
  });

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
      {/* Top Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 16,
        }}
      >
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
            <div
              style={{
                width: 32,
                height: 32,
                borderRadius: 8,
                backgroundColor: "rgba(99, 102, 241, 0.15)",
                color: "#818cf8",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <History size={18} />
            </div>
            <h1
              style={{
                fontSize: 20,
                fontWeight: 700,
                margin: 0,
                color: "var(--color-text-primary)",
              }}
            >
              Execution &amp; Agent History
            </h1>
          </div>
          <p
            style={{
              fontSize: 13,
              color: "var(--color-text-muted)",
              margin: 0,
            }}
          >
            Authoritative audit trail of code executions and model-driven agent tasks.
          </p>
        </div>

        <button
          type="button"
          onClick={handleRefresh}
          disabled={isRefreshing}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            padding: "8px 12px",
            borderRadius: 6,
            border: "1px solid var(--color-border)",
            backgroundColor: "var(--color-surface-2)",
            color: "var(--color-text-secondary)",
            fontSize: 12,
            fontWeight: 500,
            cursor: isRefreshing ? "not-allowed" : "pointer",
          }}
        >
          <RefreshCw
            size={13}
            style={{
              animation: isRefreshing ? "spin 1s linear infinite" : "none",
            }}
          />
          Refresh All
        </button>
      </div>

      {/* Filter and Sandbox Picker Bar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 12,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, flex: 1, minWidth: 260 }}>
          {/* Sandbox Selector */}
          <select
            value={effectiveSandboxId}
            onChange={(e) => setSelectedSandboxId(e.target.value)}
            disabled={isSandboxesLoading || !sandboxes || sandboxes.length === 0}
            style={{
              padding: "7px 12px",
              borderRadius: 6,
              backgroundColor: "var(--color-surface)",
              border: "1px solid var(--color-border)",
              color: "var(--color-text-primary)",
              fontSize: 12,
              outline: "none",
            }}
          >
            {sandboxes && sandboxes.length > 0 ? (
              sandboxes.map((s: SandboxDetail) => (
                <option key={s.sandbox_id} value={s.sandbox_id}>
                  Sandbox: {s.sandbox_id.slice(0, 8)}... ({s.status})
                </option>
              ))
            ) : (
              <option value="">No sandboxes found</option>
            )}
          </select>

          {/* Search Input */}
          <div style={{ position: "relative", flex: 1, maxWidth: 320 }}>
            <Search
              size={14}
              color="var(--color-text-muted)"
              style={{
                position: "absolute",
                left: 10,
                top: "50%",
                transform: "translateY(-50%)",
              }}
            />
            <input
              type="text"
              placeholder="Search by ID, prompt, or status..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{
                width: "100%",
                padding: "7px 10px 7px 30px",
                borderRadius: 6,
                backgroundColor: "var(--color-surface)",
                border: "1px solid var(--color-border)",
                color: "var(--color-text-primary)",
                fontSize: 12,
                outline: "none",
              }}
            />
          </div>
        </div>

        {/* Tab Filters */}
        <div style={{ display: "flex", gap: 6 }}>
          {(["all", "executions", "agent"] as const).map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => setActiveTab(tab)}
              style={{
                padding: "6px 12px",
                borderRadius: 5,
                border: "1px solid",
                borderColor:
                  activeTab === tab
                    ? "var(--color-accent)"
                    : "var(--color-border)",
                backgroundColor:
                  activeTab === tab
                    ? "var(--color-accent-subtle)"
                    : "transparent",
                color:
                  activeTab === tab
                    ? "var(--color-accent)"
                    : "var(--color-text-secondary)",
                fontSize: 12,
                fontWeight: activeTab === tab ? 600 : 400,
                cursor: "pointer",
              }}
            >
              {tab === "all" ? "All Activity" : tab === "executions" ? "Code Executions" : "Agent Tasks"}
            </button>
          ))}
        </div>
      </div>

      {/* History Items List */}
      <div
        style={{
          backgroundColor: "var(--color-surface)",
          border: "1px solid var(--color-border-subtle)",
          borderRadius: 8,
          overflow: "hidden",
        }}
      >
        {isExecsLoading || isAgentLoading ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)", fontSize: 13 }}>
            Loading historical activity records...
          </div>
        ) : filteredItems.length === 0 ? (
          <div style={{ padding: 48, textAlign: "center", color: "var(--color-text-muted)", fontSize: 13 }}>
            No records found matching current criteria.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column" }}>
            {filteredItems.map((item) => {
              const isExpanded = expandedItem === item.id;
              const isExec = item.type === "execution";

              return (
                <div
                  key={item.id}
                  style={{
                    borderBottom: "1px solid var(--color-border-subtle)",
                    transition: "background-color 0.1s",
                  }}
                >
                  <div
                    onClick={() => setExpandedItem(isExpanded ? null : item.id)}
                    style={{
                      padding: "14px 18px",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: 12,
                      cursor: "pointer",
                      backgroundColor: isExpanded ? "var(--color-surface-2)" : "transparent",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 10, overflow: "hidden" }}>
                      <div
                        style={{
                          width: 28,
                          height: 28,
                          borderRadius: 6,
                          backgroundColor: isExec
                            ? "rgba(59, 130, 246, 0.15)"
                            : "rgba(139, 92, 246, 0.15)",
                          color: isExec ? "#3b82f6" : "#8b5cf6",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          flexShrink: 0,
                        }}
                      >
                        {isExec ? <PlaySquare size={15} /> : <Bot size={15} />}
                      </div>

                      <div style={{ overflow: "hidden" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <span
                            style={{
                              fontSize: 10,
                              fontWeight: 700,
                              padding: "1px 6px",
                              borderRadius: 3,
                              textTransform: "uppercase",
                              backgroundColor:
                                item.status === "completed" || item.status === "running"
                                  ? "var(--color-success-subtle)"
                                  : item.status === "failed" || item.status === "error"
                                  ? "var(--color-danger-subtle)"
                                  : "var(--color-surface-3)",
                              color:
                                item.status === "completed" || item.status === "running"
                                  ? "var(--color-success)"
                                  : item.status === "failed" || item.status === "error"
                                  ? "var(--color-danger)"
                                  : "var(--color-text-muted)",
                            }}
                          >
                            {item.status}
                          </span>
                          <span
                            style={{
                              fontSize: 13,
                              fontWeight: 600,
                              color: "var(--color-text-primary)",
                              textOverflow: "ellipsis",
                              overflow: "hidden",
                              whiteSpace: "nowrap",
                            }}
                          >
                            {item.title}
                          </span>
                        </div>

                        <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 2 }}>
                          ID: <code style={{ color: "var(--color-text-secondary)" }}>{item.id}</code> · {isExec ? "Execution Job" : "Agent Orchestration"}
                        </div>
                      </div>
                    </div>

                    <div style={{ display: "flex", alignItems: "center", gap: 14, flexShrink: 0, fontSize: 11, color: "var(--color-text-muted)" }}>
                      {item.durationMs !== undefined && item.durationMs !== null && (
                        <span>{item.durationMs} ms</span>
                      )}
                      <span>{new Date(item.timestamp).toLocaleString()}</span>
                    </div>
                  </div>

                  {/* Expanded Detail Inspector */}
                  {isExpanded && (
                    <div
                      style={{
                        padding: "14px 20px",
                        backgroundColor: "var(--color-surface-2)",
                        borderTop: "1px solid var(--color-border-subtle)",
                        fontSize: 12,
                        lineHeight: 1.5,
                      }}
                    >
                      {item.rawExecution && (
                        <div>
                          <div style={{ display: "flex", gap: 16, marginBottom: 10 }}>
                            <div>Exit Code: <strong>{item.rawExecution.exit_code ?? "N/A"}</strong></div>
                            <div>Duration: <strong>{item.rawExecution.duration_ms ?? "N/A"} ms</strong></div>
                          </div>
                          {item.rawExecution.stdout && (
                            <div style={{ marginBottom: 8 }}>
                              <div style={{ fontWeight: 600, color: "var(--color-text-muted)", marginBottom: 2 }}>Stdout:</div>
                              <pre style={{ margin: 0, padding: 8, backgroundColor: "var(--color-surface)", borderRadius: 4, overflowX: "auto" }}>
                                {item.rawExecution.stdout}
                              </pre>
                            </div>
                          )}
                          {item.rawExecution.stderr && (
                            <div>
                              <div style={{ fontWeight: 600, color: "var(--color-danger)", marginBottom: 2 }}>Stderr:</div>
                              <pre style={{ margin: 0, padding: 8, backgroundColor: "var(--color-surface)", borderRadius: 4, color: "var(--color-danger)", overflowX: "auto" }}>
                                {item.rawExecution.stderr}
                              </pre>
                            </div>
                          )}
                        </div>
                      )}

                      {item.rawAgentTask && (
                        <div>
                          <div style={{ display: "flex", gap: 16, marginBottom: 10 }}>
                            <div>Iterations: <strong>{item.rawAgentTask.iterations}</strong></div>
                            <div>Tool Calls: <strong>{item.rawAgentTask.tool_calls_count}</strong></div>
                          </div>
                          {item.rawAgentTask.result_summary && (
                            <div style={{ marginBottom: 8 }}>
                              <div style={{ fontWeight: 600, color: "var(--color-text-muted)", marginBottom: 2 }}>Result Summary:</div>
                              <div style={{ padding: 10, backgroundColor: "var(--color-surface)", borderRadius: 4, whiteSpace: "pre-wrap" }}>
                                {item.rawAgentTask.result_summary}
                              </div>
                            </div>
                          )}
                          {item.rawAgentTask.error_message && (
                            <div>
                              <div style={{ fontWeight: 600, color: "var(--color-danger)", marginBottom: 2 }}>Error ({item.rawAgentTask.error_type}):</div>
                              <div style={{ padding: 10, backgroundColor: "var(--color-danger-subtle)", color: "var(--color-danger)", borderRadius: 4 }}>
                                {item.rawAgentTask.error_message}
                              </div>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
