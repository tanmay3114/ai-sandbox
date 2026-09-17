import client from "@/lib/api/client";
import type { ExecuteCodePayload, JobExecution } from "../types";

/**
 * Execute Python code inside a persistent sandbox session.
 * Endpoint: POST /api/v1/sandboxes/{sandbox_id}/execute
 */
export async function executeCode(
  sandboxId: string,
  payload: ExecuteCodePayload,
): Promise<JobExecution> {
  const { data } = await client.post<JobExecution>(
    `/api/v1/sandboxes/${sandboxId}/execute`,
    payload,
  );
  return data;
}

/**
 * List all execution jobs for a persistent sandbox session.
 * Endpoint: GET /api/v1/sandboxes/{sandbox_id}/executions
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
 * Retrieve execution job details by ID for a persistent sandbox session.
 * Endpoint: GET /api/v1/sandboxes/{sandbox_id}/executions/{execution_id}
 */
export async function getExecutionDetail(
  sandboxId: string,
  executionId: string,
): Promise<JobExecution> {
  const { data } = await client.get<JobExecution>(
    `/api/v1/sandboxes/${sandboxId}/executions/${executionId}`,
  );
  return data;
}
