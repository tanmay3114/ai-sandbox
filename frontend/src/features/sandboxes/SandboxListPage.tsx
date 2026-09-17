import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertCircle,
  Container,
  Plus,
  RefreshCw,
  Search,
} from "lucide-react";
import { CreateSandboxDialog } from "./components/CreateSandboxDialog";
import { DestroyConfirmDialog } from "./components/DestroyConfirmDialog";
import { SandboxCard } from "./components/SandboxCard";
import { useSandboxes } from "./hooks/useSandboxes";
import type { SandboxDetail } from "./types";

type StatusFilter = "ALL" | "RUNNING" | "EXPIRED" | "DESTROYED";

export function SandboxListPage() {
  const navigate = useNavigate();
  const { data: sandboxes, isLoading, isError, refetch, isFetching } =
    useSandboxes();

  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("ALL");
  const [createOpen, setCreateOpen] = useState(false);
  const [destroyTargetId, setDestroyTargetId] = useState<string | null>(null);

  // Client-side filtering
  const filteredSandboxes = (sandboxes ?? []).filter((sb: SandboxDetail) => {
    // Search match
    const matchesSearch =
      !searchQuery.trim() ||
      sb.sandbox_id.toLowerCase().includes(searchQuery.trim().toLowerCase());

    // Status match
    let matchesStatus = true;
    if (statusFilter === "RUNNING") {
      matchesStatus =
        sb.status === "running" ||
        sb.status === "creating" ||
        sb.status === "executing";
    } else if (statusFilter === "EXPIRED") {
      matchesStatus = sb.status === "expired";
    } else if (statusFilter === "DESTROYED") {
      matchesStatus =
        sb.status === "destroyed" || sb.status === "destroying";
    }

    return matchesSearch && matchesStatus;
  });

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto" }}>
      {/* Top Header Section */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          marginBottom: 24,
          flexWrap: "wrap",
          gap: 16,
        }}
      >
        <div>
          <h1
            style={{
              margin: 0,
              fontSize: 20,
              fontWeight: 700,
              color: "var(--color-text-primary)",
              letterSpacing: "-0.01em",
            }}
          >
            Sandboxes
          </h1>
          <p
            style={{
              margin: "4px 0 0",
              fontSize: 13,
              color: "var(--color-text-muted)",
            }}
          >
            Manage your isolated execution environments.
          </p>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            title="Refresh sandbox list"
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
              cursor: isFetching ? "not-allowed" : "pointer",
            }}
          >
            <RefreshCw
              size={13}
              style={{
                animation: isFetching ? "spin 1s linear infinite" : "none",
              }}
            />
            Refresh
          </button>

          <button
            onClick={() => setCreateOpen(true)}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "8px 14px",
              borderRadius: 6,
              border: "none",
              backgroundColor: "var(--color-accent)",
              color: "#ffffff",
              fontSize: 12,
              fontWeight: 600,
              cursor: "pointer",
              boxShadow: "0 1px 2px rgba(0, 0, 0, 0.2)",
            }}
          >
            <Plus size={14} />
            Create Sandbox
          </button>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 16,
          marginBottom: 20,
          flexWrap: "wrap",
        }}
      >
        {/* Search Input */}
        <div
          style={{
            position: "relative",
            minWidth: 260,
            flex: "1 1 260px",
            maxWidth: 380,
          }}
        >
          <Search
            size={14}
            color="var(--color-text-muted)"
            style={{
              position: "absolute",
              left: 12,
              top: "50%",
              transform: "translateY(-50%)",
            }}
          />
          <input
            type="text"
            placeholder="Search by Sandbox ID..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{
              width: "100%",
              padding: "8px 12px 8px 34px",
              backgroundColor: "var(--color-surface)",
              border: "1px solid var(--color-border)",
              borderRadius: 6,
              color: "var(--color-text-primary)",
              fontSize: 12,
              outline: "none",
            }}
          />
        </div>

        {/* Status Filter Buttons */}
        <div style={{ display: "flex", gap: 6 }}>
          {(["ALL", "RUNNING", "EXPIRED", "DESTROYED"] as StatusFilter[]).map(
            (status) => (
              <button
                key={status}
                onClick={() => setStatusFilter(status)}
                style={{
                  padding: "5px 10px",
                  borderRadius: 5,
                  fontSize: 11,
                  fontWeight: 500,
                  cursor: "pointer",
                  border: "1px solid",
                  borderColor:
                    statusFilter === status
                      ? "var(--color-accent)"
                      : "var(--color-border)",
                  backgroundColor:
                    statusFilter === status
                      ? "var(--color-accent-subtle)"
                      : "transparent",
                  color:
                    statusFilter === status
                      ? "var(--color-accent)"
                      : "var(--color-text-secondary)",
                }}
              >
                {status.charAt(0) + status.slice(1).toLowerCase()}
              </button>
            ),
          )}
        </div>
      </div>

      {/* Error state */}
      {isError && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "12px 16px",
            borderRadius: 8,
            backgroundColor: "var(--color-danger-subtle)",
            border: "1px solid rgba(239, 68, 68, 0.3)",
            color: "var(--color-danger)",
            fontSize: 13,
            marginBottom: 20,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <AlertCircle size={16} style={{ flexShrink: 0 }} />
            <span>
              Failed to load sandboxes. Please ensure the backend is running.
            </span>
          </div>
          <button
            onClick={() => refetch()}
            style={{
              padding: "4px 10px",
              borderRadius: 4,
              border: "1px solid var(--color-danger)",
              backgroundColor: "transparent",
              color: "var(--color-danger)",
              fontSize: 11,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Retry
          </button>
        </div>
      )}

      {/* Loading Skeleton */}
      {isLoading && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
            gap: 16,
          }}
        >
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              style={{
                backgroundColor: "var(--color-surface)",
                border: "1px solid var(--color-border-subtle)",
                borderRadius: 8,
                padding: "20px",
                height: 180,
                display: "flex",
                flexDirection: "column",
                gap: 16,
                opacity: 0.6,
              }}
            >
              <div
                style={{
                  height: 16,
                  width: "60%",
                  backgroundColor: "var(--color-surface-2)",
                  borderRadius: 4,
                }}
              />
              <div
                style={{
                  height: 40,
                  width: "100%",
                  backgroundColor: "var(--color-surface-2)",
                  borderRadius: 4,
                }}
              />
              <div
                style={{
                  height: 24,
                  width: "40%",
                  backgroundColor: "var(--color-surface-2)",
                  borderRadius: 4,
                  marginTop: "auto",
                }}
              />
            </div>
          ))}
        </div>
      )}

      {/* Empty State */}
      {!isLoading && !isError && filteredSandboxes.length === 0 && (
        <div
          style={{
            backgroundColor: "var(--color-surface)",
            border: "1px solid var(--color-border-subtle)",
            borderRadius: 8,
            padding: "48px 24px",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            textAlign: "center",
            gap: 12,
          }}
        >
          <div
            style={{
              width: 48,
              height: 48,
              borderRadius: 10,
              backgroundColor: "var(--color-surface-2)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              marginBottom: 4,
            }}
          >
            <Container size={24} color="var(--color-text-muted)" />
          </div>

          <h3
            style={{
              margin: 0,
              fontSize: 16,
              fontWeight: 600,
              color: "var(--color-text-primary)",
            }}
          >
            {searchQuery || statusFilter !== "ALL"
              ? "No matching sandboxes"
              : "No sandboxes yet"}
          </h3>

          <p
            style={{
              margin: 0,
              fontSize: 13,
              color: "var(--color-text-muted)",
              maxWidth: 360,
            }}
          >
            {searchQuery || statusFilter !== "ALL"
              ? "Try adjusting your search or filter parameters."
              : "Create your first isolated execution environment."}
          </p>

          {!searchQuery && statusFilter === "ALL" && (
            <button
              onClick={() => setCreateOpen(true)}
              style={{
                marginTop: 8,
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                padding: "8px 16px",
                borderRadius: 6,
                border: "none",
                backgroundColor: "var(--color-accent)",
                color: "#ffffff",
                fontSize: 12,
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              <Plus size={14} />
              Create Sandbox
            </button>
          )}
        </div>
      )}

      {/* Sandboxes Grid */}
      {!isLoading && !isError && filteredSandboxes.length > 0 && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
            gap: 16,
          }}
        >
          {filteredSandboxes.map((sb) => (
            <SandboxCard
              key={sb.sandbox_id}
              sandbox={sb}
              onDestroy={(id) => setDestroyTargetId(id)}
            />
          ))}
        </div>
      )}

      {/* Dialogs */}
      <CreateSandboxDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(created) => navigate(`/dashboard/sandboxes/${created.sandbox_id}`)}
      />

      <DestroyConfirmDialog
        open={Boolean(destroyTargetId)}
        sandboxId={destroyTargetId}
        onClose={() => setDestroyTargetId(null)}
      />
    </div>
  );
}
