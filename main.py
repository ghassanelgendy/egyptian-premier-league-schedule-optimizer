"""EPL Schedule Optimizer — main entry point."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Optional

from src.constants import DEFAULT_SEED, PHASES_DIR
from src.data_loader import LeagueData, load_data
from src.multi_run import calculate_run_metrics, run_monte_carlo


def _annotate_baseline_status(
    domain_policy: str,
    attempt_num: int,
    attempt_count: int,
) -> None:
    """Attach the domain-policy attempt metadata to the baseline status file."""
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


def _solve_baseline_with_domain_fallbacks(
    data: LeagueData,
    matches: list[Any],
    is_batch: bool,
) -> tuple[Any, str | None]:
    """Retry the baseline with progressively looser EPL-style pre-final domains."""
    from src.baseline_solver import solve_baseline
    from src.slot_domain import build_domains

    attempts = [
        ("compact", "compact round windows"),
        ("epl_relaxed", "extended EPL spillover windows"),
        ("epl_full", "full EPL spillover tails"),
    ]

    for attempt_num, (domain_policy, label) in enumerate(attempts, start=1):
        if not is_batch:
            print(
                f"[baseline] Domain policy {attempt_num}/{len(attempts)}: {label}."
            )

        domains = build_domains(
            data,
            matches,
            non_final_policy=domain_policy,
        )
        baseline = solve_baseline(data, matches, domains)
        _annotate_baseline_status(domain_policy, attempt_num, len(attempts))
        if baseline is not None:
            return baseline, domain_policy

        if not is_batch and attempt_num < len(attempts):
            print(
                "[baseline] Infeasible under that policy. Retrying with a looser "
                "EPL-style spillover domain."
            )

    return None, None


def run_pipeline(data: LeagueData, seed: int, is_batch: bool = False) -> Any:
    """Execute the full optimization pipeline for a single seed."""
    
    # Phase 2: Generate DRR fixtures
    if not is_batch:
        print()
        print("=" * 60)
        print(f"Phase 2: Generating DRR fixtures (seed={seed})...")
        print("=" * 60)
    from src.fixture_generator import generate_drr
    matches = generate_drr(data, seed)

    # Phase 3: Build slot domains & solve baseline
    if not is_batch:
        print()
        print("=" * 60)
        print("Phase 3: Building slot domains and solving baseline...")
        print("=" * 60)
    baseline, _domain_policy = _solve_baseline_with_domain_fallbacks(
        data,
        matches,
        is_batch,
    )
    if baseline is None:
        if not is_batch:
            print("\nFATAL: Baseline solver returned INFEASIBLE after EPL fallback retries.")
        return None

    # Write pre-CAF schedule
    from src.output_writer import (
        write_pre_caf_schedule,
        write_final_schedule,
        write_postponement_queue,
        write_rescheduled_matches,
        write_unresolved,
        write_week_round_map,
    )
    from src.validation import write_validation_reports
    
    if not is_batch:
        write_pre_caf_schedule(baseline)

    # Phase 4: CAF audit
    if not is_batch:
        print()
        print("=" * 60)
        print("Phase 4: CAF audit...")
        print("=" * 60)
    from src.caf_audit import caf_audit
    accepted, violations = caf_audit(baseline, data)

    if violations:
        if not is_batch:
            print()
            print("=" * 60)
            print("Phase 5: CAF repair...")
            print("=" * 60)
        from src.caf_repair_solver import caf_repair
        repaired, unresolved_list = caf_repair(accepted, violations, data)
    else:
        if not is_batch:
            print()
            print("=" * 60)
            print("Phase 5: CAF repair skipped - no CAF violations.")
            print("=" * 60)
        from src.caf_repair_solver import write_repair_skipped_status
        repaired = []
        unresolved_list = []
        if not is_batch:
            write_repair_skipped_status("No CAF violations found by audit.")

    # Phase 6: Write outputs
    if not is_batch:
        print()
        print("=" * 60)
        print("Phase 6: Writing final outputs...")
        print("=" * 60)
        write_final_schedule(accepted, repaired, violations)
        write_postponement_queue(violations, repaired, unresolved_list)
        write_rescheduled_matches(repaired)
        write_unresolved(unresolved_list)
        write_week_round_map(accepted, repaired)
        
    issues, sequence_rows = write_validation_reports(accepted, repaired, unresolved_list, data)

    if is_batch:
        # Load baseline status to get objective
        status_path = os.path.join(PHASES_DIR, "06_baseline_solver_status.json")
        baseline_status = {}
        if os.path.exists(status_path):
            with open(status_path, "r") as f:
                baseline_status = json.load(f)
        
        all_scheduled = list(accepted) + list(repaired)
        return calculate_run_metrics(
            seed, baseline_status, violations, repaired, unresolved_list, all_scheduled, issues, sequence_rows
        )
    
    return True


def main(seed: int = DEFAULT_SEED, runs: int = 1) -> None:
    t_start = time.time()

    # Phase 1: Load data (only once)
    print("=" * 60)
    print("Phase 1: Loading data...")
    print("=" * 60)
    data = load_data()
    print(f"  Teams: {len(data.teams)}")
    print(f"  Stadiums: {len(data.stadiums)}")
    print(f"  Total slots: {len(data.slots)}")
    print(f"  FIFA dates: {len(data.fifa_dates)}")
    print(f"  Usable slots: {len(data.usable_slots)}")
    print(f"  CAF blockers: {len(data.caf_blockers)}")
    print(f"  CAF teams: {list(data.caf_dates_by_team.keys())}")

    if runs > 1:
        # For Monte Carlo, we use the provided --parallel flag if present.
        # Otherwise, default to 4 parallel workers.
        max_workers = getattr(args, "parallel", 4)
        run_monte_carlo(data, seed, runs, run_pipeline, max_workers=max_workers)
    else:
        run_pipeline(data, seed, is_batch=False)

    elapsed = time.time() - t_start
    print()
    print("=" * 60)
    print(f"Process complete in {elapsed:.1f}s")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EPL Schedule Optimizer")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED,
                        help=f"Random seed for DRR generation (default: {DEFAULT_SEED})")
    parser.add_argument("--runs", type=int, default=1,
                        help="Number of Monte Carlo runs (default: 1)")
    parser.add_argument("--parallel", type=int, default=4,
                        help="Number of parallel runs for Monte Carlo (default: 4)")
    args = parser.parse_args()
    main(seed=args.seed, runs=args.runs)
