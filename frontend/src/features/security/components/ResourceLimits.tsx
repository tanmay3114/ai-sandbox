import {
  Activity,
  Clock,
  Cpu,
  FolderLock,
  HardDrive,
  Layers,
  Terminal,
  Users,
} from "lucide-react";
import { formatBytes } from "@/lib/utils";
import type { SecurityLimits } from "../types";

interface ResourceLimitsProps {
  limits: SecurityLimits;
}

export function ResourceLimits({ limits }: ResourceLimitsProps) {
  const cards = [
    {
      label: "Memory Limit",
      value: limits.memory_limit.toUpperCase(),
      subtext: "Hard container memory ceiling (cgroup)",
      state: "LIMITED",
      icon: HardDrive,
    },
    {
      label: "CPU Quota",
      value: `${limits.cpu_limit} Cores`,
      subtext: `${(limits.cpu_limit * 1_000_000_000).toLocaleString()} NanoCPUs quota`,
      state: "LIMITED",
      icon: Cpu,
    },
    {
      label: "Process / PID Limit",
      value: `${limits.pids_limit}`,
      subtext: "Prevents fork bombs & unbounded processes",
      state: "LIMITED",
      icon: Users,
    },
    {
      label: "Execution Timeout",
      value: `${limits.timeout_seconds}s`,
      subtext: "Deterministic termination deadline",
      state: "LIMITED",
      icon: Clock,
    },
    {
      label: "Max STDOUT Stream",
      value: formatBytes(limits.max_stdout_bytes),
      subtext: "Prevents host stream memory exhaustion",
      state: "LIMITED",
      icon: Terminal,
    },
    {
      label: "Max STDERR Stream",
      value: formatBytes(limits.max_stderr_bytes),
      subtext: "Prevents error buffer overflow",
      state: "LIMITED",
      icon: Activity,
    },
    {
      label: "Temporary /tmp tmpfs",
      value: limits.tmpfs_size.toUpperCase(),
      subtext: "RAM tmpfs: noexec, nosuid, nodev",
      state: "LIMITED",
      icon: FolderLock,
    },
    {
      label: "Global Concurrency",
      value: `${limits.global_concurrency_limit}`,
      subtext: "Platform-wide concurrency semaphore",
      state: "LIMITED",
      icon: Layers,
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
          Enforced Resource Limits & Quotas
        </h3>
        <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
          Hardware and process limits bounded and clamped by the platform policy
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
          gap: 12,
        }}
      >
        {cards.map((card) => {
          const IconComponent = card.icon;
          return (
            <div
              key={card.label}
              style={{
                backgroundColor: "var(--color-surface-2)",
                border: "1px solid var(--color-border)",
                borderRadius: 6,
                padding: "14px 16px",
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  marginBottom: 8,
                }}
              >
                <span
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    color: "var(--color-text-muted)",
                    textTransform: "uppercase",
                    letterSpacing: "0.04em",
                  }}
                >
                  {card.label}
                </span>
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 700,
                    color: "var(--color-accent)",
                    backgroundColor: "var(--color-accent-subtle)",
                    padding: "2px 6px",
                    borderRadius: 3,
                  }}
                >
                  {card.state}
                </span>
              </div>

              <div
                style={{
                  display: "flex",
                  alignItems: "baseline",
                  gap: 8,
                  marginBottom: 4,
                }}
              >
                <IconComponent size={16} color="var(--color-accent)" />
                <span
                  style={{
                    fontSize: 20,
                    fontWeight: 700,
                    fontFamily: "monospace",
                    color: "var(--color-text-primary)",
                  }}
                >
                  {card.value}
                </span>
              </div>

              <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
                {card.subtext}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
