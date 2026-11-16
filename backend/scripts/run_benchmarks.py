#!/usr/bin/env python3
"""Convenience runner script for AI Sandbox Docker vs QEMU benchmarks."""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = REPO_ROOT / "venv" / "bin" / "python"

if VENV_PYTHON.is_file() and Path(sys.executable) != VENV_PYTHON:
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), "-m", "benchmarks", *sys.argv[1:]])

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
