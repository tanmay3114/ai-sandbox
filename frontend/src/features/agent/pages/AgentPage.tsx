import { useState } from "react";
import { Bot, ShieldCheck, Sparkles, Terminal } from "lucide-react";
import { AgentPromptInput } from "../components/AgentPromptInput";
import { AgentResult } from "../components/AgentResult";
import { useRunAgent } from "../hooks/useAgent";
import type { AgentRunResponse } from "../types";

export function AgentPage() {
  const [prompt, setPrompt] = useState(
    "Calculate factorial of 20 using Python and explain the result.",
  );
  const [submittedPrompt, setSubmittedPrompt] = useState<string>("");
  const [activeResult, setActiveResult] = useState<AgentRunResponse | null>(null);

  const {
    mutate: executeAgent,
    isPending,
    error,
    data: responseData,
  } = useRunAgent();

  const handleRun = () => {
    if (!prompt.trim() || isPending) return;
    setSubmittedPrompt(prompt);
    executeAgent(
      { prompt: prompt.trim() },
      {
        onSuccess: (data) => {
          setActiveResult(data);
        },
      },
    );
  };

  return (
    <div
      style={{
        maxWidth: 1000,
        margin: "0 auto",
        display: "flex",
        flexDirection: "column",
        gap: 24,
      }}
    >
      {/* Header Banner */}
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
          <div
            style={{
              width: 32,
              height: 32,
              borderRadius: 8,
              backgroundColor: "rgba(99, 102, 241, 0.15)",
              color: "#818cf8",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <Bot size={18} />
          </div>
          <h1
            style={{
              fontSize: 20,
              fontWeight: 700,
              margin: 0,
              color: "var(--color-text-primary)",
            }}
          >
            AI Sandbox Agent
          </h1>
        </div>
        <p
          style={{
            fontSize: 13,
            color: "var(--color-text-muted)",
            margin: 0,
            maxWidth: 720,
            lineHeight: 1.5,
          }}
        >
          Model-driven autonomous agent. Interprets instructions, plans dynamic multi-step workflows, runs untrusted code within hardened Docker sandboxes, and returns synthesized answers.
        </p>
      </div>

      {/* Feature Architecture Cards */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
          gap: 12,
        }}
      >
        <div
          style={{
            backgroundColor: "var(--color-surface)",
            border: "1px solid var(--color-border-subtle)",
            borderRadius: 8,
            padding: "14px 16px",
            display: "flex",
            alignItems: "flex-start",
            gap: 10,
          }}
        >
          <Sparkles size={16} color="var(--color-accent)" style={{ marginTop: 2, flexShrink: 0 }} />
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--color-text-primary)" }}>
              Model-Driven Reasoning
            </div>
            <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 2 }}>
              Dynamic tool selection with multi-turn loop
            </div>
          </div>
        </div>

        <div
          style={{
            backgroundColor: "var(--color-surface)",
            border: "1px solid var(--color-border-subtle)",
            borderRadius: 8,
            padding: "14px 16px",
            display: "flex",
            alignItems: "flex-start",
            gap: 10,
          }}
        >
          <Terminal size={16} color="#10b981" style={{ marginTop: 2, flexShrink: 0 }} />
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--color-text-primary)" }}>
              Ephemeral Container Tools
            </div>
            <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 2 }}>
              Live creation, execution, and cleanup
            </div>
          </div>
        </div>

        <div
          style={{
            backgroundColor: "var(--color-surface)",
            border: "1px solid var(--color-border-subtle)",
            borderRadius: 8,
            padding: "14px 16px",
            display: "flex",
            alignItems: "flex-start",
            gap: 10,
          }}
        >
          <ShieldCheck size={16} color="#6366f1" style={{ marginTop: 2, flexShrink: 0 }} />
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--color-text-primary)" }}>
              Strict Security Boundary
            </div>
            <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 2 }}>
              Zero host access, no network, drop-all caps
            </div>
          </div>
        </div>
      </div>

      {/* Prompt Input Section */}
      <div>
        <AgentPromptInput
          prompt={prompt}
          onChange={setPrompt}
          onRun={handleRun}
          isPending={isPending}
        />
      </div>

      {/* Agent Result Section */}
      <div>
        <AgentResult
          result={activeResult ?? responseData ?? null}
          isPending={isPending}
          error={error}
          prompt={submittedPrompt}
        />
      </div>
    </div>
  );
}
