import { useState } from "react";
import {
  AlertCircle,
  AlertTriangle,
  Bot,
  Check,
  CheckCircle2,
  Container,
  Copy,
  Play,
  Terminal,
  Trash2,
  Wrench,
} from "lucide-react";
import type { AgentRunResponse } from "../types";

interface AgentResultProps {
  result: AgentRunResponse | null;
  isPending: boolean;
  error: any;
  prompt?: string;
}

function getToolIcon(toolName: string) {
  switch (toolName.toLowerCase()) {
    case "create_sandbox":
      return Container;
    case "execute_code":
      return Play;
    case "get_sandbox":
      return Terminal;
    case "get_execution_result":
      return Terminal;
    case "destroy_sandbox":
      return Trash2;
    default:
      return Wrench;
  }
}

export function AgentResult({
  result,
  isPending,
  error,
  prompt,
}: AgentResultProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  // Loading state
  if (isPending) {
    return (
      <div
        style={{
          backgroundColor: "var(--color-surface)",
          border: "1px solid var(--color-border-subtle)",
          borderRadius: 8,
          padding: "36px 24px",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 14,
          textAlign: "center",
        }}
      >
        <div
          style={{
            width: 44,
            height: 44,
            borderRadius: "50%",
            border: "3px solid var(--color-accent)",
            borderTopColor: "transparent",
            animation: "spin 1s linear infinite",
          }}
        />
        <div>
          <div
            style={{
              fontSize: 14,
              fontWeight: 600,
              color: "var(--color-text-primary)",
              marginBottom: 4,
            }}
          >
            Agent Reasoning & Executing Tools...
          </div>
          <div
            style={{
              fontSize: 12,
              color: "var(--color-text-muted)",
              maxWidth: 440,
              lineHeight: 1.5,
            }}
          >
            The model is actively formulating instructions, dynamically provisioning ephemeral Docker sandboxes, executing code, and inspecting results.
          </div>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    const status = error?.response?.status;
    const errorType = error?.response?.data?.error;
    const backendMessage =
      error?.response?.data?.message ||
      error?.response?.data?.detail ||
      error?.message;

    const isProviderFailure =
      status === 502 || errorType === "LLMProviderError";

    const isQuotaOrRateLimit =
      status === 429 ||
      (typeof backendMessage === "string" &&
        (backendMessage.includes("quota") ||
          backendMessage.includes("RESOURCE_EXHAUSTED")));

    const isTimeout =
      status === 504 ||
      (typeof backendMessage === "string" && backendMessage.includes("timed out"));

    return (
      <div
        style={{
          backgroundColor: "var(--color-surface)",
          border: "1px solid",
          borderColor:
            isProviderFailure || isQuotaOrRateLimit
              ? "var(--color-warning)"
              : "var(--color-danger)",
          borderRadius: 8,
          padding: "20px 24px",
          color:
            isProviderFailure || isQuotaOrRateLimit
              ? "var(--color-warning)"
              : "var(--color-danger)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
          {isProviderFailure || isQuotaOrRateLimit ? (
            <AlertTriangle size={18} />
          ) : (
            <AlertCircle size={18} />
          )}
          <span style={{ fontWeight: 600, fontSize: 14 }}>
            {isQuotaOrRateLimit
              ? "LLM Provider Quota Exhausted"
              : isProviderFailure
              ? "AI Model Provider Unavailable"
              : isTimeout
              ? "Agent Execution Timed Out"
              : "Agent Error"}
          </span>
        </div>
        <div
          style={{
            fontSize: 13,
            lineHeight: 1.5,
            color: "var(--color-text-secondary)",
          }}
        >
          {isProviderFailure
            ? "The upstream AI model provider is currently unavailable or rate-limited. Please wait a moment and try again."
            : typeof backendMessage === "string"
            ? backendMessage
            : "Request could not be completed."}
        </div>
        {isProviderFailure && (
          <div
            style={{
              fontSize: 12,
              color: "var(--color-text-muted)",
              marginTop: 10,
              paddingTop: 10,
              borderTop: "1px solid var(--color-border-subtle)",
            }}
          >
            Backend sandbox execution services remain operational.
          </div>
        )}
      </div>
    );
  }

  // No result yet
  if (!result) {
    return null;
  }

  return (
    <div
      style={{
        backgroundColor: "var(--color-surface)",
        border: "1px solid var(--color-border-subtle)",
        borderRadius: 8,
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        gap: 0,
      }}
    >
      {/* Header Banner */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "14px 20px",
          backgroundColor: "var(--color-surface-2)",
          borderBottom: "1px solid var(--color-border-subtle)",
          flexWrap: "wrap",
          gap: 12,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Bot size={18} color="var(--color-accent)" />
          <span
            style={{
              fontSize: 14,
              fontWeight: 700,
              color: "var(--color-text-primary)",
            }}
          >
            Agent Result
          </span>
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              fontSize: 11,
              fontWeight: 600,
              padding: "2px 8px",
              borderRadius: 4,
              backgroundColor: "var(--color-success-subtle)",
              color: "var(--color-success)",
            }}
          >
            <CheckCircle2 size={12} />
            COMPLETED
          </span>
        </div>

        <button
          onClick={() => handleCopy(result.response)}
          title="Copy agent response"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 5,
            padding: "4px 10px",
            borderRadius: 4,
            border: "1px solid var(--color-border)",
            backgroundColor: "var(--color-surface)",
            color: copied ? "var(--color-success)" : "var(--color-text-secondary)",
            fontSize: 12,
            cursor: "pointer",
          }}
        >
          {copied ? <Check size={13} /> : <Copy size={13} />}
          <span>{copied ? "Copied" : "Copy Response"}</span>
        </button>
      </div>

      {/* Execution Metrics Bar */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
          gap: 12,
          padding: "14px 20px",
          backgroundColor: "var(--color-surface)",
          borderBottom: "1px solid var(--color-border-subtle)",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <span
            style={{
              fontSize: 10,
              textTransform: "uppercase",
              letterSpacing: "0.04em",
              color: "var(--color-text-muted)",
              fontWeight: 600,
            }}
          >
            Iterations
          </span>
          <span
            style={{
              fontSize: 16,
              fontWeight: 700,
              fontFamily: "monospace",
              color: "var(--color-text-primary)",
            }}
          >
            {result.iterations}
          </span>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <span
            style={{
              fontSize: 10,
              textTransform: "uppercase",
              letterSpacing: "0.04em",
              color: "var(--color-text-muted)",
              fontWeight: 600,
            }}
          >
            Tool Calls
          </span>
          <span
            style={{
              fontSize: 16,
              fontWeight: 700,
              fontFamily: "monospace",
              color: "var(--color-text-primary)",
            }}
          >
            {result.tool_calls_count}
          </span>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <span
            style={{
              fontSize: 10,
              textTransform: "uppercase",
              letterSpacing: "0.04em",
              color: "var(--color-text-muted)",
              fontWeight: 600,
            }}
          >
            Tools Used
          </span>
          <span
            style={{
              fontSize: 14,
              fontWeight: 600,
              color: result.tools_used
                ? "var(--color-success)"
                : "var(--color-text-muted)",
            }}
          >
            {result.tools_used ? "Yes (Dynamic Execution)" : "None"}
          </span>
        </div>
      </div>

      {/* Executed Tools Timeline */}
      {result.executed_tools && result.executed_tools.length > 0 && (
        <div
          style={{
            padding: "14px 20px",
            borderBottom: "1px solid var(--color-border-subtle)",
            backgroundColor: "var(--color-surface-2)",
          }}
        >
          <div
            style={{
              fontSize: 11,
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: "0.04em",
              color: "var(--color-text-muted)",
              marginBottom: 8,
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            <Wrench size={12} color="var(--color-accent)" />
            <span>Chronological Tool Calls ({result.executed_tools.length})</span>
          </div>

          <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
            {result.executed_tools.map((toolName, idx) => {
              const Icon = getToolIcon(toolName);
              return (
                <div
                  key={`${toolName}-${idx}`}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    padding: "4px 10px",
                    borderRadius: 6,
                    backgroundColor: "var(--color-surface)",
                    border: "1px solid var(--color-border)",
                    fontSize: 11,
                    fontFamily: "monospace",
                    color: "var(--color-text-primary)",
                  }}
                >
                  <span
                    style={{
                      fontSize: 10,
                      color: "var(--color-text-muted)",
                      fontWeight: 600,
                    }}
                  >
                    #{idx + 1}
                  </span>
                  <Icon size={12} color="var(--color-accent)" />
                  <span>{toolName}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Prompt Re-cap if provided */}
      {prompt && (
        <div
          style={{
            padding: "12px 20px",
            borderBottom: "1px solid var(--color-border-subtle)",
            fontSize: 12,
            color: "var(--color-text-secondary)",
            backgroundColor: "rgba(255, 255, 255, 0.01)",
          }}
        >
          <strong style={{ color: "var(--color-text-muted)" }}>Prompt: </strong>
          <em>"{prompt}"</em>
        </div>
      )}

      {/* Agent Response Content */}
      <div style={{ padding: "20px 24px" }}>
        <div
          style={{
            fontSize: 11,
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: "0.04em",
            color: "var(--color-text-muted)",
            marginBottom: 10,
          }}
        >
          Agent Explanation & Outcome
        </div>
        <div
          style={{
            fontSize: 14,
            lineHeight: 1.7,
            color: "var(--color-text-primary)",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {result.response}
        </div>
      </div>
    </div>
  );
}
