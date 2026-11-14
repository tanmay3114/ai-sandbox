# AI Sandbox: Docker vs QEMU Benchmarking Subsystem

This subsystem provides reproducible, empirical performance and resource comparison between the **Docker Execution Backend** and the **QEMU ARM64 Execution Backend** on macOS (Apple Silicon with HVF) and Linux.

---

## 1. Overview

Both backends share the identical logical sandbox contract:
- Untrusted Python code is executed inside a fresh, ephemeral environment.
- Unprivileged user `10001:10001`.
- Air-gapped network isolation (`network_mode="none"` / `-nic none`).
- Read-only root filesystems and size-bounded workspace tmpfs.
- Workspace state is persisted across executions via secure tar archive serialization and atomic directory commits.

---

## 2. Metrics Measured

1. **Cold-Start & Warm-Cache Start Latency:**
   - Measures time from execution request to environment readiness.
   - `cold_host_cache_start`: Very first execution after startup.
   - `warm_cache_start`: Subsequent fresh containers/VMs benefiting from warm host-side caches.
2. **Phase Timing Decomposition:**
   - Environment startup / readiness (`env_startup_ms`).
   - Workspace injection (`workspace_inject_ms`).
   - Workload execution (`workload_exec_ms`).
   - Workspace retrieval (`workspace_retrieve_ms`).
   - Container/VM cleanup (`cleanup_ms`).
   - End-to-end total duration (`total_duration_ms`).
3. **Execution Latency Across Workload Types:**
   - Minimal process execution (`pass`).
   - Python startup and arithmetic computation.
   - CPU-intensive SHA-256 cryptographic hashing.
   - Memory allocation up to 64 MB.
   - File I/O (1 MB write, read back, and checksum verification).
   - Multiple small files creation (20 files in directory hierarchy).
4. **Memory & CPU Consumption:**
   - Docker: Container cgroup memory stats (`max_usage_in_bytes`) and CPU usage.
   - QEMU: Host macOS Process Resident Set Size (`RSS`) and CPU times.
5. **Concurrent Execution & Throughput:**
   - Measured at concurrency levels 1, 2, and 4.
   - Reports operations per second (throughput), average latency, p50, and p95.
6. **Reliability & Edge Cases:**
   - Non-zero exit code preservation.
   - Execution timeout enforcement and automatic rollback of partial writes.
   - Cleanup verification ensuring zero lingering processes, containers, or overlays.

---

## 3. How to Run Benchmarks

### A. Quick Smoke Benchmark (Fast Validation)

Runs 3 repetitions of minimal, CPU, and I/O workloads with concurrency 1 and 2:

```bash
./venv/bin/python -m benchmarks --smoke
```

Or using the convenience runner:

```bash
./scripts/run_benchmarks.py --smoke
```

### B. Full Side-by-Side Benchmark

Runs all 6 standard workloads and reliability tests with 20 repetitions and concurrency 1, 2, and 4:

```bash
./venv/bin/python -m benchmarks
```

### C. Specific Backend Only

Benchmark Docker only:
```bash
./venv/bin/python -m benchmarks --backend docker --repetitions 10
```

Benchmark QEMU only:
```bash
./venv/bin/python -m benchmarks --backend qemu --repetitions 10
```

---

## 4. Output Artifacts

Benchmark runs generate structured outputs in `benchmarks/results/<run_id>/`:

- `results.json`: Full machine-readable dataset including host metadata, all raw sample breakdowns, and statistical summaries.
- `summary.csv`: Tabular CSV of mean, median (p50), p95, min, max, throughput, and memory by backend, workload, and concurrency.
- `raw_measurements.csv`: Detailed individual sample timings for full transparency and statistical auditing.
- `REPORT.md`: Publication-grade Markdown report comparing both backends with analysis tables and engineering conclusions.
