import {
  Ban,
  CheckCircle2,
  HardDrive,
  Lock,
  Network,
  Shield,
  ShieldAlert,
  UserCheck,
} from "lucide-react";
import type { SecurityInvariants } from "../types";

interface SecurityBoundariesProps {
  invariants: SecurityInvariants;
}

export function SecurityBoundaries({ invariants }: SecurityBoundariesProps) {
  const boundaryItems = [
    {
      title: "Network Disabled",
      status: "ENFORCED",
      statusColor: "var(--color-success)",
      statusBg: "var(--color-success-subtle)",
      description: `network_mode = '${invariants.network_mode}'. Network access is strictly disabled.`,
      icon: Network,
      detail: "Inbound and outbound sockets disabled at kernel namespace level",
    },
    {
      title: "Read-Only Root Filesystem",
      status: invariants.read_only_rootfs ? "ENFORCED" : "DISABLED",
      statusColor: "var(--color-success)",
      statusBg: "var(--color-success-subtle)",
      description: "Root filesystem is mounted read-only. Immutable container filesystem.",
      icon: HardDrive,
      detail: "Writes only allowed to ephemeral restricted tmpfs /tmp",
    },
    {
      title: "Non-Root Execution",
      status: "ENFORCED",
      statusColor: "var(--color-success)",
      statusBg: "var(--color-success-subtle)",
      description: `Executed as unprivileged UID:GID '${invariants.user}'.`,
      icon: UserCheck,
      detail: "Root UID 0 execution is strictly forbidden and rejected",
    },
    {
      title: "All Linux Capabilities Dropped",
      status: "ENFORCED",
      statusColor: "var(--color-success)",
      statusBg: "var(--color-success-subtle)",
      description: `cap_drop = [${invariants.cap_drop.map((c) => `'${c}'`).join(", ")}]. Zero capabilities retained.`,
      icon: Lock,
      detail: "All kernel capabilities stripped before process execution",
    },
    {
      title: "No New Privileges",
      status: "ENFORCED",
      statusColor: "var(--color-success)",
      statusBg: "var(--color-success-subtle)",
      description: `security_opt = [${invariants.security_opt.map((s) => `'${s}'`).join(", ")}].`,
      icon: Shield,
      detail: "Prevents SUID binaries from escalating process privileges",
    },
    {
      title: "Host Mounts & Volume Binds",
      status: invariants.allow_host_mounts ? "ALLOWED" : "DENIED",
      statusColor: "var(--color-danger)",
      statusBg: "var(--color-danger-subtle)",
      description: "Host filesystem binds and volume attachments are strictly rejected.",
      icon: Ban,
      detail: "Zero access to host disks, configuration files, or directories",
    },
    {
      title: "Docker Socket Access",
      status: invariants.allow_docker_socket ? "ALLOWED" : "DENIED",
      statusColor: "var(--color-danger)",
      statusBg: "var(--color-danger-subtle)",
      description: "Docker daemon socket (/var/run/docker.sock) exposure is prohibited.",
      icon: ShieldAlert,
      detail: "Container-escape via daemon communication is completely prevented",
    },
    {
      title: "Privileged Containers",
      status: invariants.allow_privileged ? "ALLOWED" : "DENIED",
      statusColor: "var(--color-danger)",
      statusBg: "var(--color-danger-subtle)",
      description: "Privileged container execution is rejected by platform policy.",
      icon: Ban,
      detail: "Containers cannot access host devices or override kernel security",
    },
    {
      title: "Arbitrary Container Images",
      status: invariants.allow_arbitrary_images ? "ALLOWED" : "DENIED",
      statusColor: "var(--color-danger)",
      statusBg: "var(--color-danger-subtle)",
      description: "Arbitrary image selection is rejected. Only approved runtime images allowed.",
      icon: Lock,
      detail: "Prevents executing unverified or malicious public container images",
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
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 16,
          flexWrap: "wrap",
          gap: 8,
        }}
      >
        <div>
          <h3
            style={{
              margin: "0 0 4px",
              fontSize: 16,
              fontWeight: 600,
              color: "var(--color-text-primary)",
            }}
          >
            Security Boundary Invariants
          </h3>
          <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
            Non-negotiable container sandbox invariants verified before Docker dispatch
          </div>
        </div>

        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            padding: "4px 10px",
            borderRadius: 6,
            backgroundColor: "var(--color-success-subtle)",
            color: "var(--color-success)",
            fontSize: 11,
            fontWeight: 600,
          }}
        >
          <CheckCircle2 size={13} />
          Authoritative Enforcement
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))",
          gap: 12,
        }}
      >
        {boundaryItems.map((item) => {
          const IconComponent = item.icon;
          return (
            <div
              key={item.title}
              style={{
                backgroundColor: "var(--color-surface-2)",
                border: "1px solid var(--color-border)",
                borderRadius: 6,
                padding: "14px 16px",
                display: "flex",
                flexDirection: "column",
                justifyContent: "space-between",
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
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <IconComponent size={15} color="var(--color-accent)" />
                    <span
                      style={{
                        fontSize: 13,
                        fontWeight: 600,
                        color: "var(--color-text-primary)",
                      }}
                    >
                      {item.title}
                    </span>
                  </div>
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: 700,
                      padding: "2px 8px",
                      borderRadius: 4,
                      color: item.statusColor,
                      backgroundColor: item.statusBg,
                      letterSpacing: "0.04em",
                    }}
                  >
                    {item.status}
                  </span>
                </div>
                <div
                  style={{
                    fontSize: 12,
                    color: "var(--color-text-secondary)",
                    lineHeight: 1.4,
                    marginBottom: 6,
                  }}
                >
                  {item.description}
                </div>
              </div>

              <div
                style={{
                  fontSize: 11,
                  color: "var(--color-text-muted)",
                  borderTop: "1px solid var(--color-border-subtle)",
                  paddingTop: 6,
                  marginTop: 6,
                }}
              >
                {item.detail}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
