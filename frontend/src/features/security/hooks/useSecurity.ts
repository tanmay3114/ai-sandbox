import { useMutation, useQuery } from "@tanstack/react-query";
import { evaluatePolicy, getPlatformSecurityPolicy } from "../api/security.api";
import type { RequestedPolicyPayload, SecurityEvaluationResponse } from "../types";

export const SECURITY_KEYS = {
  all: ["security"] as const,
  policy: () => [...SECURITY_KEYS.all, "policy"] as const,
};

/**
 * Hook to retrieve active platform security policy.
 * Stale time is set to 60 seconds as policy is deterministic configuration.
 */
export function useSecurityPolicy() {
  return useQuery({
    queryKey: SECURITY_KEYS.policy(),
    queryFn: getPlatformSecurityPolicy,
    staleTime: 60_000,
  });
}

/**
 * Hook to evaluate a requested policy payload via the backend engine.
 */
export function useEvaluatePolicy() {
  return useMutation<SecurityEvaluationResponse, any, RequestedPolicyPayload>({
    mutationFn: evaluatePolicy,
  });
}
