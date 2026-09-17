import { useMutation } from "@tanstack/react-query";
import { runAgent } from "../api/agent.api";
import type { AgentRunRequest, AgentRunResponse } from "../types";

export function useRunAgent() {
  return useMutation<AgentRunResponse, Error, AgentRunRequest>({
    mutationFn: (payload: AgentRunRequest) => runAgent(payload),
  });
}
