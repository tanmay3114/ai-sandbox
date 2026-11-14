import type {
  AgentRunRequest,
  AgentRunResponse,
  AgentTaskCreateRequest,
  AgentTaskListResponse,
  AgentTaskResponse,
  CreateDirectoryRequest,
  CreateDirectoryResponse,
  CreateSandboxRequest,
  DeleteFileResponse,
  ExecuteCodeRequest,
  ExecutionJob,
  ExecutionResult,
  FileContent,
  FileListResponse,
  HealthResponse,
  PlatformSecurityPolicy,
  ReadyResponse,
  RequestedPolicyPayload,
  SandboxDetail,
  SandboxResponse,
  SecurityEvaluationResponse,
  WriteFileRequest,
} from "@/types";
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationOptions,
  type UseQueryOptions,
} from "@tanstack/react-query";
import * as api from "./client";

/**
 * Standard TanStack Query Keys for the entire application.
 */
export const queryKeys = {
  health: ["health"] as const,
  ready: ["ready"] as const,
  sandboxes: {
    all: ["sandboxes"] as const,
    detail: (id: string) => ["sandboxes", "detail", id] as const,
    executions: (id: string) => ["sandboxes", "executions", id] as const,
  },
  executions: {
    detail: (sandboxId: string, executionId: string) =>
      ["executions", "detail", sandboxId, executionId] as const,
  },
  workspace: {
    files: (sandboxId: string, path?: string) =>
      ["workspace", "files", sandboxId, path ?? "root"] as const,
    fileContent: (sandboxId: string, path: string) =>
      ["workspace", "content", sandboxId, path] as const,
  },
  agent: {
    tasks: (sandboxId: string) => ["agent", "tasks", sandboxId] as const,
    taskDetail: (taskId: string) => ["agent", "task", taskId] as const,
    taskExecutions: (sandboxId: string, taskId: string) =>
      ["agent", "task", "executions", sandboxId, taskId] as const,
  },
  security: {
    policy: ["security", "policy"] as const,
  },
};

// ── Health Hooks ────────────────────────────────────────────

export function useHealth(options?: Partial<UseQueryOptions<HealthResponse>>) {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: () => api.fetchHealth(),
    staleTime: 10_000,
    ...options,
  });
}

export function useReady(options?: Partial<UseQueryOptions<ReadyResponse>>) {
  return useQuery({
    queryKey: queryKeys.ready,
    queryFn: () => api.fetchReady(),
    staleTime: 10_000,
    ...options,
  });
}

// ── Sandbox Hooks ───────────────────────────────────────────

export function useSandboxes(options?: Partial<UseQueryOptions<SandboxDetail[]>>) {
  return useQuery({
    queryKey: queryKeys.sandboxes.all,
    queryFn: () => api.listSandboxes(),
    staleTime: 15_000,
    ...options,
  });
}

export function useSandbox(sandboxId: string, options?: Partial<UseQueryOptions<SandboxDetail>>) {
  return useQuery({
    queryKey: queryKeys.sandboxes.detail(sandboxId),
    queryFn: () => api.getSandbox(sandboxId),
    enabled: Boolean(sandboxId),
    staleTime: 10_000,
    ...options,
  });
}

export function useCreateSandbox(
  options?: UseMutationOptions<SandboxResponse, Error, CreateSandboxRequest | undefined>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload) => api.createSandbox(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.sandboxes.all });
    },
    ...options,
  });
}

export function useDeleteSandbox(
  options?: UseMutationOptions<SandboxResponse, Error, string>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (sandboxId) => api.deleteSandbox(sandboxId),
    onSuccess: (_, sandboxId) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.sandboxes.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.sandboxes.detail(sandboxId) });
    },
    ...options,
  });
}

// ── Execution Hooks ─────────────────────────────────────────

export function useSandboxExecutions(
  sandboxId: string,
  options?: Partial<UseQueryOptions<ExecutionJob[]>>,
) {
  return useQuery({
    queryKey: queryKeys.sandboxes.executions(sandboxId),
    queryFn: () => api.listSandboxExecutions(sandboxId),
    enabled: Boolean(sandboxId),
    staleTime: 5_000,
    ...options,
  });
}

export function useExecutionDetail(
  sandboxId: string,
  executionId: string,
  options?: Partial<UseQueryOptions<ExecutionJob>>,
) {
  return useQuery({
    queryKey: queryKeys.executions.detail(sandboxId, executionId),
    queryFn: () => api.getExecution(sandboxId, executionId),
    enabled: Boolean(sandboxId && executionId),
    staleTime: 10_000,
    ...options,
  });
}

export function useExecuteInSandbox(
  sandboxId: string,
  options?: UseMutationOptions<ExecutionJob, Error, ExecuteCodeRequest>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload) => api.executeInSandbox(sandboxId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.sandboxes.executions(sandboxId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.sandboxes.detail(sandboxId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.sandboxes.all });
      // Invalidate workspace files since execution can modify files
      queryClient.invalidateQueries({ queryKey: ["workspace", "files", sandboxId] });
    },
    ...options,
  });
}

export function useExecuteEphemeral(
  options?: UseMutationOptions<ExecutionResult, Error, ExecuteCodeRequest>,
) {
  return useMutation({
    mutationFn: (payload) => api.executeEphemeral(payload),
    ...options,
  });
}

