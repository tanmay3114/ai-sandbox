"""Integration tests executing real Docker and QEMU smoke benchmarks."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import settings
from app.sandbox.qemu.runtime import detect_qemu_capabilities
from benchmarks.config import BenchmarkConfig
from benchmarks.runner import BenchmarkRunner
from benchmarks.storage import BenchmarkResultStorage


def test_real_docker_benchmark_smoke(tmp_path: Path):
    """Verify real Docker smoke benchmark execution, metrics capture, and persistence."""
    cfg = BenchmarkConfig.create_smoke(backends=("docker",), output_dir=tmp_path)
    cfg.repetitions = 2
    cfg.concurrency_levels = (1, 2)
    cfg.workload_names = ("minimal_process", "cpu_intensive")

    runner = BenchmarkRunner(config=cfg, app_settings=settings)
    data = runner.run_all()

    assert data["total_samples_collected"] >= 4
    # All samples must be completed
    for sample in runner.samples:
        assert sample.status == "completed"
        assert sample.breakdown.cleanup_confirmed is True
        assert sample.breakdown.env_startup_ms > 0.0

    storage = BenchmarkResultStorage(base_output_dir=tmp_path)
    run_dir = storage.save_results(runner)

    assert (run_dir / "results.json").exists()
    assert (run_dir / "summary.csv").exists()
    assert (run_dir / "raw_measurements.csv").exists()
    assert (run_dir / "REPORT.md").exists()


def test_real_qemu_benchmark_smoke(tmp_path: Path):
    """Verify real QEMU smoke benchmark execution under HVF on Apple Silicon."""
    caps = detect_qemu_capabilities(settings)
    if not caps.is_ready:
        pytest.skip(f"QEMU not available: {caps.format_diagnostic()}")

    cfg = BenchmarkConfig.create_smoke(backends=("qemu",), output_dir=tmp_path)
    cfg.repetitions = 2
    cfg.concurrency_levels = (1, 2)
    cfg.workload_names = ("minimal_process", "cpu_intensive")

    runner = BenchmarkRunner(config=cfg, app_settings=settings)
    data = runner.run_all()

    assert data["total_samples_collected"] >= 4
    for sample in runner.samples:
        assert sample.status == "completed"
        assert sample.breakdown.cleanup_confirmed is True
        assert sample.breakdown.env_startup_ms > 0.0

    storage = BenchmarkResultStorage(base_output_dir=tmp_path)
    run_dir = storage.save_results(runner)

    assert (run_dir / "results.json").exists()
    assert (run_dir / "REPORT.md").exists()
