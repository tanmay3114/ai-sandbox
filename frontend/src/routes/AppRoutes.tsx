import { Navigate, Route, Routes } from "react-router-dom";
import { AppLayout } from "@/components/layout/AppLayout";
import { Dashboard } from "@/pages/Dashboard";
import { Sandboxes } from "@/pages/Sandboxes";
import { ExecutionsPage } from "@/features/executions/pages/ExecutionsPage";
import { ExecutionDetailPage } from "@/features/executions/pages/ExecutionDetailPage";
import { AgentPage } from "@/features/agent/pages/AgentPage";
import { Security } from "@/pages/Security";
import { SandboxDetailsPage } from "@/features/sandboxes/SandboxDetailsPage";

export function AppRoutes() {
  return (
    <AppLayout>
      <Routes>
        {/* Root redirect */}
        <Route path="/" element={<Navigate to="/dashboard" replace />} />

        {/* Dashboard */}
        <Route path="/dashboard" element={<Dashboard />} />

        {/* Sandbox management */}
        <Route path="/dashboard/sandboxes" element={<Sandboxes />} />
        <Route
          path="/dashboard/sandboxes/:sandboxId"
          element={<SandboxDetailsPage />}
        />

        {/* Executions */}
        <Route path="/dashboard/executions" element={<ExecutionsPage />} />
        <Route
          path="/dashboard/executions/:executionId"
          element={<ExecutionDetailPage />}
        />
        <Route
          path="/dashboard/sandboxes/:sandboxId/executions/:executionId"
          element={<ExecutionDetailPage />}
        />

        {/* Agent */}
        <Route path="/dashboard/agent" element={<AgentPage />} />

        {/* Security */}
        <Route path="/dashboard/security" element={<Security />} />

        {/* Fallback */}
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </AppLayout>
  );
}
