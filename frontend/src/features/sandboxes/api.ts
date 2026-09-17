import client from "@/lib/api/client";
import type {
  CreateSandboxPayload,
  JobExecution,
  SandboxDetail,
  SandboxResponse,
} from "./types";

/**
 * Fetch all persistent sandbox sessions.
 */
export async function getSandboxes(): Promise<SandboxDetail[]> {
  const { data } = await client.get<SandboxDetail[]>("/api/v1/sandboxes");
  return data;
}

/**
 * Fetch a single sandbox by UUID.
 */
export async function getSandbox(sandboxId: string): Promise<SandboxDetail> {
  const { data } = await client.get<SandboxDetail>(
    `/api/v1/sandboxes/${sandboxId}`,
  );
  return data;
}

/**
 * Fetch execution history for a given sandbox.
 */
export async function getSandboxExecutions(
  sandboxId: string,
): Promise<JobExecution[]> {
  const { data } = await client.get<JobExecution[]>(
    `/api/v1/sandboxes/${sandboxId}/executions`,
  );
  return data;
}

/**
 * Create a new sandbox session with defined runtime and TTL.
 */
export async function createSandbox(
  payload: CreateSandboxPayload,
): Promise<SandboxResponse> {
  const { data } = await client.post<SandboxResponse>(
    "/api/v1/sandboxes",
    payload,
  );
  return data;
}

/**
 * Idempotently destroy a sandbox session.
 */
export async function destroySandbox(
  sandboxId: string,
): Promise<SandboxResponse> {
  const { data } = await client.delete<SandboxResponse>(
    `/api/v1/sandboxes/${sandboxId}`,
  );
  return data;
}
