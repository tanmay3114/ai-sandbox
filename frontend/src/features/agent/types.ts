// ============================================================
// AI Agent Feature Domain Types matching backend schemas
// ============================================================

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
