import { useLocation } from "react-router-dom";

const ROUTE_LABELS: Record<string, string> = {
  "/dashboard": "Dashboard",
  "/dashboard/sandboxes": "Sandboxes",
  "/dashboard/executions": "Executions",
  "/dashboard/agent": "Agent",
  "/dashboard/security": "Security",
};

export function Header() {
  const location = useLocation();
  let label = ROUTE_LABELS[location.pathname];
  if (!label && location.pathname.startsWith("/dashboard/sandboxes/")) {
    label = "Sandbox Details";
  }
  if (!label) {
    label = "Dashboard";
  }

  return (
    <header
      style={{
        height: 52,
        borderBottom: "1px solid var(--color-border-subtle)",
        display: "flex",
        alignItems: "center",
        padding: "0 24px",
        backgroundColor: "var(--color-surface)",
        flexShrink: 0,
        gap: 12,
      }}
    >
      <h1
        style={{
          margin: 0,
          fontSize: 14,
          fontWeight: 600,
          color: "var(--color-text-primary)",
          letterSpacing: "0.01em",
        }}
      >
        {label}
      </h1>
      <div style={{ flex: 1 }} />
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          fontSize: 11,
          color: "var(--color-text-muted)",
        }}
      >
        <span
          style={{
            display: "inline-block",
            width: 6,
            height: 6,
            borderRadius: "50%",
            backgroundColor: "var(--color-success)",
          }}
        />
        System Operational
      </div>
    </header>
  );
}
