import { PlaySquare } from "lucide-react";

export function Executions() {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        minHeight: 400,
        gap: 12,
        color: "var(--color-text-muted)",
      }}
    >
      <PlaySquare size={36} color="var(--color-border)" />
      <div
        style={{
          fontSize: 15,
          fontWeight: 600,
          color: "var(--color-text-secondary)",
        }}
      >
        Executions
      </div>
      <div style={{ fontSize: 13 }}>
        Execution history and details coming in Module 2.
      </div>
    </div>
  );
}
