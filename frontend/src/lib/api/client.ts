import type {
  AgentRunRequest,
  AgentRunResponse,
  ExecutionJob,
  ExecutionResult,
  HealthResponse,
  ReadyResponse,
  Sandbox,
  SandboxDetail,
} from "@/types";
import axios from "axios";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

const client = axios.create({
  baseURL: BASE_URL,
  headers: {
    "Content-Type": "application/json",
  },
});

// ── Health ─────────────────────────────────────────────────────────────────

export async function fetchHealth(): Promise<HealthResponse> {
  const { data } = await client.get<HealthResponse>("/health");
  return data;
}

export async function fetchReady(): Promise<ReadyResponse> {
  const { data } = await client.get<ReadyResponse>("/ready");
  return data;
}

// ── Sandboxes ──────────────────────────────────────────────────────────────

export async function createSandbox(
  runtime = "python",
  ttl_seconds = 300,
): Promise<Sandbox> {
  const { data } = await client.post<Sandbox>("/api/v1/sandboxes", {
    runtime,
    ttl_seconds,
  });
  return data;
}

export async function getSandbox(sandboxId: string): Promise<SandboxDetail> {
  const { data } = await client.get<SandboxDetail>(
    `/api/v1/sandboxes/${sandboxId}`,
  );
  return data;
}

export async function deleteSandbox(sandboxId: string): Promise<Sandbox> {
  const { data } = await client.delete<Sandbox>(
    `/api/v1/sandboxes/${sandboxId}`,
  );
  return data;
}

// ── Executions ─────────────────────────────────────────────────────────────

export async function executeInSandbox(
  sandboxId: string,
  code: string,
  timeout_seconds?: number,
): Promise<ExecutionJob> {
  const { data } = await client.post<ExecutionJob>(
    `/api/v1/sandboxes/${sandboxId}/execute`,
    { code, timeout_seconds },
  );
  return data;
}

export async function getExecution(
  sandboxId: string,
  executionId: string,
): Promise<ExecutionJob> {
  const { data } = await client.get<ExecutionJob>(
    `/api/v1/sandboxes/${sandboxId}/executions/${executionId}`,
  );
  return data;
}

export async function executeEphemeral(
  code: string,
  timeout_seconds?: number,
): Promise<ExecutionResult> {
  const { data } = await client.post<ExecutionResult>(
    "/api/v1/sandboxes/execute",
    { code, timeout_seconds },
  );
  return data;
}

// ── Agent ──────────────────────────────────────────────────────────────────

export async function runAgent(
  request: AgentRunRequest,
): Promise<AgentRunResponse> {
  const { data } = await client.post<AgentRunResponse>(
    "/api/v1/agent/run",
    request,
  );
  return data;
}

export default client;
