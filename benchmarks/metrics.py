"""Statistical metrics, aggregation, and percentile calculations for benchmarks."""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence
from typing import Any

from benchmarks.telemetry import ExecutionBreakdown

# Two-tailed Student's t critical values for alpha = 0.05 (95% confidence interval)
_STUDENT_T_95_TABLE: dict[int, float] = {
    1: 12.706,
    2: 4.303,
    3: 3.182,
    4: 2.776,
    5: 2.571,
    6: 2.447,
    7: 2.365,
    8: 2.306,
    9: 2.262,
    10: 2.228,
    11: 2.201,
    12: 2.179,
    13: 2.160,
    14: 2.145,
    15: 2.131,
    16: 2.120,
    17: 2.110,
    18: 2.101,
    19: 2.093,
    20: 2.086,
    21: 2.080,
    22: 2.074,
    23: 2.069,
    24: 2.064,
    25: 2.060,
    26: 2.056,
    27: 2.052,
    28: 2.048,
    29: 2.045,
    30: 2.042,
    40: 2.021,
    50: 2.009,
    60: 2.000,
    80: 1.990,
    100: 1.984,
    120: 1.980,
}


def get_student_t_critical_95(df: int) -> float:
    """Return Student's t critical value for two-tailed 95% confidence interval."""
    if df < 1:
        return 1.96
    if df in _STUDENT_T_95_TABLE:
        return _STUDENT_T_95_TABLE[df]
    # For df not explicitly in table, find nearest or use standard normal approximation
    if df > 120:
        return 1.960
    for k in sorted(_STUDENT_T_95_TABLE.keys()):
        if df <= k:
            return _STUDENT_T_95_TABLE[k]
    return 1.960


