import { CheckCircle2, Code2, Container } from "lucide-react";
import type { SecurityRuntime } from "../types";

interface ApprovedRuntimeProps {
  runtime: SecurityRuntime;
}

export function ApprovedRuntime({ runtime }: ApprovedRuntimeProps) {
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
          Approved Runtime & Container Images
        </h3>
        <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
          Only explicitly whitelisted container images are accepted by the SecurityPolicyEngine
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
          gap: 12,
        }}
      >
        {Object.entries(runtime.allowed_runtimes).map(([name, image]) => (
          <div
            key={name}
            style={{
              backgroundColor: "var(--color-surface-2)",
              border: "1px solid var(--color-border)",
              borderRadius: 6,
              padding: "16px",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <div
                style={{
                  width: 36,
                  height: 36,
                  borderRadius: 6,
                  backgroundColor: "var(--color-surface-3)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "var(--color-accent)",
                }}
              >
                <Code2 size={20} />
              </div>
              <div>
                <div
                  style={{
                    fontSize: 14,
                    fontWeight: 600,
                    color: "var(--color-text-primary)",
                    textTransform: "capitalize",
                  }}
                >
                  {name}
                </div>
                <div
                  style={{
                    fontFamily: "monospace",
                    fontSize: 12,
                    color: "var(--color-text-secondary)",
                    display: "flex",
                    alignItems: "center",
                    gap: 4,
                    marginTop: 2,
                  }}
                >
                  <Container size={12} />
                  {image}
                </div>
              </div>
            </div>

            <span
              style={{
                fontSize: 11,
                fontWeight: 700,
                color: "var(--color-success)",
                backgroundColor: "var(--color-success-subtle)",
                padding: "3px 8px",
                borderRadius: 4,
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
              }}
            >
              <CheckCircle2 size={12} />
              APPROVED
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
