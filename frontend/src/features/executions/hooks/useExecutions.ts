import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  executeCode,
  getExecutionDetail,
  getSandboxExecutions,
} from "../api/executions.api";
import type { ExecuteCodePayload, JobExecution } from "../types";

export const sandboxExecutionsQueryKey = (sandboxId: string) =>
  ["sandbox", sandboxId, "executions"] as const;

export const executionDetailQueryKey = (
  sandboxId: string,
  executionId: string,
) => ["sandbox", sandboxId, "execution", executionId] as const;

export function useSandboxExecutions(sandboxId: string | undefined) {
  return useQuery<JobExecution[], Error>({
    queryKey: sandboxExecutionsQueryKey(sandboxId ?? ""),
    queryFn: () => {
      if (!sandboxId) throw new Error("Sandbox ID is required");
      return getSandboxExecutions(sandboxId);
    },
    enabled: Boolean(sandboxId),
    refetchInterval: 5_000,
    staleTime: 2_000,
  });
}

export function useExecution(
  sandboxId: string | undefined,
  executionId: string | undefined,
) {
  return useQuery<JobExecution, Error>({
    queryKey: executionDetailQueryKey(sandboxId ?? "", executionId ?? ""),
    queryFn: () => {
      if (!sandboxId || !executionId) {
        throw new Error("Both sandboxId and executionId are required");
      }
      return getExecutionDetail(sandboxId, executionId);
    },
    enabled: Boolean(sandboxId && executionId),
    staleTime: 10_000,
  });
}

export function useExecuteCode(sandboxId: string | undefined) {
  const queryClient = useQueryClient();

  return useMutation<JobExecution, Error, ExecuteCodePayload>({
    mutationFn: (payload: ExecuteCodePayload) => {
      if (!sandboxId) {
        throw new Error("Sandbox ID is required for execution");
      }
      return executeCode(sandboxId, payload);
    },
    onSuccess: () => {
      if (sandboxId) {
        // Refresh execution list for this sandbox
        queryClient.invalidateQueries({
          queryKey: sandboxExecutionsQueryKey(sandboxId),
        });
        // Invalidate sandbox summary to update executions_count
        queryClient.invalidateQueries({
          queryKey: ["sandbox", sandboxId],
        });
      }
    },
  });
}
