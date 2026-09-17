// ============================================================
// Sandbox Feature Domain Types matching backend schemas
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

export type JobStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "timed_out"
  | "error";

export interface CreateSandboxPayload {
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

export interface SandboxDetail extends SandboxResponse {
  resource_config: {
    memory_limit?: string;
    cpu_limit?: number;
    pids_limit?: number;
    max_stdout_bytes?: number;
    max_stderr_bytes?: number;
    [key: string]: unknown;
  };
  executions_count: number;
}

export interface JobExecution {
  execution_id: string;
  sandbox_id: string;
  status: JobStatus;
  exit_code: number | null;
  stdout: string;
  stderr: string;
  stdout_truncated: boolean;
  stderr_truncated: boolean;
  duration_ms: number | null;
  submitted_at: string;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
}
