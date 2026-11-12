"""Unit tests for the AI Sandbox Docker vs QEMU benchmark framework."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from app.sandbox.schemas import ExecutionRequest, ExecutionResult, ExecutionStatus
from benchmarks.config import BenchmarkConfig
from benchmarks.metrics import (
    AggregatedBenchmarkResult,
    BenchmarkExecutionSample,
    MetricSummary,
    calculate_percentile,
)
from benchmarks.report import (
    generate_markdown_report,
    generate_raw_measurements_csv,
    generate_summary_csv,
)
from benchmarks.runner import BenchmarkRunner, collect_system_metadata
from benchmarks.storage import BenchmarkResultStorage
from benchmarks.telemetry import (
    BenchmarkTelemetry,
    ExecutionBreakdown,
    get_current_telemetry,
    reset_benchmark_telemetry,
    set_benchmark_telemetry,
)
from benchmarks.workloads import ALL_WORKLOADS, get_workload


class MockBenchmarkBackend:
    """Mock backend implementing the SandboxBackend Protocol for unit testing."""

    def __init__(
        self,
        status: ExecutionStatus = ExecutionStatus.COMPLETED,
        exit_code: int = 0,
        fail_cleanup: bool = False,
    ) -> None:
        self.status = status
        self.exit_code = exit_code
        self.fail_cleanup = fail_cleanup
        self.cleaned_sandboxes: list[str] = []
        self.written_files: dict[str, dict[str, str | bytes]] = {}

    def execute(
        self, request: ExecutionRequest, *, sandbox_id: str | None = None
    ) -> ExecutionResult:
        telemetry = get_current_telemetry()
        if telemetry is not None:
            telemetry.mark("create_start")
            telemetry.mark("inject_start")
            telemetry.mark("inject_end")
            telemetry.mark("env_ready")
            telemetry.mark("workload_start")
            telemetry.mark("workload_end")
            telemetry.record_memory(peak_bytes=32 * 1024 * 1024, steady_bytes=16 * 1024 * 1024)
            telemetry.record_cpu(user_sec=0.05, sys_sec=0.01)
            telemetry.mark("retrieve_start")
            telemetry.mark("retrieve_end")
            telemetry.mark("cleanup_start")
            telemetry.mark("cleanup_end")
            telemetry.record_cleanup_confirmed(not self.fail_cleanup)
            telemetry.mark("end")

        return ExecutionResult(
            sandbox_id=sandbox_id or "mock-sbx",
            status=self.status,
            exit_code=self.exit_code if self.status != ExecutionStatus.TIMED_OUT else None,
            stdout="MOCK_STDOUT\n",
            stderr="",
            duration_ms=42,
        )

    def cleanup_sandbox(self, sandbox_id: str) -> None:
        self.cleaned_sandboxes.append(sandbox_id)

    def check_health(self) -> None:
        pass

    def write_file(self, sandbox_id: str, path: str, content: str | bytes, encoding: str = "utf-8"):
        if sandbox_id not in self.written_files:
            self.written_files[sandbox_id] = {}
        self.written_files[sandbox_id][path] = content


# -----------------------------------------------------------------------------
# 1. Statistical Calculations & Percentiles
# -----------------------------------------------------------------------------


def test_calculate_percentile_empty_and_single():
    assert calculate_percentile([], 50.0) == 0.0
    assert calculate_percentile([42.0], 50.0) == 42.0
    assert calculate_percentile([42.0], 0.0) == 42.0
    assert calculate_percentile([42.0], 100.0) == 42.0


def test_calculate_percentile_known_distributions():
    # 5 items: [10, 20, 30, 40, 50]
    vals = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert calculate_percentile(vals, 0.0) == 10.0
    assert calculate_percentile(vals, 50.0) == 30.0
    assert calculate_percentile(vals, 100.0) == 50.0
    # p95 should interpolate between 40 and 50: rank = 4 * 0.95 = 3.8 -> 40 + 0.8 * 10 = 48.0
    assert pytest.approx(calculate_percentile(vals, 95.0)) == 48.0


def test_metric_summary_computation():
    vals = [10.0, 20.0, 30.0, 40.0, 50.0]
    summary = MetricSummary.compute(vals)
    assert summary.samples == 5
    assert summary.min == 10.0
    assert summary.max == 50.0
    assert summary.mean == 30.0
    assert summary.median == 30.0
    assert pytest.approx(summary.std_dev, rel=1e-2) == math.sqrt(250.0)


def test_metric_summary_empty():
    summary = MetricSummary.compute([])
    assert summary.samples == 0
    assert summary.mean == 0.0
    assert summary.median == 0.0


# -----------------------------------------------------------------------------
# 2. Telemetry and Phase Breakdown
# -----------------------------------------------------------------------------


def test_telemetry_marks_and_breakdown():
    telem = BenchmarkTelemetry(backend_type="mock")
    telem.mark("env_ready")
    telem.mark("inject_start")
    telem.mark("inject_end")
    telem.mark("workload_start")
    telem.mark("workload_end")
    telem.mark("retrieve_start")
    telem.mark("retrieve_end")
    telem.mark("cleanup_start")
    telem.mark("cleanup_end")
    telem.mark("end")
    telem.record_memory(peak_bytes=1000, steady_bytes=800)
    telem.record_cpu(user_sec=0.1, sys_sec=0.02)
    telem.record_cleanup_confirmed(True)

    breakdown = telem.calculate_breakdown()
    assert breakdown.peak_memory_bytes == 1000
    assert breakdown.steady_memory_bytes == 800
    assert breakdown.cpu_user_seconds == 0.1
    assert breakdown.cleanup_confirmed is True
    assert breakdown.total_duration_ms >= 0.0


def test_telemetry_context_var():
    assert get_current_telemetry() is None
    telem = BenchmarkTelemetry(backend_type="test")
    token = set_benchmark_telemetry(telem)
    try:
        assert get_current_telemetry() is telem
    finally:
        reset_benchmark_telemetry(token)
    assert get_current_telemetry() is None


# -----------------------------------------------------------------------------
# 3. Workload Definitions & Validation
# -----------------------------------------------------------------------------


def test_workload_python_syntax():
    for name, wl in ALL_WORKLOADS.items():
        # Verify all benchmark Python snippets compile without syntax error
        compiled = compile(wl.code, f"<{name}>", "exec")
        assert compiled is not None


def test_get_workload_lookup():
    wl = get_workload("minimal_process")
    assert wl.name == "minimal_process"
    with pytest.raises(KeyError):
        get_workload("non_existent_workload")


# -----------------------------------------------------------------------------
# 4. Configuration and System Metadata
# -----------------------------------------------------------------------------


def test_benchmark_config_creation():
    smoke = BenchmarkConfig.create_smoke(backends=("docker",))
    assert smoke.smoke is True
    assert smoke.repetitions == 3
    assert smoke.concurrency_levels == (1, 2)

    full = BenchmarkConfig.create_full(backends=("docker", "qemu"), repetitions=20)
    assert full.smoke is False
    assert full.repetitions == 20
    assert full.concurrency_levels == (1, 2, 4)


def test_collect_system_metadata():
    meta = collect_system_metadata()
    assert "os_system" in meta
    assert "machine" in meta
    assert "python_version" in meta
    assert "timestamp_utc" in meta


# -----------------------------------------------------------------------------
# 5. Reporting and CSV / Markdown Serialization
# -----------------------------------------------------------------------------


def test_csv_and_markdown_generation(tmp_path: Path):
    s1 = BenchmarkExecutionSample(
        sample_id=1,
        backend="docker",
        workload_name="minimal_process",
        run_type="cold_host_cache_start",
        status="completed",
        exit_code=0,
        breakdown=ExecutionBreakdown(
            env_startup_ms=250.0,
            workspace_inject_ms=10.0,
            workload_exec_ms=50.0,
            workspace_retrieve_ms=5.0,
            cleanup_ms=30.0,
            total_duration_ms=345.0,
            peak_memory_bytes=32 * 1024 * 1024,
            cleanup_confirmed=True,
        ),
        concurrency_level=1,
    )
    s2 = BenchmarkExecutionSample(
        sample_id=2,
        backend="docker",
        workload_name="minimal_process",
        run_type="warm_cache_start",
        status="completed",
        exit_code=0,
        breakdown=ExecutionBreakdown(
            env_startup_ms=200.0,
            workspace_inject_ms=8.0,
            workload_exec_ms=45.0,
            workspace_retrieve_ms=5.0,
            cleanup_ms=25.0,
            total_duration_ms=283.0,
            peak_memory_bytes=30 * 1024 * 1024,
            cleanup_confirmed=True,
        ),
        concurrency_level=1,
    )

    agg = AggregatedBenchmarkResult.aggregate(
        samples=[s1, s2],
        backend="docker",
        workload_name="minimal_process",
        concurrency_level=1,
        wall_time_seconds=0.6,
    )

    summary_csv = generate_summary_csv([agg])
    assert "backend,workload,concurrency" in summary_csv
    assert "docker,minimal_process,1" in summary_csv

    raw_csv = generate_raw_measurements_csv([s1, s2])
    assert "sample_id,backend,workload" in raw_csv
    assert "cold_host_cache_start" in raw_csv

    md_report = generate_markdown_report(
        run_id="test_run",
        system_metadata={"os_system": "Darwin", "machine": "arm64"},
        aggregated=[agg],
        samples=[s1, s2],
    )
    assert "# AI Sandbox Benchmark Report" in md_report
    assert "minimal_process" in md_report
    assert "Phase Timing Breakdown" in md_report


# -----------------------------------------------------------------------------
# 6. Mock Runner Integration & Storage Round-Trip
# -----------------------------------------------------------------------------


def test_runner_with_mock_backend(tmp_path: Path):
    mock_backend = MockBenchmarkBackend()
    cfg = BenchmarkConfig.create_smoke(backends=("docker",), output_dir=tmp_path)
    cfg.repetitions = 2
    cfg.concurrency_levels = (1, 2)

    runner = BenchmarkRunner(
        config=cfg,
        custom_backends={"docker": mock_backend},
    )

    data = runner.run_all()
    assert data["total_samples_collected"] > 0
    assert len(runner.samples) > 0
    assert len(runner.aggregated) > 0

    storage = BenchmarkResultStorage(base_output_dir=tmp_path)
    run_dir = storage.save_results(runner)

    assert (run_dir / "results.json").exists()
    assert (run_dir / "summary.csv").exists()
    assert (run_dir / "raw_measurements.csv").exists()
    assert (run_dir / "REPORT.md").exists()

    loaded = BenchmarkResultStorage.load_json(run_dir)
    assert loaded["run_id"] == cfg.run_id
    assert loaded["total_samples_collected"] == len(runner.samples)