// ── Workspace Files Hooks ───────────────────────────────────

export function useWorkspaceFiles(
  sandboxId: string,
  path?: string,
  options?: Partial<UseQueryOptions<FileListResponse>>,
) {
  return useQuery({
    queryKey: queryKeys.workspace.files(sandboxId, path),
    queryFn: () => api.listWorkspaceFiles(sandboxId, path),
    enabled: Boolean(sandboxId),
    staleTime: 5_000,
    ...options,
  });
}

export function useWorkspaceFileContent(
  sandboxId: string,
  filePath: string,
  options?: Partial<UseQueryOptions<FileContent>>,
) {
  return useQuery({
    queryKey: queryKeys.workspace.fileContent(sandboxId, filePath),
    queryFn: () => api.readWorkspaceFile(sandboxId, filePath),
    enabled: Boolean(sandboxId && filePath),
    staleTime: 10_000,
    ...options,
  });
}

export function useWriteWorkspaceFile(
  sandboxId: string,
  options?: UseMutationOptions<FileContent, Error, WriteFileRequest>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload) => api.writeWorkspaceFile(sandboxId, payload),
    onSuccess: (_, vars) => {
      queryClient.invalidateQueries({ queryKey: ["workspace", "files", sandboxId] });
      queryClient.invalidateQueries({ queryKey: queryKeys.workspace.fileContent(sandboxId, vars.path) });
    },
    ...options,
  });
}

export function useCreateWorkspaceDirectory(
  sandboxId: string,
  options?: UseMutationOptions<CreateDirectoryResponse, Error, CreateDirectoryRequest>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload) => api.createWorkspaceDirectory(sandboxId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["workspace", "files", sandboxId] });
    },
    ...options,
  });
}

export function useDeleteWorkspaceFile(
  sandboxId: string,
  options?: UseMutationOptions<DeleteFileResponse, Error, string>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (filePath) => api.deleteWorkspaceFile(sandboxId, filePath),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["workspace", "files", sandboxId] });
    },
    ...options,
  });
}

// ── Agent Task Hooks ────────────────────────────────────────

/**
 * Hook for synchronous standalone agent run (POST /api/v1/agent/run).
 */
export function useRunAgent(
  options?: UseMutationOptions<AgentRunResponse, Error, AgentRunRequest>,
) {
  return useMutation({
    mutationFn: (payload) => api.runAgent(payload),
    ...options,
  });
}

/**
 * Hook for sandbox-scoped synchronous agent task.
 * Note: POST /api/v1/sandboxes/{sandbox_id}/agent/tasks is synchronous on the backend.
 */
export function useCreateAndRunAgentTask(
  sandboxId: string,
  options?: UseMutationOptions<AgentTaskResponse, Error, AgentTaskCreateRequest>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload) => api.createAndRunAgentTask(sandboxId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.agent.tasks(sandboxId) });
      queryClient.invalidateQueries({ queryKey: ["workspace", "files", sandboxId] });
      queryClient.invalidateQueries({ queryKey: queryKeys.sandboxes.executions(sandboxId) });
    },
    ...options,
  });
}

export function useSandboxAgentTasks(
  sandboxId: string,
  options?: Partial<UseQueryOptions<AgentTaskListResponse>>,
) {
  return useQuery({
    queryKey: queryKeys.agent.tasks(sandboxId),
    queryFn: () => api.listSandboxAgentTasks(sandboxId),
    enabled: Boolean(sandboxId),
    staleTime: 5_000,
    ...options,
  });
}

export function useAgentTaskDetail(
  taskId: string,
  options?: Partial<UseQueryOptions<AgentTaskResponse>>,
) {
  return useQuery({
    queryKey: queryKeys.agent.taskDetail(taskId),
    queryFn: () => api.getAgentTaskById(taskId),
    enabled: Boolean(taskId),
    staleTime: 5_000,
    ...options,
  });
}

export function useCancelAgentTask(
  sandboxId: string,
  options?: UseMutationOptions<AgentTaskResponse, Error, string>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (taskId) => api.cancelSandboxAgentTask(sandboxId, taskId),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.agent.tasks(sandboxId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.agent.taskDetail(data.task_id) });
    },
    ...options,
  });
}

export function useAgentTaskExecutions(
  sandboxId: string,
  taskId: string,
  options?: Partial<UseQueryOptions<ExecutionJob[]>>,
) {
  return useQuery({
    queryKey: queryKeys.agent.taskExecutions(sandboxId, taskId),
    queryFn: () => api.getSandboxAgentTaskExecutions(sandboxId, taskId),
    enabled: Boolean(sandboxId && taskId),
    staleTime: 5_000,
    ...options,
  });
}

// ── Security Policy Hooks ───────────────────────────────────

export function usePlatformSecurityPolicy(
  options?: Partial<UseQueryOptions<PlatformSecurityPolicy>>,
) {
  return useQuery({
    queryKey: queryKeys.security.policy,
    queryFn: () => api.getPlatformSecurityPolicy(),
    staleTime: 60_000,
    ...options,
  });
}

export function useEvaluateSecurityPolicy(
  options?: UseMutationOptions<SecurityEvaluationResponse, Error, RequestedPolicyPayload>,
) {
  return useMutation({
    mutationFn: (payload) => api.evaluateSecurityPolicy(payload),
    ...options,
  });
}
