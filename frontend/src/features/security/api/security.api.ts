import client from "@/lib/api/client";
import type {
  PlatformSecurityPolicy,
  RequestedPolicyPayload,
  SecurityEvaluationResponse,
} from "../types";

/**
 * Fetch the authoritative platform security policy directly from the backend.
 */
export async function getPlatformSecurityPolicy(): Promise<PlatformSecurityPolicy> {
  const { data } = await client.get<PlatformSecurityPolicy>("/api/v1/security/policy");
  return data;
}

/**
 * Perform a dry-run policy evaluation against the backend SecurityPolicyEngine.
 * Returns either an allowed/clamped decision or raises a SecurityPolicyViolationError (HTTP 400).
 */
export async function evaluatePolicy(
  payload: RequestedPolicyPayload,
): Promise<SecurityEvaluationResponse> {
  const { data } = await client.post<SecurityEvaluationResponse>(
    "/api/v1/security/evaluate",
    payload,
  );
  return data;
}
