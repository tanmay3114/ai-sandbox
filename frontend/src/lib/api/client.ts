import type {
  AgentRunRequest,
  AgentRunResponse,
  AgentTaskCreateRequest,
  AgentTaskListResponse,
  AgentTaskResponse,
  CreateDirectoryRequest,
  CreateDirectoryResponse,
  CreateSandboxRequest,
  DeleteFileResponse,
  ExecuteCodeRequest,
  ExecutionJob,
  ExecutionResult,
  FileContent,
  FileListResponse,
  HealthResponse,
  PlatformSecurityPolicy,
  ReadyResponse,
  RequestedPolicyPayload,

  SandboxDetail,
  SandboxResponse,
  SecurityEvaluationResponse,
  WriteFileRequest,
} from "@/types";
import axios, { type AxiosInstance, type AxiosRequestConfig } from "axios";

/**
 * AI Sandbox - Unified Typed API Client.
 * All requests route through the same-origin BFF proxy (/api/*, /health, /ready).
 * The browser NEVER transmits or receives SANDBOX_API_KEY.
 */

const client: AxiosInstance = axios.create({
  baseURL: "", // Same-origin relative path routes directly to BFF
  headers: {
    "Content-Type": "application/json",
  },
  timeout: 300_000, // 300s default to support long-running agent tasks
});

// ── Health Probes ───────────────────────────────────────────

export async function fetchHealth(config?: AxiosRequestConfig): Promise<HealthResponse> {
  const { data } = await client.get<HealthResponse>("/health", config);
  return data;
}

export async function fetchReady(config?: AxiosRequestConfig): Promise<ReadyResponse> {
  const { data } = await client.get<ReadyResponse>("/ready", config);
  return data;
}

// ── Sandboxes ───────────────────────────────────────────────

export async function listSandboxes(config?: AxiosRequestConfig): Promise<SandboxDetail[]> {
  const { data } = await client.get<SandboxDetail[]>("/api/v1/sandboxes", config);
  return data;
}

export async function createSandbox(
  payload?: CreateSandboxRequest,
  config?: AxiosRequestConfig,
): Promise<SandboxResponse> {
  const { data } = await client.post<SandboxResponse>(
    "/api/v1/sandboxes",
    payload ?? { runtime: "python", ttl_seconds: 300 },
    config,
  );
  return data;
}

export async function getSandbox(
  sandboxId: string,
  config?: AxiosRequestConfig,
): Promise<SandboxDetail> {
  const { data } = await client.get<SandboxDetail>(
    `/api/v1/sandboxes/${sandboxId}`,
    config,
  );
  return data;
}

export async function deleteSandbox(
  sandboxId: string,
  config?: AxiosRequestConfig,
): Promise<SandboxResponse> {
  const { data } = await client.delete<SandboxResponse>(
    `/api/v1/sandboxes/${sandboxId}`,
    config,
  );
  return data;
}

// ── Executions ──────────────────────────────────────────────

export async function executeInSandbox(
  sandboxId: string,
  payload: ExecuteCodeRequest,
  config?: AxiosRequestConfig,
): Promise<ExecutionJob> {
  const { data } = await client.post<ExecutionJob>(
    `/api/v1/sandboxes/${sandboxId}/execute`,
    payload,
    config,
  );
  return data;
}

export async function listSandboxExecutions(
  sandboxId: string,
  config?: AxiosRequestConfig,
): Promise<ExecutionJob[]> {
  const { data } = await client.get<ExecutionJob[]>(
    `/api/v1/sandboxes/${sandboxId}/executions`,
    config,
  );
  return data;
}

export async function getExecution(
  sandboxId: string,
  executionId: string,
  config?: AxiosRequestConfig,
): Promise<ExecutionJob> {
  const { data } = await client.get<ExecutionJob>(
    `/api/v1/sandboxes/${sandboxId}/executions/${executionId}`,
    config,
  );
  return data;
}

export async function executeEphemeral(
  payload: ExecuteCodeRequest,
  config?: AxiosRequestConfig,
): Promise<ExecutionResult> {
  const { data } = await client.post<ExecutionResult>(
    "/api/v1/sandboxes/execute",
    payload,
    config,
  );
  return data;
}

// ── Workspace Files ─────────────────────────────────────────

export async function listWorkspaceFiles(
  sandboxId: string,
  path?: string,
  config?: AxiosRequestConfig,
): Promise<FileListResponse> {
  const params = path ? { path } : undefined;
  const { data } = await client.get<FileListResponse>(
    `/api/v1/sandboxes/${sandboxId}/files`,
    { ...config, params: { ...config?.params, ...params } },
  );
  return data;
}

export async function readWorkspaceFile(
  sandboxId: string,
  filePath: string,
  config?: AxiosRequestConfig,
): Promise<FileContent> {
  const cleanPath = filePath.startsWith("/") ? filePath.slice(1) : filePath;
  const { data } = await client.get<FileContent>(
    `/api/v1/sandboxes/${sandboxId}/files/${cleanPath}`,
    config,
  );
  return data;
}

export async function writeWorkspaceFile(
  sandboxId: string,
  payload: WriteFileRequest,
  config?: AxiosRequestConfig,
): Promise<FileContent> {
  const { data } = await client.post<FileContent>(
    `/api/v1/sandboxes/${sandboxId}/files`,
    payload,
    config,
  );
  return data;
}

