import { Loader2, Play } from "lucide-react";

interface RunCodeButtonProps {
  onRun: () => void;
  isPending: boolean;
  disabled?: boolean;
  title?: string;
}

export function RunCodeButton({
  onRun,
  isPending,
  disabled = false,
  title,
}: RunCodeButtonProps) {
  return (
    <button
      onClick={onRun}
      disabled={disabled || isPending}
      title={title ?? (disabled ? "Cannot run code" : "Run Python code (⌘+Enter / Ctrl+Enter)")}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 8,
        padding: "8px 18px",
        borderRadius: 6,
        backgroundColor: disabled || isPending ? "var(--color-surface-2)" : "var(--color-accent)",
        color: disabled || isPending ? "var(--color-text-muted)" : "#ffffff",
        border: "1px solid",
        borderColor: disabled || isPending ? "var(--color-border)" : "transparent",
        fontSize: 13,
        fontWeight: 600,
        cursor: disabled || isPending ? "not-allowed" : "pointer",
        transition: "all 0.15s ease",
        opacity: disabled ? 0.6 : 1,
      }}
    >
      {isPending ? (
        <>
          <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} />
          <span>Executing...</span>
        </>
      ) : (
        <>
          <Play size={14} fill="currentColor" />
          <span>Run Code</span>
          <span
            style={{
              fontSize: 10,
              padding: "1px 5px",
              borderRadius: 3,
              backgroundColor: "rgba(255, 255, 255, 0.2)",
              color: "inherit",
              marginLeft: 2,
            }}
          >
            ⌘↵
          </span>
        </>
      )}
    </button>
  );
}
