/**
 * Types representing the authoritative backend Security Policy & Enforcement layer.
 */

export interface SecurityInvariants {
  network_mode: string;
  read_only_rootfs: boolean;
  user: string;
  cap_drop: string[];
  security_opt: string[];
  allow_host_mounts: boolean;
  allow_docker_socket: boolean;
  allow_privileged: boolean;
  allow_arbitrary_images: boolean;
}

export interface SecurityLimits {
  memory_limit: string;
  cpu_limit: number;
  pids_limit: number;
  timeout_seconds: number;
  max_stdout_bytes: number;
  max_stderr_bytes: number;
  tmpfs_size: string;
  global_concurrency_limit: number;
}

export interface SecurityRuntime {
  default_runtime: string;
  approved_image: string;
  allowed_runtimes: Record<string, string>;
}

export interface PlatformSecurityPolicy {
  engine: string;
  enforcement: string;
  invariants: SecurityInvariants;
  resource_limits: SecurityLimits;
  runtime: SecurityRuntime;
}

export interface SecurityAuditRecord {
  timestamp: string;
  sandbox_id: string;
  decision: "allowed" | "clamped" | "rejected" | string;
  clamped_fields: string[];
  violations: string[];
  requested_summary: Record<string, any>;
  effective_summary: Record<string, any>;
}

export interface SecurityEvaluationResponse {
  status: "allowed" | "clamped" | string;
  audit: SecurityAuditRecord;
  effective: Record<string, any>;
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
  user?: string;
  read_only?: boolean;
  volumes?: Record<string, any>;
}
