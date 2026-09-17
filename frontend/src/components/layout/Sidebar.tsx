import {
  Bot,
  Container,
  LayoutDashboard,
  PlaySquare,
  Shield,
} from "lucide-react";
import { NavLink } from "react-router-dom";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/dashboard/sandboxes", label: "Sandboxes", icon: Container },
  { to: "/dashboard/executions", label: "Executions", icon: PlaySquare },
  { to: "/dashboard/agent", label: "Agent", icon: Bot },
  { to: "/dashboard/security", label: "Security", icon: Shield },
];

export function Sidebar() {
  return (
    <aside
      style={{
        width: 220,
        minHeight: "100vh",
        backgroundColor: "var(--color-surface)",
        borderRight: "1px solid var(--color-border-subtle)",
        display: "flex",
        flexDirection: "column",
        flexShrink: 0,
      }}
    >
      {/* Logo / wordmark */}
      <div
        style={{
          padding: "20px 20px 16px",
          borderBottom: "1px solid var(--color-border-subtle)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div
            style={{
              width: 28,
              height: 28,
              borderRadius: 6,
              backgroundColor: "var(--color-accent)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <Container size={14} color="white" />
          </div>
          <div>
            <div
              style={{
                fontSize: 13,
                fontWeight: 600,
                color: "var(--color-text-primary)",
                letterSpacing: "0.01em",
                lineHeight: 1.2,
              }}
            >
              AI Sandbox
            </div>
            <div
              style={{
                fontSize: 10,
                color: "var(--color-text-muted)",
                letterSpacing: "0.05em",
                textTransform: "uppercase",
              }}
            >
              Platform
            </div>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav style={{ padding: "12px 10px", flex: 1 }}>
        <div
          style={{
            fontSize: 10,
            color: "var(--color-text-muted)",
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            padding: "0 10px",
            marginBottom: 6,
            marginTop: 4,
          }}
        >
          Navigation
        </div>
        {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            style={({ isActive }) => ({
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "8px 10px",
              borderRadius: 6,
              textDecoration: "none",
              fontSize: 13,
              fontWeight: isActive ? 500 : 400,
              color: isActive
                ? "var(--color-text-primary)"
                : "var(--color-text-secondary)",
              backgroundColor: isActive
                ? "var(--color-surface-3)"
                : "transparent",
              marginBottom: 2,
              transition: "background-color 0.1s, color 0.1s",
            })}
            className={({ isActive }) =>
              cn("sidebar-nav-link", isActive && "active")
            }
          >
            <Icon size={15} />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div
        style={{
          padding: "12px 20px",
          borderTop: "1px solid var(--color-border-subtle)",
          fontSize: 11,
          color: "var(--color-text-muted)",
        }}
      >
        Phase 5 · Ephemeral Execution
      </div>
    </aside>
  );
}
