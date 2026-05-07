"""CP-SAT baseline solver: assign fixtures to calendar slots and venues."""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from ortools.sat.python import cp_model

from src.constants import (
    BASELINE_SOLVER_TIME_LIMIT_S,
    HARD_MAX_MATCHES_PER_WEEK,
    MAX_MATCHES_PER_DAY,
    MAX_MATCHES_PER_SLOT,
    MIN_REST_DAYS_LOCAL,
    MIN_STADIUM_SERVICE_GAP_DAYS,
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
from src.data_loader import LeagueData
from src.fixture_generator import Match
from src.tiers import compute_slot_tiers
from src.venue_rules import build_team_lookup, get_venue_options


ALT_STADIUM_RELIEF_PENALTY = 1_000_000


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
    is_forced_venue: bool = False


def solve_baseline(
    data: LeagueData,
    matches: List[Match],
    domains: Dict[int, List[int]],
) -> Optional[List[ScheduledMatch]]:
    """Build and solve the baseline model.

    Legacy behavior is preserved exactly when MIN_STADIUM_SERVICE_GAP_DAYS == 0:
    the solver uses the precomputed fixed venue on each Match. When the gap is
    positive, venue choice is lifted into the CP model for non-forced matches so
    the alternate stadium can relieve the primary home stadium.
    """

    if MIN_STADIUM_SERVICE_GAP_DAYS <= 0:
        return _solve_baseline_legacy(data, matches, domains)
    return _solve_baseline_with_stadium_gap(data, matches, domains)


def _build_slot_context(data: LeagueData) -> dict:
    slots = data.usable_slots
    n_slots = len(slots)

    slot_dates: List[date] = list(slots["_date"])
    slot_weeks: List[int] = list(slots["Week_Num"].fillna(0).astype(int))
    slot_day_names: List[str] = list(slots["Day_name"].fillna(""))
    slot_tiers: List[int] = list(compute_slot_tiers(slots))
    slot_day_ids: List[str] = list(slots["Day_ID"].fillna(""))
    slot_datetimes = list(
        slots["Date time"] if "Date time" in slots.columns else [None] * n_slots
    )
    slot_order = {
        item: idx
        for idx, item in enumerate(
            sorted(set((slot_dates[si], str(slot_datetimes[si])) for si in range(n_slots)))
        )
    }
    slot_time_index = [
        slot_order[(slot_dates[si], str(slot_datetimes[si]))]
        for si in range(n_slots)
    ]

    all_dates = sorted(set(slot_dates))
    all_weeks = sorted(set(slot_weeks))

    slots_by_date: Dict[date, List[int]] = defaultdict(list)
    for si, slot_date in enumerate(slot_dates):
        slots_by_date[slot_date].append(si)

    slots_by_week: Dict[int, List[int]] = defaultdict(list)
    for si, week_num in enumerate(slot_weeks):
        slots_by_week[week_num].append(si)

    min_week = min(all_weeks) if all_weeks else 1
    max_week = max(all_weeks) if all_weeks else 45
    week_span = max_week - min_week
    nominal_week = {}
    for round_num in range(1, NUM_ROUNDS + 1):
        nominal_week[round_num] = min_week + int(
            (round_num - 1) * week_span / (NUM_ROUNDS - 1)
        )

    return {
        "slots": slots,
        "n_slots": n_slots,
        "slot_dates": slot_dates,
        "slot_weeks": slot_weeks,
        "slot_day_names": slot_day_names,
        "slot_tiers": slot_tiers,
        "slot_day_ids": slot_day_ids,
        "slot_datetimes": slot_datetimes,
        "slot_time_index": slot_time_index,
        "all_dates": all_dates,
        "all_weeks": all_weeks,
        "slots_by_date": slots_by_date,
        "slots_by_week": slots_by_week,
        "nominal_week": nominal_week,
        "max_slot_time": max(slot_time_index) if slot_time_index else 0,
    }


def _build_match_context(
    data: LeagueData,
    matches: List[Match],
) -> tuple[Dict[str, dict], set[str], Dict[str, List[int]], Dict[int, List[int]]]:
    teams_dict = build_team_lookup(data)
    tier1_teams = {
        team_id
        for team_id, meta in teams_dict.items()
        if int(meta.get("Tier", 0)) == 1
    }

    matches_by_team: Dict[str, List[int]] = defaultdict(list)
    matches_by_round: Dict[int, List[int]] = defaultdict(list)
    for match in matches:
        matches_by_team[match.home_team].append(match.match_idx)
        matches_by_team[match.away_team].append(match.match_idx)
        matches_by_round[match.round_num].append(match.match_idx)

    return teams_dict, tier1_teams, matches_by_team, matches_by_round


def _solve_baseline_legacy(
    data: LeagueData,
    matches: List[Match],
    domains: Dict[int, List[int]],
) -> Optional[List[ScheduledMatch]]:
    print("[baseline] Building CP-SAT model...")
    t0 = time.time()

    slot_ctx = _build_slot_context(data)
    slot_dates = slot_ctx["slot_dates"]
    slot_weeks = slot_ctx["slot_weeks"]
    slot_day_names = slot_ctx["slot_day_names"]
    slot_tiers = slot_ctx["slot_tiers"]
    slot_day_ids = slot_ctx["slot_day_ids"]
    slot_datetimes = slot_ctx["slot_datetimes"]
    slot_time_index = slot_ctx["slot_time_index"]
    all_dates = slot_ctx["all_dates"]
    all_weeks = slot_ctx["all_weeks"]
    slots_by_date = slot_ctx["slots_by_date"]
    slots_by_week = slot_ctx["slots_by_week"]
    nominal_week = slot_ctx["nominal_week"]
    max_slot_time = slot_ctx["max_slot_time"]
    n_slots = slot_ctx["n_slots"]

    teams_dict, tier1_teams, matches_by_team, matches_by_round = _build_match_context(
        data, matches
    )

    venue_options_by_match = {
        match.match_idx: get_venue_options(
            match.home_team, match.away_team, teams_dict, data.sec_rules
        )
        for match in matches
    }

    matches_by_venue: Dict[str, List[int]] = defaultdict(list)
    for match in matches:
        matches_by_venue[match.venue].append(match.match_idx)

    def get_travel(match: Match) -> float:
        away_home_stadium = teams_dict.get(match.away_team, {}).get(
            "Home_Stadium_ID", ""
        )
        return data.dist_matrix.get(away_home_stadium, {}).get(match.venue, 0.0)

    model = cp_model.CpModel()

    x: Dict[int, Dict[int, cp_model.IntVar]] = {}
    for match in matches:
        x[match.match_idx] = {}
        for slot_idx in domains[match.match_idx]:
            x[match.match_idx][slot_idx] = model.NewBoolVar(
                f"x_{match.match_idx}_{slot_idx}"
            )

    print(f"[baseline] Variables created: {sum(len(v) for v in x.values())}")

    match_time: Dict[int, cp_model.IntVar] = {}
    for match in matches:
        t_var = model.NewIntVar(0, max_slot_time, f"match_time_{match.match_idx}")
        model.Add(
            t_var
            == sum(
                slot_time_index[slot_idx] * var
                for slot_idx, var in x[match.match_idx].items()
            )
        )
        match_time[match.match_idx] = t_var

    for match in matches:
        model.Add(sum(x[match.match_idx].values()) == 1)

    for match in matches:
        if match.home_team in tier1_teams and match.away_team in tier1_teams:
            tier1_slot_vars = [
                var
                for slot_idx, var in x[match.match_idx].items()
                if slot_tiers[slot_idx] == 1
            ]
            if not tier1_slot_vars:
                raise RuntimeError(
                    "No tier-1 slots available in domain for tier-1 derby: "
                    f"{match.home_team} vs {match.away_team} "
                    f"(match_idx={match.match_idx})."
                )
            model.Add(sum(tier1_slot_vars) == 1)

    for team_id, match_indices in matches_by_team.items():
        for slot_date, slot_indices in slots_by_date.items():
            vars_on_date = []
            for match_idx in match_indices:
                for slot_idx in slot_indices:
                    if slot_idx in x[match_idx]:
                        vars_on_date.append(x[match_idx][slot_idx])
            if len(vars_on_date) > 1:
                model.Add(sum(vars_on_date) <= 1)

    for venue, match_indices in matches_by_venue.items():
        for slot_idx in range(n_slots):
            vars_in_slot = []
            for match_idx in match_indices:
                if slot_idx in x[match_idx]:
                    vars_in_slot.append(x[match_idx][slot_idx])
            if len(vars_in_slot) > 1:
                model.Add(sum(vars_in_slot) <= 1)

    for slot_date, slot_indices in slots_by_date.items():
        all_vars_on_date = []
        for match in matches:
            for slot_idx in slot_indices:
                if slot_idx in x[match.match_idx]:
                    all_vars_on_date.append(x[match.match_idx][slot_idx])
        if len(all_vars_on_date) > MAX_MATCHES_PER_DAY:
            model.Add(sum(all_vars_on_date) <= MAX_MATCHES_PER_DAY)

    for slot_idx in range(n_slots):
        all_vars_in_slot = []
        for match in matches:
            if slot_idx in x[match.match_idx]:
                all_vars_in_slot.append(x[match.match_idx][slot_idx])
        if len(all_vars_in_slot) > MAX_MATCHES_PER_SLOT:
            model.Add(sum(all_vars_in_slot) <= MAX_MATCHES_PER_SLOT)

    rest_gap = MIN_REST_DAYS_LOCAL
    for team_id, match_indices in matches_by_team.items():
        for start_idx, start_date in enumerate(all_dates):
            end_date = start_date + timedelta(days=rest_gap)
            window_slots = []
            for slot_date in all_dates[start_idx:]:
                if slot_date > end_date:
                    break
                window_slots.extend(slots_by_date[slot_date])

            if not window_slots:
                continue

            vars_in_window = []
            for match_idx in match_indices:
                for slot_idx in window_slots:
                    if slot_idx in x[match_idx]:
                        vars_in_window.append(x[match_idx][slot_idx])

            if len(vars_in_window) > 1:
                model.Add(sum(vars_in_window) <= 1)

    round_min: Dict[int, cp_model.IntVar] = {}
    round_max: Dict[int, cp_model.IntVar] = {}
    for round_num in range(1, NUM_ROUNDS + 1):
        vars_in_round = [match_time[match_idx] for match_idx in matches_by_round[round_num]]
        round_min_var = model.NewIntVar(0, max_slot_time, f"round_{round_num}_min")
        round_max_var = model.NewIntVar(0, max_slot_time, f"round_{round_num}_max")
        model.AddMinEquality(round_min_var, vars_in_round)
        model.AddMaxEquality(round_max_var, vars_in_round)
        round_min[round_num] = round_min_var
        round_max[round_num] = round_max_var

    for round_num in range(1, NUM_ROUNDS):
        model.Add(round_max[round_num] + 1 <= round_min[round_num + 1])

    print("[baseline] Hard constraints added.")

    objective_terms = []

    for match in matches:
        nominal = nominal_week[match.round_num]
        for slot_idx, var in x[match.match_idx].items():
            week_diff = abs(slot_weeks[slot_idx] - nominal)
            if week_diff > 0:
                objective_terms.append(var * (W_ROUND_ORDER * week_diff))

    for week_num in all_weeks:
        week_slots = slots_by_week.get(week_num, [])
        if not week_slots:
            continue

        load_vars = []
        for match in matches:
            for slot_idx in week_slots:
                if slot_idx in x[match.match_idx]:
                    load_vars.append(x[match.match_idx][slot_idx])

        if not load_vars:
            continue

        load = model.NewIntVar(0, len(load_vars), f"load_w{week_num}")
        model.Add(load == sum(load_vars))
        model.Add(load <= HARD_MAX_MATCHES_PER_WEEK)

        under = model.NewIntVar(0, SOFT_MIN_MATCHES_PER_WEEK, f"under_w{week_num}")
        model.Add(under >= SOFT_MIN_MATCHES_PER_WEEK - load)
        model.Add(under >= 0)
        objective_terms.append(under * W_WEEK_UNDERLOAD)

        over = model.NewIntVar(0, len(load_vars), f"over_w{week_num}")
        model.Add(over >= load - SOFT_MAX_MATCHES_PER_WEEK)
        model.Add(over >= 0)
        objective_terms.append(over * W_WEEK_OVERLOAD)

    for match in matches:
        travel = get_travel(match)
        if travel > 0:
            for _, var in x[match.match_idx].items():
                cost = int(travel * W_TRAVEL)
                if cost > 0:
                    objective_terms.append(var * cost)

    for match in matches:
        for slot_idx, var in x[match.match_idx].items():
            tier_diff = abs(match.match_tier - slot_tiers[slot_idx])
            if tier_diff > 0:
                objective_terms.append(var * (W_TIER_MISMATCH * tier_diff))

    if objective_terms:
        model.Minimize(sum(objective_terms))

    print(f"[baseline] Model built in {time.time() - t0:.1f}s. Solving...")

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = BASELINE_SOLVER_TIME_LIMIT_S
    solver.parameters.num_workers = 8
    solver.parameters.log_search_progress = True

    status = solver.Solve(model)
    status_name = solver.StatusName(status)
    wall_time = solver.WallTime()

    print(f"[baseline] Solver status: {status_name} ({wall_time:.1f}s)")

    os.makedirs(PHASES_DIR, exist_ok=True)
    with open(os.path.join(PHASES_DIR, "06_baseline_solver_status.json"), "w") as f:
        json.dump(
            {
                "status": int(status),
                "status_name": status_name,
                "wall_time_s": round(wall_time, 2),
                "objective": (
                    solver.ObjectiveValue()
                    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
                    else None
                ),
                "stadium_service_gap_days": MIN_STADIUM_SERVICE_GAP_DAYS,
            },
            f,
            indent=2,
        )

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("[baseline] INFEASIBLE - no schedule produced.")
        return None

    result: List[ScheduledMatch] = []
    for match in matches:
        options = venue_options_by_match[match.match_idx]
        for slot_idx, var in x[match.match_idx].items():
            if solver.Value(var) == 1:
                result.append(
                    ScheduledMatch(
                        match_idx=match.match_idx,
                        round_num=match.round_num,
                        home_team=match.home_team,
                        away_team=match.away_team,
                        venue=match.venue,
                        match_tier=match.match_tier,
                        slot_idx=slot_idx,
                        day_id=slot_day_ids[slot_idx],
                        date=slot_dates[slot_idx],
                        date_time=slot_datetimes[slot_idx],
                        week_num=slot_weeks[slot_idx],
                        day_name=slot_day_names[slot_idx],
                        slot_tier=slot_tiers[slot_idx],
                        travel_km=get_travel(match),
                        is_forced_venue=options.is_forced_only,
                    )
                )
                break

    print(f"[baseline] {len(result)} matches scheduled.")
    return result


def _solve_baseline_with_stadium_gap(
    data: LeagueData,
    matches: List[Match],
    domains: Dict[int, List[int]],
) -> Optional[List[ScheduledMatch]]:
    print(
        "[baseline] Building CP-SAT model with stadium service gap "
        f"({MIN_STADIUM_SERVICE_GAP_DAYS} days)..."
    )
    t0 = time.time()

    slot_ctx = _build_slot_context(data)
    slot_dates = slot_ctx["slot_dates"]
    slot_weeks = slot_ctx["slot_weeks"]
    slot_day_names = slot_ctx["slot_day_names"]
    slot_tiers = slot_ctx["slot_tiers"]
    slot_day_ids = slot_ctx["slot_day_ids"]
    slot_datetimes = slot_ctx["slot_datetimes"]
    slot_time_index = slot_ctx["slot_time_index"]
    all_dates = slot_ctx["all_dates"]
    all_weeks = slot_ctx["all_weeks"]
    slots_by_date = slot_ctx["slots_by_date"]
    slots_by_week = slot_ctx["slots_by_week"]
    nominal_week = slot_ctx["nominal_week"]
    max_slot_time = slot_ctx["max_slot_time"]
    n_slots = slot_ctx["n_slots"]

    teams_dict, tier1_teams, matches_by_team, matches_by_round = _build_match_context(
        data, matches
    )

    venue_options_by_match = {
        match.match_idx: get_venue_options(
            match.home_team, match.away_team, teams_dict, data.sec_rules
        )
        for match in matches
    }

    def get_travel(away_team: str, venue: str) -> float:
        away_home_stadium = teams_dict.get(away_team, {}).get("Home_Stadium_ID", "")
        return data.dist_matrix.get(away_home_stadium, {}).get(venue, 0.0)

    model = cp_model.CpModel()

    x: Dict[int, Dict[Tuple[int, str], cp_model.IntVar]] = {}
    assignment_meta: Dict[Tuple[int, int, str], dict] = {}
    venue_slot_vars: Dict[Tuple[str, int], List[cp_model.IntVar]] = defaultdict(list)
    venue_date_non_forced_vars: Dict[Tuple[str, date], List[cp_model.IntVar]] = defaultdict(list)

    for match in matches:
        options = venue_options_by_match[match.match_idx]
        x[match.match_idx] = {}
        for slot_idx in domains[match.match_idx]:
            for venue in options.allowed_venues:
                key = (slot_idx, venue)
                var = model.NewBoolVar(f"x_{match.match_idx}_{slot_idx}_{venue}")
                x[match.match_idx][key] = var

                is_forced = options.is_forced_only
                is_alt = (not is_forced) and venue != options.primary_venue
                travel = get_travel(match.away_team, venue)

                assignment_meta[(match.match_idx, slot_idx, venue)] = {
                    "is_forced": is_forced,
                    "is_alt": is_alt,
                    "travel_km": travel,
                }
                venue_slot_vars[(venue, slot_idx)].append(var)
                if not is_forced:
                    venue_date_non_forced_vars[(venue, slot_dates[slot_idx])].append(var)

    print(f"[baseline] Variables created: {sum(len(v) for v in x.values())}")

    match_time: Dict[int, cp_model.IntVar] = {}
    for match in matches:
        t_var = model.NewIntVar(0, max_slot_time, f"match_time_{match.match_idx}")
        model.Add(
            t_var
            == sum(
                slot_time_index[slot_idx] * var
                for (slot_idx, _venue), var in x[match.match_idx].items()
            )
        )
        match_time[match.match_idx] = t_var

    for match in matches:
        model.Add(sum(x[match.match_idx].values()) == 1)

    for match in matches:
        if match.home_team in tier1_teams and match.away_team in tier1_teams:
            tier1_slot_vars = [
                var
                for (slot_idx, _venue), var in x[match.match_idx].items()
                if slot_tiers[slot_idx] == 1
            ]
            if not tier1_slot_vars:
                raise RuntimeError(
                    "No tier-1 slots available in domain for tier-1 derby: "
                    f"{match.home_team} vs {match.away_team} "
                    f"(match_idx={match.match_idx})."
                )
            model.Add(sum(tier1_slot_vars) == 1)

    for team_id, match_indices in matches_by_team.items():
        for slot_date, slot_indices in slots_by_date.items():
            vars_on_date = []
            for match_idx in match_indices:
                for slot_idx in slot_indices:
                    for venue in venue_options_by_match[match_idx].allowed_venues:
                        var = x[match_idx].get((slot_idx, venue))
                        if var is not None:
                            vars_on_date.append(var)
            if len(vars_on_date) > 1:
                model.Add(sum(vars_on_date) <= 1)

    for (_venue, _slot_idx), vars_in_slot in venue_slot_vars.items():
        if len(vars_in_slot) > 1:
            model.Add(sum(vars_in_slot) <= 1)

    for slot_date, slot_indices in slots_by_date.items():
        all_vars_on_date = []
        for match in matches:
            for slot_idx in slot_indices:
                for venue in venue_options_by_match[match.match_idx].allowed_venues:
                    var = x[match.match_idx].get((slot_idx, venue))
                    if var is not None:
                        all_vars_on_date.append(var)
        if len(all_vars_on_date) > MAX_MATCHES_PER_DAY:
            model.Add(sum(all_vars_on_date) <= MAX_MATCHES_PER_DAY)

    for slot_idx in range(n_slots):
        all_vars_in_slot = []
        for match in matches:
            for venue in venue_options_by_match[match.match_idx].allowed_venues:
                var = x[match.match_idx].get((slot_idx, venue))
                if var is not None:
                    all_vars_in_slot.append(var)
        if len(all_vars_in_slot) > MAX_MATCHES_PER_SLOT:
            model.Add(sum(all_vars_in_slot) <= MAX_MATCHES_PER_SLOT)

    rest_gap = MIN_REST_DAYS_LOCAL
    for team_id, match_indices in matches_by_team.items():
        for start_idx, start_date in enumerate(all_dates):
            end_date = start_date + timedelta(days=rest_gap)
            window_slots = []
            for slot_date in all_dates[start_idx:]:
                if slot_date > end_date:
                    break
                window_slots.extend(slots_by_date[slot_date])

            if not window_slots:
                continue

            vars_in_window = []
            for match_idx in match_indices:
                for slot_idx in window_slots:
                    for venue in venue_options_by_match[match_idx].allowed_venues:
                        var = x[match_idx].get((slot_idx, venue))
                        if var is not None:
                            vars_in_window.append(var)

            if len(vars_in_window) > 1:
                model.Add(sum(vars_in_window) <= 1)

    service_gap = MIN_STADIUM_SERVICE_GAP_DAYS
    venue_dates: Dict[str, List[date]] = defaultdict(list)
    for venue, venue_date in venue_date_non_forced_vars.keys():
        venue_dates[venue].append(venue_date)

    for venue, dates in venue_dates.items():
        ordered_dates = sorted(set(dates))
        for start_idx, start_date in enumerate(ordered_dates):
            end_date = start_date + timedelta(days=service_gap)
            vars_in_window = []
            for venue_date in ordered_dates[start_idx:]:
                if venue_date > end_date:
                    break
                vars_in_window.extend(venue_date_non_forced_vars[(venue, venue_date)])
            if len(vars_in_window) > 1:
                model.Add(sum(vars_in_window) <= 1)

    round_min: Dict[int, cp_model.IntVar] = {}
    round_max: Dict[int, cp_model.IntVar] = {}
    for round_num in range(1, NUM_ROUNDS + 1):
        vars_in_round = [match_time[match_idx] for match_idx in matches_by_round[round_num]]
        round_min_var = model.NewIntVar(0, max_slot_time, f"round_{round_num}_min")
        round_max_var = model.NewIntVar(0, max_slot_time, f"round_{round_num}_max")
        model.AddMinEquality(round_min_var, vars_in_round)
        model.AddMaxEquality(round_max_var, vars_in_round)
        round_min[round_num] = round_min_var
        round_max[round_num] = round_max_var

    for round_num in range(1, NUM_ROUNDS):
        model.Add(round_max[round_num] + 1 <= round_min[round_num + 1])

    print("[baseline] Hard constraints added.")

    objective_terms = []

    for match in matches:
        nominal = nominal_week[match.round_num]
        for (slot_idx, _venue), var in x[match.match_idx].items():
            week_diff = abs(slot_weeks[slot_idx] - nominal)
            if week_diff > 0:
                objective_terms.append(var * (W_ROUND_ORDER * week_diff))

    for week_num in all_weeks:
        week_slots = slots_by_week.get(week_num, [])
        if not week_slots:
            continue

        load_vars = []
        for match in matches:
            for slot_idx in week_slots:
                for venue in venue_options_by_match[match.match_idx].allowed_venues:
                    var = x[match.match_idx].get((slot_idx, venue))
                    if var is not None:
                        load_vars.append(var)

        if not load_vars:
            continue

        load = model.NewIntVar(0, len(load_vars), f"load_w{week_num}")
        model.Add(load == sum(load_vars))
        model.Add(load <= HARD_MAX_MATCHES_PER_WEEK)

        under = model.NewIntVar(0, SOFT_MIN_MATCHES_PER_WEEK, f"under_w{week_num}")
        model.Add(under >= SOFT_MIN_MATCHES_PER_WEEK - load)
        model.Add(under >= 0)
        objective_terms.append(under * W_WEEK_UNDERLOAD)

        over = model.NewIntVar(0, len(load_vars), f"over_w{week_num}")
        model.Add(over >= load - SOFT_MAX_MATCHES_PER_WEEK)
        model.Add(over >= 0)
        objective_terms.append(over * W_WEEK_OVERLOAD)

    for match in matches:
        for (slot_idx, venue), var in x[match.match_idx].items():
            meta = assignment_meta[(match.match_idx, slot_idx, venue)]
            travel_cost = int(meta["travel_km"] * W_TRAVEL)
            if travel_cost > 0:
                objective_terms.append(var * travel_cost)

            tier_diff = abs(match.match_tier - slot_tiers[slot_idx])
            if tier_diff > 0:
                objective_terms.append(var * (W_TIER_MISMATCH * tier_diff))

            if meta["is_alt"]:
                objective_terms.append(var * ALT_STADIUM_RELIEF_PENALTY)

    if objective_terms:
        model.Minimize(sum(objective_terms))

    print(f"[baseline] Model built in {time.time() - t0:.1f}s. Solving...")

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = BASELINE_SOLVER_TIME_LIMIT_S
    solver.parameters.num_workers = 8
    solver.parameters.log_search_progress = True

    status = solver.Solve(model)
    status_name = solver.StatusName(status)
    wall_time = solver.WallTime()

    print(f"[baseline] Solver status: {status_name} ({wall_time:.1f}s)")

    os.makedirs(PHASES_DIR, exist_ok=True)
    with open(os.path.join(PHASES_DIR, "06_baseline_solver_status.json"), "w") as f:
        json.dump(
            {
                "status": int(status),
                "status_name": status_name,
                "wall_time_s": round(wall_time, 2),
                "objective": (
                    solver.ObjectiveValue()
                    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
                    else None
                ),
                "stadium_service_gap_days": MIN_STADIUM_SERVICE_GAP_DAYS,
            },
            f,
            indent=2,
        )

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("[baseline] INFEASIBLE - no schedule produced.")
        return None

    result: List[ScheduledMatch] = []
    for match in matches:
        for (slot_idx, venue), var in x[match.match_idx].items():
            if solver.Value(var) == 1:
                meta = assignment_meta[(match.match_idx, slot_idx, venue)]
                result.append(
                    ScheduledMatch(
                        match_idx=match.match_idx,
                        round_num=match.round_num,
                        home_team=match.home_team,
                        away_team=match.away_team,
                        venue=venue,
                        match_tier=match.match_tier,
                        slot_idx=slot_idx,
                        day_id=slot_day_ids[slot_idx],
                        date=slot_dates[slot_idx],
                        date_time=slot_datetimes[slot_idx],
                        week_num=slot_weeks[slot_idx],
                        day_name=slot_day_names[slot_idx],
                        slot_tier=slot_tiers[slot_idx],
                        travel_km=meta["travel_km"],
                        is_forced_venue=meta["is_forced"],
                    )
                )
                break

    print(f"[baseline] {len(result)} matches scheduled.")
    return result
