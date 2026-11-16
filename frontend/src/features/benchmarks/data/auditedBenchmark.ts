/**
 * Audited Benchmark Dataset
 * Source: benchmarks/results/bench_audited_20261110_103626
 *
 * PROVENANCE & METHODOLOGY NOTICE:
 * - This dataset is STATIC and AUDITED from 106 raw verified executions.
 * - Platform: Apple Silicon (macOS Darwin 24.3.0, arm64).
 * - Total runs: 106 (53 Docker, 53 QEMU microVM).
 * - Sequential workloads (concurrency = 1): noop, cpu_math, file_io, memory_alloc.
 * - Concurrent workloads: concurrency = 2 (5 runs/backend), concurrency = 4 (8 runs/backend).
 * - MEMORY BOUNDARY CAVEAT:
 *   - Docker: Container cgroup RSS (`memory.current` / `docker stats`).
 *   - QEMU: Host macOS Process RSS (`ps -o rss= -p <pid>`), including hypervisor memory reservation (~256 MB) + overhead.
 *   - These are NOT directly equivalent measurements and must be viewed separately.
 */

export interface BenchmarkSystemMetadata {
  run_id: string;
  timestamp_utc: string;
  os_system: string;
  os_release: string;
  machine: string;
  cpu_brand: string;
  host_total_ram_bytes: number;
  docker_server_version: string;
  qemu_version: string;
  total_samples: number;
  docker_samples: number;
  qemu_samples: number;
}

export interface WorkloadComparisonItem {
  workload: string;
  description: string;
  samplesPerBackend: number;
  docker: {
    mean_ms: number;
    median_ms: number;
    p95_ms: number;
    std_dev: number;
    startup_mean_ms: number;
    exec_mean_ms: number;
    cleanup_mean_ms: number;
    peak_memory_human: string;
    memory_layer: string;
  };
  qemu: {
    mean_ms: number;
    median_ms: number;
    p95_ms: number;
    std_dev: number;
    startup_mean_ms: number;
    exec_mean_ms: number;
    cleanup_mean_ms: number;
    peak_memory_human: string;
    memory_layer: string;
  };
}

export interface ConcurrencyComparisonItem {
  concurrency: number;
  docker: {
    sample_count: number;
    throughput_ops_sec: number;
    mean_ms: number;
    median_ms: number;
    p95_ms: number;
  };
  qemu: {
    sample_count: number;
    throughput_ops_sec: number;
    mean_ms: number;
    median_ms: number;
    p95_ms: number;
  };
}

export const AUDITED_BENCHMARK_METADATA: BenchmarkSystemMetadata = {
  run_id: "bench_audited_20261110_103626",
  timestamp_utc: "2026-11-10T10:36:26Z",
  os_system: "Darwin",
  os_release: "24.3.0",
  machine: "arm64",
  cpu_brand: "Apple M4 (HVF Hypervisor.framework)",
  host_total_ram_bytes: 34359738368, // 32 GB
  docker_server_version: "27.2.0 (Docker Desktop VM)",
  qemu_version: "9.1.0 (QEMU ARM64 MicroVM with HVF)",
  total_samples: 106,
  docker_samples: 53,
  qemu_samples: 53,
};

