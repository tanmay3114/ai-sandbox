import { Bot, PlaySquare, Plus } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { StatCard } from "@/components/dashboard/StatCard";
import { RecentExecutions } from "@/components/dashboard/RecentExecutions";
import { SystemStatus } from "@/components/dashboard/SystemStatus";

// Demo stat values — clearly labelled as demo data, not fetched from backend
const STAT_CARDS = [
  {
    label: "Active Sandboxes",
    value: 3,
    delta: "+1 today",
    deltaType: "positive" as const,
    icon: "Container",
    description: "demo",
  },
  {
    label: "Total Executions",
    value: 142,
    delta: "+18 today",
    deltaType: "positive" as const,
    icon: "PlaySquare",
    description: "demo",
  },
  {
    label: "Agent Runs",
    value: 7,
    delta: "last 24h",
    deltaType: "neutral" as const,
    icon: "Bot",
    description: "demo",
  },
  {
    label: "Policy Violations",
    value: 0,
    delta: "All clear",
    deltaType: "positive" as const,
    icon: "Shield",
    description: "demo",
  },
];

export function Dashboard() {
  const navigate = useNavigate();

  return (
    <div style={{ maxWidth: 1100 }}>
      {/* Demo data notice */}
      <div
        style={{
          marginBottom: 20,
          padding: "8px 14px",
          borderRadius: 6,
          border: "1px solid var(--color-border)",
          backgroundColor: "var(--color-surface-2)",
          fontSize: 12,
          color: "var(--color-text-muted)",
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <span
          style={{
            fontWeight: 600,
            color: "var(--color-warning)",
            fontSize: 10,
            letterSpacing: "0.05em",
          }}
        >
          DEMO
        </span>
        Dashboard displays static placeholder data. Start the backend at{" "}
        <code
          style={{
            fontFamily: "monospace",
            fontSize: 11,
            color: "var(--color-text-secondary)",
          }}
        >
          {import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000"}
        </code>{" "}
        for live data.
      </div>

      {/* Stat Cards */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 12,
          marginBottom: 20,
        }}
      >
        {STAT_CARDS.map((card) => (
          <StatCard key={card.label} {...card} />
        ))}
      </div>

      {/* Main grid: recent executions + system status */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 320px",
          gap: 16,
          marginBottom: 20,
        }}
      >
        <RecentExecutions />
        <SystemStatus />
      </div>

      {/* Quick Actions */}
      <div
        style={{
          backgroundColor: "var(--color-surface)",
          border: "1px solid var(--color-border-subtle)",
          borderRadius: 8,
          padding: "16px 20px",
        }}
      >
        <div
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: "var(--color-text-primary)",
            marginBottom: 12,
          }}
        >
          Quick Actions
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button
            onClick={() => navigate("/dashboard/sandboxes")}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "8px 14px",
              borderRadius: 6,
              border: "1px solid var(--color-border)",
              backgroundColor: "var(--color-surface-2)",
              color: "var(--color-text-primary)",
              fontSize: 12,
              fontWeight: 500,
              cursor: "pointer",
              transition: "border-color 0.1s",
            }}
          >
            <Plus size={13} />
            New Sandbox
          </button>
          <button
            onClick={() => navigate("/dashboard/executions")}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "8px 14px",
              borderRadius: 6,
              border: "1px solid var(--color-border)",
              backgroundColor: "var(--color-surface-2)",
              color: "var(--color-text-primary)",
              fontSize: 12,
              fontWeight: 500,
              cursor: "pointer",
            }}
          >
            <PlaySquare size={13} />
            Run Code
          </button>
          <button
            onClick={() => navigate("/dashboard/agent")}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "8px 14px",
              borderRadius: 6,
              border: "1px solid var(--color-border)",
              backgroundColor: "var(--color-surface-2)",
              color: "var(--color-text-primary)",
              fontSize: 12,
              fontWeight: 500,
              cursor: "pointer",
            }}
          >
            <Bot size={13} />
            Ask Agent
          </button>
        </div>
      </div>
    </div>
  );
}
