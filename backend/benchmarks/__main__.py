"""Command-line entrypoint for the AI Sandbox benchmark harness."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from app.core.config import settings
from benchmarks.config import BenchmarkConfig
from benchmarks.runner import BenchmarkRunner
from benchmarks.storage import BenchmarkResultStorage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("benchmarks")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="AI Sandbox: Docker vs QEMU MicroVM Benchmarking System",
    )
    parser.add_argument(
        "--backend",
        choices=["docker", "qemu", "all"],
        default="all",
        help="Backend(s) to benchmark (default: all)",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run fast smoke benchmark with minimal repetitions",
    )
    parser.add_argument(
        "--audit",
        action="store_true",
        help="Run statistically reconciled audit benchmark (N >= 20 across all configurations)",
    )
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="Audit existing historical benchmark datasets and generate discrepancy report",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=None,
        help="Number of repetitions per workload (default: 20 full, 3 smoke)",
    )
    parser.add_argument(
        "--concurrency",
        type=str,
        default="1,2,4",
        help="Comma-separated concurrency levels to test (default: 1,2,4)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmarks/results"),
        help="Directory where benchmark results are saved",
    )

    args = parser.parse_args()

    backends = ("docker", "qemu") if args.backend == "all" else (args.backend,)
    concurrency_levels = tuple(int(c.strip()) for c in args.concurrency.split(",") if c.strip())

    if args.reconcile:
        from benchmarks.reconcile import (
            audit_historical_benchmark,
            generate_reconciliation_markdown,
        )

        hist_dirs = [
            d for d in args.output_dir.iterdir() if d.is_dir() and d.name.startswith("bench_full")
        ]
        if not hist_dirs:
            logger.error("No historical bench_full directory found in %s", args.output_dir)
            return 1
        target_dir = sorted(hist_dirs)[-1]
        logger.info("Auditing historical dataset in: %s", target_dir)
        audit_res = audit_historical_benchmark(target_dir)
        recon_md = generate_reconciliation_markdown(audit_res)
        out_file = args.output_dir / "HISTORICAL_AUDIT_RECONCILIATION.md"
        out_file.write_text(recon_md, encoding="utf-8")
        logger.info("Historical audit reconciliation saved to: %s", out_file)
        print(f"\n===> Historical audit complete: {out_file}\n")
        if not args.audit:
            return 0

    if args.smoke:
        reps = args.repetitions or 3
        config = BenchmarkConfig.create_smoke(backends=backends, output_dir=args.output_dir)
        config.repetitions = reps
        config.concurrency_levels = tuple(c for c in concurrency_levels if c <= 2)
    elif args.audit:
        reps = args.repetitions or 20
        config = BenchmarkConfig.create_audited(
            backends=backends,
            repetitions=reps,
            output_dir=args.output_dir,
        )
        config.concurrency_levels = concurrency_levels
    else:
        reps = args.repetitions or 20
        config = BenchmarkConfig.create_full(
            backends=backends,
            repetitions=reps,
            output_dir=args.output_dir,
        )
        config.concurrency_levels = concurrency_levels

    logger.info("Initializing benchmark run: %s", config.run_id)
    logger.info(
        "Backends: %s | Repetitions: %d | Concurrency: %s",
        backends,
        config.repetitions,
        config.concurrency_levels,
    )

    runner = BenchmarkRunner(config=config, app_settings=settings)
    runner.run_all()

    storage = BenchmarkResultStorage(base_output_dir=config.output_dir)
    saved_dir = storage.save_results(runner)

    logger.info("Benchmark complete! Results written to: %s", saved_dir)
    print(f"\n===> Benchmark completed successfully. Output saved to: {saved_dir}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
