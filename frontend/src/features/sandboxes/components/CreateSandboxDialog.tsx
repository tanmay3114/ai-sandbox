import { useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, X } from "lucide-react";
import { useCreateSandbox } from "../hooks/useCreateSandbox";
import type { SandboxResponse } from "../types";

interface CreateSandboxDialogProps {
  open: boolean;
  onClose: () => void;
  onCreated?: (sandbox: SandboxResponse) => void;
}

const SUPPORTED_RUNTIMES = [
  { id: "python", label: "Python 3.12 (Standard Runtime)" },
];

const TTL_PRESETS = [
  { label: "1 min", seconds: 60 },
  { label: "5 min", seconds: 300 },
  { label: "15 min", seconds: 900 },
  { label: "1 hour", seconds: 3600 },
];

export function CreateSandboxDialog({
  open,
  onClose,
  onCreated,
}: CreateSandboxDialogProps) {
  const [runtime, setRuntime] = useState<string>("python");
  const [ttlSeconds, setTtlSeconds] = useState<number>(300);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const { mutate: createSandboxMutate, isPending } = useCreateSandbox();

  if (!open) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);
    setSuccessMessage(null);

    // Client-side UX validation (backend remains authoritative)
    if (ttlSeconds < 10 || ttlSeconds > 86400) {
      setErrorMessage("TTL must be between 10 seconds and 86,400 seconds (24 hours).");
      return;
    }

    createSandboxMutate(
      { runtime, ttl_seconds: ttlSeconds },
      {
        onSuccess: (data) => {
          setSuccessMessage(`Sandbox created successfully.`);
          setTimeout(() => {
            onClose();
            onCreated?.(data);
          }, 800);
        },
        onError: (err: any) => {
          // Safe error handling: never leak stack traces or credentials
          const detail =
            err?.response?.data?.message ||
            err?.response?.data?.detail ||
            "Unable to create sandbox. Please verify configuration and try again.";
          setErrorMessage(typeof detail === "string" ? detail : "Validation failed.");
        },
      },
    );
  };

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        backgroundColor: "rgba(0, 0, 0, 0.7)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 50,
        padding: 16,
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget && !isPending) onClose();
      }}
    >
      <div
        style={{
          backgroundColor: "var(--color-surface)",
          border: "1px solid var(--color-border)",
          borderRadius: 10,
          width: "100%",
          maxWidth: 480,
          boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.5)",
          overflow: "hidden",
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
          }}
        >
          <div>
            <h2
              style={{
                margin: 0,
                fontSize: 15,
                fontWeight: 600,
                color: "var(--color-text-primary)",
              }}
            >
              Create Sandbox Session
            </h2>
            <p
              style={{
                margin: "4px 0 0",
                fontSize: 12,
                color: "var(--color-text-muted)",
              }}
            >
              Instantiate a new isolated, ephemeral execution environment.
            </p>
          </div>
          <button
            onClick={onClose}
            disabled={isPending}
            style={{
              background: "none",
              border: "none",
              color: "var(--color-text-muted)",
              cursor: isPending ? "not-allowed" : "pointer",
              padding: 4,
              borderRadius: 4,
              display: "flex",
            }}
          >
            <X size={16} />
          </button>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSubmit} style={{ padding: 20 }}>
          {errorMessage && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "10px 12px",
                borderRadius: 6,
                backgroundColor: "var(--color-danger-subtle)",
                border: "1px solid rgba(239, 68, 68, 0.3)",
                color: "var(--color-danger)",
                fontSize: 12,
                marginBottom: 16,
              }}
            >
              <AlertCircle size={14} style={{ flexShrink: 0 }} />
              <span>{errorMessage}</span>
            </div>
          )}

          {successMessage && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "10px 12px",
                borderRadius: 6,
                backgroundColor: "var(--color-success-subtle)",
                border: "1px solid rgba(16, 185, 129, 0.3)",
                color: "var(--color-success)",
                fontSize: 12,
                marginBottom: 16,
              }}
            >
              <CheckCircle2 size={14} style={{ flexShrink: 0 }} />
              <span>{successMessage}</span>
            </div>
          )}

          {/* Runtime Selector */}
          <div style={{ marginBottom: 16 }}>
            <label
              style={{
                display: "block",
                fontSize: 12,
                fontWeight: 500,
                color: "var(--color-text-secondary)",
                marginBottom: 6,
              }}
            >
              Runtime Environment
            </label>
            <select
              value={runtime}
              onChange={(e) => setRuntime(e.target.value)}
              disabled={isPending}
              style={{
                width: "100%",
                padding: "9px 12px",
                backgroundColor: "var(--color-surface-2)",
                border: "1px solid var(--color-border)",
                borderRadius: 6,
                color: "var(--color-text-primary)",
                fontSize: 13,
                outline: "none",
              }}
            >
              {SUPPORTED_RUNTIMES.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.label}
                </option>
              ))}
            </select>
            <span
              style={{
                display: "block",
                fontSize: 11,
                color: "var(--color-text-muted)",
                marginTop: 4,
              }}
            >
              Runtime image and security controls are managed authoritatively by the backend.
            </span>
          </div>

          {/* TTL Selector */}
          <div style={{ marginBottom: 20 }}>
            <label
              style={{
                display: "block",
                fontSize: 12,
                fontWeight: 500,
                color: "var(--color-text-secondary)",
                marginBottom: 6,
              }}
            >
              Time-to-Live (TTL in seconds)
            </label>
            <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
              <input
                type="number"
                value={ttlSeconds}
                onChange={(e) => setTtlSeconds(Number(e.target.value))}
                disabled={isPending}
                min={10}
                max={86400}
                style={{
                  flex: 1,
                  padding: "8px 12px",
                  backgroundColor: "var(--color-surface-2)",
                  border: "1px solid var(--color-border)",
                  borderRadius: 6,
                  color: "var(--color-text-primary)",
                  fontSize: 13,
                  outline: "none",
                }}
              />
              <span
                style={{
                  display: "flex",
                  alignItems: "center",
                  fontSize: 12,
                  color: "var(--color-text-muted)",
                  padding: "0 8px",
                }}
              >
                ({Math.round(ttlSeconds / 60)} min)
              </span>
            </div>

            {/* Presets */}
            <div style={{ display: "flex", gap: 6 }}>
              {TTL_PRESETS.map((p) => (
                <button
                  type="button"
                  key={p.seconds}
                  onClick={() => setTtlSeconds(p.seconds)}
                  disabled={isPending}
                  style={{
                    padding: "4px 8px",
                    borderRadius: 4,
                    border: "1px solid var(--color-border)",
                    backgroundColor:
                      ttlSeconds === p.seconds
                        ? "var(--color-accent-subtle)"
                        : "transparent",
                    color:
                      ttlSeconds === p.seconds
                        ? "var(--color-accent)"
                        : "var(--color-text-muted)",
                    fontSize: 11,
                    cursor: "pointer",
                    fontWeight: ttlSeconds === p.seconds ? 600 : 400,
                  }}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {/* Actions */}
          <div
            style={{
              display: "flex",
              justifyContent: "flex-end",
              gap: 10,
              paddingTop: 12,
              borderTop: "1px solid var(--color-border-subtle)",
            }}
          >
            <button
              type="button"
              onClick={onClose}
              disabled={isPending}
              style={{
                padding: "8px 14px",
                borderRadius: 6,
                border: "1px solid var(--color-border)",
                backgroundColor: "transparent",
                color: "var(--color-text-secondary)",
                fontSize: 12,
                fontWeight: 500,
                cursor: isPending ? "not-allowed" : "pointer",
              }}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isPending}
              style={{
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
                cursor: isPending ? "not-allowed" : "pointer",
                opacity: isPending ? 0.7 : 1,
              }}
            >
              {isPending && <Loader2 size={13} className="animate-spin" />}
              {isPending ? "Creating..." : "Create Sandbox"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
