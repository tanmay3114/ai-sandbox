import { useParams } from "react-router-dom";
import { FileCode } from "lucide-react";

export function ExecutionDetails() {
  const { id } = useParams<{ id: string }>();

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        minHeight: 400,
        gap: 12,
        color: "var(--color-text-muted)",
      }}
    >
      <FileCode size={36} color="var(--color-border)" />
      <div
        style={{
          fontSize: 15,
          fontWeight: 600,
          color: "var(--color-text-secondary)",
        }}
      >
        Execution Details
      </div>
      {id && (
        <div
          style={{
            fontFamily: "monospace",
            fontSize: 12,
            color: "var(--color-accent)",
          }}
        >
          ID: {id}
        </div>
      )}
      <div style={{ fontSize: 13 }}>
        Detailed execution view coming in Module 2.
      </div>
    </div>
  );
}
