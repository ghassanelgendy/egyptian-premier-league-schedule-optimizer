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
    ALT_STADIUM_RELIEF_PENALTY,
    BASELINE_SOLVER_TIME_LIMIT_S,
    ENFORCE_FINAL_ROUND_SINGLE_DAY,
    ENFORCE_FINAL_ROUND_SINGLE_SLOT,
    FINAL_ROUND_MAX_MATCHES_PER_DAY,
    FINAL_ROUND_MAX_MATCHES_PER_SLOT,
    HARD_MAX_MATCHES_PER_WEEK,
    MATCHES_PER_ROUND,
    MAX_MATCHES_PER_DAY,
    MAX_MATCHES_PER_SLOT,
    MIN_DAYS_BETWEEN_ROUNDS,
    MIN_REST_DAYS_CAF,
    MIN_REST_DAYS_LOCAL,
    MIN_STADIUM_SERVICE_GAP_DAYS,
    NUM_ROUNDS,
    OTHER_STADIUM_RELIEF_PENALTY,
    PHASES_DIR,
    SOFT_MAX_MATCHES_PER_WEEK,
    SOFT_MIN_MATCHES_PER_WEEK,
    W_EVENING_PREFERENCE,
    W_HOME_VENUE_DISPLACEMENT,
    W_ROUND_ORDER,
    W_SLOT_SPREAD,
    W_STADIUM_MAINTENANCE_OVERLAP,
    W_TIER_MISMATCH,
    W_TRAVEL,
    W_WEEK_OVERLOAD,
    W_WEEK_UNDERLOAD,
)

# May be patched by UI
NUM_WORKERS = 4
from src.data_loader import LeagueData
from src.final_round import collect_final_round_matches, is_final_round
from src.fixture_generator import Match
from src.slot_domain import build_round_windows
from src.tiers import compute_slot_tiers
from src.venue_rules import (
    VenueCandidate,
    build_team_lookup,
    get_ranked_venue_candidates,
    get_venue_options,
    stadium_distance,
)


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


@dataclass
class _FixedScheduleState:
    """Occupied state for the non-final schedule used by the rescue model."""

    team_dates: Dict[str, List[date]]
    venue_slots: Dict[str, set[int]]
    venue_non_forced_dates: Dict[str, List[date]]
    week_load: Dict[int, int]
    date_load: Dict[date, int]
    slot_usage: Dict[int, int]
    latest_round_dates: Dict[int, date]


TIER_WEIGHTS = {1: 10, 2: 5, 3: 2, 4: 1}

FINAL_ROUND_RESCUE_FORCED_VENUE_BREAK_PENALTY = OTHER_STADIUM_RELIEF_PENALTY * 8
FINAL_ROUND_RESCUE_TIER1_SLOT_PENALTY = OTHER_STADIUM_RELIEF_PENALTY * 4
FINAL_ROUND_RESCUE_LOCAL_REST_SHORTFALL_PENALTY = OTHER_STADIUM_RELIEF_PENALTY * 10
FINAL_ROUND_RESCUE_CAF_SHORTFALL_PENALTY = OTHER_STADIUM_RELIEF_PENALTY * 12
FINAL_ROUND_RESCUE_ROUND_GAP_SHORTFALL_PENALTY = OTHER_STADIUM_RELIEF_PENALTY * 8
FINAL_ROUND_RESCUE_WEEK_OVERFLOW_PENALTY = OTHER_STADIUM_RELIEF_PENALTY * 6


def solve_baseline(
    data: LeagueData,
    matches: List[Match],
    domains: Dict[int, List[int]],
) -> Optional[List[ScheduledMatch]]:
    """Build and solve the baseline model."""
    if ENFORCE_FINAL_ROUND_SINGLE_SLOT or MIN_STADIUM_SERVICE_GAP_DAYS > 0:
        try:
            baseline = _solve_baseline_with_venue_flex(data, matches, domains)
        except RuntimeError as exc:
            if not collect_final_round_matches(matches):
                raise
            strict_status = _read_baseline_status()
            print(
                "[baseline] Strict final-round model raised a recoverable error: "
                f"{exc}"
            )
            rescued = _solve_baseline_with_final_round_rescue(data, matches, domains)
            _attach_rescue_attempt_metadata(strict_status, rescued is not None)
            return rescued
        if baseline is not None or not collect_final_round_matches(matches):
            return baseline

        strict_status = _read_baseline_status()
        print(
            "[baseline] Strict final-round model is infeasible. Retrying with a "
            "dedicated Round 34 rescue model."
        )
        rescued = _solve_baseline_with_final_round_rescue(data, matches, domains)
        _attach_rescue_attempt_metadata(strict_status, rescued is not None)
        return rescued
    return _solve_baseline_legacy(data, matches, domains)


def _baseline_status_path() -> str:
    return os.path.join(PHASES_DIR, "06_baseline_solver_status.json")


