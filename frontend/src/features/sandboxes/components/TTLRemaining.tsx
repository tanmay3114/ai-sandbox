import { useEffect, useState } from "react";
import { Clock } from "lucide-react";

interface TTLRemainingProps {
  expiresAt: string;
  status?: string;
}

export function TTLRemaining({ expiresAt, status }: TTLRemainingProps) {
  const [now, setNow] = useState<number>(Date.now());

  useEffect(() => {
    const timer = setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const isTerminal =
    status === "expired" || status === "destroyed" || status === "destroying";

  const expiresTime = new Date(expiresAt).getTime();
  const diffMs = expiresTime - now;
  const remainingSec = Math.floor(diffMs / 1000);

  if (isTerminal || remainingSec <= 0) {
    return (
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 5,
          color: "var(--color-text-muted)",
          fontSize: 12,
          fontWeight: 500,
        }}
      >
        <Clock size={12} />
        Expired
      </span>
    );
  }

  const hours = Math.floor(remainingSec / 3600);
  const minutes = Math.floor((remainingSec % 3600) / 60);
  const seconds = remainingSec % 60;

  let text = "";
  if (hours > 0) {
    text = `${hours}h ${minutes}m remaining`;
  } else if (minutes > 0) {
    text = `${minutes}m ${seconds}s remaining`;
  } else {
    text = `${seconds}s remaining`;
  }

  const isUrgent = remainingSec <= 60;

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        color: isUrgent ? "var(--color-warning)" : "var(--color-text-secondary)",
        fontSize: 12,
        fontWeight: 500,
      }}
    >
      <Clock size={12} color={isUrgent ? "var(--color-warning)" : "var(--color-text-muted)"} />
      {text}
    </span>
  );
}
