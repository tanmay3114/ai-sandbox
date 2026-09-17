import { useQuery } from "@tanstack/react-query";
import { getSandboxes } from "../api";
import type { SandboxDetail } from "../types";

export const SANDBOXES_QUERY_KEY = ["sandboxes"] as const;

export function useSandboxes() {
  return useQuery<SandboxDetail[], Error>({
    queryKey: SANDBOXES_QUERY_KEY,
    queryFn: getSandboxes,
    refetchInterval: 10_000,
    staleTime: 5_000,
  });
}