def _read_baseline_status() -> dict:
    path = _baseline_status_path()
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_baseline_status(
    status: int,
    status_name: str,
    wall_time_s: float,
    objective: float | None,
    *,
    extra: Optional[dict] = None,
) -> None:
    payload = {
        "status": int(status),
        "status_name": status_name,
        "wall_time_s": round(wall_time_s, 2),
        "objective": objective,
        "stadium_service_gap_days": MIN_STADIUM_SERVICE_GAP_DAYS,
    }
    if extra:
        payload.update(extra)

    os.makedirs(PHASES_DIR, exist_ok=True)
    with open(_baseline_status_path(), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _attach_rescue_attempt_metadata(
    strict_status: dict,
    rescue_used: bool,
) -> None:
    status = _read_baseline_status()
    status["final_round_rescue_attempted"] = True
    status["final_round_rescue_used"] = rescue_used
    if strict_status:
        status["strict_attempt"] = {
            "status": strict_status.get("status"),
            "status_name": strict_status.get("status_name"),
            "wall_time_s": strict_status.get("wall_time_s"),
            "objective": strict_status.get("objective"),
            "solver_mode": strict_status.get("solver_mode"),
        }
    os.makedirs(PHASES_DIR, exist_ok=True)
    with open(_baseline_status_path(), "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2)


def _build_venue_candidates_by_match(
    data: LeagueData,
    matches: List[Match],
    teams_dict: Dict[str, dict],
) -> Dict[int, List[VenueCandidate]]:
    stadium_ids = sorted(data.stadiums["Stadium_ID"].astype(str).str.strip().str.upper().tolist())
    candidates_by_match: Dict[int, List[VenueCandidate]] = {}

    for match in matches:
        options = get_venue_options(
            match.home_team,
            match.away_team,
            teams_dict,
            data.sec_rules,
        )

        if options.is_forced_only:
            candidates_by_match[match.match_idx] = get_ranked_venue_candidates(
                match.home_team,
                match.away_team,
                teams_dict,
                data.sec_rules,
                stadium_ids,
                data.dist_matrix,
                allow_other_stadiums=False,
            )
            continue

        if is_final_round(match.round_num):
            candidates_by_match[match.match_idx] = get_ranked_venue_candidates(
                match.home_team,
                match.away_team,
                teams_dict,
                data.sec_rules,
                stadium_ids,
                data.dist_matrix,
                allow_other_stadiums=True,
            )
            continue

        if MIN_STADIUM_SERVICE_GAP_DAYS > 0:
            candidates_by_match[match.match_idx] = get_ranked_venue_candidates(
                match.home_team,
                match.away_team,
                teams_dict,
                data.sec_rules,
                stadium_ids,
                data.dist_matrix,
                allow_other_stadiums=False,
            )
            continue

        candidates_by_match[match.match_idx] = [
            VenueCandidate(
                venue=match.venue,
                is_forced=False,
                is_primary=True,
                is_alt=False,
                is_other=False,
                home_displacement_km=0.0,
            )
        ]

    return candidates_by_match


def _build_final_round_rescue_candidates(
    match: Match,
    data: LeagueData,
    teams_dict: Dict[str, dict],
    stadium_ids: List[str],
) -> tuple[List[VenueCandidate], str]:
    """Return Round 34 rescue venue choices with banned venues kept hard."""
    options = get_venue_options(
        match.home_team,
        match.away_team,
        teams_dict,
        data.sec_rules,
    )
    primary = options.primary_venue
    alt = options.alt_venue
    forced = (
        ""
        if options.forced_venue in options.banned_venues
        else options.forced_venue
    )

    candidates: List[VenueCandidate] = []
    seen: set[str] = set()

    def add_candidate(
        venue: str,
        *,
        is_forced: bool,
        is_primary: bool,
        is_alt: bool,
        is_other: bool,
    ) -> None:
        normalized = str(venue or "").strip().upper()
        if (
            not normalized
            or normalized in seen
            or normalized in options.banned_venues
        ):
            return
        candidates.append(
            VenueCandidate(
                venue=normalized,
                is_forced=is_forced,
                is_primary=is_primary,
                is_alt=is_alt,
                is_other=is_other,
                home_displacement_km=stadium_distance(
                    data.dist_matrix,
                    primary,
                    normalized,
                ),
            )
        )
        seen.add(normalized)

    add_candidate(
        forced,
        is_forced=True,
        is_primary=forced == primary,
        is_alt=forced == alt,
        is_other=forced not in {"", primary, alt},
    )
    add_candidate(
        primary,
        is_forced=False,
        is_primary=True,
        is_alt=False,
        is_other=False,
    )
    add_candidate(
        alt,
        is_forced=False,
        is_primary=False,
        is_alt=True,
        is_other=False,
    )

    other_venues = []
    for venue in stadium_ids:
        normalized = str(venue or "").strip().upper()
        if (
            not normalized
            or normalized in seen
            or normalized in options.banned_venues
        ):
            continue
        other_venues.append(normalized)
    other_venues.sort(
        key=lambda venue: (
            stadium_distance(data.dist_matrix, primary, venue),
            venue,
        )
    )
    for venue in other_venues:
        add_candidate(
            venue,
            is_forced=False,
            is_primary=False,
            is_alt=False,
            is_other=True,
        )

    return candidates, forced


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
    all_dates = sorted(set(slot_dates))
    all_weeks = sorted(set(slot_weeks))
    slot_day_lookup = {slot_date: idx for idx, slot_date in enumerate(all_dates)}
    slot_day_index = [slot_day_lookup[slot_date] for slot_date in slot_dates]

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

    slot_kickoff_hours: List[int] = []
    for dt in slot_datetimes:
        hour = 12  # default if time is missing
        if dt is not None:
            try:
                import pandas as _pd
                if not _pd.isna(dt):
                    hour = dt.hour
            except (AttributeError, TypeError):
                pass
        slot_kickoff_hours.append(hour)

    return {
        "slots": slots,
        "n_slots": n_slots,
        "slot_dates": slot_dates,
        "slot_weeks": slot_weeks,
        "slot_day_names": slot_day_names,
        "slot_tiers": slot_tiers,
        "slot_day_ids": slot_day_ids,
        "slot_datetimes": slot_datetimes,
        "slot_day_index": slot_day_index,
        "slot_kickoff_hours": slot_kickoff_hours,
        "all_dates": all_dates,
        "all_weeks": all_weeks,
        "slots_by_date": slots_by_date,
        "slots_by_week": slots_by_week,
        "nominal_week": nominal_week,
        "max_slot_day": max(slot_day_index) if slot_day_index else 0,
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


def _build_fixed_schedule_state(matches: List[ScheduledMatch]) -> _FixedScheduleState:
    team_dates: Dict[str, List[date]] = defaultdict(list)
    venue_slots: Dict[str, set[int]] = defaultdict(set)
    venue_non_forced_dates: Dict[str, List[date]] = defaultdict(list)
    week_load: Dict[int, int] = defaultdict(int)
    date_load: Dict[date, int] = defaultdict(int)
    slot_usage: Dict[int, int] = defaultdict(int)
    latest_round_dates: Dict[int, date] = {}

    for match in matches:
        team_dates[match.home_team].append(match.date)
        team_dates[match.away_team].append(match.date)
        venue_slots[match.venue].add(match.slot_idx)
        if not match.is_forced_venue:
            venue_non_forced_dates[match.venue].append(match.date)
        week_load[match.week_num] += 1
        date_load[match.date] += 1
        slot_usage[match.slot_idx] += 1
        latest_round_dates[match.round_num] = max(
            latest_round_dates.get(match.round_num, match.date),
            match.date,
        )

    for team_id in team_dates:
        team_dates[team_id].sort()
    for venue in venue_non_forced_dates:
        venue_non_forced_dates[venue].sort()

    return _FixedScheduleState(
        team_dates=dict(team_dates),
        venue_slots=dict(venue_slots),
        venue_non_forced_dates=dict(venue_non_forced_dates),
        week_load=dict(week_load),
        date_load=dict(date_load),
        slot_usage=dict(slot_usage),
        latest_round_dates=latest_round_dates,
    )


def _has_same_day_team_conflict(
    match: Match,
    candidate_date: date,
    state: _FixedScheduleState,
) -> bool:
    return (
        candidate_date in state.team_dates.get(match.home_team, [])
        or candidate_date in state.team_dates.get(match.away_team, [])
    )


def _required_gap_shortfall(
    existing_dates: List[date],
    candidate_date: date,
    required_gap_days: int,
) -> int:
    if not existing_dates:
        return 0
    return max(
        (
            max(0, required_gap_days - abs((candidate_date - existing_date).days))
            for existing_date in existing_dates
        ),
        default=0,
    )


def _round_gap_shortfall(
    state: _FixedScheduleState,
    candidate_date: date,
) -> int:
    previous_round_end = state.latest_round_dates.get(NUM_ROUNDS - 1)
    if previous_round_end is None:
        return 0
    return max(
        0,
        MIN_DAYS_BETWEEN_ROUNDS - (candidate_date - previous_round_end).days,
    )


def _build_match_day_vars(
    model: cp_model.CpModel,
    matches: List[Match],
    assignment_terms_by_match: Dict[int, List[Tuple[int, cp_model.IntVar]]],
    max_slot_day: int,
) -> Dict[int, cp_model.IntVar]:
    match_day: Dict[int, cp_model.IntVar] = {}
    for match in matches:
        d_var = model.NewIntVar(0, max_slot_day, f"match_day_{match.match_idx}")
        model.Add(
            d_var
            == sum(
                day_index * var
                for day_index, var in assignment_terms_by_match[match.match_idx]
            )
        )
        match_day[match.match_idx] = d_var
    return match_day


def _build_final_round_shared_slot_vars(
    model: cp_model.CpModel,
    matches: List[Match],
    assignment_vars_by_match_slot: Dict[int, Dict[int, List[cp_model.IntVar]]],
    slot_dates: List[date],
) -> Dict[int, cp_model.IntVar]:
    """Force every final-round match onto one shared kickoff slot."""
    if not ENFORCE_FINAL_ROUND_SINGLE_SLOT:
        return {}

    final_round_matches = collect_final_round_matches(matches)
    if not final_round_matches:
        return {}

    candidate_slots = sorted({
        slot_idx
        for match in final_round_matches
        for slot_idx in assignment_vars_by_match_slot[match.match_idx]
    })
    if not candidate_slots:
        raise RuntimeError("Final round has no candidate slots in its domain")

    chosen_slot_vars: Dict[int, cp_model.IntVar] = {}
    for candidate_slot in candidate_slots:
        slot_date = slot_dates[candidate_slot]
        label = f"{slot_date:%Y%m%d}_{candidate_slot}" if slot_date is not None else str(candidate_slot)
        chosen_slot_vars[candidate_slot] = model.NewBoolVar(
            f"final_round_slot_{label}"
        )

    model.Add(sum(chosen_slot_vars.values()) == 1)

    for match in final_round_matches:
        for candidate_slot, chosen_var in chosen_slot_vars.items():
            model.Add(
                sum(assignment_vars_by_match_slot[match.match_idx].get(candidate_slot, []))
                == chosen_var
            )

    return chosen_slot_vars


def _build_final_round_shared_date_vars(
    final_round_slot_vars: Dict[int, cp_model.IntVar],
    slot_dates: List[date],
) -> Dict[date, cp_model.LinearExpr]:
    """Aggregate chosen final-round slot indicators into chosen-date indicators."""
    chosen_date_vars: Dict[date, List[cp_model.IntVar]] = defaultdict(list)
    for slot_idx, chosen_var in final_round_slot_vars.items():
        slot_date = slot_dates[slot_idx]
        if slot_date is not None:
            chosen_date_vars[slot_date].append(chosen_var)
    return {
        slot_date: sum(vars_on_date)
        for slot_date, vars_on_date in chosen_date_vars.items()
    }


def _add_daily_capacity_constraints(
    model: cp_model.CpModel,
    all_vars_by_date: Dict[date, List[cp_model.IntVar]],
    final_round_date_vars: Dict[date, cp_model.LinearExpr],
) -> None:
    extra_capacity = FINAL_ROUND_MAX_MATCHES_PER_DAY - MAX_MATCHES_PER_DAY
    for slot_date, vars_on_date in all_vars_by_date.items():
        if not vars_on_date:
            continue

        chosen_var = final_round_date_vars.get(slot_date)
        if chosen_var is None or extra_capacity <= 0:
            if len(vars_on_date) > MAX_MATCHES_PER_DAY:
                model.Add(sum(vars_on_date) <= MAX_MATCHES_PER_DAY)
            continue

        model.Add(
            sum(vars_on_date)
            <= MAX_MATCHES_PER_DAY + (extra_capacity * chosen_var)
        )


def _add_slot_capacity_constraints(
    model: cp_model.CpModel,
    all_vars_by_slot: Dict[int, List[cp_model.IntVar]],
    final_round_slot_vars: Dict[int, cp_model.IntVar],
) -> None:
    extra_capacity = FINAL_ROUND_MAX_MATCHES_PER_SLOT - MAX_MATCHES_PER_SLOT
    for slot_idx, vars_in_slot in all_vars_by_slot.items():
        if not vars_in_slot:
            continue

        chosen_var = final_round_slot_vars.get(slot_idx)
        if chosen_var is None or extra_capacity <= 0:
            if len(vars_in_slot) > MAX_MATCHES_PER_SLOT:
                model.Add(sum(vars_in_slot) <= MAX_MATCHES_PER_SLOT)
            continue

        model.Add(
            sum(vars_in_slot)
            <= MAX_MATCHES_PER_SLOT + (extra_capacity * chosen_var)
        )


def _add_round_gap_constraints(
    model: cp_model.CpModel,
    matches_by_round: Dict[int, List[int]],
    match_day: Dict[int, cp_model.IntVar],
    max_slot_day: int,
) -> None:
    round_start_day: Dict[int, cp_model.IntVar] = {}
    round_end_day: Dict[int, cp_model.IntVar] = {}

    for round_num in range(1, NUM_ROUNDS + 1):
        vars_in_round = [
            match_day[match_idx]
            for match_idx in matches_by_round.get(round_num, [])
            if match_idx in match_day
        ]
        if not vars_in_round:
            continue
        start_var = model.NewIntVar(0, max_slot_day, f"round_{round_num}_start_day")
        end_var = model.NewIntVar(0, max_slot_day, f"round_{round_num}_end_day")
        model.AddMinEquality(start_var, vars_in_round)
        model.AddMaxEquality(end_var, vars_in_round)
        round_start_day[round_num] = start_var
        round_end_day[round_num] = end_var

    for round_num in range(1, NUM_ROUNDS):
        if round_num not in round_end_day or (round_num + 1) not in round_start_day:
            continue
        model.Add(
            round_end_day[round_num] + MIN_DAYS_BETWEEN_ROUNDS
            <= round_start_day[round_num + 1]
        )


def _solve_baseline_with_final_round_rescue(
    data: LeagueData,
    matches: List[Match],
    domains: Dict[int, List[int]],
) -> Optional[List[ScheduledMatch]]:
    final_round_matches = collect_final_round_matches(matches)
    if not final_round_matches:
        return None

    print("[baseline] Solving Rounds 1-33 subproblem for final-round rescue...")
    regular_matches = [match for match in matches if not is_final_round(match.round_num)]
    regular_domains = {
        match.match_idx: domains[match.match_idx]
        for match in regular_matches
    }
    regular_schedule = _solve_baseline_with_venue_flex(
        data,
        regular_matches,
        regular_domains,
        write_status=False,
        solve_label="Rounds 1-33 subproblem",
    )
    if regular_schedule is None:
        _write_baseline_status(
            cp_model.INFEASIBLE,
            "INFEASIBLE",
            0.0,
            None,
            extra={
                "solver_mode": "final_round_rescue",
                "final_round_rescue_mode": True,
                "final_round_rescue_candidate_slot_count": 0,
                "reason": "Rounds 1-33 subproblem is infeasible under the current domain policy.",
            },
        )
        return None

    print("[baseline] Building dedicated Round 34 rescue model...")
    t0 = time.time()

    slot_ctx = _build_slot_context(data)
    slot_dates = slot_ctx["slot_dates"]
    slot_weeks = slot_ctx["slot_weeks"]
    slot_day_names = slot_ctx["slot_day_names"]
    slot_tiers = slot_ctx["slot_tiers"]
    slot_day_ids = slot_ctx["slot_day_ids"]
    slot_datetimes = slot_ctx["slot_datetimes"]
    nominal_week = slot_ctx["nominal_week"]

    teams_dict, tier1_teams, _matches_by_team, _matches_by_round = _build_match_context(
        data, matches
    )
    state = _build_fixed_schedule_state(regular_schedule)
    stadium_ids = sorted(
        data.stadiums["Stadium_ID"].astype(str).str.strip().str.upper().tolist()
    )

    round_windows = build_round_windows(data)
    final_round_window = next(
        (
            round_window
            for round_window in round_windows
            if round_window.round_num == NUM_ROUNDS
        ),
        None,
    )
    if final_round_window is None:
        _write_baseline_status(
            cp_model.INFEASIBLE,
            "INFEASIBLE",
            0.0,
            None,
            extra={
                "solver_mode": "final_round_rescue",
                "final_round_rescue_mode": True,
                "final_round_rescue_candidate_slot_count": 0,
                "reason": "Round 34 tail window could not be reconstructed for rescue.",
            },
        )
        return None

    candidate_slots = sorted(final_round_window.slot_indices)
    if not candidate_slots:
        _write_baseline_status(
            cp_model.INFEASIBLE,
            "INFEASIBLE",
            0.0,
            None,
            extra={
                "solver_mode": "final_round_rescue",
                "final_round_rescue_mode": True,
                "final_round_rescue_candidate_slot_count": 0,
                "reason": "Round 34 tail window has no usable slots.",
            },
        )
        return None

    required_local_gap = MIN_REST_DAYS_LOCAL + 1
    required_caf_gap = MIN_REST_DAYS_CAF + 1

    model = cp_model.CpModel()
    objective_terms = []

    chosen_slot_vars: Dict[int, cp_model.IntVar] = {}
    y: Dict[Tuple[int, int, str], cp_model.IntVar] = {}
    assignment_vars_by_match_slot: Dict[int, Dict[int, List[cp_model.IntVar]]] = defaultdict(
        lambda: defaultdict(list)
    )
    venue_slot_vars: Dict[Tuple[str, int], List[cp_model.IntVar]] = defaultdict(list)

    for slot_idx in candidate_slots:
        slot_date = slot_dates[slot_idx]
        label = f"{slot_date:%Y%m%d}_{slot_idx}" if slot_date is not None else str(slot_idx)
        chosen_slot_vars[slot_idx] = model.NewBoolVar(f"final_round_rescue_slot_{label}")

    model.Add(sum(chosen_slot_vars.values()) == 1)

    for match in final_round_matches:
        venue_candidates, forced_venue = _build_final_round_rescue_candidates(
            match,
            data,
            teams_dict,
            stadium_ids,
        )
        home_tier = int(teams_dict.get(match.home_team, {}).get("Tier", 4))
        tier_weight = TIER_WEIGHTS.get(home_tier, 1)
        for slot_idx in candidate_slots:
            slot_date = slot_dates[slot_idx]
            if slot_date is None:
                continue
            if _has_same_day_team_conflict(match, slot_date, state):
                continue
            if (
                state.date_load.get(slot_date, 0) + MATCHES_PER_ROUND
                > FINAL_ROUND_MAX_MATCHES_PER_DAY
            ):
                continue
            if (
                state.slot_usage.get(slot_idx, 0) + MATCHES_PER_ROUND
                > FINAL_ROUND_MAX_MATCHES_PER_SLOT
            ):
                continue

            slot_local_rest_shortfall = (
                _required_gap_shortfall(
                    state.team_dates.get(match.home_team, []),
                    slot_date,
                    required_local_gap,
                )
                + _required_gap_shortfall(
                    state.team_dates.get(match.away_team, []),
                    slot_date,
                    required_local_gap,
                )
            )
            slot_caf_shortfall = (
                _required_gap_shortfall(
                    data.caf_dates_by_team.get(match.home_team, []),
                    slot_date,
                    required_caf_gap,
                )
                + _required_gap_shortfall(
                    data.caf_dates_by_team.get(match.away_team, []),
                    slot_date,
                    required_caf_gap,
                )
            )
            slot_round_gap_shortfall = _round_gap_shortfall(state, slot_date)
            slot_week_overflow = max(
                0,
                state.week_load.get(slot_weeks[slot_idx], 0) + MATCHES_PER_ROUND
                - HARD_MAX_MATCHES_PER_WEEK,
            )
            misses_tier1_slot = int(
                match.home_team in tier1_teams
                and match.away_team in tier1_teams
                and slot_tiers[slot_idx] != 1
            )

            nominal = nominal_week[match.round_num]
            week_diff = abs(slot_weeks[slot_idx] - nominal)
            tier_diff = abs(match.match_tier - slot_tiers[slot_idx])

            for candidate in venue_candidates:
                venue = candidate.venue
                if slot_idx in state.venue_slots.get(venue, set()):
                    continue

                key = (match.match_idx, slot_idx, venue)
                y[key] = model.NewBoolVar(f"fr_rescue_{match.match_idx}_{slot_idx}_{venue}")
                assignment_vars_by_match_slot[match.match_idx][slot_idx].append(y[key])
                venue_slot_vars[(venue, slot_idx)].append(y[key])

                away_home_stadium = teams_dict.get(match.away_team, {}).get(
                    "Home_Stadium_ID",
                    "",
                )
                away_travel = stadium_distance(data.dist_matrix, away_home_stadium, venue)

                if week_diff > 0:
                    objective_terms.append(y[key] * (W_ROUND_ORDER * week_diff))
                if tier_diff > 0:
                    objective_terms.append(y[key] * (W_TIER_MISMATCH * tier_diff))

                away_travel_cost = int(away_travel * W_TRAVEL)
                if away_travel_cost > 0:
                    objective_terms.append(y[key] * away_travel_cost)

                if candidate.is_alt:
                    objective_terms.append(
                        y[key] * (ALT_STADIUM_RELIEF_PENALTY * tier_weight)
                    )
                elif candidate.is_other:
                    objective_terms.append(
                        y[key] * (OTHER_STADIUM_RELIEF_PENALTY * tier_weight)
                    )

                home_displacement_cost = int(
                    candidate.home_displacement_km * W_HOME_VENUE_DISPLACEMENT
                )
                if home_displacement_cost > 0:
                    objective_terms.append(y[key] * home_displacement_cost)

                if forced_venue and venue != forced_venue:
                    objective_terms.append(
                        y[key]
                        * (FINAL_ROUND_RESCUE_FORCED_VENUE_BREAK_PENALTY * tier_weight)
                    )
                if misses_tier1_slot:
                    objective_terms.append(
                        y[key] * FINAL_ROUND_RESCUE_TIER1_SLOT_PENALTY
                    )
                if slot_local_rest_shortfall > 0:
                    objective_terms.append(
                        y[key]
                        * (
                            FINAL_ROUND_RESCUE_LOCAL_REST_SHORTFALL_PENALTY
                            * slot_local_rest_shortfall
                        )
                    )
                if slot_caf_shortfall > 0:
                    objective_terms.append(
                        y[key]
                        * (
                            FINAL_ROUND_RESCUE_CAF_SHORTFALL_PENALTY
                            * slot_caf_shortfall
                        )
                    )
                if slot_round_gap_shortfall > 0:
                    objective_terms.append(
                        y[key]
                        * (
                            FINAL_ROUND_RESCUE_ROUND_GAP_SHORTFALL_PENALTY
                            * slot_round_gap_shortfall
                        )
                    )
                if slot_week_overflow > 0:
                    objective_terms.append(
                        y[key]
                        * (
                            FINAL_ROUND_RESCUE_WEEK_OVERFLOW_PENALTY
                            * slot_week_overflow
                        )
                    )
                if (
                    MIN_STADIUM_SERVICE_GAP_DAYS > 0
                    and not candidate.is_forced
                    and _required_gap_shortfall(
                        state.venue_non_forced_dates.get(venue, []),
                        slot_date,
                        MIN_STADIUM_SERVICE_GAP_DAYS + 1,
                    )
                    > 0
                ):
                    objective_terms.append(y[key] * W_STADIUM_MAINTENANCE_OVERLAP)

        if match.match_idx not in assignment_vars_by_match_slot:
            assignment_vars_by_match_slot[match.match_idx] = defaultdict(list)

    for match in final_round_matches:
        match_slot_vars = assignment_vars_by_match_slot.get(match.match_idx, {})
        flat_vars = [
            var
            for vars_at_slot in match_slot_vars.values()
            for var in vars_at_slot
        ]
        if not flat_vars:
            _write_baseline_status(
                cp_model.INFEASIBLE,
                "INFEASIBLE",
                0.0,
                None,
                extra={
                    "solver_mode": "final_round_rescue",
                    "final_round_rescue_mode": True,
                    "final_round_rescue_candidate_slot_count": len(candidate_slots),
                    "reason": (
                        "At least one Round 34 match has no non-banned rescue "
                        "assignment in the shared-slot tail window."
                    ),
                },
            )
            return None

        model.Add(sum(flat_vars) == 1)
        for slot_idx, chosen_var in chosen_slot_vars.items():
            model.Add(sum(match_slot_vars.get(slot_idx, [])) == chosen_var)

    for vars_in_slot in venue_slot_vars.values():
        if len(vars_in_slot) > 1:
            model.Add(sum(vars_in_slot) <= 1)

    if objective_terms:
        model.Minimize(sum(objective_terms))

    print(f"[baseline] Rescue model built in {time.time() - t0:.1f}s. Solving...")
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = BASELINE_SOLVER_TIME_LIMIT_S
    solver.parameters.num_workers = NUM_WORKERS
    solver.parameters.log_search_progress = True

    status = solver.Solve(model)
    status_name = solver.StatusName(status)
    wall_time = solver.WallTime()
    objective = (
        solver.ObjectiveValue()
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        else None
    )
    print(f"[baseline] Rescue solver status: {status_name} ({wall_time:.1f}s)")

    _write_baseline_status(
        status,
        status_name,
        wall_time,
        objective,
        extra={
            "solver_mode": "final_round_rescue",
            "final_round_rescue_mode": True,
            "final_round_rescue_candidate_slot_count": len(candidate_slots),
            "final_round_rescue_relaxations": [
                "forced_venue",
                "tier1_slot",
                "local_rest",
                "caf_buffer",
                "round_gap",
                "week_cap",
                "stadium_service_gap",
            ],
            "regular_round_match_count": len(regular_schedule),
        },
    )

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("[baseline] Final-round rescue still infeasible.")
        return None

    rescued_matches: List[ScheduledMatch] = []
    for match in final_round_matches:
        for slot_idx in candidate_slots:
            for candidate in _build_final_round_rescue_candidates(
                match,
                data,
                teams_dict,
                stadium_ids,
            )[0]:
                venue = candidate.venue
                var = y.get((match.match_idx, slot_idx, venue))
                if var is None or solver.Value(var) != 1:
                    continue

                away_home_stadium = teams_dict.get(match.away_team, {}).get(
                    "Home_Stadium_ID",
                    "",
                )
                rescued_matches.append(
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
                        travel_km=stadium_distance(
                            data.dist_matrix,
                            away_home_stadium,
                            venue,
                        ),
                        is_forced_venue=candidate.is_forced,
                    )
                )
                break
            else:
                continue
            break

    result = sorted(
        regular_schedule + rescued_matches,
        key=lambda scheduled: (
            scheduled.date,
            str(scheduled.date_time),
            scheduled.round_num,
            scheduled.match_idx,
        ),
    )
    print(f"[baseline] Final-round rescue scheduled {len(rescued_matches)} matches.")
    return result


def _solve_baseline_legacy(
    data: LeagueData,
    matches: List[Match],
    domains: Dict[int, List[int]],
) -> Optional[List[ScheduledMatch]]:
    print("[baseline] Building CP-SAT model (legacy mode)...")
    t0 = time.time()

    slot_ctx = _build_slot_context(data)
    slot_dates = slot_ctx["slot_dates"]
    slot_weeks = slot_ctx["slot_weeks"]
    slot_day_names = slot_ctx["slot_day_names"]
    slot_tiers = slot_ctx["slot_tiers"]
    slot_day_ids = slot_ctx["slot_day_ids"]
    slot_datetimes = slot_ctx["slot_datetimes"]
    slot_day_index = slot_ctx["slot_day_index"]
    all_dates = slot_ctx["all_dates"]
    all_weeks = slot_ctx["all_weeks"]
    slots_by_date = slot_ctx["slots_by_date"]
    slots_by_week = slot_ctx["slots_by_week"]
    nominal_week = slot_ctx["nominal_week"]
    max_slot_day = slot_ctx["max_slot_day"]
    n_slots = slot_ctx["n_slots"]
    slot_kickoff_hours = slot_ctx["slot_kickoff_hours"]

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

    match_day = _build_match_day_vars(
        model,
        matches,
        {
            match.match_idx: [
                (slot_day_index[slot_idx], var)
                for slot_idx, var in x[match.match_idx].items()
            ]
            for match in matches
        },
        max_slot_day,
    )
    assignment_vars_by_match_slot = {
        match.match_idx: {
            slot_idx: [var]
            for slot_idx, var in x[match.match_idx].items()
        }
        for match in matches
    }
    final_round_slot_vars = _build_final_round_shared_slot_vars(
        model,
        matches,
        assignment_vars_by_match_slot,
        slot_dates,
    )
    final_round_date_vars = _build_final_round_shared_date_vars(
        final_round_slot_vars,
        slot_dates,
    )

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
                if is_final_round(match.round_num):
                    _write_baseline_status(
                        cp_model.INFEASIBLE,
                        "INFEASIBLE",
                        0.0,
                        None,
                        extra={
                            "solver_mode": "legacy",
                            "reason": (
                                "Round 34 strict tier-1 slot requirement has no "
                                "candidate slot and must fall back to rescue."
                            ),
                        },
                    )
                    print(
                        "[baseline] Strict final-round tier-1 slot rule has no "
                        "candidate slot."
                    )
                    return None
                print(
                    f"[baseline] No tier-1 slots available in domain for tier-1 derby: "
                    f"{match.home_team} vs {match.away_team}. Returning None to trigger fallback."
                )
                return None
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

    all_vars_by_date: Dict[date, List[cp_model.IntVar]] = defaultdict(list)
    for slot_date, slot_indices in slots_by_date.items():
        for match in matches:
            for slot_idx in slot_indices:
                if slot_idx in x[match.match_idx]:
                    all_vars_by_date[slot_date].append(x[match.match_idx][slot_idx])
    _add_daily_capacity_constraints(model, all_vars_by_date, final_round_date_vars)

    all_vars_by_slot: Dict[int, List[cp_model.IntVar]] = defaultdict(list)
    for slot_idx in range(n_slots):
        for match in matches:
            if slot_idx in x[match.match_idx]:
                all_vars_by_slot[slot_idx].append(x[match.match_idx][slot_idx])
    _add_slot_capacity_constraints(
        model,
        all_vars_by_slot,
        final_round_slot_vars,
    )

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

    _add_round_gap_constraints(model, matches_by_round, match_day, max_slot_day)

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

    # --- Evening preference: penalize earlier kickoff times ---
    if W_EVENING_PREFERENCE > 0:
        for match in matches:
            for slot_idx, var in x[match.match_idx].items():
                hour_penalty = max(0, 21 - slot_kickoff_hours[slot_idx])
                if hour_penalty > 0:
                    objective_terms.append(var * (W_EVENING_PREFERENCE * hour_penalty))

    # --- Slot spread: penalize >1 match in the same kickoff slot on same day ---
    if W_SLOT_SPREAD > 0:
        for slot_idx in range(n_slots):
            vars_in_slot = all_vars_by_slot.get(slot_idx, [])
            if len(vars_in_slot) > 1:
                collision = model.NewBoolVar(f"slot_collision_{slot_idx}")
                model.Add(sum(vars_in_slot) > 1).OnlyEnforceIf(collision)
                model.Add(sum(vars_in_slot) <= 1).OnlyEnforceIf(collision.Not())
                objective_terms.append(collision * W_SLOT_SPREAD)

    if objective_terms:
        model.Minimize(sum(objective_terms))

    print(f"[baseline] Model built in {time.time() - t0:.1f}s. Solving...")

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = BASELINE_SOLVER_TIME_LIMIT_S
    solver.parameters.num_workers = NUM_WORKERS
    solver.parameters.log_search_progress = True

    status = solver.Solve(model)
    status_name = solver.StatusName(status)
    wall_time = solver.WallTime()

    print(f"[baseline] Solver status: {status_name} ({wall_time:.1f}s)")

    _write_baseline_status(
        status,
        status_name,
        wall_time,
        (
            solver.ObjectiveValue()
            if status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
            else None
        ),
        extra={
            "solver_mode": "legacy",
            "final_round_rescue_attempted": False,
            "final_round_rescue_used": False,
        },
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


def _solve_baseline_with_venue_flex(
    data: LeagueData,
    matches: List[Match],
    domains: Dict[int, List[int]],
    *,
    write_status: bool = True,
    solve_label: str = "flexible venue assignment",
) -> Optional[List[ScheduledMatch]]:
    print(f"[baseline] Building CP-SAT model with {solve_label}...")
    t0 = time.time()

    slot_ctx = _build_slot_context(data)
    slot_dates = slot_ctx["slot_dates"]
    slot_weeks = slot_ctx["slot_weeks"]
    slot_day_names = slot_ctx["slot_day_names"]
    slot_tiers = slot_ctx["slot_tiers"]
    slot_day_ids = slot_ctx["slot_day_ids"]
    slot_datetimes = slot_ctx["slot_datetimes"]
    slot_day_index = slot_ctx["slot_day_index"]
    all_dates = slot_ctx["all_dates"]
    all_weeks = slot_ctx["all_weeks"]
    slots_by_date = slot_ctx["slots_by_date"]
    slots_by_week = slot_ctx["slots_by_week"]
    nominal_week = slot_ctx["nominal_week"]
    max_slot_day = slot_ctx["max_slot_day"]
    n_slots = slot_ctx["n_slots"]
    slot_kickoff_hours = slot_ctx["slot_kickoff_hours"]

    teams_dict, tier1_teams, matches_by_team, matches_by_round = _build_match_context(
        data, matches
    )

    venue_candidates_by_match = _build_venue_candidates_by_match(data, matches, teams_dict)

    def get_travel(away_team: str, venue: str) -> float:
        away_home_stadium = teams_dict.get(away_team, {}).get("Home_Stadium_ID", "")
        return stadium_distance(data.dist_matrix, away_home_stadium, venue)

    model = cp_model.CpModel()
    objective_terms = []

    x: Dict[int, Dict[Tuple[int, str], cp_model.IntVar]] = {}
    assignment_meta: Dict[Tuple[int, int, str], dict] = {}
    venue_slot_vars: Dict[Tuple[str, int], List[cp_model.IntVar]] = defaultdict(list)
    venue_date_vars: Dict[Tuple[str, date], List[cp_model.IntVar]] = defaultdict(list)

    for match in matches:
        candidates = venue_candidates_by_match[match.match_idx]
        x[match.match_idx] = {}
        for slot_idx in domains[match.match_idx]:
            for candidate in candidates:
                venue = candidate.venue
                key = (slot_idx, venue)
                var = model.NewBoolVar(f"x_{match.match_idx}_{slot_idx}_{venue}")
                x[match.match_idx][key] = var

                travel = get_travel(match.away_team, venue)

                assignment_meta[(match.match_idx, slot_idx, venue)] = {
                    "is_forced": candidate.is_forced,
                    "is_alt": candidate.is_alt,
                    "is_other": candidate.is_other,
                    "home_displacement_km": candidate.home_displacement_km,
                    "travel_km": travel,
                }
                venue_slot_vars[(venue, slot_idx)].append(var)
                venue_date_vars[(venue, slot_dates[slot_idx])].append(var)

    print(f"[baseline] Variables created: {sum(len(v) for v in x.values())}")

    match_day = _build_match_day_vars(
        model,
        matches,
        {
            match.match_idx: [
                (slot_day_index[slot_idx], var)
                for (slot_idx, _venue), var in x[match.match_idx].items()
            ]
            for match in matches
        },
        max_slot_day,
    )
    assignment_vars_by_match_slot: Dict[int, Dict[int, List[cp_model.IntVar]]] = {}
    for match in matches:
        grouped: Dict[int, List[cp_model.IntVar]] = defaultdict(list)
        for (slot_idx, _venue), var in x[match.match_idx].items():
            grouped[slot_idx].append(var)
        assignment_vars_by_match_slot[match.match_idx] = dict(grouped)

    final_round_slot_vars = _build_final_round_shared_slot_vars(
        model,
        matches,
        assignment_vars_by_match_slot,
        slot_dates,
    )
    final_round_date_vars = _build_final_round_shared_date_vars(
        final_round_slot_vars,
        slot_dates,
    )

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
                if is_final_round(match.round_num):
                    if write_status:
                        _write_baseline_status(
                            cp_model.INFEASIBLE,
                            "INFEASIBLE",
                            0.0,
                            None,
                            extra={
                                "solver_mode": "strict_flexible_venue",
                                "reason": (
                                    "Round 34 strict tier-1 slot requirement has no "
                                    "candidate slot and must fall back to rescue."
                                ),
                            },
                        )
                    print(
                        "[baseline] Strict final-round tier-1 slot rule has no "
                        "candidate slot."
                    )
                    return None
                print(
                    f"[baseline] No tier-1 slots available in domain for tier-1 derby: "
                    f"{match.home_team} vs {match.away_team}. Returning None to trigger fallback."
                )
                return None
            model.Add(sum(tier1_slot_vars) == 1)

    for team_id, match_indices in matches_by_team.items():
        for slot_date, slot_indices in slots_by_date.items():
            vars_on_date = []
            for match_idx in match_indices:
                for slot_idx in slot_indices:
                    for candidate in venue_candidates_by_match[match_idx]:
                        venue = candidate.venue
                        var = x[match_idx].get((slot_idx, venue))
                        if var is not None:
                            vars_on_date.append(var)
            if len(vars_on_date) > 1:
                model.Add(sum(vars_on_date) <= 1)

    for (_venue, _slot_idx), vars_in_slot in venue_slot_vars.items():
        if len(vars_in_slot) > 1:
            model.Add(sum(vars_in_slot) <= 1)

    all_vars_by_date: Dict[date, List[cp_model.IntVar]] = defaultdict(list)
    for slot_date, slot_indices in slots_by_date.items():
        for match in matches:
            for slot_idx in slot_indices:
                for candidate in venue_candidates_by_match[match.match_idx]:
                    venue = candidate.venue
                    var = x[match.match_idx].get((slot_idx, venue))
                    if var is not None:
                        all_vars_by_date[slot_date].append(var)
    _add_daily_capacity_constraints(model, all_vars_by_date, final_round_date_vars)

    all_vars_by_slot: Dict[int, List[cp_model.IntVar]] = defaultdict(list)
    for slot_idx in range(n_slots):
        for match in matches:
            for candidate in venue_candidates_by_match[match.match_idx]:
                venue = candidate.venue
                var = x[match.match_idx].get((slot_idx, venue))
                if var is not None:
                    all_vars_by_slot[slot_idx].append(var)
    _add_slot_capacity_constraints(
        model,
        all_vars_by_slot,
        final_round_slot_vars,
    )

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
                    for candidate in venue_candidates_by_match[match_idx]:
                        venue = candidate.venue
                        var = x[match_idx].get((slot_idx, venue))
                        if var is not None:
                            vars_in_window.append(var)

            if len(vars_in_window) > 1:
                model.Add(sum(vars_in_window) <= 1)

    service_gap = MIN_STADIUM_SERVICE_GAP_DAYS
    venue_to_dates: Dict[str, List[date]] = defaultdict(list)
    for (v, d) in venue_date_vars.keys():
        venue_to_dates[v].append(d)

    if service_gap > 0:
        for venue, dates in venue_to_dates.items():
            ordered_dates = sorted(set(dates))
            for i, start_date in enumerate(ordered_dates):
                end_date = start_date + timedelta(days=service_gap)
                vars_in_window = []
                for v_date in ordered_dates[i:]:
                    if v_date > end_date:
                        break
                    vars_in_window.extend(venue_date_vars[(venue, v_date)])
                
                if len(vars_in_window) > 1:
                    overlap_var = model.NewBoolVar(f"overlap_{venue}_{start_date}")
                    model.Add(sum(vars_in_window) > 1).OnlyEnforceIf(overlap_var)
                    model.Add(sum(vars_in_window) <= 1).OnlyEnforceIf(overlap_var.Not())
                    
                    # Base maintenance penalty
                    penalty = W_STADIUM_MAINTENANCE_OVERLAP
                    objective_terms.append(overlap_var * penalty)

    _add_round_gap_constraints(model, matches_by_round, match_day, max_slot_day)

    print("[baseline] Hard constraints added.")

    if service_gap > 0:
        # Same-day venue reuse remains a strong soft discouragement when
        # stadium-service logic is active.
        for venue, dates in venue_to_dates.items():
            for d in dates:
                same_day_vars = venue_date_vars.get((venue, d), [])
                if len(same_day_vars) > 1:
                    sd_overlap = model.NewBoolVar(f"sd_overlap_{venue}_{d}")
                    model.Add(sum(same_day_vars) > 1).OnlyEnforceIf(sd_overlap)
                    model.Add(sum(same_day_vars) <= 1).OnlyEnforceIf(sd_overlap.Not())
                    objective_terms.append(sd_overlap * 50_000_000)

    for match in matches:
        home_tier = int(teams_dict.get(match.home_team, {}).get("Tier", 4))
        tier_weight = TIER_WEIGHTS.get(home_tier, 1)
        
        nominal = nominal_week[match.round_num]
        for (slot_idx, venue), var in x[match.match_idx].items():
            meta = assignment_meta[(match.match_idx, slot_idx, venue)]
            
            week_diff = abs(slot_weeks[slot_idx] - nominal)
            if week_diff > 0:
                objective_terms.append(var * (W_ROUND_ORDER * week_diff))

            travel_cost = int(meta["travel_km"] * W_TRAVEL)
            if travel_cost > 0:
                objective_terms.append(var * travel_cost)

            tier_diff = abs(match.match_tier - slot_tiers[slot_idx])
            if tier_diff > 0:
                objective_terms.append(var * (W_TIER_MISMATCH * tier_diff))

            if meta["is_alt"]:
                objective_terms.append(var * (ALT_STADIUM_RELIEF_PENALTY * tier_weight))
            elif meta["is_other"]:
                objective_terms.append(var * (OTHER_STADIUM_RELIEF_PENALTY * tier_weight))

            home_displacement_cost = int(
                meta["home_displacement_km"] * W_HOME_VENUE_DISPLACEMENT
            )
            if home_displacement_cost > 0:
                objective_terms.append(var * home_displacement_cost)

    for week_num in all_weeks:
        week_slots = slots_by_week.get(week_num, [])
        if not week_slots:
            continue

        load_vars = []
        for match in matches:
            for slot_idx in week_slots:
                for candidate in venue_candidates_by_match[match.match_idx]:
                    venue = candidate.venue
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

    # --- Evening preference: penalize earlier kickoff times ---
    if W_EVENING_PREFERENCE > 0:
        for match in matches:
            for (slot_idx, venue), var in x[match.match_idx].items():
                hour_penalty = max(0, 21 - slot_kickoff_hours[slot_idx])
                if hour_penalty > 0:
                    objective_terms.append(var * (W_EVENING_PREFERENCE * hour_penalty))

    # --- Slot spread: penalize >1 match in the same kickoff slot on same day ---
    if W_SLOT_SPREAD > 0:
        for slot_idx in range(n_slots):
            vars_in_slot = all_vars_by_slot.get(slot_idx, [])
            if len(vars_in_slot) > 1:
                collision = model.NewBoolVar(f"slot_collision_{slot_idx}")
                model.Add(sum(vars_in_slot) > 1).OnlyEnforceIf(collision)
                model.Add(sum(vars_in_slot) <= 1).OnlyEnforceIf(collision.Not())
                objective_terms.append(collision * W_SLOT_SPREAD)

    if objective_terms:
        model.Minimize(sum(objective_terms))

    print(f"[baseline] Model built in {time.time() - t0:.1f}s. Solving...")

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = BASELINE_SOLVER_TIME_LIMIT_S
    solver.parameters.num_workers = NUM_WORKERS
    solver.parameters.log_search_progress = True

    status = solver.Solve(model)
    status_name = solver.StatusName(status)
    wall_time = solver.WallTime()

    print(f"[baseline] Solver status: {status_name} ({wall_time:.1f}s)")

    if write_status:
        _write_baseline_status(
            status,
            status_name,
            wall_time,
            (
                solver.ObjectiveValue()
                if status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
                else None
            ),
            extra={
                "solver_mode": "strict_flexible_venue",
                "final_round_rescue_attempted": False,
                "final_round_rescue_used": False,
            },
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
