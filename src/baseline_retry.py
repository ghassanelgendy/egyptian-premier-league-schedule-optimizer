"""Shared baseline retry helpers for CLI and Streamlit runs."""

from __future__ import annotations

import json
import os
from typing import Any, MutableMapping, Sequence

from src.constants import PHASES_DIR
from src.data_loader import LeagueData


DOMAIN_POLICY_ATTEMPTS = [
    ("compact", "compact round windows"),
    ("epl_relaxed", "extended EPL spillover windows"),
    ("epl_full", "full EPL spillover tails"),
]


def _annotate_baseline_status(
    domain_policy: str,
    attempt_num: int,
    attempt_count: int,
) -> None:
    """Attach domain-policy metadata to the baseline status file."""
    status_path = os.path.join(PHASES_DIR, "06_baseline_solver_status.json")
    if not os.path.exists(status_path):
        return

    with open(status_path, "r", encoding="utf-8") as f:
        status = json.load(f)

    status["domain_policy"] = domain_policy
    status["domain_attempt"] = attempt_num
    status["domain_attempt_count"] = attempt_count
    status["domain_fallback_used"] = attempt_num > 1

    with open(status_path, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2)


def solve_baseline_with_domain_fallbacks(
    data: LeagueData,
    matches: Sequence[Any],
    *,
    is_batch: bool,
    initial_domains: dict[int, list[int]] | None = None,
    initial_policy: str = "compact",
    progress: MutableMapping[str, Any] | None = None,
) -> tuple[Any, str | None]:
    """Retry the baseline with progressively looser EPL-style domains."""
    from src.baseline_solver import solve_baseline
    from src.slot_domain import build_domains

    attempt_count = len(DOMAIN_POLICY_ATTEMPTS)

    for attempt_num, (domain_policy, label) in enumerate(
        DOMAIN_POLICY_ATTEMPTS,
        start=1,
    ):
        if progress is not None:
            progress.update(
                {
                    "attempt_num": attempt_num,
                    "attempt_count": attempt_count,
                    "domain_policy": domain_policy,
                    "label": label,
                    "step": "build_domains",
                }
            )

        if not is_batch:
            print(f"[baseline] Domain policy {attempt_num}/{attempt_count}: {label}.")

        if initial_domains is not None and domain_policy == initial_policy:
            domains = initial_domains
        else:
            domains = build_domains(
                data,
                matches,
                non_final_policy=domain_policy,
            )

        if progress is not None:
            progress.update(
                {
                    "attempt_num": attempt_num,
                    "attempt_count": attempt_count,
                    "domain_policy": domain_policy,
                    "label": label,
                    "step": "solve_baseline",
                }
            )

        baseline = solve_baseline(data, matches, domains)
        _annotate_baseline_status(domain_policy, attempt_num, attempt_count)
        if baseline is not None:
            if progress is not None:
                progress.update(
                    {
                        "attempt_num": attempt_num,
                        "attempt_count": attempt_count,
                        "domain_policy": domain_policy,
                        "label": label,
                        "step": "done",
                        "solved": True,
                    }
                )
            return baseline, domain_policy

        if progress is not None:
            progress.update(
                {
                    "attempt_num": attempt_num,
                    "attempt_count": attempt_count,
                    "domain_policy": domain_policy,
                    "label": label,
                    "step": "retry",
                    "solved": False,
                }
            )

        if not is_batch and attempt_num < attempt_count:
            print(
                "[baseline] Infeasible under that policy. Retrying with a looser "
                "EPL-style spillover domain."
            )

    if progress is not None:
        progress.update(
            {
                "attempt_num": attempt_count,
                "attempt_count": attempt_count,
                "domain_policy": None,
                "label": None,
                "step": "done",
                "solved": False,
            }
        )
    return None, None
