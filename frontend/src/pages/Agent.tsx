import { Bot } from "lucide-react";

export function Agent() {
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
      <Bot size={36} color="var(--color-border)" />
      <div
        style={{
          fontSize: 15,
          fontWeight: 600,
          color: "var(--color-text-secondary)",
        }}
      >
        AI Agent
      </div>
      <div style={{ fontSize: 13 }}>
        Agent chat interface coming in Module 2.
      </div>
    </div>
  );
}
