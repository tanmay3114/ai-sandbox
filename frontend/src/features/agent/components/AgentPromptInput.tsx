import { useEffect, useRef } from "react";
import { Bot, RotateCcw, Sparkles } from "lucide-react";
import { AgentRunButton } from "./AgentRunButton";

interface AgentPromptInputProps {
  prompt: string;
  onChange: (prompt: string) => void;
  onRun: () => void;
  isPending: boolean;
  disabled?: boolean;
}

const PRESET_PROMPTS = [
  {
    title: "Factorial of 20",
    prompt: "Calculate factorial of 20 using Python and explain the result.",
  },
  {
    title: "Prime Check (104729)",
    prompt: "Check whether 104729 is prime using Python and explain how you verified it.",
  },
  {
    title: "Fibonacci Sequence",
    prompt: "Generate a Python program that calculates the first 15 Fibonacci numbers, runs it in the sandbox, and explains the output.",
  },
  {
    title: "Environment Inspection",
    prompt: "Inspect the Python version, operating system, and current user inside the sandbox and summarize the security posture.",
  },
];

export function AgentPromptInput({
  prompt,
  onChange,
  onRun,
  isPending,
  disabled = false,
}: AgentPromptInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Keyboard shortcut: Cmd/Ctrl + Enter to trigger run
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        if (!disabled && !isPending && prompt.trim().length > 0) {
          e.preventDefault();
          onRun();
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [prompt, disabled, isPending, onRun]);

  const charCount = prompt.length;
  const isPromptValid = prompt.trim().length > 0 && prompt.length <= 10000;

  return (
    <div
      style={{
        backgroundColor: "var(--color-surface)",
        border: "1px solid var(--color-border-subtle)",
        borderRadius: 8,
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
      }}
    >
      {/* Header bar with icon and clear action */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "12px 18px",
          backgroundColor: "var(--color-surface-2)",
          borderBottom: "1px solid var(--color-border-subtle)",
          flexWrap: "wrap",
          gap: 10,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Bot size={16} color="var(--color-accent)" />
          <span
            style={{
              fontSize: 13,
              fontWeight: 600,
              color: "var(--color-text-primary)",
            }}
          >
            Autonomous Agent Prompt
          </span>
          <span
            style={{
              fontSize: 10,
              padding: "1px 6px",
              borderRadius: 3,
              backgroundColor: "rgba(99, 102, 241, 0.15)",
              color: "#818cf8",
              fontWeight: 500,
            }}
          >
            Multi-Turn Tool Calling
          </span>
        </div>

        {charCount > 0 && (
          <button
            onClick={() => onChange("")}
            disabled={isPending}
            title="Clear prompt"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              padding: "3px 8px",
              borderRadius: 4,
              border: "1px solid var(--color-border)",
              backgroundColor: "transparent",
              color: "var(--color-text-muted)",
              fontSize: 11,
              cursor: "pointer",
            }}
          >
            <RotateCcw size={11} />
            Clear
          </button>
        )}
      </div>

      {/* Textarea */}
      <div style={{ position: "relative" }}>
        <textarea
          ref={textareaRef}
          value={prompt}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled || isPending}
          placeholder="Instruct the AI Agent in plain English (e.g. 'Calculate factorial of 20 using Python and explain the result.'). The agent will autonomously create a sandbox, execute Python code, verify output, and clean up."
          rows={5}
          maxLength={10000}
          style={{
            width: "100%",
            boxSizing: "border-box",
            padding: "16px 18px",
            backgroundColor: "var(--color-background)",
            color: disabled ? "var(--color-text-muted)" : "var(--color-text-primary)",
            fontFamily: "inherit",
            fontSize: 13,
            lineHeight: 1.6,
            border: "none",
            outline: "none",
            resize: "vertical",
          }}
        />
      </div>

      {/* Preset Prompt Shortcuts */}
      <div
        style={{
          padding: "10px 18px",
          borderTop: "1px solid var(--color-border-subtle)",
          backgroundColor: "var(--color-surface)",
          display: "flex",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 8,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11, color: "var(--color-text-muted)" }}>
          <Sparkles size={12} color="var(--color-accent)" />
          <span>Presets:</span>
        </div>
        {PRESET_PROMPTS.map((preset) => (
          <button
            key={preset.title}
            onClick={() => onChange(preset.prompt)}
            disabled={isPending}
            title={preset.prompt}
            style={{
              fontSize: 11,
              padding: "3px 10px",
              borderRadius: 12,
              backgroundColor: "var(--color-surface-2)",
              border: "1px solid var(--color-border-subtle)",
              color: "var(--color-text-secondary)",
              cursor: isPending ? "not-allowed" : "pointer",
              transition: "all 0.1s ease",
            }}
          >
            {preset.title}
          </button>
        ))}
      </div>

      {/* Footer Run Controls */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "12px 18px",
          backgroundColor: "var(--color-surface-2)",
          borderTop: "1px solid var(--color-border-subtle)",
          flexWrap: "wrap",
          gap: 12,
        }}
      >
        <span
          style={{
            fontSize: 11,
            color: charCount > 9500 ? "var(--color-warning)" : "var(--color-text-muted)",
          }}
        >
          {charCount} / 10,000 characters
        </span>

        <AgentRunButton
          onRun={onRun}
          isPending={isPending}
          disabled={disabled || !isPromptValid}
          title={
            !isPromptValid
              ? "Please enter an agent instruction"
              : "Run autonomous model-driven agent"
          }
        />
      </div>
    </div>
  );
}
