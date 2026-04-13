"""Central path for per-phase audit artifacts (CSV/JSON) written during ``run_optimization``."""
from __future__ import annotations

from pathlib import Path

from .paths import OUTPUT


def phases_dir() -> Path:
    return OUTPUT / "phases"
