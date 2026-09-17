import {
  Activity,
  Bot,
  Container,
  PlaySquare,
  Shield,
  TrendingDown,
  TrendingUp,
} from "lucide-react";

const ICON_MAP: Record<string, React.ElementType> = {
  Container,
  PlaySquare,
  Bot,
  Shield,
  Activity,
};

interface StatCardProps {
  label: string;
  value: string | number;
  delta?: string;
  deltaType?: "positive" | "negative" | "neutral";
  icon: string;
  description?: string;
}

export function StatCard({
  label,
  value,
  delta,
  deltaType = "neutral",
  icon,
  description,
}: StatCardProps) {
  const Icon = ICON_MAP[icon] ?? Activity;

  const deltaColor =
    deltaType === "positive"
      ? "var(--color-success)"
      : deltaType === "negative"
        ? "var(--color-danger)"
        : "var(--color-text-muted)";

  return (
    <div
      style={{
        backgroundColor: "var(--color-surface)",
        border: "1px solid var(--color-border-subtle)",
        borderRadius: 8,
        padding: "18px 20px",
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      {/* Top row: icon + label */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <span
          style={{
            fontSize: 12,
            color: "var(--color-text-secondary)",
            fontWeight: 500,
            letterSpacing: "0.01em",
          }}
        >
          {label}
        </span>
        <div
          style={{
            width: 30,
            height: 30,
            borderRadius: 6,
            backgroundColor: "var(--color-accent-subtle)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <Icon size={14} color="var(--color-accent)" />
        </div>
      </div>

      {/* Value */}
      <div
        style={{
          fontSize: 28,
          fontWeight: 700,
          color: "var(--color-text-primary)",
          letterSpacing: "-0.02em",
          lineHeight: 1,
        }}
      >
        {value}
      </div>

      {/* Delta + description */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          fontSize: 11,
        }}
      >
        {delta && (
          <span
            style={{
              display: "flex",
              alignItems: "center",
              gap: 2,
              color: deltaColor,
              fontWeight: 500,
            }}
          >
            {deltaType === "positive" && <TrendingUp size={11} />}
            {deltaType === "negative" && <TrendingDown size={11} />}
            {delta}
          </span>
        )}
        {description && (
          <span style={{ color: "var(--color-text-muted)" }}>{description}</span>
        )}
      </div>
    </div>
  );
}
