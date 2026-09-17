import { AlertCircle, RefreshCw, ShieldCheck } from "lucide-react";
import { ApprovedRuntime } from "../components/ApprovedRuntime";
import { ArchitectureDiagram } from "../components/ArchitectureDiagram";
import { PolicyEvaluator } from "../components/PolicyEvaluator";
import { ResourceLimits } from "../components/ResourceLimits";
import { SecurityBoundaries } from "../components/SecurityBoundaries";
import { useSecurityPolicy } from "../hooks/useSecurity";

export function SecurityPage() {
  const { data: policy, isLoading, isError, error, refetch, isFetching } = useSecurityPolicy();

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
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
            <div
              style={{
                width: 32,
                height: 32,
                borderRadius: 8,
                backgroundColor: "var(--color-accent)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "#ffffff",
              }}
            >
              <ShieldCheck size={18} />
            </div>
            <h1
              style={{
                margin: 0,
                fontSize: 20,
                fontWeight: 700,
                color: "var(--color-text-primary)",
              }}
            >
              Security Policy & Enforcement
            </h1>
          </div>
          <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
            Authoritative Phase 5 Defense-in-Depth layer protecting host infrastructure against untrusted AI agent code
          </div>
        </div>

        <button
          type="button"
          onClick={() => refetch()}
          disabled={isFetching}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            padding: "8px 14px",
            borderRadius: 6,
            border: "1px solid var(--color-border)",
            backgroundColor: "var(--color-surface-2)",
            color: "var(--color-text-secondary)",
            fontSize: 12,
            fontWeight: 500,
            cursor: isFetching ? "not-allowed" : "pointer",
          }}
        >
          <RefreshCw
            size={13}
            style={{
              animation: isFetching ? "spin 1s linear infinite" : "none",
            }}
          />
          Refresh Policy
        </button>
      </div>

      {/* Loading Skeleton */}
      {isLoading && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={{ height: 140, backgroundColor: "var(--color-surface)", borderRadius: 8 }} />
          <div style={{ height: 280, backgroundColor: "var(--color-surface)", borderRadius: 8 }} />
          <div style={{ height: 200, backgroundColor: "var(--color-surface)", borderRadius: 8 }} />
        </div>
      )}

      {/* Error View */}
      {isError && (
        <div
          style={{
            backgroundColor: "var(--color-surface)",
            border: "1px solid var(--color-danger)",
            borderRadius: 8,
            padding: "32px 24px",
            textAlign: "center",
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
            Failed to Load Security Policy
          </h3>
          <p style={{ margin: "0 0 16px", fontSize: 13, color: "var(--color-text-muted)" }}>
            Unable to connect to the backend security policy endpoint: {(error as any)?.message}
          </p>
          <button
            type="button"
            onClick={() => refetch()}
            style={{
              padding: "8px 16px",
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
        </div>
      )}

      {/* Main Content */}
      {!isLoading && !isError && policy && (
        <>
          <ArchitectureDiagram />
          <SecurityBoundaries invariants={policy.invariants} />
          <ResourceLimits limits={policy.resource_limits} />
          <ApprovedRuntime runtime={policy.runtime} />
          <PolicyEvaluator />
        </>
      )}
    </div>
  );
}
