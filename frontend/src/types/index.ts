// ============================================================
// AI Sandbox - Complete Domain Types (Matching Backend & OpenAPI)
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

export type AgentTaskStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "timed_out";

// ── Sandbox Entities ────────────────────────────────────────

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

export interface CreateSandboxRequest {
  runtime?: string;
  ttl_seconds?: number;
}

export interface SandboxResponse {
  sandbox_id: string;
  status: SandboxStatus;
  runtime: string;
  created_at: string;
  expires_at: string;
  destroyed_at: string | null;
}

// ── Execution Entities ──────────────────────────────────────

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

export interface ExecuteCodeRequest {
  code: string;
  timeout_seconds?: number;
}

// ── Workspace Files ─────────────────────────────────────────

export interface FileInfo {
  path: string;
  size_bytes: number;
  is_directory: boolean;
  modified_at: string;
}

export interface FileContent {
  path: string;
  content: string;
  encoding: "utf-8" | "base64";
  size_bytes: number;
}

export interface FileListResponse {
  files: FileInfo[];
  total_count: number;
  total_size_bytes: number;
}

export interface WriteFileRequest {
  path: string;
  content: string;
  encoding?: string;
}

export interface CreateDirectoryRequest {
  path: string;
}

export interface CreateDirectoryResponse {
  path: string;
  created: boolean;
}

export interface DeleteFileResponse {
  path: string;
  deleted: boolean;
}

// ── Agent Entities ──────────────────────────────────────────

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

export interface AgentTaskCreateRequest {
  prompt: string;
  timeout_seconds?: number | null;
}

export interface AgentTaskResponse {
  task_id: string;
  sandbox_id: string;
  task_description: string;
  status: AgentTaskStatus | string;
  iterations: number;
  tool_calls_count: number;
  result_summary: string | null;
  error_message: string | null;
  error_type: string | null;
  tool_history: Array<Record<string, unknown>>;
  cancellation_requested_at: string | null;
  interruption_reason: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface AgentTaskListResponse {
  tasks: AgentTaskResponse[];
  total: number;
}

// ── Security Policy Entities ────────────────────────────────

export interface PlatformSecurityPolicy {
  allowed_runtimes: Record<string, string>;
  limits: {
    cpu_limit: number;
    memory_limit: string;
    memswap_limit: string;
    timeout_seconds: number;
    pids_limit: number;
    max_stdout_bytes: number;
    max_stderr_bytes: number;
    tmpfs_size: string;
  };
  invariants: {
    network_mode: string;
    privileged: boolean;
    cap_drop: string[];
    security_opt: string[];
    user: string;
    read_only: boolean;
    host_mounts_allowed: boolean;
  };
}

export interface RequestedPolicyPayload {
  runtime?: string;
  timeout_seconds?: number;
  memory_limit?: string;
  cpu_limit?: number;
  pids_limit?: number;
  max_stdout_bytes?: number;
  max_stderr_bytes?: number;
  image?: string;
  privileged?: boolean;
  network_mode?: string;
  cap_add?: string[];
  cap_drop?: string[];
  security_opt?: string[];
  user?: string;
  read_only?: boolean;
  volumes?: Record<string, unknown> | unknown[];
}

export interface SecurityEvaluationResponse {
  status: "allowed" | "clamped" | "rejected";
  audit_record: {
    timestamp: string;
    sandbox_id: string;
    decision: string;
    clamped_fields: string[];
    violations: string[];
    requested_summary: Record<string, unknown>;
    effective_summary: Record<string, unknown>;
  };
}

// ── Infrastructure Probes ───────────────────────────────────

export interface HealthResponse {
  status: string;
  service?: string;
}

export interface ReadyResponse {
  status: string;
  database?: string;
  docker?: string;
}

// ── UI-Specific Types ───────────────────────────────────────

export interface StatCardData {
  label: string;
  value: string | number;
  delta?: string;
  deltaType?: "positive" | "negative" | "neutral";
  icon: string;
}
