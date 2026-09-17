// ============================================================
// Execution Feature Domain Types matching backend schemas
// ============================================================

export type JobStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "timed_out"
  | "error";

export interface ExecuteCodePayload {
  code: string;
  timeout_seconds?: number;
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
