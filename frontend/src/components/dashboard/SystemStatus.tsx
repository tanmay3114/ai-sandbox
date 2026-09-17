import { CheckCircle, Database, Server, XCircle } from "lucide-react";

interface ServiceRowProps {
  label: string;
  status: "ok" | "error" | "unknown";
  detail?: string;
  icon: React.ElementType;
}

function ServiceRow({ label, status, detail, icon: Icon }: ServiceRowProps) {
  const isOk = status === "ok";
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "10px 0",
        borderBottom: "1px solid var(--color-border-subtle)",
      }}
    >
      <div
        style={{
          width: 32,
          height: 32,
          borderRadius: 6,
          backgroundColor: isOk
            ? "var(--color-success-subtle)"
            : "var(--color-danger-subtle)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
        }}
      >
        <Icon
          size={14}
          color={isOk ? "var(--color-success)" : "var(--color-danger)"}
        />
      </div>
      <div style={{ flex: 1 }}>
        <div
          style={{
            fontSize: 13,
            fontWeight: 500,
            color: "var(--color-text-primary)",
          }}
        >
          {label}
        </div>
        {detail && (
          <div
            style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 1 }}
          >
            {detail}
          </div>
        )}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
        {isOk ? (
          <CheckCircle size={14} color="var(--color-success)" />
        ) : (
          <XCircle size={14} color="var(--color-danger)" />
        )}
        <span
          style={{
            fontSize: 11,
            color: isOk ? "var(--color-success)" : "var(--color-danger)",
            fontWeight: 500,
          }}
        >
          {isOk ? "Operational" : "Degraded"}
        </span>
      </div>
    </div>
  );
}

export function SystemStatus() {
  // Demo values — clearly labelled as such
  const services: ServiceRowProps[] = [
    {
      label: "FastAPI Backend",
      status: "ok",
      detail: "HTTP API · Port 8000",
      icon: Server,
    },
    {
      label: "PostgreSQL",
      status: "ok",
      detail: "Primary database · Connected",
      icon: Database,
    },
    {
      label: "Docker Engine",
      status: "ok",
      detail: "Sandbox execution backend",
      icon: Server,
    },
  ];

  return (
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
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 4,
        }}
      >
        <span
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: "var(--color-text-primary)",
          }}
        >
          System Status
        </span>
        <span
          style={{
            fontSize: 10,
            color: "var(--color-text-muted)",
            padding: "2px 6px",
            borderRadius: 4,
            border: "1px solid var(--color-border)",
            letterSpacing: "0.04em",
          }}
        >
          DEMO
        </span>
      </div>
      <div>
        {services.map((s) => (
          <ServiceRow key={s.label} {...s} />
        ))}
      </div>
      <div style={{ marginTop: 10, fontSize: 11, color: "var(--color-text-muted)" }}>
        Demo data · Connect backend for live status
      </div>
    </div>
  );
}
