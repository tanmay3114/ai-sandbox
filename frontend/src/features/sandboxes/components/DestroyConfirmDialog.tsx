import { useState } from "react";
import { AlertCircle, AlertTriangle, Loader2 } from "lucide-react";
import { useDestroySandbox } from "../hooks/useDestroySandbox";

interface DestroyConfirmDialogProps {
  open: boolean;
  sandboxId: string | null;
  onClose: () => void;
  onDestroyed?: () => void;
}

export function DestroyConfirmDialog({
  open,
  sandboxId,
  onClose,
  onDestroyed,
}: DestroyConfirmDialogProps) {
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const { mutate: destroyMutate, isPending } = useDestroySandbox();

  if (!open || !sandboxId) return null;

  const handleDestroy = () => {
    setErrorMessage(null);
    destroyMutate(sandboxId, {
      onSuccess: () => {
        onClose();
        onDestroyed?.();
      },
      onError: (err: any) => {
        const status = err?.response?.status;
        if (status === 404) {
          setErrorMessage("Sandbox not found or already removed.");
        } else if (status === 409) {
          setErrorMessage("Sandbox is currently executing a job. Please wait for completion.");
        } else if (status === 503) {
          setErrorMessage("Docker execution backend is currently unavailable.");
        } else {
          setErrorMessage(
            err?.response?.data?.message || "Unable to destroy sandbox. Please try again.",
          );
        }
      },
    });
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
          maxWidth: 420,
          boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.5)",
          padding: 20,
        }}
      >
        <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 16 }}>
          <div
            style={{
              width: 36,
              height: 36,
              borderRadius: 8,
              backgroundColor: "var(--color-danger-subtle)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
            }}
          >
            <AlertTriangle size={18} color="var(--color-danger)" />
          </div>
          <div>
            <h3
              style={{
                margin: 0,
                fontSize: 15,
                fontWeight: 600,
                color: "var(--color-text-primary)",
              }}
            >
              Destroy sandbox?
            </h3>
            <p
              style={{
                margin: "6px 0 0",
                fontSize: 12,
                color: "var(--color-text-muted)",
                lineHeight: 1.4,
              }}
            >
              This will permanently destroy the sandbox session and release any associated
              ephemeral containers.
            </p>
            <div
              style={{
                marginTop: 8,
                padding: "4px 8px",
                borderRadius: 4,
                backgroundColor: "var(--color-surface-2)",
                fontFamily: "monospace",
                fontSize: 11,
                color: "var(--color-text-secondary)",
              }}
            >
              {sandboxId}
            </div>
          </div>
        </div>

        {errorMessage && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "8px 12px",
              borderRadius: 6,
              backgroundColor: "var(--color-danger-subtle)",
              color: "var(--color-danger)",
              fontSize: 12,
              marginBottom: 16,
            }}
          >
            <AlertCircle size={14} style={{ flexShrink: 0 }} />
            <span>{errorMessage}</span>
          </div>
        )}

        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: 10,
          }}
        >
          <button
            type="button"
            onClick={onClose}
            disabled={isPending}
            style={{
              padding: "7px 14px",
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
            type="button"
            onClick={handleDestroy}
            disabled={isPending}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "7px 14px",
              borderRadius: 6,
              border: "none",
              backgroundColor: "var(--color-danger)",
              color: "#ffffff",
              fontSize: 12,
              fontWeight: 600,
              cursor: isPending ? "not-allowed" : "pointer",
              opacity: isPending ? 0.7 : 1,
            }}
          >
            {isPending && <Loader2 size={13} className="animate-spin" />}
            {isPending ? "Destroying..." : "Destroy"}
          </button>
        </div>
      </div>
    </div>
  );
}
