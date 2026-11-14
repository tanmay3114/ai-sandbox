"""Core benchmark execution engine and orchestrator for Docker and QEMU backends."""

from __future__ import annotations

import concurrent.futures
import contextlib
import logging
import os
import platform
import subprocess
import threading
import time
from datetime import UTC, datetime
from typing import Any

from app.core.config import SandboxSettings, settings
from app.sandbox.backend import SandboxBackend
from app.sandbox.docker_backend import DockerSandboxBackend
from app.sandbox.factory import create_sandbox_backend
from app.sandbox.qemu.runtime import detect_qemu_capabilities
from app.sandbox.qemu_backend import QemuSandboxBackend
from app.sandbox.schemas import ExecutionRequest
from benchmarks.config import BenchmarkConfig
from benchmarks.metrics import (
    AggregatedBenchmarkResult,
    BenchmarkExecutionSample,
)
from benchmarks.telemetry import (
    BenchmarkTelemetry,
    reset_benchmark_telemetry,
    set_benchmark_telemetry,
)
from benchmarks.workloads import (
    ALL_WORKLOADS,
    BenchmarkWorkload,
)

logger = logging.getLogger(__name__)


def collect_system_metadata() -> dict[str, Any]:
    """Capture host architecture, OS versions, Docker and QEMU versions for reproducibility."""
    meta: dict[str, Any] = {
        "os_system": platform.system(),
        "os_release": platform.release(),
        "os_version": platform.version(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "timestamp_utc": datetime.now(UTC).isoformat(),
    }

    # macOS CPU model and hardware memory
    if platform.system().lower() == "darwin":
        with contextlib.suppress(Exception):
            proc = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                timeout=1.0,
                check=False,
            )
            if proc.stdout.strip():
                meta["cpu_brand"] = proc.stdout.strip()

        with contextlib.suppress(Exception):
            proc = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
                timeout=1.0,
                check=False,
            )
            if proc.stdout.strip():
                meta["host_total_ram_bytes"] = int(proc.stdout.strip())

    # Docker version
    try:
        import docker

        client = docker.from_env()
        meta["docker_server_version"] = client.version().get("Version", "unknown")
    except Exception as exc:
        meta["docker_server_version"] = f"unavailable ({exc})"

    # QEMU version
    try:
        proc = subprocess.run(
            ["qemu-system-aarch64", "--version"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if proc.returncode == 0:
            meta["qemu_version"] = proc.stdout.splitlines()[0]
        else:
            meta["qemu_version"] = "unavailable"
    except Exception:
        meta["qemu_version"] = "unavailable"

    return meta


class BenchmarkRunner:
    """Executes benchmark workloads across Docker and QEMU backends with telemetry collection."""

    def __init__(
        self,
        config: BenchmarkConfig,
        app_settings: SandboxSettings = settings,
        custom_backends: dict[str, SandboxBackend] | None = None,
    ) -> None:
        self.config = config
        self.app_settings = app_settings
        self.system_metadata = collect_system_metadata()
        self.samples: list[BenchmarkExecutionSample] = []
        self.aggregated: list[AggregatedBenchmarkResult] = []
        self.custom_backends = custom_backends or {}
        self._sample_counter = 0

    def _get_backend(self, backend_name: str) -> SandboxBackend:
        """Instantiate or retrieve verified backend implementation."""
        if backend_name in self.custom_backends:
            return self.custom_backends[backend_name]

        if backend_name == "docker":
            return DockerSandboxBackend(config=self.app_settings)
        if backend_name == "qemu":
            caps = detect_qemu_capabilities(self.app_settings)
            if not caps.is_ready:
                raise RuntimeError(
                    f"QEMU backend not ready on this host:\n{caps.format_diagnostic()}"
                )
            return QemuSandboxBackend(config=self.app_settings)

        return create_sandbox_backend(
            self.app_settings.model_copy(update={"BACKEND": backend_name})
        )

    def run_single_workload(
        self,
        backend: SandboxBackend,
        backend_name: str,
        workload: BenchmarkWorkload,
        run_type: str = "warm_cache_start",
        concurrency_level: int = 1,
    ) -> BenchmarkExecutionSample:
        """Execute a single workload against a backend while recording complete phase telemetry."""
        self._sample_counter += 1
        sample_id = self._sample_counter

        sandbox_id = f"bench-{backend_name}-{workload.name}-{sample_id}-{os.getpid()}"
        has_workspace = workload.has_persistent_workspace

        telemetry = BenchmarkTelemetry(backend_type=backend_name)
        token = set_benchmark_telemetry(telemetry)

        status_str = "error"
        exit_code: int | None = None
        error_msg: str | None = None
        slot_wait_ms = 0.0

        try:
            # Seed workspace files if specified
            if has_workspace and workload.setup_files:
                for file_path, content in workload.setup_files.items():
                    backend.write_file(sandbox_id, file_path, content)

            req = ExecutionRequest(
                code=workload.code,
                timeout_seconds=workload.timeout_seconds,
            )

            res = backend.execute(req, sandbox_id=sandbox_id if has_workspace else None)
            status_str = res.status.value
            exit_code = res.exit_code
            error_msg = res.error_message

            if res.stdout and telemetry.peak_memory_bytes is None:
                import re

                match = re.search(r"PEAK_RSS_KB=(\d+)", res.stdout)
                if match:
                    rss_bytes = int(match.group(1)) * 1024
                    telemetry.record_memory(peak_bytes=rss_bytes, steady_bytes=rss_bytes)
            is_expected = (status_str == workload.expected_status) and (
                workload.expected_exit_code is None or exit_code == workload.expected_exit_code
            )
        except Exception as exc:
            logger.warning("Benchmark sample %d raised exception: %s", sample_id, exc)
            status_str = "error"
            error_msg = str(exc)
            is_expected = False
        finally:
            reset_benchmark_telemetry(token)
            if has_workspace:
                with contextlib.suppress(Exception):
                    backend.cleanup_sandbox(sandbox_id)

        breakdown = telemetry.calculate_breakdown()

        return BenchmarkExecutionSample(
            sample_id=sample_id,
            backend=backend_name,
            workload_name=workload.name,
            run_type=run_type,
            status=status_str,
            exit_code=exit_code,
            is_expected_outcome=is_expected,
            breakdown=breakdown,
            concurrency_level=concurrency_level,
            slot_wait_ms=slot_wait_ms,
            timestamp=datetime.now(UTC).isoformat(),
            error_message=error_msg,
        )

    def run_workload_repetitions(
        self,
        backend_name: str,
        workload: BenchmarkWorkload,
        repetitions: int,
    ) -> list[BenchmarkExecutionSample]:
        """Execute repeated iterations of a workload, tracking cold vs warm starts."""
        backend = self._get_backend(backend_name)
        samples: list[BenchmarkExecutionSample] = []

        start_wall = time.perf_counter()
        for i in range(repetitions):
            # First execution is cold host-cache start, subsequent are warm cache runs
            run_type = "cold_host_cache_start" if i == 0 else "warm_cache_start"
            sample = self.run_single_workload(
                backend=backend,
                backend_name=backend_name,
                workload=workload,
                run_type=run_type,
                concurrency_level=1,
            )
            samples.append(sample)
            self.samples.append(sample)

        elapsed_wall = time.perf_counter() - start_wall

        # Compute aggregate for this (backend, workload, 1) slice
        agg = AggregatedBenchmarkResult.aggregate(
            samples=samples,
            backend=backend_name,
            workload_name=workload.name,
            concurrency_level=1,
            wall_time_seconds=elapsed_wall,
            expected_exit_code=workload.expected_exit_code,
            expected_status=workload.expected_status,
        )
        self.aggregated.append(agg)
        return samples

    def run_concurrent_workload(
        self,
        backend_name: str,
        workload: BenchmarkWorkload,
        concurrency: int,
        total_runs: int,
    ) -> list[BenchmarkExecutionSample]:
        """Execute workloads concurrently across a pool of threads within resource limits."""
        backend = self._get_backend(backend_name)
        samples: list[BenchmarkExecutionSample] = []

        active_lock = threading.Lock()
        active_count = 0
        max_active_observed = 0

        start_wall = time.perf_counter()

        def _worker(idx: int) -> BenchmarkExecutionSample:
            nonlocal active_count, max_active_observed
            enqueued_at = time.perf_counter()
            with active_lock:
                active_count += 1
                if active_count > max_active_observed:
                    max_active_observed = active_count

            try:
                sample = self.run_single_workload(
                    backend=backend,
                    backend_name=backend_name,
                    workload=workload,
                    run_type="concurrent",
                    concurrency_level=concurrency,
                )
                sample.slot_wait_ms = max(
                    0.0,
                    (time.perf_counter() - enqueued_at) * 1000.0
                    - sample.breakdown.total_duration_ms,
                )
                return sample
            finally:
                with active_lock:
                    active_count -= 1

        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(_worker, i) for i in range(total_runs)]
            for fut in concurrent.futures.as_completed(futures):
                try:
                    sample = fut.result()
                    samples.append(sample)
                    self.samples.append(sample)
                except Exception as exc:
                    logger.error("Concurrent benchmark task raised exception: %s", exc)

        elapsed_wall = time.perf_counter() - start_wall

        agg = AggregatedBenchmarkResult.aggregate(
            samples=samples,
            backend=backend_name,
            workload_name=workload.name,
            concurrency_level=concurrency,
            wall_time_seconds=elapsed_wall,
            expected_exit_code=workload.expected_exit_code,
            expected_status=workload.expected_status,
        )
        agg.max_observed_concurrency = max_active_observed
        self.aggregated.append(agg)
        return samples

    def run_all(self) -> dict[str, Any]:
        """Execute the entire benchmark plan according to BenchmarkConfig."""
        selected_workloads: list[BenchmarkWorkload] = []
        for name in self.config.workload_names:
            if name in ALL_WORKLOADS:
                selected_workloads.append(ALL_WORKLOADS[name])

        for backend_name in self.config.backends:
            logger.info("=== Starting benchmark suite for backend: %s ===", backend_name)

            # Check readiness
            try:
                backend = self._get_backend(backend_name)
                backend.check_health()
            except Exception as exc:
                logger.error("Backend %s health check failed: %s. Skipping.", backend_name, exc)
                continue

            # 1. Standard sequential repetitions (warm/cold start, latencies, memory/CPU)
            for workload in selected_workloads:
                logger.info(
                    "Running workload %s on %s (reps=%d)",
                    workload.name,
                    backend_name,
                    self.config.repetitions,
                )
                self.run_workload_repetitions(
                    backend_name=backend_name,
                    workload=workload,
                    repetitions=self.config.repetitions,
                )

            # 2. Concurrency benchmarks (levels > 1)
            for conc in self.config.concurrency_levels:
                if conc <= 1:
                    continue
                # For full benchmarks, target at least 20 runs per concurrency level
                conc_runs = self.config.repetitions if not self.config.smoke else max(conc * 2, 4)
                logger.info(
                    "Running concurrency %d on %s (total_runs=%d)",
                    conc,
                    backend_name,
                    conc_runs,
                )
                self.run_concurrent_workload(
                    backend_name=backend_name,
                    workload=ALL_WORKLOADS.get("minimal_process", selected_workloads[0]),
                    concurrency=conc,
                    total_runs=conc_runs,
                )

            # 3. Reliability workloads (non-zero exits, timeouts)
            if not self.config.smoke:
                for rel_name in self.config.reliability_workload_names:
                    if rel_name in ALL_WORKLOADS:
                        rel_workload = ALL_WORKLOADS[rel_name]
                        rel_reps = self.config.repetitions
                        logger.info(
                            "Running reliability test %s on %s (reps=%d)",
                            rel_name,
                            backend_name,
                            rel_reps,
                        )
                        self.run_workload_repetitions(
                            backend_name=backend_name,
                            workload=rel_workload,
                            repetitions=rel_reps,
                        )

        return self.to_dict()

    def to_dict(self) -> dict[str, Any]:
        """Convert complete benchmark run data into a structured serializable dictionary."""
        return {
            "run_id": self.config.run_id,
            "config": {
                "backends": list(self.config.backends),
                "workload_names": list(self.config.workload_names),
                "repetitions": self.config.repetitions,
                "concurrency_levels": list(self.config.concurrency_levels),
                "smoke": self.config.smoke,
            },
            "system_metadata": self.system_metadata,
            "total_samples_collected": len(self.samples),
            "samples": [s.to_dict() for s in self.samples],
            "aggregated": [a.to_dict() for a in self.aggregated],
        }
