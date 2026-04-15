"""EPL Schedule Optimizer — main entry point."""

from __future__ import annotations

import argparse
import sys
import time

from src.constants import DEFAULT_SEED


def main(seed: int = DEFAULT_SEED) -> None:
    t_start = time.time()

    # Phase 1: Load data
    print("=" * 60)
    print("Phase 1: Loading data...")
    print("=" * 60)
    from src.data_loader import load_data
    data = load_data()
    print(f"  Teams: {len(data.teams)}")
    print(f"  Stadiums: {len(data.stadiums)}")
    print(f"  Total slots: {len(data.slots)}")
    print(f"  FIFA dates: {len(data.fifa_dates)}")
    print(f"  Usable slots: {len(data.usable_slots)}")
    print(f"  CAF blockers: {len(data.caf_blockers)}")
    print(f"  CAF teams: {list(data.caf_dates_by_team.keys())}")

    # Phase 2: Generate DRR fixtures
    print()
    print("=" * 60)
    print(f"Phase 2: Generating DRR fixtures (seed={seed})...")
    print("=" * 60)
    from src.fixture_generator import generate_drr
    matches = generate_drr(data, seed)
    print(f"  Generated {len(matches)} fixtures across "
          f"{max(m.round_num for m in matches)} rounds.")

    # Phase 3: Build slot domains & solve baseline
    print()
    print("=" * 60)
    print("Phase 3: Building slot domains and solving baseline...")
    print("=" * 60)
    from src.slot_domain import build_domains
    domains = build_domains(data, matches)
    sample = list(domains.values())[0]
    print(f"  Domain size per match: {len(sample)} slots")

    from src.baseline_solver import solve_baseline
    baseline = solve_baseline(data, matches, domains)
    if baseline is None:
        print("\nFATAL: Baseline solver returned INFEASIBLE. Stopping.")
        sys.exit(1)

    # Write pre-CAF schedule
    from src.output_writer import (
        write_pre_caf_schedule,
        write_final_schedule,
        write_rescheduled_matches,
        write_unresolved,
        write_week_round_map,
    )
    write_pre_caf_schedule(baseline)

    # Phase 4: CAF audit
    print()
    print("=" * 60)
    print("Phase 4: CAF audit...")
    print("=" * 60)
    from src.caf_audit import caf_audit
    accepted, violations = caf_audit(baseline, data)

    # Phase 5: CAF repair
    print()
    print("=" * 60)
    print("Phase 5: CAF repair...")
    print("=" * 60)
    from src.caf_repair_solver import caf_repair
    repaired, unresolved_list = caf_repair(accepted, violations, data)

    # Phase 6: Write outputs
    print()
    print("=" * 60)
    print("Phase 6: Writing final outputs...")
    print("=" * 60)
    write_final_schedule(accepted, repaired, violations)
    write_rescheduled_matches(repaired)
    write_unresolved(unresolved_list)
    write_week_round_map(accepted, repaired)

    elapsed = time.time() - t_start
    print()
    print("=" * 60)
    print(f"Pipeline complete in {elapsed:.1f}s")
    print(f"  Baseline: {len(baseline)} matches")
    print(f"  CAF violations: {len(set(v.match.match_idx for v in violations))}")
    print(f"  Repaired: {len(repaired)}")
    print(f"  Unresolved: {len(unresolved_list)}")
    print(f"  Final schedule: {len(accepted) + len(repaired)} matches")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EPL Schedule Optimizer")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED,
                        help=f"Random seed for DRR generation (default: {DEFAULT_SEED})")
    args = parser.parse_args()
    main(seed=args.seed)
