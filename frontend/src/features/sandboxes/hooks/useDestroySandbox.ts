import { useMutation, useQueryClient } from "@tanstack/react-query";
import { destroySandbox } from "../api";
import type { SandboxResponse } from "../types";
import { sandboxQueryKey } from "./useSandbox";
import { SANDBOXES_QUERY_KEY } from "./useSandboxes";

export function useDestroySandbox() {
  const queryClient = useQueryClient();

  return useMutation<SandboxResponse, Error, string>({
    mutationFn: (sandboxId: string) => destroySandbox(sandboxId),
    onSuccess: (_, sandboxId) => {
      queryClient.invalidateQueries({ queryKey: SANDBOXES_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: sandboxQueryKey(sandboxId) });
    },
  });
}
