import { useEffect, useState } from "react";
import {
  Container,
  ExternalLink,
  Plus,
  PlaySquare,
} from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { useSandboxes } from "@/features/sandboxes/hooks/useSandboxes";
import type { SandboxDetail } from "@/features/sandboxes/types";
import { CodeEditor } from "../components/CodeEditor";
import { ExecutionList } from "../components/ExecutionList";
import { ExecutionOutput } from "../components/ExecutionOutput";
import {
  useExecuteCode,
  useSandboxExecutions,
} from "../hooks/useExecutions";
import type { JobExecution } from "../types";

export function ExecutionsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const urlSandboxId = searchParams.get("sandboxId");

  const {
    data: sandboxes,
    isLoading: isSandboxesLoading,
  } = useSandboxes();

  // Active selected sandbox
  const [selectedSandboxId, setSelectedSandboxId] = useState<string>("");

  // Keep state in sync with URL param or first available sandbox
  useEffect(() => {
    if (urlSandboxId) {
      setSelectedSandboxId(urlSandboxId);
    } else if (sandboxes && sandboxes.length > 0 && !selectedSandboxId) {
      // Pick the first running sandbox or first available
      const activeSb =
        sandboxes.find((s) => s.status === "running") ?? sandboxes[0];
      setSelectedSandboxId(activeSb.sandbox_id);
    }
  }, [urlSandboxId, sandboxes, selectedSandboxId]);

  const handleSelectSandbox = (id: string) => {
    setSelectedSandboxId(id);
    setSearchParams(id ? { sandboxId: id } : {});
  };

  const selectedSandbox = sandboxes?.find(
    (s: SandboxDetail) => s.sandbox_id === selectedSandboxId,
  );

  // Execution query and mutation
  const {
    data: executions,
    isLoading: isExecsLoading,
    isError: isExecsError,
    refetch: refetchExecs,
    isFetching: isExecsFetching,
  } = useSandboxExecutions(selectedSandboxId || undefined);

  const {
    mutate: runCode,
    isPending: isExecuting,
    error: executionError,
    data: latestResult,
  } = useExecuteCode(selectedSandboxId || undefined);

  // Local editor code state
  const [code, setCode] = useState('print("Hello World")');
  const [timeoutSeconds, setTimeoutSeconds] = useState<number | undefined>(10);
  const [activeResult, setActiveResult] = useState<JobExecution | null>(null);

  // Update active result when mutation resolves
  useEffect(() => {
    if (latestResult) {
      setActiveResult(latestResult);
    }
  }, [latestResult]);

  const handleRun = () => {
    if (!selectedSandboxId || !code.trim()) return;
    runCode({ code, timeout_seconds: timeoutSeconds });
  };

  const isSandboxRunnable = selectedSandbox?.status === "running";

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto", display: "flex", flexDirection: "column", gap: 24 }}>
      {/* Header Banner */}
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
          <h1
            style={{
              fontSize: 20,
              fontWeight: 700,
              margin: "0 0 4px",
              color: "var(--color-text-primary)",
            }}
          >
            Code Executions
          </h1>
          <p
            style={{
              fontSize: 13,
              color: "var(--color-text-muted)",
              margin: 0,
            }}
          >
            Execute untrusted Python code and inspect real job outputs inside isolated containers.
          </p>
        </div>

        {/* Link to sandboxes */}
        <Link
          to="/dashboard/sandboxes"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            padding: "8px 14px",
            borderRadius: 6,
            backgroundColor: "var(--color-surface-2)",
            border: "1px solid var(--color-border)",
            color: "var(--color-text-primary)",
            fontSize: 12,
            fontWeight: 500,
            textDecoration: "none",
          }}
        >
          <Container size={14} />
          <span>Manage Sandboxes</span>
        </Link>
      </div>

      {/* Sandbox Selector Card */}
      <div
        style={{
          backgroundColor: "var(--color-surface)",
          border: "1px solid var(--color-border-subtle)",
          borderRadius: 8,
          padding: "16px 20px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 14,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <Container size={16} color="var(--color-accent)" />
            <span style={{ fontSize: 13, fontWeight: 600, color: "var(--color-text-primary)" }}>
              Target Sandbox:
            </span>
          </div>

          {isSandboxesLoading ? (
            <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
              Loading available sandboxes...
            </span>
          ) : sandboxes && sandboxes.length > 0 ? (
            <select
              value={selectedSandboxId}
              onChange={(e) => handleSelectSandbox(e.target.value)}
              style={{
                fontSize: 12,
                fontFamily: "monospace",
                padding: "6px 12px",
                borderRadius: 6,
                backgroundColor: "var(--color-surface-2)",
                border: "1px solid var(--color-border)",
                color: "var(--color-text-primary)",
                outline: "none",
                cursor: "pointer",
                minWidth: 260,
              }}
            >
              {sandboxes.map((sb: SandboxDetail) => (
                <option key={sb.sandbox_id} value={sb.sandbox_id}>
                  {sb.sandbox_id.slice(0, 8)}... ({sb.runtime}, {sb.status})
                </option>
              ))}
            </select>
          ) : (
            <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
              No sandboxes currently exist.
            </span>
          )}
        </div>

        {/* Selected Sandbox Quick Actions */}
        {selectedSandbox && (
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span
              style={{
                fontSize: 11,
                padding: "2px 8px",
                borderRadius: 4,
                backgroundColor:
                  selectedSandbox.status === "running"
                    ? "var(--color-success-subtle)"
                    : "var(--color-surface-2)",
                color:
                  selectedSandbox.status === "running"
                    ? "var(--color-success)"
                    : "var(--color-text-muted)",
                fontWeight: 600,
                textTransform: "uppercase",
              }}
            >
              {selectedSandbox.status}
            </span>

            <Link
              to={`/dashboard/sandboxes/${selectedSandbox.sandbox_id}`}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
                fontSize: 12,
                color: "var(--color-accent)",
                textDecoration: "none",
              }}
            >
              <span>Sandbox Details</span>
              <ExternalLink size={12} />
            </Link>
          </div>
        )}
      </div>

      {/* When no sandboxes exist */}
      {!isSandboxesLoading && (!sandboxes || sandboxes.length === 0) ? (
        <div
          style={{
            backgroundColor: "var(--color-surface)",
            border: "1px solid var(--color-border-subtle)",
            borderRadius: 8,
            padding: "48px 24px",
            textAlign: "center",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 12,
          }}
        >
          <PlaySquare size={36} color="var(--color-text-muted)" />
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>
            No Active Sandboxes Available
          </h3>
          <p
            style={{
              margin: 0,
              fontSize: 13,
              color: "var(--color-text-muted)",
              maxWidth: 420,
            }}
          >
            Code executions require a persistent sandbox session. Create a sandbox first to begin executing Python code.
          </p>
          <Link
            to="/dashboard/sandboxes"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "8px 18px",
              borderRadius: 6,
              backgroundColor: "var(--color-accent)",
              color: "#ffffff",
              fontSize: 13,
              fontWeight: 600,
              textDecoration: "none",
              marginTop: 6,
            }}
          >
            <Plus size={15} />
            Create Sandbox
          </Link>
        </div>
      ) : (
        <>
          {/* Code Execution Workspace */}
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <CodeEditor
              code={code}
              onChange={setCode}
              timeoutSeconds={timeoutSeconds}
              onTimeoutChange={setTimeoutSeconds}
              onRun={handleRun}
              isPending={isExecuting}
              disabled={!isSandboxRunnable}
              disabledMessage={
                !isSandboxRunnable
                  ? `Sandbox is ${selectedSandbox?.status ?? "unavailable"}. Code can only run in a 'running' sandbox.`
                  : undefined
              }
            />

            {/* Latest Execution Output */}
            <ExecutionOutput
              execution={activeResult}
              isPending={isExecuting}
              error={executionError}
            />
          </div>

          {/* Execution History Table */}
          <div>
            <ExecutionList
              executions={executions}
              isLoading={isExecsLoading}
              isError={isExecsError}
              onRefresh={refetchExecs}
              isRefreshing={isExecsFetching}
              title={`Executions for ${selectedSandboxId.slice(0, 8)}...`}
            />
          </div>
        </>
      )}
    </div>
  );
}
