import { ArrowRight, Bot, Container, Layers, ShieldCheck, Terminal } from "lucide-react";

export function ArchitectureDiagram() {
  const steps = [
    {
      title: "AI Agent / Caller",
      subtitle: "Untrusted Client",
      description: "Generates untrusted code or execution requests without Docker access",
      icon: Bot,
      color: "var(--color-text-primary)",
      badge: "UNTRUSTED",
      badgeColor: "var(--color-warning)",
      badgeBg: "var(--color-warning-subtle)",
    },
    {
      title: "Tool Request",
      subtitle: "Requested Policy",
      description: "Carries parameters (code, optional timeout, memory, runtime)",
      icon: Terminal,
      color: "var(--color-text-secondary)",
      badge: "UNVERIFIED",
      badgeColor: "var(--color-text-muted)",
      badgeBg: "var(--color-surface-3)",
    },
    {
      title: "Security Policy Engine",
      subtitle: "Defense-in-Depth Layer",
      description: "Validates invariants, clamps resource bounds, or rejects forbidden requests",
      icon: ShieldCheck,
      color: "var(--color-accent)",
      badge: "AUTHORITATIVE",
      badgeColor: "var(--color-accent)",
      badgeBg: "var(--color-accent-subtle)",
    },
    {
      title: "Effective Policy",
      subtitle: "Immutable Sandbox Spec",
      description: "FrozenDict & tuples guaranteeing deep immutability before dispatch",
      icon: Layers,
      color: "var(--color-info)",
      badge: "VERIFIED",
      badgeColor: "var(--color-info)",
      badgeBg: "var(--color-info-subtle)",
    },
    {
      title: "Ephemeral Engine",
      subtitle: "Docker Isolation",
      description: "Single-request container execution destroyed immediately upon completion",
      icon: Container,
      color: "var(--color-success)",
      badge: "CONTAINED",
      badgeColor: "var(--color-success)",
      badgeBg: "var(--color-success-subtle)",
    },
  ];

  return (
    <div
      style={{
        backgroundColor: "var(--color-surface)",
        border: "1px solid var(--color-border-subtle)",
        borderRadius: 8,
        padding: "20px 24px",
      }}
    >
      <div style={{ marginBottom: 16 }}>
        <h3
          style={{
            margin: "0 0 4px",
            fontSize: 16,
            fontWeight: 600,
            color: "var(--color-text-primary)",
          }}
        >
          Security Enforcement Pipeline
        </h3>
        <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
          The AI Agent is untrusted. The backend Security Policy Engine authoritatively validates and normalizes all requests before Docker containerization.
        </div>
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "stretch",
          gap: 8,
          overflowX: "auto",
          paddingBottom: 8,
        }}
      >
        {steps.map((step, idx) => {
          const IconComponent = step.icon;
          return (
            <div
              key={step.title}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                flex: "1 0 190px",
              }}
            >
              <div
                style={{
                  backgroundColor: "var(--color-surface-2)",
                  border: "1px solid var(--color-border)",
                  borderRadius: 6,
                  padding: "14px",
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "space-between",
                  flex: 1,
                  minHeight: 140,
                }}
              >
                <div>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      marginBottom: 8,
                    }}
                  >
                    <IconComponent size={18} color={step.color} />
                    <span
                      style={{
                        fontSize: 9,
                        fontWeight: 700,
                        padding: "1px 5px",
                        borderRadius: 3,
                        color: step.badgeColor,
                        backgroundColor: step.badgeBg,
                        letterSpacing: "0.04em",
                      }}
                    >
                      {step.badge}
                    </span>
                  </div>
                  <div
                    style={{
                      fontSize: 13,
                      fontWeight: 600,
                      color: "var(--color-text-primary)",
                      marginBottom: 2,
                    }}
                  >
                    {step.title}
                  </div>
                  <div
                    style={{
                      fontSize: 11,
                      fontWeight: 500,
                      color: "var(--color-text-secondary)",
                      marginBottom: 6,
                    }}
                  >
                    {step.subtitle}
                  </div>
                </div>

                <div
                  style={{
                    fontSize: 11,
                    color: "var(--color-text-muted)",
                    lineHeight: 1.3,
                  }}
                >
                  {step.description}
                </div>
              </div>

              {idx < steps.length - 1 && (
                <div style={{ color: "var(--color-text-muted)", flexShrink: 0 }}>
                  <ArrowRight size={14} />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
