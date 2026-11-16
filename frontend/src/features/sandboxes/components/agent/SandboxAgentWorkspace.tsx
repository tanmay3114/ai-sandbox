import { useState, useEffect, useRef } from "react";
import {
  AlertCircle,
  AlertTriangle,
  Bot,
  History,
  Loader2,
  RefreshCw,
  Send,
  Shield,
  StopCircle,
  Terminal,
  Wrench,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import {
  useCreateAndRunAgentTask,
  useSandboxAgentTasks,
  useAgentTaskDetail,
  useCancelAgentTask,
} from "@/lib/api/queries";
import type { AgentTaskResponse } from "@/types";

interface SandboxAgentWorkspaceProps {
  sandboxId: string;
  isSandboxRunning?: boolean;
}

export function SandboxAgentWorkspace({
  sandboxId,
  isSandboxRunning = true,
}: SandboxAgentWorkspaceProps) {
  const [prompt, setPrompt] = useState<string>("");
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [activeTaskData, setActiveTaskData] = useState<AgentTaskResponse | null>(null);
  const [connectionInterrupted, setConnectionInterrupted] = useState<boolean>(false);
  const [elapsedSeconds, setElapsedSeconds] = useState<number>(0);
  const [expandedToolIdx, setExpandedToolIdx] = useState<number | null>(null);

  // Timer for active execution
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // TanStack queries and mutations
  const {
    data: taskListResponse,
    isLoading: isHistoryLoading,
    refetch: refetchHistory,
    isFetching: isHistoryFetching,
  } = useSandboxAgentTasks(sandboxId);

  // Polling query for task recovery / checking authoritative state
  const isRecovering =
    Boolean(activeTaskId) &&
    (connectionInterrupted ||
      activeTaskData?.status === "pending" ||
      activeTaskData?.status === "running");

  const {
    data: polledTaskDetail,
    refetch: refetchTaskDetail,
    isFetching: isPolledFetching,
  } = useAgentTaskDetail(activeTaskId ?? "", {
    enabled: Boolean(activeTaskId) && isRecovering,
    refetchInterval: isRecovering ? 3000 : false,
  });

  // Effective task data derives polled data when available
  const displayTaskData = polledTaskDetail ?? activeTaskData;

  // Task creation mutation (synchronous request)
  const createTaskMutation = useCreateAndRunAgentTask(sandboxId);

  // Task cancellation mutation
  const cancelTaskMutation = useCancelAgentTask(sandboxId);

  const isExecuting = createTaskMutation.isPending;

  // Manage elapsed timer
  useEffect(() => {
    if (!isExecuting) return;
    const interval = setInterval(() => {
      setElapsedSeconds((prev) => prev + 1);
    }, 1000);
    timerRef.current = interval;
    return () => clearInterval(interval);
  }, [isExecuting]);

  // Submit task
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = prompt.trim();
    if (!trimmed || isExecuting || !isSandboxRunning) return;

    setConnectionInterrupted(false);
    setActiveTaskData(null);
    setElapsedSeconds(0);

    createTaskMutation.mutate(
      { prompt: trimmed },
      {
        onSuccess: (data) => {
          setActiveTaskId(data.task_id);
          setActiveTaskData(data);
          refetchHistory();
        },
        onError: (err: any) => {
          // If connection dropped or timeout occurred on client side
          const status = err?.response?.status;
          if (status === 504 || status === 502 || !err?.response) {
            setConnectionInterrupted(true);
            // Refresh history to check if task was persisted before drop
            refetchHistory().then((res) => {
              if (res.data?.tasks && res.data.tasks.length > 0) {
                const latest = res.data.tasks[0];
                setActiveTaskId(latest.task_id);
                setActiveTaskData(latest);
              }
            });
          }
        },
      }
    );
  };

  // Explicit cancellation
  const handleCancel = () => {
    if (!activeTaskId || cancelTaskMutation.isPending) return;

    cancelTaskMutation.mutate(activeTaskId, {
      onSuccess: (updated) => {
        setActiveTaskData(updated);
        refetchHistory();
      },
      onError: () => {
        // Refresh authoritative state if cancellation was rejected or already finished
        refetchTaskDetail();
      },
    });
  };

  const currentStatus = displayTaskData?.status;
  const isTerminal =
    currentStatus === "completed" ||
    currentStatus === "failed" ||
    currentStatus === "cancelled" ||
    currentStatus === "timed_out";

  const canCancel =
    Boolean(activeTaskId) &&
    !isTerminal &&
    (isExecuting || currentStatus === "running" || currentStatus === "pending");

  return (
    <div
      style={{
        backgroundColor: "var(--color-surface)",
        border: "1px solid var(--color-border-subtle)",
        borderRadius: 8,
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        marginBottom: 24,
      }}
    >
      {/* Header */}
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
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Bot size={18} color="var(--color-accent)" />
            <h3
              style={{
                margin: 0,
                fontSize: 15,
                fontWeight: 600,
                color: "var(--color-text-primary)",
              }}
            >
              Autonomous Agent Orchestration
            </h3>
          </div>
          <p
            style={{
              margin: "4px 0 0",
              fontSize: 12,
              color: "var(--color-text-muted)",
            }}
          >
            Submit natural language coding tasks to be planned and executed inside this sandbox.
          </p>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <button
            type="button"
            onClick={() => refetchHistory()}
            disabled={isHistoryFetching}
            title="Refresh task history"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "6px 10px",
              borderRadius: 6,
              border: "1px solid var(--color-border)",
              backgroundColor: "var(--color-surface-2)",
              color: "var(--color-text-secondary)",
              fontSize: 12,
              cursor: isHistoryFetching ? "not-allowed" : "pointer",
            }}
          >
            <RefreshCw
              size={13}
              style={{
                animation: isHistoryFetching ? "spin 1s linear infinite" : "none",
              }}
            />
            Tasks History
          </button>
        </div>
      </div>

      {/* Main Body */}
      <div style={{ padding: 20, display: "flex", flexDirection: "column", gap: 20 }}>
        {/* Prompt Input Form */}
        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <label
            htmlFor="agent-task-prompt"
            style={{
              fontSize: 12,
              fontWeight: 600,
              color: "var(--color-text-secondary)",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <span>Task Prompt (Natural Language)</span>
            <span style={{ fontSize: 11, color: "var(--color-text-muted)", fontWeight: 400 }}>
              {prompt.length} / 10,000 max characters
            </span>
          </label>

          <textarea
            id="agent-task-prompt"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            disabled={isExecuting || !isSandboxRunning}
            placeholder={
              !isSandboxRunning
                ? "Sandbox is not in a running state. Agent execution is disabled."
                : "e.g., Create a python script that calculates prime numbers up to 100, save it to primes.py, execute it, and explain results."
            }
            maxLength={10000}
            rows={3}
            style={{
              width: "100%",
              padding: "10px 12px",
              borderRadius: 6,
              backgroundColor: "var(--color-surface-2)",
              border: "1px solid var(--color-border)",
              color: "var(--color-text-primary)",
              fontSize: 13,
              lineHeight: 1.5,
              outline: "none",
              resize: "vertical",
            }}
          />

          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: "var(--color-text-muted)" }}>
              <Shield size={13} color="var(--color-success)" />
              <span>Hardened execution · Read/Write Workspace · Safe tool audit</span>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              {canCancel && (
                <button
                  type="button"
                  onClick={handleCancel}
                  disabled={cancelTaskMutation.isPending}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    padding: "7px 14px",
                    borderRadius: 6,
                    border: "1px solid var(--color-danger)",
                    backgroundColor: "transparent",
                    color: "var(--color-danger)",
                    fontSize: 12,
                    fontWeight: 600,
                    cursor: cancelTaskMutation.isPending ? "not-allowed" : "pointer",
                    opacity: cancelTaskMutation.isPending ? 0.6 : 1,
                  }}
                >
                  <StopCircle size={14} />
                  {cancelTaskMutation.isPending ? "Cancelling..." : "Cancel Task"}
                </button>
              )}

              <button
                type="submit"
                disabled={isExecuting || !prompt.trim() || !isSandboxRunning}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  padding: "7px 16px",
                  borderRadius: 6,
                  border: "none",
                  backgroundColor: "var(--color-accent)",
                  color: "#ffffff",
                  fontSize: 12,
                  fontWeight: 600,
                  cursor:
                    isExecuting || !prompt.trim() || !isSandboxRunning
                      ? "not-allowed"
                      : "pointer",
                  opacity: isExecuting || !prompt.trim() || !isSandboxRunning ? 0.6 : 1,
                }}
              >
                {isExecuting ? (
                  <>
                    <Loader2 size={14} className="animate-spin" />
                    <span>Orchestrating ({elapsedSeconds}s)...</span>
                  </>
                ) : (
                  <>
                    <Send size={13} />
                    <span>Run Agent Task</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </form>

        {/* Long-Running Notice Banner */}
        {isExecuting && (
          <div
            style={{
              padding: "12px 16px",
              borderRadius: 6,
              backgroundColor: "var(--color-surface-2)",
              border: "1px solid var(--color-border)",
              display: "flex",
              alignItems: "center",
              gap: 12,
            }}
          >
            <Loader2 size={18} color="var(--color-accent)" className="animate-spin" />
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "var(--color-text-primary)" }}>
                Agent task is running synchronously ({elapsedSeconds}s)
              </div>
              <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 2 }}>
                Reasoning iterations and workspace tool invocations are being executed on the backend. This request accommodates up to 300 seconds.
              </div>
            </div>
          </div>
        )}

        {/* Connection Interruption Recovery Notice */}
        {connectionInterrupted && (
          <div
            style={{
              padding: "12px 16px",
              borderRadius: 6,
              backgroundColor: "var(--color-warning-subtle)",
              border: "1px solid rgba(245, 158, 11, 0.3)",
              display: "flex",
              alignItems: "flex-start",
              gap: 12,
            }}
          >
            <AlertTriangle size={18} color="var(--color-warning)" style={{ flexShrink: 0, marginTop: 2 }} />
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "var(--color-warning)" }}>
                Connection Interrupted — Task May Still Be Running
              </div>
              <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginTop: 2, lineHeight: 1.4 }}>
                The HTTP connection was closed or timed out, but the backend orchestrator continues executing durable tasks asynchronously.
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 8 }}>
                <button
                  type="button"
                  onClick={() => {
                    refetchHistory();
                    if (activeTaskId) refetchTaskDetail();
                  }}
                  disabled={isPolledFetching}
                  style={{
                    padding: "4px 10px",
                    borderRadius: 4,
                    border: "1px solid var(--color-warning)",
                    backgroundColor: "transparent",
                    color: "var(--color-warning)",
                    fontSize: 11,
                    fontWeight: 600,
                    cursor: "pointer",
                  }}
                >
                  {isPolledFetching ? "Checking state..." : "Check Authoritative State"}
                </button>
                {activeTaskId && (
                  <span style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
                    Tracking task: <code>{activeTaskId}</code>
                  </span>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Active / Selected Task Details */}
        {displayTaskData && (
          <div
            style={{
              backgroundColor: "var(--color-surface-2)",
              border: "1px solid var(--color-border)",
              borderRadius: 8,
              padding: "16px 18px",
              display: "flex",
              flexDirection: "column",
              gap: 14,
            }}
          >
            {/* Task Status Bar */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                flexWrap: "wrap",
                gap: 8,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <Terminal size={16} color="var(--color-accent)" />
                <span style={{ fontSize: 13, fontWeight: 700, color: "var(--color-text-primary)" }}>
                  Task Result:
                </span>
                <span
                  style={{
                    fontSize: 11,
                    fontWeight: 700,
                    padding: "2px 8px",
                    borderRadius: 4,
                    textTransform: "uppercase",
                    backgroundColor:
                      displayTaskData.status === "completed"
                        ? "var(--color-success-subtle)"
                        : displayTaskData.status === "failed"
                        ? "var(--color-danger-subtle)"
                        : displayTaskData.status === "cancelled"
                        ? "rgba(156, 163, 175, 0.2)"
                        : "var(--color-accent-subtle)",
                    color:
                      displayTaskData.status === "completed"
                        ? "var(--color-success)"
                        : displayTaskData.status === "failed"
                        ? "var(--color-danger)"
                        : displayTaskData.status === "cancelled"
                        ? "#9ca3af"
                        : "var(--color-accent)",
                    border: "1px solid currentColor",
                  }}
                >
                  {displayTaskData.status}
                </span>
                <span style={{ fontSize: 11, color: "var(--color-text-muted)", fontFamily: "monospace" }}>
                  {displayTaskData.task_id}
                </span>
              </div>

              <div style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 11, color: "var(--color-text-muted)" }}>
                <span>Iterations: <strong>{displayTaskData.iterations}</strong></span>
                <span>•</span>
                <span>Tool Calls: <strong>{displayTaskData.tool_calls_count}</strong></span>
              </div>
            </div>

            {/* Prompt description */}
            <div style={{ fontSize: 12, color: "var(--color-text-secondary)", fontStyle: "italic" }}>
              "{displayTaskData.task_description}"
            </div>

            {/* Error Message if failed */}
            {displayTaskData.error_message && (
              <div
                style={{
                  padding: "10px 12px",
                  borderRadius: 6,
                  backgroundColor: "var(--color-danger-subtle)",
                  border: "1px solid rgba(239, 68, 68, 0.3)",
                  color: "var(--color-danger)",
                  fontSize: 12,
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 8,
                }}
              >
                <AlertCircle size={15} style={{ flexShrink: 0, marginTop: 2 }} />
                <div>
                  <div style={{ fontWeight: 600 }}>{displayTaskData.error_type || "Task Error"}</div>
                  <div style={{ marginTop: 2 }}>{displayTaskData.error_message}</div>
                </div>
              </div>
            )}

            {/* Result summary */}
            {displayTaskData.result_summary && (
              <div
                style={{
                  padding: "12px 14px",
                  backgroundColor: "var(--color-surface)",
                  border: "1px solid var(--color-border-subtle)",
                  borderRadius: 6,
                  fontSize: 13,
                  lineHeight: 1.6,
                  color: "var(--color-text-primary)",
                  whiteSpace: "pre-wrap",
                }}
              >
                {displayTaskData.result_summary}
              </div>
            )}

            {/* Tool History / Audit Trail */}
            {displayTaskData.tool_history && displayTaskData.tool_history.length > 0 && (
              <div style={{ marginTop: 6 }}>
                <div
                  style={{
                    fontSize: 11,
                    fontWeight: 700,
                    textTransform: "uppercase",
                    letterSpacing: "0.04em",
                    color: "var(--color-text-muted)",
                    marginBottom: 8,
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                  }}
                >
                  <Wrench size={13} color="var(--color-accent)" />
                  <span>Structured Tool Activity Audit ({displayTaskData.tool_history.length})</span>
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {displayTaskData.tool_history.map((toolCall: any, idx: number) => {
                    const isExpanded = expandedToolIdx === idx;
                    const toolName = toolCall.tool || "unknown_tool";
                    const isErr = toolCall.is_error;

                    return (
                      <div
                        key={idx}
                        style={{
                          backgroundColor: "var(--color-surface)",
                          border: "1px solid var(--color-border-subtle)",
                          borderRadius: 6,
                          overflow: "hidden",
                        }}
                      >
                        <div
                          onClick={() => setExpandedToolIdx(isExpanded ? null : idx)}
                          style={{
                            padding: "8px 12px",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "space-between",
                            cursor: "pointer",
                            fontSize: 12,
                          }}
                        >
                          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                            <span style={{ fontWeight: 600, fontFamily: "monospace", color: "var(--color-accent)" }}>
                              {toolName}
                            </span>
                            {isErr ? (
                              <span style={{ fontSize: 10, color: "var(--color-danger)", fontWeight: 700 }}>
                                FAILED
                              </span>
                            ) : (
                              <span style={{ fontSize: 10, color: "var(--color-success)", fontWeight: 700 }}>
                                SUCCESS
                              </span>
                            )}
                          </div>

                          <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
                            {toolCall.timestamp ? new Date(toolCall.timestamp).toLocaleTimeString() : ""}
                          </div>
                        </div>

                        {isExpanded && (
                          <div
                            style={{
                              padding: "10px 12px",
                              backgroundColor: "var(--color-surface-2)",
                              borderTop: "1px solid var(--color-border-subtle)",
                              fontSize: 11,
                              fontFamily: "monospace",
                              color: "var(--color-text-secondary)",
                              overflowX: "auto",
                            }}
                          >
                            <div style={{ marginBottom: 4, fontWeight: 600, color: "var(--color-text-muted)" }}>
                              Arguments:
                            </div>
                            <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
                              {JSON.stringify(toolCall.arguments ?? {}, null, 2)}
                            </pre>
                            {toolCall.execution_id && (
                              <div style={{ marginTop: 6, color: "var(--color-text-muted)" }}>
                                Execution ID: <code>{toolCall.execution_id}</code>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Task History Listing */}
        <div style={{ marginTop: 10 }}>
          <div
            style={{
              fontSize: 12,
              fontWeight: 600,
              color: "var(--color-text-secondary)",
              marginBottom: 10,
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            <History size={14} />
            <span>Recent Sandbox Agent Tasks</span>
          </div>

          {isHistoryLoading ? (
            <div style={{ padding: 16, textAlign: "center", color: "var(--color-text-muted)", fontSize: 12 }}>
              Loading task history...
            </div>
          ) : !taskListResponse?.tasks || taskListResponse.tasks.length === 0 ? (
            <div
              style={{
                padding: "24px 16px",
                textAlign: "center",
                color: "var(--color-text-muted)",
                fontSize: 12,
                backgroundColor: "var(--color-surface-2)",
                borderRadius: 6,
                border: "1px dashed var(--color-border)",
              }}
            >
              No agent tasks recorded yet for this sandbox. Submit a prompt above to start.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {taskListResponse.tasks.map((task) => {
                const isSelected = activeTaskId === task.task_id;

                return (
                  <div
                    key={task.task_id}
                    onClick={() => {
                      setActiveTaskId(task.task_id);
                      setActiveTaskData(task);
                      setConnectionInterrupted(false);
                    }}
                    style={{
                      padding: "10px 14px",
                      borderRadius: 6,
                      backgroundColor: isSelected
                        ? "var(--color-accent-subtle)"
                        : "var(--color-surface-2)",
                      border: "1px solid",
                      borderColor: isSelected
                        ? "var(--color-accent)"
                        : "var(--color-border-subtle)",
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: 12,
                      fontSize: 12,
                      transition: "all 0.15s ease",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 10, overflow: "hidden" }}>
                      <span
                        style={{
                          fontSize: 10,
                          fontWeight: 700,
                          padding: "2px 6px",
                          borderRadius: 3,
                          textTransform: "uppercase",
                          backgroundColor:
                            task.status === "completed"
                              ? "var(--color-success-subtle)"
                              : task.status === "failed"
                              ? "var(--color-danger-subtle)"
                              : task.status === "cancelled"
                              ? "rgba(156, 163, 175, 0.2)"
                              : "var(--color-accent-subtle)",
                          color:
                            task.status === "completed"
                              ? "var(--color-success)"
                              : task.status === "failed"
                              ? "var(--color-danger)"
                              : task.status === "cancelled"
                              ? "#9ca3af"
                              : "var(--color-accent)",
                        }}
                      >
                        {task.status}
                      </span>
                      <span
                        style={{
                          color: "var(--color-text-primary)",
                          textOverflow: "ellipsis",
                          overflow: "hidden",
                          whiteSpace: "nowrap",
                        }}
                        title={task.task_description}
                      >
                        {task.task_description}
                      </span>
                    </div>

                    <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0, fontSize: 11, color: "var(--color-text-muted)" }}>
                      <span>{new Date(task.created_at).toLocaleTimeString()}</span>
                      <span style={{ fontFamily: "monospace" }}>
                        {task.task_id.slice(0, 8)}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
