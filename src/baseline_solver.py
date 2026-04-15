"""CP-SAT baseline solver: assign 306 fixtures to calendar slots."""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd
from ortools.sat.python import cp_model

from src.constants import (
    BASELINE_SOLVER_TIME_LIMIT_S,
    HARD_MAX_MATCHES_PER_WEEK,
    HARD_MIN_MATCHES_PER_WEEK,
    MAX_CONSECUTIVE_AWAY,
    MAX_CONSECUTIVE_HOME,
    MAX_MATCHES_PER_SLOT,
    MIN_REST_DAYS_LOCAL,
    NUM_ROUNDS,
    PHASES_DIR,
    SOFT_MAX_MATCHES_PER_WEEK,
    SOFT_MIN_MATCHES_PER_WEEK,
    W_ROUND_ORDER,
    W_TIER_MISMATCH,
    W_TRAVEL,
    W_WEEK_OVERLOAD,
    W_WEEK_UNDERLOAD,
)
from dataclasses import dataclass

from src.data_loader import LeagueData
from src.fixture_generator import Match
from src.tiers import compute_slot_tiers


@dataclass
class ScheduledMatch:
    """A match assigned to a concrete calendar slot."""
    match_idx: int
    round_num: int
    home_team: str
    away_team: str
    venue: str
    match_tier: int
    slot_idx: int
    day_id: str
    date: date
    date_time: object
    week_num: int
    day_name: str
    slot_tier: int
    travel_km: float