export async function createWorkspaceDirectory(
  sandboxId: string,
  payload: CreateDirectoryRequest,
  config?: AxiosRequestConfig,
): Promise<CreateDirectoryResponse> {
  const { data } = await client.post<CreateDirectoryResponse>(
    `/api/v1/sandboxes/${sandboxId}/directories`,
    payload,
    config,
  );
  return data;
}

export async function deleteWorkspaceFile(
  sandboxId: string,
  filePath: string,
  config?: AxiosRequestConfig,
): Promise<DeleteFileResponse> {
  const cleanPath = filePath.startsWith("/") ? filePath.slice(1) : filePath;
  const { data } = await client.delete<DeleteFileResponse>(
    `/api/v1/sandboxes/${sandboxId}/files/${cleanPath}`,
    config,
  );
  return data;
}

export async function deleteWorkspaceFileByQuery(
  sandboxId: string,
  path: string,
  config?: AxiosRequestConfig,
): Promise<DeleteFileResponse> {
  const { data } = await client.delete<DeleteFileResponse>(
    `/api/v1/sandboxes/${sandboxId}/files`,
    { ...config, params: { ...config?.params, path } },
  );
  return data;
}

// ── Agent Tasks ─────────────────────────────────────────────

/**
 * Execute synchronous model-driven task via backend SandboxAgent.
 */
export async function runAgent(
  payload: AgentRunRequest,
  config?: AxiosRequestConfig,
): Promise<AgentRunResponse> {
  const { data } = await client.post<AgentRunResponse>(
    "/api/v1/agent/run",
    payload,
    config,
  );
  return data;
}

/**
 * Submit synchronous agent task to a designated persistent sandbox session.
 * Request-bound and synchronous on backend.
 */
export async function createAndRunAgentTask(
  sandboxId: string,
  payload: AgentTaskCreateRequest,
  config?: AxiosRequestConfig,
): Promise<AgentTaskResponse> {
  const { data } = await client.post<AgentTaskResponse>(
    `/api/v1/sandboxes/${sandboxId}/agent/tasks`,
    payload,
    config,
  );
  return data;
}

/**
 * List all agent tasks for a given sandbox.
 */
export async function listSandboxAgentTasks(
  sandboxId: string,
  config?: AxiosRequestConfig,
): Promise<AgentTaskListResponse> {
  const { data } = await client.get<AgentTaskListResponse>(
    `/api/v1/sandboxes/${sandboxId}/agent/tasks`,
    config,
  );
  return data;
}

/**
 * Retrieve details for a sandbox-scoped agent task.
 */
export async function getSandboxAgentTask(
  sandboxId: string,
  taskId: string,
  config?: AxiosRequestConfig,
): Promise<AgentTaskResponse> {
  const { data } = await client.get<AgentTaskResponse>(
    `/api/v1/sandboxes/${sandboxId}/agent/tasks/${taskId}`,
    config,
  );
  return data;
}

/**
 * Cancel an active sandbox agent task.
 */
export async function cancelSandboxAgentTask(
  sandboxId: string,
  taskId: string,
  config?: AxiosRequestConfig,
): Promise<AgentTaskResponse> {
  const { data } = await client.post<AgentTaskResponse>(
    `/api/v1/sandboxes/${sandboxId}/agent/tasks/${taskId}/cancel`,
    {},
    config,
  );
  return data;
}

/**
 * Retrieve execution jobs produced during a sandbox agent task.
 */
export async function getSandboxAgentTaskExecutions(
  sandboxId: string,
  taskId: string,
  config?: AxiosRequestConfig,
): Promise<ExecutionJob[]> {
  const { data } = await client.get<ExecutionJob[]>(
    `/api/v1/sandboxes/${sandboxId}/agent/tasks/${taskId}/executions`,
    config,
  );
  return data;
}

/**
 * Retrieve agent task details by ID across sandboxes.
 */
export async function getAgentTaskById(
  taskId: string,
  config?: AxiosRequestConfig,
): Promise<AgentTaskResponse> {
  const { data } = await client.get<AgentTaskResponse>(
    `/api/v1/agent/tasks/${taskId}`,
    config,
  );
  return data;
}

/**
 * Cancel agent task by ID.
 */
export async function cancelAgentTaskById(
  taskId: string,
  config?: AxiosRequestConfig,
): Promise<AgentTaskResponse> {
  const { data } = await client.post<AgentTaskResponse>(
    `/api/v1/agent/tasks/${taskId}/cancel`,
    {},
    config,
  );
  return data;
}

// ── Security Policy Engine ──────────────────────────────────

export async function getPlatformSecurityPolicy(
  config?: AxiosRequestConfig,
): Promise<PlatformSecurityPolicy> {
  const { data } = await client.get<PlatformSecurityPolicy>(
    "/api/v1/security/policy",
    config,
  );
  return data;
}

export async function evaluateSecurityPolicy(
  payload: RequestedPolicyPayload,
  config?: AxiosRequestConfig,
): Promise<SecurityEvaluationResponse> {
  const { data } = await client.post<SecurityEvaluationResponse>(
    "/api/v1/security/evaluate",
    payload,
    config,
  );
  return data;
}

export default client;