def calculate_wilson_ci_95(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Calculate 95% Wilson score confidence interval for a binomial proportion."""
    if total <= 0:
        return 0.0, 0.0
    p = successes / total
    z2 = z * z
    denom = 1.0 + (z2 / total)
    mid = (p + (z2 / (2.0 * total))) / denom
    margin = (z * math.sqrt((p * (1.0 - p) / total) + (z2 / (4.0 * total * total)))) / denom
    low = max(0.0, mid - margin)
    high = min(1.0, mid + margin)
    return round(low, 4), round(high, 4)


def calculate_percentile(values: Sequence[float], percentile: float) -> float:
    """Calculate percentile using linear interpolation between closest ranks (Hyndman-Fan Type 7).

    Formula:
        rank = (N - 1) * (p / 100)
        low = floor(rank), high = ceil(rank)
        val = values[low] * (1 - weight) + values[high] * weight
    Matches numpy default method='linear'.
    """
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    if percentile <= 0.0:
        return float(min(values))
    if percentile >= 100.0:
        return float(max(values))

    sorted_vals = sorted(values)
    n = len(sorted_vals)
    rank = (n - 1) * (percentile / 100.0)
    low_idx = int(math.floor(rank))
    high_idx = int(math.ceil(rank))
    weight = rank - low_idx

    if low_idx == high_idx:
        return float(sorted_vals[low_idx])
    return float(sorted_vals[low_idx] * (1.0 - weight) + sorted_vals[high_idx] * weight)


@dataclasses.dataclass
class MetricSummary:
    """Statistical summary for a sampled metric with 95% confidence intervals."""

    samples: int = 0
    min: float = 0.0
    max: float = 0.0
    mean: float = 0.0
    median: float = 0.0
    p95: float = 0.0
    std_dev: float = 0.0
    ci95_low: float = 0.0
    ci95_high: float = 0.0

    @classmethod
    def compute(cls, values: Sequence[float]) -> MetricSummary:
        """Compute statistical summary from a sequence of floating point samples."""
        clean = [float(v) for v in values if v is not None and not math.isnan(v)]
        if not clean:
            return cls()

        n = len(clean)
        min_val = min(clean)
        max_val = max(clean)
        mean_val = sum(clean) / n
        median_val = calculate_percentile(clean, 50.0)
        p95_val = calculate_percentile(clean, 95.0)

        if n > 1:
            # Sample standard deviation with Bessel's correction (n - 1)
            variance = sum((x - mean_val) ** 2 for x in clean) / (n - 1)
            std_dev_val = math.sqrt(variance)
            t_crit = get_student_t_critical_95(n - 1)
            margin_err = t_crit * (std_dev_val / math.sqrt(n))
            ci_low = max(0.0, mean_val - margin_err)
            ci_high = mean_val + margin_err
        else:
            std_dev_val = 0.0
            ci_low = mean_val
            ci_high = mean_val

        return cls(
            samples=n,
            min=round(min_val, 3),
            max=round(max_val, 3),
            mean=round(mean_val, 3),
            median=round(median_val, 3),
            p95=round(p95_val, 3),
            std_dev=round(std_dev_val, 3),
            ci95_low=round(ci_low, 3),
            ci95_high=round(ci_high, 3),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert summary to serializable dict."""
        return {
            "samples": self.samples,
            "min": self.min,
            "max": self.max,
            "mean": self.mean,
            "median": self.median,
            "p95": self.p95,
            "std_dev": self.std_dev,
            "ci95_low": self.ci95_low,
            "ci95_high": self.ci95_high,
        }


@dataclasses.dataclass
class BenchmarkExecutionSample:
    """Individual execution benchmark sample with outcome verification."""

    sample_id: int
    backend: str
    workload_name: str
    run_type: str  # "cold_host_cache_start", "warm_cache_start", "repeated", "concurrent"
    status: str
    exit_code: int | None
    breakdown: ExecutionBreakdown
    concurrency_level: int = 1
    slot_wait_ms: float = 0.0
    timestamp: str = ""
    error_message: str | None = None
    is_expected_outcome: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Convert sample to serializable dict."""
        return {
            "sample_id": self.sample_id,
            "backend": self.backend,
            "workload_name": self.workload_name,
            "run_type": self.run_type,
            "status": self.status,
            "exit_code": self.exit_code,
            "is_expected_outcome": self.is_expected_outcome,
            "concurrency_level": self.concurrency_level,
            "slot_wait_ms": round(self.slot_wait_ms, 3),
            "timestamp": self.timestamp,
            "error_message": self.error_message,
            "breakdown": self.breakdown.to_dict(),
        }


@dataclasses.dataclass
class AggregatedBenchmarkResult:
    """Aggregated statistical outcome for a specific (backend, workload, concurrency) tuple."""

    backend: str
    workload_name: str
    concurrency_level: int
    sample_count: int
    success_count: int
    expected_nonzero_count: int
    expected_timeout_count: int
    unexpected_failure_count: int
    cleanup_failure_count: int

    env_startup_ms: MetricSummary
    workspace_inject_ms: MetricSummary
    workload_exec_ms: MetricSummary
    workspace_retrieve_ms: MetricSummary
    cleanup_ms: MetricSummary
    unexplained_overhead_ms: MetricSummary
    total_duration_ms: MetricSummary
    successful_total_duration_ms: MetricSummary
    slot_wait_ms: MetricSummary

    peak_memory_bytes: MetricSummary
    cpu_user_seconds: MetricSummary
    cpu_system_seconds: MetricSummary

    throughput_successful_ops_sec: float = 0.0
    throughput_attempted_ops_sec: float = 0.0
    max_observed_concurrency: int = 1

    behavioral_success_rate: float = 0.0
    infrastructure_failure_rate: float = 0.0
    wilson_ci95_low: float = 0.0
    wilson_ci95_high: float = 0.0

    @classmethod
    def aggregate(
        cls,
        samples: Sequence[BenchmarkExecutionSample],
        backend: str,
        workload_name: str,
        concurrency_level: int,
        wall_time_seconds: float = 0.0,
        expected_exit_code: int | None = 0,
        expected_status: str = "completed",
    ) -> AggregatedBenchmarkResult:
        """Aggregate a slice of samples into statistical summaries."""
        matching = [
            s
            for s in samples
            if s.backend == backend
            and s.workload_name == workload_name
            and s.concurrency_level == concurrency_level
        ]

        total_samples = len(matching)
        successes = sum(
            1
            for s in matching
            if s.status == "completed" and (s.exit_code == 0 or s.exit_code == expected_exit_code)
        )
        expected_nonzeros = sum(
            1
            for s in matching
            if expected_exit_code not in (0, None) and s.exit_code == expected_exit_code
        )
        expected_timeouts = sum(
            1 for s in matching if expected_status == "timed_out" and s.status == "timed_out"
        )
        cleanup_failures = sum(1 for s in matching if not s.breakdown.cleanup_confirmed)

        # Behavioral successes: completed normally or matched expected test outcome
        valid_behaviors = sum(1 for s in matching if s.is_expected_outcome)
        unexpected_failures = total_samples - valid_behaviors

        env_startup_vals = [s.breakdown.env_startup_ms for s in matching]
        inject_vals = [s.breakdown.workspace_inject_ms for s in matching]
        workload_vals = [s.breakdown.workload_exec_ms for s in matching]
        retrieve_vals = [s.breakdown.workspace_retrieve_ms for s in matching]
        cleanup_vals = [s.breakdown.cleanup_ms for s in matching]
        overhead_vals = [s.breakdown.unexplained_overhead_ms for s in matching]
        total_vals = [s.breakdown.total_duration_ms for s in matching]
        slot_wait_vals = [s.slot_wait_ms for s in matching]

        # Latency distribution for successful/expected executions only
        successful_durations = [
            s.breakdown.total_duration_ms for s in matching if s.is_expected_outcome
        ]

        mem_vals = [
            float(s.breakdown.peak_memory_bytes)
            for s in matching
            if s.breakdown.peak_memory_bytes is not None
        ]
        cpu_user_vals = [
            s.breakdown.cpu_user_seconds
            for s in matching
            if s.breakdown.cpu_user_seconds is not None
        ]
        cpu_sys_vals = [
            s.breakdown.cpu_system_seconds
            for s in matching
            if s.breakdown.cpu_system_seconds is not None
        ]

        # Throughput: successful completed executions / wall clock time
        throughput_successful = 0.0
        throughput_attempted = 0.0
        if wall_time_seconds > 0.0 and total_samples > 0:
            throughput_successful = round(valid_behaviors / wall_time_seconds, 3)
            throughput_attempted = round(total_samples / wall_time_seconds, 3)

        behavioral_rate = (valid_behaviors / total_samples) if total_samples > 0 else 0.0
        infra_failure_rate = (unexpected_failures / total_samples) if total_samples > 0 else 0.0
        w_low, w_high = calculate_wilson_ci_95(valid_behaviors, total_samples)

        return cls(
            backend=backend,
            workload_name=workload_name,
            concurrency_level=concurrency_level,
            sample_count=total_samples,
            success_count=successes,
            expected_nonzero_count=expected_nonzeros,
            expected_timeout_count=expected_timeouts,
            unexpected_failure_count=unexpected_failures,
            cleanup_failure_count=cleanup_failures,
            env_startup_ms=MetricSummary.compute(env_startup_vals),
            workspace_inject_ms=MetricSummary.compute(inject_vals),
            workload_exec_ms=MetricSummary.compute(workload_vals),
            workspace_retrieve_ms=MetricSummary.compute(retrieve_vals),
            cleanup_ms=MetricSummary.compute(cleanup_vals),
            unexplained_overhead_ms=MetricSummary.compute(overhead_vals),
            total_duration_ms=MetricSummary.compute(total_vals),
            successful_total_duration_ms=MetricSummary.compute(successful_durations),
            slot_wait_ms=MetricSummary.compute(slot_wait_vals),
            peak_memory_bytes=MetricSummary.compute(mem_vals),
            cpu_user_seconds=MetricSummary.compute(cpu_user_vals),
            cpu_system_seconds=MetricSummary.compute(cpu_sys_vals),
            throughput_successful_ops_sec=throughput_successful,
            throughput_attempted_ops_sec=throughput_attempted,
            max_observed_concurrency=concurrency_level,
            behavioral_success_rate=round(behavioral_rate, 4),
            infrastructure_failure_rate=round(infra_failure_rate, 4),
            wilson_ci95_low=w_low,
            wilson_ci95_high=w_high,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert aggregated result to serializable dict."""
        return {
            "backend": self.backend,
            "workload_name": self.workload_name,
            "concurrency_level": self.concurrency_level,
            "sample_count": self.sample_count,
            "success_count": self.success_count,
            "expected_nonzero_count": self.expected_nonzero_count,
            "expected_timeout_count": self.expected_timeout_count,
            "unexpected_failure_count": self.unexpected_failure_count,
            "cleanup_failure_count": self.cleanup_failure_count,
            "throughput_successful_ops_sec": self.throughput_successful_ops_sec,
            "throughput_attempted_ops_sec": self.throughput_attempted_ops_sec,
            "max_observed_concurrency": self.max_observed_concurrency,
            "behavioral_success_rate": self.behavioral_success_rate,
            "infrastructure_failure_rate": self.infrastructure_failure_rate,
            "wilson_ci95_low": self.wilson_ci95_low,
            "wilson_ci95_high": self.wilson_ci95_high,
            "env_startup_ms": self.env_startup_ms.to_dict(),
            "workspace_inject_ms": self.workspace_inject_ms.to_dict(),
            "workload_exec_ms": self.workload_exec_ms.to_dict(),
            "workspace_retrieve_ms": self.workspace_retrieve_ms.to_dict(),
            "cleanup_ms": self.cleanup_ms.to_dict(),
            "unexplained_overhead_ms": self.unexplained_overhead_ms.to_dict(),
            "total_duration_ms": self.total_duration_ms.to_dict(),
            "successful_total_duration_ms": self.successful_total_duration_ms.to_dict(),
            "slot_wait_ms": self.slot_wait_ms.to_dict(),
            "peak_memory_bytes": self.peak_memory_bytes.to_dict(),
            "cpu_user_seconds": self.cpu_user_seconds.to_dict(),
            "cpu_system_seconds": self.cpu_system_seconds.to_dict(),
        }
