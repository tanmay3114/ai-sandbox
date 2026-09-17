import type { SandboxStatus } from "../types";

interface SandboxStatusBadgeProps {
  status: SandboxStatus;
}

interface StatusConfig {
  label: string;
  color: string;
  bg: string;
  border: string;
  dotColor: string;
  animate?: boolean;
}

const STATUS_CONFIGS: Record<SandboxStatus, StatusConfig> = {
  creating: {
    label: "CREATING",
    color: "#60a5fa",
    bg: "#1e3a5f33",
    border: "#2563eb4d",
    dotColor: "#60a5fa",
    animate: true,
  },
  running: {
    label: "RUNNING",
    color: "#34d399",
    bg: "#064e3b33",
    border: "#0596694d",
    dotColor: "#10b981",
  },
  executing: {
    label: "EXECUTING",
    color: "#818cf8",
    bg: "#312e8133",
    border: "#4f46e54d",
    dotColor: "#6366f1",
    animate: true,
  },
  completed: {
    label: "COMPLETED",
    color: "#10b981",
    bg: "#064e3b33",
    border: "#0596694d",
    dotColor: "#10b981",
  },
  failed: {
    label: "FAILED",
    color: "#f87171",
    bg: "#450a0a33",
    border: "#dc26264d",
    dotColor: "#ef4444",
  },
  timed_out: {
    label: "TIMED OUT",
    color: "#fbbf24",
    bg: "#451a0333",
    border: "#d977064d",
    dotColor: "#f59e0b",
  },
  expired: {
    label: "EXPIRED",
    color: "#9ca3af",
    bg: "#1f293733",
    border: "#3741514d",
    dotColor: "#6b7280",
  },
  destroying: {
    label: "DESTROYING",
    color: "#fb923c",
    bg: "#43140733",
    border: "#ea580c4d",
    dotColor: "#f97316",
    animate: true,
  },
  destroyed: {
    label: "DESTROYED",
    color: "#6b7280",
    bg: "#11182733",
    border: "#1f29374d",
    dotColor: "#4b5563",
  },
};

export function SandboxStatusBadge({ status }: SandboxStatusBadgeProps) {
  const config =
    STATUS_CONFIGS[status] ?? {
      label: status.toUpperCase(),
      color: "#9ca3af",
      bg: "#1f293733",
      border: "#3741514d",
      dotColor: "#6b7280",
    };

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "3px 8px",
        borderRadius: 4,
        fontSize: 11,
        fontWeight: 600,
        letterSpacing: "0.04em",
        color: config.color,
        backgroundColor: config.bg,
        border: `1px solid ${config.border}`,
        lineHeight: 1,
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          backgroundColor: config.dotColor,
          display: "inline-block",
        }}
      />
      {config.label}
    </span>
  );
}
