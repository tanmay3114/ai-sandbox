"""Execution telemetry and phase timing collectors for the benchmark subsystem."""

from __future__ import annotations

import contextvars
import dataclasses
import time
from typing import Any


@dataclasses.dataclass
class ExecutionBreakdown:
    """Detailed phase timing breakdown and resource metrics for a single execution."""

    env_startup_ms: float = 0.0
    workspace_inject_ms: float = 0.0
    workload_exec_ms: float = 0.0
    workspace_retrieve_ms: float = 0.0
    cleanup_ms: float = 0.0
    measured_phases_sum_ms: float = 0.0
    unexplained_overhead_ms: float = 0.0
    total_duration_ms: float = 0.0

    # Resource consumption snapshots
    peak_memory_bytes: int | None = None
    steady_memory_bytes: int | None = None
    cpu_user_seconds: float | None = None
    cpu_system_seconds: float | None = None

    # Status & verification
    cleanup_confirmed: bool = False
    details: dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert breakdown to serializable dictionary."""
        return {
            "env_startup_ms": round(self.env_startup_ms, 3),
            "workspace_inject_ms": round(self.workspace_inject_ms, 3),
            "workload_exec_ms": round(self.workload_exec_ms, 3),
            "workspace_retrieve_ms": round(self.workspace_retrieve_ms, 3),
            "cleanup_ms": round(self.cleanup_ms, 3),
            "measured_phases_sum_ms": round(self.measured_phases_sum_ms, 3),
            "unexplained_overhead_ms": round(self.unexplained_overhead_ms, 3),
            "total_duration_ms": round(self.total_duration_ms, 3),
            "peak_memory_bytes": self.peak_memory_bytes,
            "steady_memory_bytes": self.steady_memory_bytes,
            "cpu_user_seconds": (
                round(self.cpu_user_seconds, 4) if self.cpu_user_seconds is not None else None
            ),
            "cpu_system_seconds": (
                round(self.cpu_system_seconds, 4) if self.cpu_system_seconds is not None else None
            ),
            "cleanup_confirmed": self.cleanup_confirmed,
            "details": self.details,
        }


class BenchmarkTelemetry:
    """Contextual telemetry sink for recording execution phases and resource metrics."""

    def __init__(self, backend_type: str = "unknown") -> None:
        self.backend_type = backend_type
        self.marks: dict[str, float] = {}
        self.peak_memory_bytes: int | None = None
        self.steady_memory_bytes: int | None = None
        self.cpu_user_seconds: float | None = None
        self.cpu_system_seconds: float | None = None
        self.cleanup_confirmed: bool = False
        self.details: dict[str, Any] = {}
        self.mark("start")

    def mark(self, event_name: str) -> None:
        """Record the monotonic timestamp of a phase event."""
        self.marks[event_name] = time.perf_counter()

    def duration_ms(self, start_event: str, end_event: str) -> float:
        """Compute duration in milliseconds between two recorded events (0.0 if either missing)."""
        if start_event in self.marks and end_event in self.marks:
            diff = self.marks[end_event] - self.marks[start_event]
            return max(0.0, diff * 1000.0)
        return 0.0

    def record_memory(
        self,
        peak_bytes: int | None = None,
        steady_bytes: int | None = None,
    ) -> None:
        """Record observed memory consumption."""
        if peak_bytes is not None:
            self.peak_memory_bytes = peak_bytes
        if steady_bytes is not None:
            self.steady_memory_bytes = steady_bytes

    def record_cpu(
        self,
        user_sec: float | None = None,
        sys_sec: float | None = None,
    ) -> None:
        """Record observed CPU time."""
        if user_sec is not None:
            self.cpu_user_seconds = user_sec
        if sys_sec is not None:
            self.cpu_system_seconds = sys_sec

    def record_cleanup_confirmed(self, confirmed: bool) -> None:
        """Record verified removal of container/VM resources."""
        self.cleanup_confirmed = confirmed

    def calculate_breakdown(self) -> ExecutionBreakdown:
        """Synthesize recorded phase timestamps into a coherent execution breakdown."""
        # Non-overlapping environment setup latency
        if "create_end" in self.marks and "start_start" in self.marks:
            # Docker model: create container + start container (excluding inject)
            env_startup_ms = self.duration_ms("start", "create_end") + self.duration_ms(
                "start_start", "env_ready"
            )
        else:
            # QEMU model: VM start to agent ready
            env_startup_ms = self.duration_ms("start", "env_ready")
            if env_startup_ms == 0.0:
                env_startup_ms = self.duration_ms("start", "workload_start")

        # Workspace injection
        inject_ms = self.duration_ms("inject_start", "inject_end")

        # Workload execution
        workload_ms = self.duration_ms("workload_start", "workload_end")

        # Workspace retrieval
        retrieve_ms = self.duration_ms("retrieve_start", "retrieve_end")

        # Cleanup
        cleanup_ms = self.duration_ms("cleanup_start", "cleanup_end")

        # Total wall-clock duration
        total_ms = self.duration_ms("start", "end")
        measured_sum_ms = env_startup_ms + inject_ms + workload_ms + retrieve_ms + cleanup_ms
        if total_ms == 0.0:
            total_ms = measured_sum_ms

        unexplained_overhead_ms = max(0.0, total_ms - measured_sum_ms)

        details_copy = dict(self.details)
        details_copy["raw_marks"] = {k: round(v, 6) for k, v in self.marks.items()}

        return ExecutionBreakdown(
            env_startup_ms=env_startup_ms,
            workspace_inject_ms=inject_ms,
            workload_exec_ms=workload_ms,
            workspace_retrieve_ms=retrieve_ms,
            cleanup_ms=cleanup_ms,
            measured_phases_sum_ms=measured_sum_ms,
            unexplained_overhead_ms=unexplained_overhead_ms,
            total_duration_ms=total_ms,
            peak_memory_bytes=self.peak_memory_bytes,
            steady_memory_bytes=self.steady_memory_bytes,
            cpu_user_seconds=self.cpu_user_seconds,
            cpu_system_seconds=self.cpu_system_seconds,
            cleanup_confirmed=self.cleanup_confirmed,
            details=details_copy,
        )


_current_telemetry: contextvars.ContextVar[BenchmarkTelemetry | None] = contextvars.ContextVar(
    "current_benchmark_telemetry",
    default=None,
)


def get_current_telemetry() -> BenchmarkTelemetry | None:
    """Return active benchmark telemetry sink if execution is being benchmarked."""
    return _current_telemetry.get()


def set_benchmark_telemetry(
    telemetry: BenchmarkTelemetry | None,
) -> contextvars.Token[BenchmarkTelemetry | None]:
    """Set active benchmark telemetry sink for the current context."""
    return _current_telemetry.set(telemetry)


def reset_benchmark_telemetry(token: contextvars.Token[BenchmarkTelemetry | None]) -> None:
    """Reset benchmark telemetry sink to its prior context value."""
    _current_telemetry.reset(token)
