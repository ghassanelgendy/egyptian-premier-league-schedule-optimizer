"""Discover and load tabular files under the project data tree."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def list_tabular_files(
    roots: list[Path] | None = None,
    *,
    extensions: tuple[str, ...] = (".xlsx", ".csv"),
) -> list[Path]:
    """Sorted unique paths relative to repo root when possible."""
    if roots is None:
        roots = [repo_root() / "data"]
    seen: set[Path] = set()
    out: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for ext in extensions:
            for p in sorted(root.rglob(f"*{ext}")):
                if p in seen:
                    continue
                seen.add(p)
                out.append(p)
    out.sort(key=lambda p: str(p).lower())
    return out


def load_excel_sheet(path: Path, sheet: str | int, nrows: int | None = 500) -> pd.DataFrame:
    return pd.read_excel(path, sheet_name=sheet, nrows=nrows)


def load_csv(path: Path, nrows: int | None = 500) -> pd.DataFrame:
    return pd.read_csv(path, nrows=nrows)


def excel_sheet_names(path: Path) -> list[str]:
    xl = pd.ExcelFile(path)
    return list(xl.sheet_names)


def describe_path(path: Path) -> dict[str, Any]:
    root = repo_root()
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path
    return {
        "path": path,
        "relative": str(rel),
        "suffix": path.suffix.lower(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
    }
