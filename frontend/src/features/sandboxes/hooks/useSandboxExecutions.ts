import { useQuery } from "@tanstack/react-query";
import { getSandboxExecutions } from "../api";
import type { JobExecution } from "../types";

export const sandboxExecutionsQueryKey = (id: string) =>
  ["sandbox", id, "executions"] as const;

export function useSandboxExecutions(sandboxId: string | undefined) {
  return useQuery<JobExecution[], Error>({
    queryKey: sandboxExecutionsQueryKey(sandboxId ?? ""),
    queryFn: () => {
      if (!sandboxId) throw new Error("Sandbox ID is required");
      return getSandboxExecutions(sandboxId);
    },
    enabled: Boolean(sandboxId),
    refetchInterval: 5_000,
    staleTime: 3_000,
  });
}
