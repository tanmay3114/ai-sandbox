"""Workload definitions for reproducible Docker vs QEMU benchmarking."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping


@dataclasses.dataclass(frozen=True)
class BenchmarkWorkload:
    """Specification of a deterministic benchmark workload."""

    name: str
    description: str
    code: str
    timeout_seconds: float = 5.0
    has_persistent_workspace: bool = False
    expected_exit_code: int | None = 0
    expected_status: str = "completed"
    setup_files: Mapping[str, str | bytes] = dataclasses.field(default_factory=dict)


# Workload 1: Minimal process execution (measures minimum VM/container overhead)
MINIMAL_PROCESS = BenchmarkWorkload(
    name="minimal_process",
    description="Minimal process execution testing base overhead (pass)",
    code="pass\n",
)

# Workload 2: Python startup and basic computation
PYTHON_STARTUP = BenchmarkWorkload(
    name="python_startup",
    description="Python startup, module import and basic arithmetic",
    code=("import math\nres = sum(math.isqrt(i) for i in range(10_000))\nprint(f'RES={res}')\n"),
)

# Workload 3: CPU-intensive SHA-256 hashing
CPU_INTENSIVE = BenchmarkWorkload(
    name="cpu_intensive",
    description="CPU-intensive iterative SHA-256 cryptographic hashing",
    code=(
        "import hashlib\n"
        "h = b'ai-sandbox-bench-seed'\n"
        "for _ in range(30_000):\n"
        "    h = hashlib.sha256(h).digest()\n"
        "print(f'HASH={h.hex()[:16]}')\n"
    ),
)

# Workload 4: Memory-intensive allocation (within 256MB policy limit)
MEMORY_INTENSIVE = BenchmarkWorkload(
    name="memory_intensive",
    description="Bounded memory allocation (64 MB allocated and verified)",
    code=(
        "import resource\n"
        "blocks = [bytearray(1024 * 1024) for _ in range(64)]\n"
        "total = sum(len(b) for b in blocks)\n"
        "rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss\n"
        "print(f'ALLOC_BYTES={total} PEAK_RSS_KB={rss_kb}')\n"
    ),
)

# Workload 5: Workspace file I/O (write 1 MB, read back, verify checksum)
FILE_IO = BenchmarkWorkload(
    name="file_io",
    description="Workspace single large file write (1 MB), read-back, and checksum validation",
    has_persistent_workspace=True,
    code=(
        "import hashlib, pathlib\n"
        "p = pathlib.Path('bench_data.bin')\n"
        "chunk = b'0123456789abcdef' * 4096  # 64 KB\n"
        "with p.open('wb') as f:\n"
        "    for _ in range(16):\n"
        "        f.write(chunk)\n"
        "data = p.read_bytes()\n"
        "assert len(data) == 1048576, f'Bad size: {len(data)}'\n"
        "digest = hashlib.sha256(data).hexdigest()[:16]\n"
        "print(f'IO_DIGEST={digest}')\n"
    ),
)

# Workload 6: Multiple small files in subdirectories
MULTIPLE_SMALL_FILES = BenchmarkWorkload(
    name="multiple_small_files",
    description="Workspace metadata and multiple small files creation (20 files in subdirs)",
    has_persistent_workspace=True,
    code=(
        "import pathlib\n"
        "base = pathlib.Path('bench_tree')\n"
        "base.mkdir(parents=True, exist_ok=True)\n"
        "for i in range(20):\n"
        "    sub = base / f'sub_{i % 4}'\n"
        "    sub.mkdir(exist_ok=True)\n"
        "    (sub / f'leaf_{i}.txt').write_text(f'content_{i}\\n')\n"
        "leaves = list(base.rglob('leaf_*.txt'))\n"
        "assert len(leaves) == 20, f'Expected 20, got {len(leaves)}'\n"
        "print(f'LEAVES={len(leaves)}')\n"
    ),
)

# Reliability: Non-zero exit code (must be preserved and workspace changes kept)
RELIABILITY_NONZERO = BenchmarkWorkload(
    name="reliability_nonzero",
    description="Non-zero exit code reporting and state preservation",
    has_persistent_workspace=True,
    expected_exit_code=19,
    expected_status="failed",
    code=(
        "import pathlib, sys\n"
        "pathlib.Path('nonzero_marker.txt').write_text('persisted')\n"
        "sys.exit(19)\n"
    ),
)

# Reliability: Execution timeout (hard termination and uncommitted change rollback)
RELIABILITY_TIMEOUT = BenchmarkWorkload(
    name="reliability_timeout",
    description="Runaway execution timeout and partial write rollback",
    timeout_seconds=0.8,
    expected_exit_code=None,
    expected_status="timed_out",
    code=(
        "import pathlib, time\n"
        "pathlib.Path('uncommitted_leak.txt').write_text('should_discard')\n"
        "while True:\n"
        "    time.sleep(0.1)\n"
    ),
)


STANDARD_WORKLOADS: tuple[BenchmarkWorkload, ...] = (
    MINIMAL_PROCESS,
    PYTHON_STARTUP,
    CPU_INTENSIVE,
    MEMORY_INTENSIVE,
    FILE_IO,
    MULTIPLE_SMALL_FILES,
)

RELIABILITY_WORKLOADS: tuple[BenchmarkWorkload, ...] = (
    RELIABILITY_NONZERO,
    RELIABILITY_TIMEOUT,
)

ALL_WORKLOADS: dict[str, BenchmarkWorkload] = {
    w.name: w for w in (*STANDARD_WORKLOADS, *RELIABILITY_WORKLOADS)
}


def get_workload(name: str) -> BenchmarkWorkload:
    """Retrieve workload definition by name."""
    if name not in ALL_WORKLOADS:
        raise KeyError(
            f"Unknown workload: {name}. Available workloads: {list(ALL_WORKLOADS.keys())}"
        )
    return ALL_WORKLOADS[name]
