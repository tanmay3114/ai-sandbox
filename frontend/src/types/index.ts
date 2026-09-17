// ============================================================
// Domain types matching backend API surface
// ============================================================

export type SandboxStatus =
  | "creating"
  | "running"
  | "executing"
  | "completed"
  | "failed"
  | "timed_out"
  | "expired"
  | "destroying"
  | "destroyed";

export type ExecutionStatus =
  | "completed"
  | "failed"
  | "timed_out"
  | "error";

export interface Sandbox {
  sandbox_id: string;
  status: SandboxStatus;
  runtime: string;
  created_at: string;
  expires_at: string;
  destroyed_at: string | null;
}

export interface SandboxDetail extends Sandbox {
  resource_config: Record<string, unknown>;
  executions_count: number;
}

export interface ExecutionResult {
  sandbox_id: string | null;
  status: ExecutionStatus;
  exit_code: number | null;
  stdout: string;
  stderr: string;
  stdout_truncated: boolean;
  stderr_truncated: boolean;
  duration_ms: number | null;
  error_message: string | null;
  audit: Record<string, unknown> | null;
}

export interface ExecutionJob {
  execution_id: string;
  sandbox_id: string;
  status: ExecutionStatus;
  submitted_at: string;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  exit_code: number | null;
  stdout: string;
  stderr: string;
  stdout_truncated: boolean;
  stderr_truncated: boolean;
  error_message: string | null;
}

export interface AgentRunRequest {
  prompt: string;
}

export interface AgentRunResponse {
  response: string;
  tools_used: boolean;
  iterations: number;
  tool_calls_count: number;
  executed_tools: string[];
}

export interface HealthResponse {
  status: string;
}

export interface ReadyResponse {
  status: string;
  database: string;
  docker: string;
}

// ============================================================
// UI-specific types (not from backend)
// ============================================================

export interface StatCardData {
  label: string;
  value: string | number;
  delta?: string;
  deltaType?: "positive" | "negative" | "neutral";
  icon: string; // lucide icon name
}
