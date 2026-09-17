import { useEffect, useRef } from "react";
import { Code2, RotateCcw, Sparkles } from "lucide-react";
import { RunCodeButton } from "./RunCodeButton";

interface CodeEditorProps {
  code: string;
  onChange: (code: string) => void;
  timeoutSeconds?: number;
  onTimeoutChange?: (timeout: number | undefined) => void;
  onRun: () => void;
  isPending: boolean;
  disabled?: boolean;
  disabledMessage?: string;
}

const SNIPPETS = [
  {
    label: "Hello World",
    code: 'print("Hello World")',
  },
  {
    label: "Math Calculation",
    code: `import math

print(f"pi = {math.pi}")
print(f"sqrt(144) = {math.sqrt(144)}")
print(f"hypot(3, 4) = {math.hypot(3, 4)}")`,
  },
  {
    label: "System & Environment",
    code: `import sys
import os
import platform

print(f"Python version: {platform.python_version()}")
print(f"OS: {platform.system()} {platform.release()}")
print(f"User ID: {os.getuid() if hasattr(os, 'getuid') else 'N/A'}")`,
  },
  {
    label: "Loop & Calculation",
    code: `squares = [i ** 2 for i in range(1, 11)]
print("Squares 1..10:", squares)
print("Sum:", sum(squares))`,
  },
  {
    label: "Intentional Error (Test)",
    code: `def divide(a, b):
    return a / b

print("Attempting divide by zero:")
divide(10, 0)`,
  },
];

export function CodeEditor({
  code,
  onChange,
  timeoutSeconds,
  onTimeoutChange,
  onRun,
  isPending,
  disabled = false,
  disabledMessage,
}: CodeEditorProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Keyboard shortcut: Cmd/Ctrl + Enter to run
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        if (!disabled && !isPending && code.trim().length > 0) {
          e.preventDefault();
          onRun();
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [code, disabled, isPending, onRun]);

  const handleTab = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Tab") {
      e.preventDefault();
      const target = e.currentTarget;
      const start = target.selectionStart;
      const end = target.selectionEnd;
      const val = target.value;
      const nextVal = val.substring(0, start) + "    " + val.substring(end);
      onChange(nextVal);
      setTimeout(() => {
        target.selectionStart = target.selectionEnd = start + 4;
      }, 0);
    }
  };

  const lineCount = code.split("\n").length;
  const charCount = code.length;
  const isCodeValid = code.trim().length > 0;

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
      {/* Editor Header Bar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "10px 16px",
          backgroundColor: "var(--color-surface-2)",
          borderBottom: "1px solid var(--color-border-subtle)",
          flexWrap: "wrap",
          gap: 8,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Code2 size={15} color="var(--color-accent)" />
          <span
            style={{
              fontSize: 12,
              fontWeight: 600,
              color: "var(--color-text-primary)",
            }}
          >
            Python 3.12 Editor
          </span>
          <span
            style={{
              fontSize: 10,
              padding: "1px 6px",
              borderRadius: 3,
              backgroundColor: "rgba(59, 130, 246, 0.15)",
              color: "var(--color-accent)",
              fontWeight: 500,
            }}
          >
            Ephemeral Sandbox
          </span>
        </div>

        {/* Snippets and Actions */}
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <Sparkles size={13} color="var(--color-text-muted)" />
            <select
              defaultValue=""
              onChange={(e) => {
                const snip = SNIPPETS.find((s) => s.label === e.target.value);
                if (snip) {
                  onChange(snip.code);
                  e.target.value = "";
                }
              }}
              style={{
                fontSize: 11,
                padding: "3px 8px",
                borderRadius: 4,
                backgroundColor: "var(--color-surface)",
                border: "1px solid var(--color-border)",
                color: "var(--color-text-secondary)",
                cursor: "pointer",
                outline: "none",
              }}
            >
              <option value="" disabled>
                Insert Snippet...
              </option>
              {SNIPPETS.map((s) => (
                <option key={s.label} value={s.label}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>

          <button
            onClick={() => onChange("")}
            title="Clear editor"
            disabled={charCount === 0 || isPending}
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
              cursor: charCount === 0 ? "not-allowed" : "pointer",
              opacity: charCount === 0 ? 0.4 : 1,
            }}
          >
            <RotateCcw size={11} />
            Clear
          </button>
        </div>
      </div>

      {/* Code Textarea Area */}
      <div style={{ position: "relative" }}>
        <textarea
          ref={textareaRef}
          value={code}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleTab}
          disabled={disabled || isPending}
          placeholder={`# Enter Python code to execute in this ephemeral sandbox session\nprint("Hello World")`}
          rows={Math.max(6, Math.min(lineCount + 2, 18))}
          style={{
            width: "100%",
            boxSizing: "border-box",
            padding: "14px 16px",
            backgroundColor: "var(--color-background)",
            color: disabled ? "var(--color-text-muted)" : "var(--color-text-primary)",
            fontFamily: "monospace",
            fontSize: 13,
            lineHeight: 1.5,
            border: "none",
            outline: "none",
            resize: "vertical",
            whiteSpace: "pre",
            tabSize: 4,
          }}
        />
      </div>

      {/* Editor Footer / Run Controls */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "10px 16px",
          backgroundColor: "var(--color-surface-2)",
          borderTop: "1px solid var(--color-border-subtle)",
          flexWrap: "wrap",
          gap: 12,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          {/* Timeout Config */}
          {onTimeoutChange && (
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
                Timeout:
              </span>
              <select
                value={timeoutSeconds ?? 10}
                onChange={(e) => onTimeoutChange(Number(e.target.value))}
                disabled={disabled || isPending}
                style={{
                  fontSize: 11,
                  padding: "3px 6px",
                  borderRadius: 4,
                  backgroundColor: "var(--color-surface)",
                  border: "1px solid var(--color-border)",
                  color: "var(--color-text-primary)",
                  outline: "none",
                }}
              >
                <option value={2}>2s (Fast)</option>
                <option value={5}>5s</option>
                <option value={10}>10s (Standard)</option>
                <option value={30}>30s</option>
                <option value={60}>60s (Max)</option>
              </select>
            </div>
          )}

          {/* Lines / Characters Counter */}
          <span style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
            {lineCount} {lineCount === 1 ? "line" : "lines"} · {charCount} chars
          </span>

          {disabledMessage && (
            <span style={{ fontSize: 11, color: "var(--color-danger)" }}>
              {disabledMessage}
            </span>
          )}
        </div>

        {/* Run Button */}
        <div>
          <RunCodeButton
            onRun={onRun}
            isPending={isPending}
            disabled={disabled || !isCodeValid}
            title={
              disabled
                ? disabledMessage ?? "Sandbox is not available for execution"
                : !isCodeValid
                ? "Please enter Python code first"
                : "Execute code in sandbox"
            }
          />
        </div>
      </div>
    </div>
  );
}
