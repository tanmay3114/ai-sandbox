import { useState } from "react";
import {
  AlertCircle,
  ArrowLeft,
  Check,
  Copy,
  RefreshCw,
  Shield,
  Trash2,
} from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { formatDate } from "@/lib/utils";
import { DestroyConfirmDialog } from "./components/DestroyConfirmDialog";
import { SandboxStatusBadge } from "./components/SandboxStatusBadge";
import { TTLRemaining } from "./components/TTLRemaining";
import { useSandbox } from "./hooks/useSandbox";
import { useSandboxExecutions } from "./hooks/useSandboxExecutions";
import { CodeEditor } from "@/features/executions/components/CodeEditor";
import { ExecutionList } from "@/features/executions/components/ExecutionList";
import { ExecutionOutput } from "@/features/executions/components/ExecutionOutput";
import { useExecuteCode } from "@/features/executions/hooks/useExecutions";

export function SandboxDetailsPage() {
  const { sandboxId } = useParams<{ sandboxId: string }>();
  const [copied, setCopied] = useState(false);
  const [destroyOpen, setDestroyOpen] = useState(false);

  // Execution Code Runner state
  const [code, setCode] = useState('print("Hello World")');
  const [timeoutSeconds, setTimeoutSeconds] = useState<number | undefined>(10);

  const {
    mutate: runCode,
    isPending: isExecuting,
    error: executionError,
    data: latestResult,
  } = useExecuteCode(sandboxId);

  const {
    data: sandbox,
    isLoading: isSandboxLoading,
    isError: isSandboxError,
    refetch: refetchSandbox,
    isFetching: isSandboxFetching,
  } = useSandbox(sandboxId);

  const {
    data: executions,
    isLoading: isExecsLoading,
    isError: isExecsError,
    refetch: refetchExecs,
    isFetching: isExecsFetching,
  } = useSandboxExecutions(sandboxId);

  const isRunnable = sandbox?.status === "running";

  const handleRunCode = () => {
    if (!sandboxId || !code.trim() || !isRunnable) return;
    runCode({ code, timeout_seconds: timeoutSeconds });
  };

  const handleCopyId = () => {
    if (sandboxId) {
      navigator.clipboard.writeText(sandboxId);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  };

  const isDestroyed =
    sandbox?.status === "destroyed" || sandbox?.status === "destroying";

  if (isSandboxLoading) {
    return (
      <div style={{ maxWidth: 1000, margin: "0 auto", padding: "20px 0" }}>
        <div style={{ height: 24, width: 120, backgroundColor: "var(--color-surface)", borderRadius: 4, marginBottom: 20 }} />
        <div style={{ height: 160, backgroundColor: "var(--color-surface)", borderRadius: 8, marginBottom: 20 }} />
        <div style={{ height: 240, backgroundColor: "var(--color-surface)", borderRadius: 8 }} />
      </div>
    );
  }

  if (isSandboxError || !sandbox) {
    return (
      <div style={{ maxWidth: 800, margin: "40px auto", textAlign: "center" }}>
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            width: 48,
            height: 48,
            borderRadius: 10,
            backgroundColor: "var(--color-danger-subtle)",
            color: "var(--color-danger)",
            marginBottom: 16,
          }}
        >
          <AlertCircle size={24} />
        </div>
        <h2 style={{ margin: "0 0 8px", fontSize: 18, fontWeight: 600 }}>
          Sandbox not found
        </h2>
        <p style={{ margin: "0 0 20px", fontSize: 13, color: "var(--color-text-muted)" }}>
          The requested sandbox session could not be found or has been completely removed.
        </p>
        <Link
          to="/dashboard/sandboxes"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            padding: "8px 16px",
            borderRadius: 6,
            backgroundColor: "var(--color-surface-2)",
            border: "1px solid var(--color-border)",
            color: "var(--color-text-primary)",
            fontSize: 12,
            textDecoration: "none",
          }}
        >
          <ArrowLeft size={14} />
          Return to Sandboxes
        </Link>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto" }}>
      {/* Navigation Breadcrumb */}
      <div style={{ marginBottom: 16 }}>
        <Link
          to="/dashboard/sandboxes"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            fontSize: 12,
            color: "var(--color-text-muted)",
            textDecoration: "none",
          }}
        >
          <ArrowLeft size={13} />
          Back to Sandboxes
        </Link>
      </div>

      {/* Header Banner */}
      <div
        style={{
          backgroundColor: "var(--color-surface)",
          border: "1px solid var(--color-border-subtle)",
          borderRadius: 8,
          padding: "20px 24px",
          marginBottom: 20,
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
              {sandbox.sandbox_id}
            </span>
            <button
              onClick={handleCopyId}
              title="Copy ID"
              style={{
                background: "none",
                border: "none",
                color: copied ? "var(--color-success)" : "var(--color-text-muted)",
                cursor: "pointer",
                padding: 4,
                borderRadius: 4,
                display: "flex",
              }}
            >
              {copied ? <Check size={14} /> : <Copy size={14} />}
            </button>
            <SandboxStatusBadge status={sandbox.status} />
          </div>
          <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
            Created on {formatDate(sandbox.created_at)}
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <button
            onClick={() => {
              refetchSandbox();
              refetchExecs();
            }}
            disabled={isSandboxFetching}
            title="Refresh sandbox data"
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
              fontWeight: 500,
              cursor: isSandboxFetching ? "not-allowed" : "pointer",
            }}
          >
            <RefreshCw
              size={13}
              style={{
                animation: isSandboxFetching ? "spin 1s linear infinite" : "none",
              }}
            />
            Refresh
          </button>

          <button
            onClick={() => setDestroyOpen(true)}
            disabled={isDestroyed}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "7px 14px",
              borderRadius: 6,
              border: "1px solid var(--color-border)",
              backgroundColor: "transparent",
              color: isDestroyed ? "var(--color-text-muted)" : "var(--color-danger)",
              fontSize: 12,
              fontWeight: 600,
              cursor: isDestroyed ? "not-allowed" : "pointer",
              opacity: isDestroyed ? 0.4 : 1,
            }}
          >
            <Trash2 size={13} />
            Destroy Sandbox
          </button>
        </div>
      </div>

      {/* Metadata Cards Grid */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
          gap: 12,
          marginBottom: 24,
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
          <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.04em" }}>
            Runtime
          </div>
          <div style={{ fontSize: 15, fontWeight: 600, color: "var(--color-text-primary)", textTransform: "capitalize" }}>
            {sandbox.runtime}
          </div>
          <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 2 }}>
            Pinned execution container
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
          <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.04em" }}>
            TTL Status
          </div>
          <div style={{ marginTop: 2 }}>
            <TTLRemaining expiresAt={sandbox.expires_at} status={sandbox.status} />
          </div>
          <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 4 }}>
            Expires: {formatDate(sandbox.expires_at)}
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
          <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.04em" }}>
            Total Executions
          </div>
          <div style={{ fontSize: 20, fontWeight: 700, color: "var(--color-text-primary)" }}>
            {executions ? executions.length : sandbox.executions_count}
          </div>
          <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 2 }}>
            Recorded execution jobs
          </div>
        </div>

        <Link
          to="/dashboard/security"
          title="Inspect Security Policy & Boundaries"
          style={{
            backgroundColor: "var(--color-surface)",
            border: "1px solid var(--color-border-subtle)",
            borderRadius: 8,
            padding: "16px 18px",
            textDecoration: "none",
            display: "block",
          }}
        >
          <div
            style={{
              fontSize: 11,
              color: "var(--color-text-muted)",
              marginBottom: 4,
              textTransform: "uppercase",
              letterSpacing: "0.04em",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <span>Security</span>
            <Shield size={13} color="var(--color-success)" />
          </div>
          <div
            style={{
              fontSize: 14,
              fontWeight: 600,
              color: "var(--color-success)",
              marginBottom: 4,
            }}
          >
            ✓ Hardened Sandbox
          </div>
          <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
            RAM: {String(sandbox.resource_config?.memory_limit ?? "256m")} · View boundaries →
          </div>
        </Link>
      </div>

      {/* Code Runner Workspace */}
      <div style={{ marginBottom: 24, display: "flex", flexDirection: "column", gap: 16 }}>
        <div>
          <h3
            style={{
              margin: "0 0 4px",
              fontSize: 14,
              fontWeight: 600,
              color: "var(--color-text-primary)",
            }}
          >
            Code Runner
          </h3>
          <p
            style={{
              margin: 0,
              fontSize: 12,
              color: "var(--color-text-muted)",
            }}
          >
            Execute untrusted Python code inside this persistent sandbox session.
          </p>
        </div>

        <CodeEditor
          code={code}
          onChange={setCode}
          timeoutSeconds={timeoutSeconds}
          onTimeoutChange={setTimeoutSeconds}
          onRun={handleRunCode}
          isPending={isExecuting}
          disabled={!isRunnable}
          disabledMessage={
            !isRunnable
              ? `Execution is disabled because sandbox status is '${sandbox.status}'.`
              : undefined
          }
        />

        <ExecutionOutput
          execution={latestResult ?? null}
          isPending={isExecuting}
          error={executionError}
        />
      </div>

      {/* Execution History Section */}
      <div style={{ marginBottom: 24 }}>
        <ExecutionList
          executions={executions}
          isLoading={isExecsLoading}
          isError={isExecsError}
          onRefresh={refetchExecs}
          isRefreshing={isExecsFetching}
          title="Execution History"
          subtitle="All code execution runs submitted to this persistent sandbox session."
        />
      </div>

      {/* Destroy Confirmation Modal */}
      <DestroyConfirmDialog
        open={destroyOpen}
        sandboxId={sandbox.sandbox_id}
        onClose={() => setDestroyOpen(false)}
        onDestroyed={() => refetchSandbox()}
      />
    </div>
  );
}
