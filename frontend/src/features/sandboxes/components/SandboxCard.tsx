import { ArrowRight, Copy, Check, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { formatDate } from "@/lib/utils";
import { SandboxStatusBadge } from "./SandboxStatusBadge";
import { TTLRemaining } from "./TTLRemaining";
import type { SandboxDetail } from "../types";

interface SandboxCardProps {
  sandbox: SandboxDetail;
  onDestroy: (sandboxId: string) => void;
}

export function SandboxCard({ sandbox, onDestroy }: SandboxCardProps) {
  const [copied, setCopied] = useState(false);

  const handleCopyId = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(sandbox.sandbox_id);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const isDestroyed =
    sandbox.status === "destroyed" || sandbox.status === "destroying";

  return (
    <div
      style={{
        backgroundColor: "var(--color-surface)",
        border: "1px solid var(--color-border-subtle)",
        borderRadius: 8,
        padding: "18px 20px",
        display: "flex",
        flexDirection: "column",
        gap: 16,
        transition: "border-color 0.15s",
      }}
    >
      {/* Header Row: ID + Status */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span
            style={{
              fontFamily: "monospace",
              fontSize: 13,
              fontWeight: 600,
              color: "var(--color-text-primary)",
            }}
            title={sandbox.sandbox_id}
          >
            {sandbox.sandbox_id.slice(0, 8)}...{sandbox.sandbox_id.slice(-4)}
          </span>
          <button
            onClick={handleCopyId}
            title="Copy Sandbox ID"
            style={{
              background: "none",
              border: "none",
              color: copied ? "var(--color-success)" : "var(--color-text-muted)",
              cursor: "pointer",
              padding: 2,
              borderRadius: 3,
              display: "flex",
              alignItems: "center",
            }}
          >
            {copied ? <Check size={12} /> : <Copy size={12} />}
          </button>
        </div>
        <SandboxStatusBadge status={sandbox.status} />
      </div>

      {/* Metadata Grid */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(2, 1fr)",
          gap: "10px 16px",
          fontSize: 12,
        }}
      >
        <div>
          <span
            style={{
              display: "block",
              color: "var(--color-text-muted)",
              fontSize: 11,
              marginBottom: 2,
            }}
          >
            Runtime
          </span>
          <span
            style={{
              color: "var(--color-text-secondary)",
              fontWeight: 500,
              textTransform: "capitalize",
            }}
          >
            {sandbox.runtime}
          </span>
        </div>

        <div>
          <span
            style={{
              display: "block",
              color: "var(--color-text-muted)",
              fontSize: 11,
              marginBottom: 2,
            }}
          >
            Executions
          </span>
          <span
            style={{
              color: "var(--color-text-primary)",
              fontWeight: 600,
            }}
          >
            {sandbox.executions_count}
          </span>
        </div>

        <div>
          <span
            style={{
              display: "block",
              color: "var(--color-text-muted)",
              fontSize: 11,
              marginBottom: 2,
            }}
          >
            Created
          </span>
          <span style={{ color: "var(--color-text-secondary)" }}>
            {formatDate(sandbox.created_at)}
          </span>
        </div>

        <div>
          <span
            style={{
              display: "block",
              color: "var(--color-text-muted)",
              fontSize: 11,
              marginBottom: 2,
            }}
          >
            TTL
          </span>
          <TTLRemaining expiresAt={sandbox.expires_at} status={sandbox.status} />
        </div>
      </div>

      {/* Footer Actions */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          paddingTop: 12,
          borderTop: "1px solid var(--color-border-subtle)",
        }}
      >
        <Link
          to={`/dashboard/sandboxes/${sandbox.sandbox_id}`}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            fontSize: 12,
            fontWeight: 500,
            color: "var(--color-accent)",
            textDecoration: "none",
          }}
        >
          View Details
          <ArrowRight size={13} />
        </Link>

        <button
          onClick={() => onDestroy(sandbox.sandbox_id)}
          disabled={isDestroyed}
          title={isDestroyed ? "Already destroyed" : "Destroy sandbox"}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            padding: "5px 10px",
            borderRadius: 5,
            border: "1px solid var(--color-border)",
            backgroundColor: "transparent",
            color: isDestroyed ? "var(--color-text-muted)" : "var(--color-danger)",
            fontSize: 11,
            fontWeight: 500,
            cursor: isDestroyed ? "not-allowed" : "pointer",
            opacity: isDestroyed ? 0.4 : 1,
            transition: "color 0.15s, border-color 0.15s",
          }}
        >
          <Trash2 size={12} />
          Destroy
        </button>
      </div>
    </div>
  );
}
