"""Configuration parameters and settings for benchmark executions."""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent / "results"


@dataclasses.dataclass
class BenchmarkConfig:
    """Settings controlling the benchmark runner, iterations, backends, and storage."""

    backends: tuple[str, ...] = ("docker", "qemu")
    workload_names: tuple[str, ...] = (
        "minimal_process",
        "python_startup",
        "cpu_intensive",
        "memory_intensive",
        "file_io",
        "multiple_small_files",
    )
    reliability_workload_names: tuple[str, ...] = (
        "reliability_nonzero",
        "reliability_timeout",
    )
    repetitions: int = 20
    concurrency_levels: tuple[int, ...] = (1, 2, 4)
    smoke: bool = False
    output_dir: Path = DEFAULT_RESULTS_DIR
    run_id: str = ""
    collect_resource_metrics: bool = True

    def __post_init__(self) -> None:
        if not self.run_id:
            ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            mode = "smoke" if self.smoke else "full"
            self.run_id = f"bench_{mode}_{ts}"

        if self.smoke:
            # Smoke benchmark configuration for fast verification
            self.repetitions = min(self.repetitions, 3)
            self.concurrency_levels = tuple(c for c in self.concurrency_levels if c <= 2)
            # Use minimal + cpu + file_io for smoke
            self.workload_names = ("minimal_process", "cpu_intensive", "file_io")

    @classmethod
    def create_smoke(
        cls,
        backends: Sequence[str] = ("docker", "qemu"),
        output_dir: Path | None = None,
    ) -> BenchmarkConfig:
        """Create a lightweight configuration suitable for quick smoke verification."""
        return cls(
            backends=tuple(backends),
            repetitions=3,
            concurrency_levels=(1, 2),
            smoke=True,
            output_dir=output_dir or DEFAULT_RESULTS_DIR,
        )

    @classmethod
    def create_full(
        cls,
        backends: Sequence[str] = ("docker", "qemu"),
        repetitions: int = 20,
        output_dir: Path | None = None,
    ) -> BenchmarkConfig:
        """Create a full benchmark configuration with 20 repetitions and concurrency 1, 2, 4."""
        return cls(
            backends=tuple(backends),
            repetitions=repetitions,
            concurrency_levels=(1, 2, 4),
            smoke=False,
            output_dir=output_dir or DEFAULT_RESULTS_DIR,
        )

    @classmethod
    def create_audited(
        cls,
        backends: Sequence[str] = ("docker", "qemu"),
        repetitions: int = 20,
        output_dir: Path | None = None,
    ) -> BenchmarkConfig:
        """Create an audited configuration with N >= 20 repetitions across all test slices."""
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        return cls(
            backends=tuple(backends),
            repetitions=repetitions,
            concurrency_levels=(1, 2, 4),
            smoke=False,
            output_dir=output_dir or DEFAULT_RESULTS_DIR,
            run_id=f"bench_audited_{ts}",
        )
