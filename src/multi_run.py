"""Batch execution and Monte Carlo analysis for the EPL optimizer."""

from __future__ import annotations

import csv
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pandas as pd

from src.data_loader import LeagueData


@dataclass
class RunMetrics:
    seed: int
    baseline_objective: Optional[float]
    caf_violations: int
    repaired_count: int
    unresolved_count: int
    total_travel_km: float
    max_rest_gap: int
    top_3_venue_share: float
    validation_errors: int
    validation_warnings: int
    wall_time_s: float


def run_monte_carlo(
    data: LeagueData,
    initial_seed: int,
    num_runs: int,
    pipeline_fn: Any,
) -> None:
    """Run the pipeline multiple times with different seeds and aggregate results."""
    
    results_dir = os.path.join("output", "multi_run")
    os.makedirs(results_dir, exist_ok=True)
    
    metrics_list: List[RunMetrics] = []
    best_metrics: Optional[RunMetrics] = None
    best_seed: int = initial_seed

    print(f"\nStarting Monte Carlo simulation: {num_runs} runs starting with seed {initial_seed}")
    
    for i in range(num_runs):
        current_seed = initial_seed + i
        print(f"\n>>> RUN {i+1}/{num_runs} (Seed: {current_seed})")
        
        t0 = time.time()
        
        try:
            metrics = pipeline_fn(data, current_seed, is_batch=True)
            if metrics is None:
                print(f"  !!! Run {current_seed} returned INFEASIBLE.")
                continue
                
            wall_time = time.time() - t0
            metrics.wall_time_s = wall_time
            
            metrics_list.append(metrics)
            
            if best_metrics is None or _is_better(metrics, best_metrics):
                best_metrics = metrics
                best_seed = current_seed
                print(f"  *** New Best Seed Found: {best_seed} (Objective: {metrics.baseline_objective}) ***")

        except Exception as e:
            print(f"  !!! Run {current_seed} failed with error: {e}")
            import traceback
            traceback.print_exc()
            continue

    # Write summary CSV
    summary_path = os.path.join(results_dir, "monte_carlo_results.csv")
    if metrics_list:
        keys = metrics_list[0].__dict__.keys()
        with open(summary_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(keys))
            writer.writeheader()
            for m in metrics_list:
                writer.writerow(m.__dict__)
        
        print("\n" + "=" * 60)
        print("MONTE CARLO SUMMARY")
        print("=" * 60)
        print(f"  Total Successful Runs: {len(metrics_list)}/{num_runs}")
        print(f"  Best Seed: {best_seed}")
        if best_metrics:
            print(f"  Best Objective: {best_metrics.baseline_objective}")
            print(f"  Best Travel: {best_metrics.total_travel_km:,.0f} km")
            print(f"  Best Max Rest Gap: {best_metrics.max_rest_gap} days")
        print(f"  Results saved to: {summary_path}")
        print("=" * 60)
        
        # Re-run best seed once to restore final artifacts to root output/
        print(f"\nRestoring final artifacts for best seed {best_seed}...")
        pipeline_fn(data, best_seed, is_batch=False)
    else:
        print("\nNo successful runs to aggregate.")


def _is_better(cur: RunMetrics, best: RunMetrics) -> bool:
    """Heuristic to decide if current run is better than best so far."""
    # Priority 1: Errors (hard constraints)
    if cur.validation_errors < best.validation_errors:
        return True
    if cur.validation_errors > best.validation_errors:
        return False
        
    # Priority 2: Unresolved CAF matches
    if cur.unresolved_count < best.unresolved_count:
        return True
    if cur.unresolved_count > best.unresolved_count:
        return False
        
    # Priority 3: Baseline Objective value
    if cur.baseline_objective is not None and best.baseline_objective is not None:
        if cur.baseline_objective < best.baseline_objective:
            return True
        if cur.baseline_objective > best.baseline_objective:
            return False
            
    # Priority 4: Travel distance
    if cur.total_travel_km < best.total_travel_km:
        return True

    return False


def calculate_run_metrics(
    seed: int,
    baseline_status: Optional[Dict[str, Any]],
    violations: List[Any],
    repaired: List[Any],
    unresolved: List[Any],
    all_scheduled: List[Any],
    issues: List[Dict[str, Any]],
    sequence_rows: List[Dict[str, Any]],
) -> RunMetrics:
    """Extract summary statistics from a single run's artifacts."""
    
    # Objective
    objective = baseline_status.get("objective") if baseline_status else None
    
    # CAF counts
    v_count = len(set(v.match.match_idx for v in violations))
    r_count = len(repaired)
    u_count = len(unresolved)
    
    # Travel
    total_travel = sum(getattr(m, "travel_km", 0.0) for m in all_scheduled)
    
    # Rest Gaps
    max_gap = 0
    if sequence_rows:
        gaps = [r["Gap_Days_From_Previous"] for r in sequence_rows if isinstance(r["Gap_Days_From_Previous"], int)]
        if gaps:
            max_gap = max(gaps)
    
    # Venue share
    venue_counts: Dict[str, int] = {}
    for m in all_scheduled:
        v = getattr(m, "venue", "unknown")
        venue_counts[v] = venue_counts.get(v, 0) + 1
    
    top_3_sum = sum(sorted(venue_counts.values(), reverse=True)[:3])
    share = top_3_sum / len(all_scheduled) if all_scheduled else 0.0
    
    # Validation findings
    errors = sum(1 for issue in issues if issue.get("Severity") == "ERROR")
    warnings = sum(1 for issue in issues if issue.get("Severity") == "WARN")

    return RunMetrics(
        seed=seed,
        baseline_objective=objective,
        caf_violations=v_count,
        repaired_count=r_count,
        unresolved_count=u_count,
        total_travel_km=total_travel,
        max_rest_gap=max_gap,
        top_3_venue_share=share,
        validation_errors=errors,
        validation_warnings=warnings,
        wall_time_s=0.0,
    )
