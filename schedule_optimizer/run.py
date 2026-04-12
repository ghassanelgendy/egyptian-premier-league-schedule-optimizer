"""CLI entry when executed as script (use python -m schedule_optimizer)."""
from __future__ import annotations

import os
import sys

from .pipeline import run_optimization


def main() -> int:
    caf = int(os.environ.get("EPL_CAF_BUFFER_DAYS", "1"))
    res = run_optimization(caf_buffer_days=caf, write_outputs=True)
    print(res.message)
    return res.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
