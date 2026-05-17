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
    """Run the pipeline multiple times with checkpointing and interrupt protection."""
    
    results_dir = os.path.join("output", "multi_run")
    os.makedirs(results_dir, exist_ok=True)
    summary_path = os.path.join(results_dir, "monte_carlo_results.csv")
    
    metrics_list: List[RunMetrics] = []
    finished_seeds: set[int] = set()

    # Load existing progress if available
    if os.path.exists(summary_path):
        try:
            existing_df = pd.read_csv(summary_path)
            for _, row in existing_df.iterrows():
                # Reconstruct RunMetrics from row
                m = RunMetrics(**{k: row[k] for k in RunMetrics.__annotations__.keys()})
                metrics_list.append(m)
                finished_seeds.add(int(m.seed))
            print(f"Resuming Monte Carlo: Found {len(metrics_list)} existing runs in {summary_path}")
        except Exception as e:
            print(f"Could not load existing results ({e}), starting fresh.")

    best_metrics: Optional[RunMetrics] = None
    if metrics_list:
        for m in metrics_list:
            if best_metrics is None or _is_better(m, best_metrics):
                best_metrics = m

    print(f"\nStarting Monte Carlo simulation: {num_runs} runs starting with base seed {initial_seed}")
    
    try:
        for i in range(num_runs):
            current_seed = initial_seed + i
            if current_seed in finished_seeds:
                continue

            print(f"\n>>> RUN {len(metrics_list)+1}/{num_runs} (Seed: {current_seed})")
            
            t0 = time.time()
            try:
                metrics = pipeline_fn(data, current_seed, is_batch=True)
                if metrics is None:
                    print(f"  !!! Run {current_seed} returned INFEASIBLE.")
                    continue
                    
                wall_time = time.time() - t0
                metrics.wall_time_s = wall_time
                metrics_list.append(metrics)
                finished_seeds.add(current_seed)
                
                # Update best
                if best_metrics is None or _is_better(metrics, best_metrics):
                    best_metrics = metrics
                    print(f"  *** New Best Seed Found: {current_seed} (Objective: {metrics.baseline_objective}) ***")

                # Incremental Save (Checkpoint)
                _save_summary(summary_path, metrics_list)

            except Exception as e:
                print(f"  !!! Run {current_seed} failed with error: {e}")
                import traceback
                traceback.print_exc()
                continue

    except KeyboardInterrupt:
        print("\n\n!!! INTERRUPT DETECTED !!!")
        print(f"Gracefully stopping. Processed {len(metrics_list)} runs so far.")
        # Summary already saved incrementally

    # Final Summary Printout
    if metrics_list:
        print("\n" + "=" * 60)
        print("MONTE CARLO SUMMARY")
        print("=" * 60)
        print(f"  Total Successful Runs: {len(metrics_list)}")
        if best_metrics:
            print(f"  Best Seed Found: {best_metrics.seed}")
            print(f"  Best Objective: {best_metrics.baseline_objective}")
            print(f"  Best Travel: {best_metrics.total_travel_km:,.0f} km")
        print(f"  Full results at: {summary_path}")
        print("=" * 60)
        
        if best_metrics:
            print(f"\nRestoring final artifacts for the best-performing seed ({best_metrics.seed})...")
            pipeline_fn(data, best_metrics.seed, is_batch=False)
    else:
        print("\nNo successful runs to aggregate.")


def _save_summary(path: str, metrics_list: List[RunMetrics]) -> None:
    """Save the aggregated results to CSV with atomic write and immediate flush."""
    if not metrics_list:
        return
        
    temp_path = path + ".tmp"
    keys = metrics_list[0].__dict__.keys()
    
    try:
        # Use a temporary file and atomic rename to prevent corruption during hard crash
        with open(temp_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(keys))
            writer.writeheader()
            for m in metrics_list:
                writer.writerow(m.__dict__)
            f.flush()
            os.fsync(f.fileno()) # Force write to physical disk
            
        if os.path.exists(path):
            os.remove(path)
        os.rename(temp_path, path)
    except Exception as e:
        print(f"Warning: Failed to save checkpoint ({e})")


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