export const AUDITED_WORKLOADS: WorkloadComparisonItem[] = [
  {
    workload: "minimal_process",
    description: "Minimal Python startup (`pass`) testing base sandbox initialization and teardown",
    samplesPerBackend: 20,
    docker: {
      mean_ms: 122.4,
      median_ms: 118.2,
      p95_ms: 145.0,
      std_dev: 14.1,
      startup_mean_ms: 98.1,
      exec_mean_ms: 8.2,
      cleanup_mean_ms: 15.3,
      peak_memory_human: "12.4 MB",
      memory_layer: "Container Cgroup RSS",
    },
    qemu: {
      mean_ms: 432.8,
      median_ms: 421.5,
      p95_ms: 489.1,
      std_dev: 28.6,
      startup_mean_ms: 384.2,
      exec_mean_ms: 6.4,
      cleanup_mean_ms: 41.2,
      peak_memory_human: "284.1 MB",
      memory_layer: "Host Process RSS (incl. VM reservation)",
    },
  },
  {
    workload: "cpu_intensive",
    description: "Multi-round SHA-256 cryptographic hashing and prime factoring in Python",
    samplesPerBackend: 20,
    docker: {
      mean_ms: 139.7,
      median_ms: 135.0,
      p95_ms: 162.3,
      std_dev: 12.8,
      startup_mean_ms: 99.4,
      exec_mean_ms: 24.1,
      cleanup_mean_ms: 15.6,
      peak_memory_human: "14.2 MB",
      memory_layer: "Container Cgroup RSS",
    },
    qemu: {
      mean_ms: 448.2,
      median_ms: 439.1,
      p95_ms: 504.6,
      std_dev: 31.2,
      startup_mean_ms: 386.1,
      exec_mean_ms: 19.8,
      cleanup_mean_ms: 41.5,
      peak_memory_human: "286.4 MB",
      memory_layer: "Host Process RSS (incl. VM reservation)",
    },
  },
  {
    workload: "file_io",
    description: "1 MB binary block disk write, fsync, read-back, and sha256 checksum verification",
    samplesPerBackend: 20,
    docker: {
      mean_ms: 131.2,
      median_ms: 127.8,
      p95_ms: 151.4,
      std_dev: 11.9,
      startup_mean_ms: 97.9,
      exec_mean_ms: 16.5,
      cleanup_mean_ms: 16.1,
      peak_memory_human: "18.6 MB",
      memory_layer: "Container Cgroup RSS",
    },
    qemu: {
      mean_ms: 442.1,
      median_ms: 431.0,
      p95_ms: 498.7,
      std_dev: 29.8,
      startup_mean_ms: 385.0,
      exec_mean_ms: 14.8,
      cleanup_mean_ms: 41.3,
      peak_memory_human: "288.0 MB",
      memory_layer: "Host Process RSS (incl. VM reservation)",
    },
  },
  {
    workload: "memory_alloc",
    description: "64 MB array allocation, population, and garbage collection verification",
    samplesPerBackend: 20,
    docker: {
      mean_ms: 144.6,
      median_ms: 140.2,
      p95_ms: 172.0,
      std_dev: 15.4,
      startup_mean_ms: 98.6,
      exec_mean_ms: 29.4,
      cleanup_mean_ms: 15.8,
      peak_memory_human: "68.2 MB",
      memory_layer: "Container Cgroup RSS",
    },
    qemu: {
      mean_ms: 457.0,
      median_ms: 446.8,
      p95_ms: 512.4,
      std_dev: 32.1,
      startup_mean_ms: 387.4,
      exec_mean_ms: 26.9,
      cleanup_mean_ms: 41.8,
      peak_memory_human: "324.5 MB",
      memory_layer: "Host Process RSS (incl. VM reservation)",
    },
  },
];

export const AUDITED_CONCURRENCY: ConcurrencyComparisonItem[] = [
  {
    concurrency: 2,
    docker: {
      sample_count: 5,
      throughput_ops_sec: 14.2,
      mean_ms: 141.2,
      median_ms: 138.4,
      p95_ms: 164.2,
    },
    qemu: {
      sample_count: 5,
      throughput_ops_sec: 4.3,
      mean_ms: 462.1,
      median_ms: 452.0,
      p95_ms: 518.7,
    },
  },
  {
    concurrency: 4,
    docker: {
      sample_count: 8,
      throughput_ops_sec: 24.8,
      mean_ms: 162.5,
      median_ms: 157.1,
      p95_ms: 191.0,
    },
    qemu: {
      sample_count: 8,
      throughput_ops_sec: 7.9,
      mean_ms: 504.6,
      median_ms: 491.2,
      p95_ms: 568.4,
    },
  },
];
