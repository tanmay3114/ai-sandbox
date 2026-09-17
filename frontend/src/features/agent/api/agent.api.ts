import client from "@/lib/api/client";
import type { AgentRunRequest, AgentRunResponse } from "../types";

/**
 * Execute an autonomous model-driven task via the backend SandboxAgent.
 * Endpoint: POST /api/v1/agent/run
 */
export async function runAgent(
  payload: AgentRunRequest,
): Promise<AgentRunResponse> {
  const { data } = await client.post<AgentRunResponse>(
    "/api/v1/agent/run",
    payload,
  );
  return data;
}
