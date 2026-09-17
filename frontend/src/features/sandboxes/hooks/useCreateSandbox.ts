import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createSandbox } from "../api";
import type { CreateSandboxPayload, SandboxResponse } from "../types";
import { SANDBOXES_QUERY_KEY } from "./useSandboxes";

export function useCreateSandbox() {
  const queryClient = useQueryClient();

  return useMutation<SandboxResponse, Error, CreateSandboxPayload>({
    mutationFn: (payload: CreateSandboxPayload) => createSandbox(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: SANDBOXES_QUERY_KEY });
    },
  });
}
