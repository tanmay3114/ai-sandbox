import { useQuery } from "@tanstack/react-query";
import { getSandbox } from "../api";
import type { SandboxDetail } from "../types";

export const sandboxQueryKey = (id: string) => ["sandbox", id] as const;

export function useSandbox(sandboxId: string | undefined) {
  return useQuery<SandboxDetail, Error>({
    queryKey: sandboxQueryKey(sandboxId ?? ""),
    queryFn: () => {
      if (!sandboxId) throw new Error("Sandbox ID is required");
      return getSandbox(sandboxId);
    },
    enabled: Boolean(sandboxId),
    refetchInterval: 5_000,
    staleTime: 3_000,
  });
}
