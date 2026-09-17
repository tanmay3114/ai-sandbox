import { useState } from "react";
import {
  AlertCircle,
  ArrowLeft,
  Container,
} from "lucide-react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useSandboxes } from "@/features/sandboxes/hooks/useSandboxes";
import type { SandboxDetail } from "@/features/sandboxes/types";
import { ExecutionDetail } from "../components/ExecutionDetail";
import { useExecution } from "../hooks/useExecutions";

export function ExecutionDetailPage() {
  const { executionId } = useParams<{ executionId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const urlSandboxId = searchParams.get("sandboxId");

  const { data: sandboxes } = useSandboxes();
  const [selectedSandboxId, setSelectedSandboxId] = useState<string>(
    urlSandboxId ?? "",
  );

  const effectiveSandboxId = urlSandboxId || selectedSandboxId;

  const {
    data: execution,
    isLoading,
    isError,
    refetch,
    isFetching,
  } = useExecution(effectiveSandboxId || undefined, executionId);

  // If no sandboxId is provided in URL, render a sandbox picker
  if (!effectiveSandboxId) {
    return (
      <div style={{ maxWidth: 700, margin: "40px auto", textAlign: "center" }}>
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            width: 48,
            height: 48,
            borderRadius: 10,
            backgroundColor: "var(--color-surface-2)",
            color: "var(--color-text-secondary)",
            marginBottom: 16,
          }}
        >
          <Container size={24} />
        </div>
        <h2 style={{ margin: "0 0 8px", fontSize: 18, fontWeight: 600 }}>
          Select Parent Sandbox
        </h2>
        <p style={{ margin: "0 0 20px", fontSize: 13, color: "var(--color-text-muted)" }}>
          Backend execution details are scoped by sandbox. Please specify which sandbox session ran execution{" "}
          <code style={{ color: "var(--color-accent)" }}>{executionId}</code>.
        </p>

        {sandboxes && sandboxes.length > 0 ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 360, margin: "0 auto" }}>
            <select
              defaultValue=""
              onChange={(e) => {
                if (e.target.value) {
                  setSelectedSandboxId(e.target.value);
                  setSearchParams({ sandboxId: e.target.value });
                }
              }}
              style={{
                padding: "8px 12px",
                borderRadius: 6,
                backgroundColor: "var(--color-surface)",
                border: "1px solid var(--color-border)",
                color: "var(--color-text-primary)",
                fontSize: 13,
              }}
            >
              <option value="" disabled>
                Choose Sandbox...
              </option>
              {sandboxes.map((sb: SandboxDetail) => (
                <option key={sb.sandbox_id} value={sb.sandbox_id}>
                  {sb.sandbox_id.slice(0, 8)}... ({sb.runtime}, {sb.status})
                </option>
              ))}
            </select>
          </div>
        ) : (
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
            <ArrowLeft size={13} />
            Return to Sandboxes
          </Link>
        )}
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto" }}>
      {/* Navigation Breadcrumb */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          marginBottom: 16,
          fontSize: 12,
          color: "var(--color-text-muted)",
        }}
      >
        <Link
          to={`/dashboard/sandboxes/${effectiveSandboxId}`}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            color: "var(--color-text-muted)",
            textDecoration: "none",
          }}
        >
          <ArrowLeft size={13} />
          Back to Sandbox
        </Link>
        <span>/</span>
        <Link
          to={`/dashboard/executions?sandboxId=${effectiveSandboxId}`}
          style={{ color: "var(--color-text-muted)", textDecoration: "none" }}
        >
          Executions
        </Link>
        <span>/</span>
        <span style={{ color: "var(--color-text-primary)", fontFamily: "monospace" }}>
          {executionId?.slice(0, 8)}...
        </span>
      </div>

      {/* Loading State */}
      {isLoading && (
        <div style={{ maxWidth: 1000, margin: "0 auto", padding: "20px 0" }}>
          <div
            style={{
              height: 80,
              backgroundColor: "var(--color-surface)",
              borderRadius: 8,
              marginBottom: 16,
            }}
          />
          <div
            style={{
              height: 120,
              backgroundColor: "var(--color-surface)",
              borderRadius: 8,
              marginBottom: 16,
            }}
          />
          <div
            style={{
              height: 200,
              backgroundColor: "var(--color-surface)",
              borderRadius: 8,
            }}
          />
        </div>
      )}

      {/* Error State */}
      {isError && (
        <div
          style={{
            backgroundColor: "var(--color-surface)",
            border: "1px solid var(--color-danger)",
            borderRadius: 8,
            padding: "32px 24px",
            textAlign: "center",
            maxWidth: 600,
            margin: "40px auto",
          }}
        >
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              width: 44,
              height: 44,
              borderRadius: 10,
              backgroundColor: "var(--color-danger-subtle)",
              color: "var(--color-danger)",
              marginBottom: 12,
            }}
          >
            <AlertCircle size={22} />
          </div>
          <h3 style={{ margin: "0 0 8px", fontSize: 16, fontWeight: 600 }}>
            Execution Record Not Found
          </h3>
          <p
            style={{
              margin: "0 0 20px",
              fontSize: 13,
              color: "var(--color-text-muted)",
            }}
          >
            The execution job was not found within sandbox session{" "}
            <code style={{ color: "var(--color-text-primary)" }}>{effectiveSandboxId}</code>.
          </p>
          <div style={{ display: "flex", justifyContent: "center", gap: 10 }}>
            <button
              onClick={() => refetch()}
              style={{
                padding: "8px 14px",
                borderRadius: 6,
                backgroundColor: "var(--color-surface-2)",
                border: "1px solid var(--color-border)",
                color: "var(--color-text-primary)",
                fontSize: 12,
                cursor: "pointer",
              }}
            >
              Retry
            </button>
            <Link
              to={`/dashboard/sandboxes/${effectiveSandboxId}`}
              style={{
                padding: "8px 14px",
                borderRadius: 6,
                backgroundColor: "var(--color-accent)",
                color: "#ffffff",
                fontSize: 12,
                fontWeight: 500,
                textDecoration: "none",
              }}
            >
              Return to Sandbox
            </Link>
          </div>
        </div>
      )}

      {/* Execution Detail View */}
      {!isLoading && !isError && execution && (
        <ExecutionDetail
          execution={execution}
          onRefresh={refetch}
          isRefreshing={isFetching}
        />
      )}
    </div>
  );
}