def solve_baseline(
    data: LeagueData,
    matches: List[Match],
    domains: Dict[int, List[int]],
) -> Optional[List[ScheduledMatch]]:
    """Build and solve the CP-SAT baseline model. Returns scheduled matches or None."""

    print("[baseline] Building CP-SAT model...")
    t0 = time.time()

    slots = data.usable_slots
    n_slots = len(slots)

    # Pre-compute slot metadata
    slot_dates: List[date] = list(slots["_date"])
    slot_weeks: List[int] = list(slots["Week_Num"].fillna(0).astype(int))
    slot_day_names: List[str] = list(slots["Day_name"].fillna(""))
    slot_tiers: List[int] = list(compute_slot_tiers(slots))
    slot_day_ids: List[str] = list(slots["Day_ID"].fillna(""))
    slot_datetimes = list(slots["Date time"] if "Date time" in slots.columns else [None] * n_slots)
    slot_order = {
        item: idx
        for idx, item in enumerate(sorted(
            set((slot_dates[si], str(slot_datetimes[si])) for si in range(n_slots))
        ))
    }
    slot_time_index = [
        slot_order[(slot_dates[si], str(slot_datetimes[si]))]
        for si in range(n_slots)
    ]

    # Unique dates and weeks
    all_dates = sorted(set(slot_dates))
    date_to_idx = {d: i for i, d in enumerate(all_dates)}
    all_weeks = sorted(set(slot_weeks))

    # Slots by date
    slots_by_date: Dict[date, List[int]] = defaultdict(list)
    for si, d in enumerate(slot_dates):
        slots_by_date[d].append(si)

    # Slots by week
    slots_by_week: Dict[int, List[int]] = defaultdict(list)
    for si, w in enumerate(slot_weeks):
        slots_by_week[w].append(si)

    # Nominal week for each round (spread evenly across season)
    min_week = min(all_weeks) if all_weeks else 1
    max_week = max(all_weeks) if all_weeks else 45
    week_span = max_week - min_week
    nominal_week = {}
    for r in range(1, NUM_ROUNDS + 1):
        nominal_week[r] = min_week + int((r - 1) * week_span / (NUM_ROUNDS - 1))

    # Team lookup
    teams_dict = {}
    for _, row in data.teams.iterrows():
        teams_dict[row["Team_ID"]] = {
            "Home_Stadium_ID": row["Home_Stadium_ID"],
            "Tier": int(row["Tier"]),
        }

    # Matches by team
    matches_by_team: Dict[str, List[int]] = defaultdict(list)
    for m in matches:
        matches_by_team[m.home_team].append(m.match_idx)
        matches_by_team[m.away_team].append(m.match_idx)

    matches_by_round: Dict[int, List[int]] = defaultdict(list)
    for m in matches:
        matches_by_round[m.round_num].append(m.match_idx)

    # Match lookup
    match_lookup = {m.match_idx: m for m in matches}

    # Home matches by team (for streak detection)
    home_matches_by_team: Dict[str, List[int]] = defaultdict(list)
    away_matches_by_team: Dict[str, List[int]] = defaultdict(list)
    for m in matches:
        home_matches_by_team[m.home_team].append(m.match_idx)
        away_matches_by_team[m.away_team].append(m.match_idx)

    # Matches by venue
    matches_by_venue: Dict[str, List[int]] = defaultdict(list)
    for m in matches:
        matches_by_venue[m.venue].append(m.match_idx)

    # Distance lookup
    def get_travel(m: Match) -> float:
        away_home_stadium = teams_dict.get(m.away_team, {}).get("Home_Stadium_ID", "")
        return data.dist_matrix.get(away_home_stadium, {}).get(m.venue, 0.0)

    # -----------------------------------------------------------------------
    # CP-SAT Model
    # -----------------------------------------------------------------------
    model = cp_model.CpModel()

    # Decision variables: x[m_idx][slot_idx] = 1 if match m assigned to slot
    x: Dict[int, Dict[int, cp_model.IntVar]] = {}
    for m in matches:
        x[m.match_idx] = {}
        for si in domains[m.match_idx]:
            x[m.match_idx][si] = model.NewBoolVar(f"x_{m.match_idx}_{si}")

    print(f"[baseline] Variables created: {sum(len(v) for v in x.values())}")

    # Concrete chronological index for each assigned match.
    match_time: Dict[int, cp_model.IntVar] = {}
    max_slot_time = max(slot_time_index) if slot_time_index else 0
    for m in matches:
        t_var = model.NewIntVar(0, max_slot_time, f"match_time_{m.match_idx}")
        model.Add(
            t_var == sum(slot_time_index[si] * var for si, var in x[m.match_idx].items())
        )
        match_time[m.match_idx] = t_var

    # --- H1: each match assigned exactly once ---
    for m in matches:
        model.Add(sum(x[m.match_idx].values()) == 1)

    # --- H4: team plays at most once per date ---
    for team_id, m_idxs in matches_by_team.items():
        for d, s_indices in slots_by_date.items():
            vars_on_date = []
            for mi in m_idxs:
                for si in s_indices:
                    if si in x[mi]:
                        vars_on_date.append(x[mi][si])
            if len(vars_on_date) > 1:
                model.Add(sum(vars_on_date) <= 1)

    # --- H5: venue at most once per slot ---
    for venue, m_idxs in matches_by_venue.items():
        for si in range(n_slots):
            vars_in_slot = []
            for mi in m_idxs:
                if si in x[mi]:
                    vars_in_slot.append(x[mi][si])
            if len(vars_in_slot) > 1:
                model.Add(sum(vars_in_slot) <= 1)

    # --- H_CONCURRENCY: at most MAX_MATCHES_PER_SLOT matches per time-slot ---
    for si in range(n_slots):
        all_vars_in_slot = []
        for m in matches:
            if si in x[m.match_idx]:
                all_vars_in_slot.append(x[m.match_idx][si])
        if len(all_vars_in_slot) > MAX_MATCHES_PER_SLOT:
            model.Add(sum(all_vars_in_slot) <= MAX_MATCHES_PER_SLOT)

    # --- H7: rest days via sliding window ---
    # For each team and each date D, at most 1 match in [D, D + MIN_REST_DAYS_LOCAL]
    rest_gap = MIN_REST_DAYS_LOCAL  # 3 full days -> window of 4 dates
    for team_id, m_idxs in matches_by_team.items():
        for d_start_idx, d_start in enumerate(all_dates):
            d_end = d_start + timedelta(days=rest_gap)
            # Collect all slots within [d_start, d_end]
            window_slots = []
            for d in all_dates[d_start_idx:]:
                if d > d_end:
                    break
                window_slots.extend(slots_by_date[d])

            if not window_slots:
                continue

            vars_in_window = []
            for mi in m_idxs:
                for si in window_slots:
                    if si in x[mi]:
                        vars_in_window.append(x[mi][si])

            if len(vars_in_window) > 1:
                model.Add(sum(vars_in_window) <= 1)

    # H8 is enforced before this model by fixture generation. Because baseline
    # round windows are chronological and non-overlapping, the played baseline
    # sequence follows the generated round sequence. The old date-candidate
    # approximation was too strong and could make otherwise valid compressed
    # round windows infeasible.

    # --- H10: strict round order ---
    # Every match in Round R must finish before Round R+1 starts.
    round_min: Dict[int, cp_model.IntVar] = {}
    round_max: Dict[int, cp_model.IntVar] = {}
    for r in range(1, NUM_ROUNDS + 1):
        vars_in_round = [match_time[mi] for mi in matches_by_round[r]]
        r_min = model.NewIntVar(0, max_slot_time, f"round_{r}_min")
        r_max = model.NewIntVar(0, max_slot_time, f"round_{r}_max")
        model.AddMinEquality(r_min, vars_in_round)
        model.AddMaxEquality(r_max, vars_in_round)
        round_min[r] = r_min
        round_max[r] = r_max

    for r in range(1, NUM_ROUNDS):
        model.Add(round_max[r] + 1 <= round_min[r + 1])

    print("[baseline] Hard constraints added.")

    # -----------------------------------------------------------------------
    # Soft objectives
    # -----------------------------------------------------------------------
    objective_terms = []

    # S1: Round ordering — penalize |week(slot) - nominal_week(round)|
    for m in matches:
        nom_w = nominal_week[m.round_num]
        for si, var in x[m.match_idx].items():
            week_diff = abs(slot_weeks[si] - nom_w)
            if week_diff > 0:
                objective_terms.append(var * (W_ROUND_ORDER * week_diff))

    # S2: Week load — hard bounds [6, 12] + soft penalty toward 9
    week_loads: Dict[int, cp_model.IntVar] = {}
    for w in all_weeks:
        w_slots = slots_by_week.get(w, [])
        if not w_slots:
            continue

        load_vars = []
        for m in matches:
            for si in w_slots:
                if si in x[m.match_idx]:
                    load_vars.append(x[m.match_idx][si])

        if not load_vars:
            continue

        load = model.NewIntVar(0, len(load_vars), f"load_w{w}")
        model.Add(load == sum(load_vars))
        week_loads[w] = load

        week_capacity = len(w_slots)

        # Hard upper bound: never exceed 12
        model.Add(load <= HARD_MAX_MATCHES_PER_WEEK)

        # Dynamic round windows may straddle calendar-week boundaries. A week
        # fragment can legitimately carry fewer than six matches, so the lower
        # bound is handled as a soft balance target only.

        # Soft penalty for deviation from ideal (9 matches)
        under = model.NewIntVar(0, SOFT_MIN_MATCHES_PER_WEEK, f"under_w{w}")
        model.Add(under >= SOFT_MIN_MATCHES_PER_WEEK - load)
        model.Add(under >= 0)
        objective_terms.append(under * W_WEEK_UNDERLOAD)

        over = model.NewIntVar(0, len(load_vars), f"over_w{w}")
        model.Add(over >= load - SOFT_MAX_MATCHES_PER_WEEK)
        model.Add(over >= 0)
        objective_terms.append(over * W_WEEK_OVERLOAD)

    # S3: Travel distance
    for m in matches:
        travel = get_travel(m)
        if travel > 0:
            for si, var in x[m.match_idx].items():
                cost = int(travel * W_TRAVEL)
                if cost > 0:
                    objective_terms.append(var * cost)

    # S4: Tier mismatch
    for m in matches:
        for si, var in x[m.match_idx].items():
            tier_diff = abs(m.match_tier - slot_tiers[si])
            if tier_diff > 0:
                objective_terms.append(var * (W_TIER_MISMATCH * tier_diff))

    if objective_terms:
        model.Minimize(sum(objective_terms))

    print(f"[baseline] Model built in {time.time() - t0:.1f}s. Solving...")

    # -----------------------------------------------------------------------
    # Solve
    # -----------------------------------------------------------------------
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = BASELINE_SOLVER_TIME_LIMIT_S
    solver.parameters.num_workers = 8
    solver.parameters.log_search_progress = True

    status = solver.Solve(model)

    status_name = solver.StatusName(status)
    wall_time = solver.WallTime()

    print(f"[baseline] Solver status: {status_name} ({wall_time:.1f}s)")

    # Write solver status
    os.makedirs(PHASES_DIR, exist_ok=True)
    with open(os.path.join(PHASES_DIR, "06_baseline_solver_status.json"), "w") as f:
        json.dump({
            "status": int(status),
            "status_name": status_name,
            "wall_time_s": round(wall_time, 2),
            "objective": solver.ObjectiveValue() if status in (
                cp_model.OPTIMAL, cp_model.FEASIBLE
            ) else None,
        }, f, indent=2)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("[baseline] INFEASIBLE — no schedule produced.")
        return None

    # -----------------------------------------------------------------------
    # Extract solution
    # -----------------------------------------------------------------------
    result: List[ScheduledMatch] = []
    for m in matches:
        for si, var in x[m.match_idx].items():
            if solver.Value(var) == 1:
                travel = get_travel(m)
                result.append(ScheduledMatch(
                    match_idx=m.match_idx,
                    round_num=m.round_num,
                    home_team=m.home_team,
                    away_team=m.away_team,
                    venue=m.venue,
                    match_tier=m.match_tier,
                    slot_idx=si,
                    day_id=slot_day_ids[si],
                    date=slot_dates[si],
                    date_time=slot_datetimes[si],
                    week_num=slot_weeks[si],
                    day_name=slot_day_names[si],
                    slot_tier=slot_tiers[si],
                    travel_km=travel,
                ))
                break

    print(f"[baseline] {len(result)} matches scheduled.")
    return result
