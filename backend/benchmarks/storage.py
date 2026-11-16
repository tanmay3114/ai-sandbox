"""Result persistence and serialization utilities for the benchmark subsystem."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from benchmarks.report import (
    generate_markdown_report,
    generate_raw_measurements_csv,
    generate_summary_csv,
)
from benchmarks.runner import BenchmarkRunner


class BenchmarkResultStorage:
    """Handles structured persistence of benchmark runs as JSON, CSV, and Markdown."""

    def __init__(self, base_output_dir: Path) -> None:
        self.base_output_dir = Path(base_output_dir)

    def save_results(self, runner: BenchmarkRunner) -> Path:
        """Serialize complete runner data into a dedicated run directory."""
        run_dir = self.base_output_dir / runner.config.run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        data = runner.to_dict()

        # 1. Save results.json
        json_path = run_dir / "results.json"
        with json_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        # 2. Save summary.csv
        summary_csv = generate_summary_csv(runner.aggregated)
        (run_dir / "summary.csv").write_text(summary_csv, encoding="utf-8")

        # 3. Save raw_measurements.csv
        raw_csv = generate_raw_measurements_csv(runner.samples)
        (run_dir / "raw_measurements.csv").write_text(raw_csv, encoding="utf-8")

        # 4. Save REPORT.md
        report_md = generate_markdown_report(
            run_id=runner.config.run_id,
            system_metadata=runner.system_metadata,
            aggregated=runner.aggregated,
            samples=runner.samples,
        )
        (run_dir / "REPORT.md").write_text(report_md, encoding="utf-8")

        return run_dir

    @classmethod
    def load_json(cls, run_dir: Path) -> dict[str, Any]:
        """Load results.json from an existing benchmark directory."""
        path = Path(run_dir) / "results.json"
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
