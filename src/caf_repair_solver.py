"""CAF repair: search the season for valid rescheduling options."""

from __future__ import annotations

import bisect
import csv
import json
import os
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Set, Tuple

from ortools.sat.python import cp_model

from src.constants import (
    ENFORCE_FINAL_ROUND_SINGLE_DAY,
    FINAL_ROUND_MAX_MATCHES_PER_DAY,
    FINAL_ROUND_MAX_MATCHES_PER_SLOT,
    FINAL_ROUND_SHARED_DATE_IN_FINAL_SCHEDULE,
    HARD_MAX_MATCHES_PER_WEEK,
    MAX_CONSECUTIVE_HOME,
    MAX_MATCHES_PER_DAY,
    MAX_MATCHES_PER_SLOT,
    MIN_REST_DAYS_CAF,
    MIN_REST_DAYS_LOCAL,
    MIN_STADIUM_SERVICE_GAP_DAYS,
    PHASES_DIR,
    REPAIR_SOLVER_TIME_LIMIT_S,
)
from src.baseline_solver import ScheduledMatch
from src.caf_audit import CAFViolation
from src.data_loader import LeagueData
from src.final_round import is_final_round
from src.tiers import compute_slot_tiers
from src.venue_rules import build_team_lookup, get_venue_options


@dataclass
class _OccupiedState:
    """Mutable state tracking what's already scheduled."""

    team_dates: Dict[str, List[date]]
    team_sequence: Dict[str, List[Tuple[date, str]]]
    venue_slots: Dict[str, Set[int]]
    venue_non_forced_dates: Dict[str, List[date]]
    week_load: Dict[int, int]
    date_load: Dict[date, int]
    slot_usage: Dict[int, int]


def _build_state(accepted: List[ScheduledMatch]) -> _OccupiedState:
    team_dates: Dict[str, List[date]] = defaultdict(list)
    team_sequence: Dict[str, List[Tuple[date, str]]] = defaultdict(list)
    venue_slots: Dict[str, Set[int]] = defaultdict(set)
    venue_non_forced_dates: Dict[str, List[date]] = defaultdict(list)
    week_load: Dict[int, int] = defaultdict(int)
    date_load: Dict[date, int] = defaultdict(int)
    slot_usage: Dict[int, int] = defaultdict(int)

    for sm in accepted:
        team_dates[sm.home_team].append(sm.date)
        team_dates[sm.away_team].append(sm.date)
        team_sequence[sm.home_team].append((sm.date, "H"))
        team_sequence[sm.away_team].append((sm.date, "A"))
        venue_slots[sm.venue].add(sm.slot_idx)
        if not sm.is_forced_venue:
            venue_non_forced_dates[sm.venue].append(sm.date)
        week_load[sm.week_num] += 1
        date_load[sm.date] += 1
        slot_usage[sm.slot_idx] += 1

    for team_id in team_dates:
        team_dates[team_id].sort()
    for team_id in team_sequence:
        team_sequence[team_id].sort(key=lambda item: item[0])
    for venue in venue_non_forced_dates:
        venue_non_forced_dates[venue].sort()

    return _OccupiedState(
        team_dates=dict(team_dates),
        team_sequence=dict(team_sequence),
        venue_slots=dict(venue_slots),
        venue_non_forced_dates=dict(venue_non_forced_dates),
        week_load=dict(week_load),
        date_load=dict(date_load),
        slot_usage=dict(slot_usage),
    )


def _check_rest_days(
    team_id: str,
    candidate_date: date,
    state: _OccupiedState,
    gap: int,
) -> bool:
    dates = state.team_dates.get(team_id, [])
    if not dates:
        return True

    idx = bisect.bisect_left(dates, candidate_date)
    if idx > 0:
        prev = dates[idx - 1]
        if (candidate_date - prev).days < gap + 1:
            return False
    if idx < len(dates):
        nxt = dates[idx]
        if nxt == candidate_date:
            return False
        if (nxt - candidate_date).days < gap + 1:
            return False
    return True


def _check_streak(
    team_id: str,
    candidate_date: date,
    direction: str,
    state: _OccupiedState,
) -> bool:
    seq = state.team_sequence.get(team_id, [])
    if not seq:
        return True

    insert_idx = bisect.bisect_left([item[0] for item in seq], candidate_date)
    window_start = max(0, insert_idx - MAX_CONSECUTIVE_HOME)
    window_end = min(len(seq), insert_idx + MAX_CONSECUTIVE_HOME)

    local = list(seq[window_start:insert_idx])
    local.append((candidate_date, direction))
    local.extend(seq[insert_idx:window_end])

    for i in range(len(local) - 2):
        if local[i][1] == local[i + 1][1] == local[i + 2][1]:
            return False
    return True


def _check_caf_buffer(
    team_id: str,
    candidate_date: date,
    caf_dates_by_team: Dict[str, List[date]],
    caf_teams: Set[str],
) -> bool:
    if team_id not in caf_teams:
        return True

    caf_dates = caf_dates_by_team.get(team_id, [])
    if not caf_dates:
        return True

    required_gap = MIN_REST_DAYS_CAF + 1
    idx = bisect.bisect_left(caf_dates, candidate_date)
    if idx > 0:
        prev_caf = caf_dates[idx - 1]
        if (candidate_date - prev_caf).days < required_gap:
            return False
    if idx < len(caf_dates):
        next_caf = caf_dates[idx]
        if next_caf == candidate_date:
            return False
        if (next_caf - candidate_date).days < required_gap:
            return False
    return True


def _check_stadium_service_gap(
    venue: str,
    candidate_date: date,
    state: _OccupiedState,
) -> bool:
    dates = state.venue_non_forced_dates.get(venue, [])
    if not dates:
        return True

    idx = bisect.bisect_left(dates, candidate_date)
    if idx > 0:
        prev = dates[idx - 1]
        if (candidate_date - prev).days <= MIN_STADIUM_SERVICE_GAP_DAYS:
            return False
    if idx < len(dates):
        nxt = dates[idx]
        if (nxt - candidate_date).days <= MIN_STADIUM_SERVICE_GAP_DAYS:
            return False
    return True


def _find_valid_slots(
    match: ScheduledMatch,
    data: LeagueData,
    state: _OccupiedState,
    slot_dates: List[date],
    slot_weeks: List[int],
    caf_teams: Set[str],
) -> List[int]:
    valid: List[int] = []

    for slot_idx, slot_date in enumerate(slot_dates):
        if slot_date is None:
            continue
        if slot_date < match.date:
            continue
        if state.date_load.get(slot_date, 0) >= MAX_MATCHES_PER_DAY:
            continue

        home_dates = state.team_dates.get(match.home_team, [])
        hi = bisect.bisect_left(home_dates, slot_date)
        if hi < len(home_dates) and home_dates[hi] == slot_date:
            continue

        away_dates = state.team_dates.get(match.away_team, [])
        ai = bisect.bisect_left(away_dates, slot_date)
        if ai < len(away_dates) and away_dates[ai] == slot_date:
            continue

        if not _check_rest_days(match.home_team, slot_date, state, MIN_REST_DAYS_LOCAL):
            continue
        if not _check_rest_days(match.away_team, slot_date, state, MIN_REST_DAYS_LOCAL):
            continue

        if slot_idx in state.venue_slots.get(match.venue, set()):
            continue

        if not _check_streak(match.home_team, slot_date, "H", state):
            continue
        if not _check_streak(match.away_team, slot_date, "A", state):
            continue

        if not _check_caf_buffer(match.home_team, slot_date, data.caf_dates_by_team, caf_teams):
            continue
        if not _check_caf_buffer(match.away_team, slot_date, data.caf_dates_by_team, caf_teams):
            continue

        if state.slot_usage.get(slot_idx, 0) >= MAX_MATCHES_PER_SLOT:
            continue
        if state.week_load.get(slot_weeks[slot_idx], 0) >= HARD_MAX_MATCHES_PER_WEEK:
            continue

        valid.append(slot_idx)

    return valid


def _find_valid_assignments(
    match: ScheduledMatch,
    data: LeagueData,
    state: _OccupiedState,
    slot_dates: List[date],
    slot_weeks: List[int],
    caf_teams: Set[str],
    teams_dict: Dict[str, dict],
) -> List[Tuple[int, str, bool, bool, int]]:
    valid: List[Tuple[int, str, bool, bool, int]] = []
    options = get_venue_options(match.home_team, match.away_team, teams_dict, data.sec_rules)

    for slot_idx, slot_date in enumerate(slot_dates):
        if slot_date is None:
            continue
        if slot_date < match.date:
            continue
        if state.date_load.get(slot_date, 0) >= MAX_MATCHES_PER_DAY:
            continue

        home_dates = state.team_dates.get(match.home_team, [])
        hi = bisect.bisect_left(home_dates, slot_date)
        if hi < len(home_dates) and home_dates[hi] == slot_date:
            continue

        away_dates = state.team_dates.get(match.away_team, [])
        ai = bisect.bisect_left(away_dates, slot_date)
        if ai < len(away_dates) and away_dates[ai] == slot_date:
            continue

        if not _check_rest_days(match.home_team, slot_date, state, MIN_REST_DAYS_LOCAL):
            continue
        if not _check_rest_days(match.away_team, slot_date, state, MIN_REST_DAYS_LOCAL):
            continue

        if not _check_streak(match.home_team, slot_date, "H", state):
            continue
        if not _check_streak(match.away_team, slot_date, "A", state):
            continue

        if not _check_caf_buffer(match.home_team, slot_date, data.caf_dates_by_team, caf_teams):
            continue
        if not _check_caf_buffer(match.away_team, slot_date, data.caf_dates_by_team, caf_teams):
            continue

        if state.slot_usage.get(slot_idx, 0) >= MAX_MATCHES_PER_SLOT:
            continue
        if state.week_load.get(slot_weeks[slot_idx], 0) >= HARD_MAX_MATCHES_PER_WEEK:
            continue

        for venue in options.allowed_venues:
            is_forced = options.is_forced_only
            is_alt = (not is_forced) and venue != options.primary_venue

            if slot_idx in state.venue_slots.get(venue, set()):
                continue
            
            # Maintenance check is now soft in repair too
            maintenance_violation = 0
            if (not is_forced) and (not _check_stadium_service_gap(venue, slot_date, state)):
                maintenance_violation = 1

            valid.append((slot_idx, venue, is_forced, is_alt, maintenance_violation))

    return valid


def _update_state(
    state: _OccupiedState,
    match: ScheduledMatch,
    slot_idx: int,
    slot_date: date,
    slot_week: int,
) -> None:
    for team_id in (match.home_team, match.away_team):
        dates = state.team_dates.setdefault(team_id, [])
        bisect.insort(dates, slot_date)

    seq_home = state.team_sequence.setdefault(match.home_team, [])
    bisect.insort(seq_home, (slot_date, "H"))
    seq_away = state.team_sequence.setdefault(match.away_team, [])
    bisect.insort(seq_away, (slot_date, "A"))

    state.venue_slots.setdefault(match.venue, set()).add(slot_idx)
    if not match.is_forced_venue:
        venue_dates = state.venue_non_forced_dates.setdefault(match.venue, [])
        bisect.insort(venue_dates, slot_date)
    state.week_load[slot_week] = state.week_load.get(slot_week, 0) + 1
    state.date_load[slot_date] = state.date_load.get(slot_date, 0) + 1
    state.slot_usage[slot_idx] = state.slot_usage.get(slot_idx, 0) + 1


def _collect_caf_teams(data: LeagueData) -> Set[str]:
    return {
        row["Team_ID"]
        for _, row in data.teams.iterrows()
        if row["Cont_Flag"] in ("CL", "CC")
    }


def _match_can_play_on_date(
    match: ScheduledMatch,
    candidate_date: date,
    data: LeagueData,
    state: _OccupiedState,
    caf_teams: Set[str],
) -> bool:
    if candidate_date < match.date:
        return False

    home_dates = state.team_dates.get(match.home_team, [])
    hi = bisect.bisect_left(home_dates, candidate_date)
    if hi < len(home_dates) and home_dates[hi] == candidate_date:
        return False

    away_dates = state.team_dates.get(match.away_team, [])
    ai = bisect.bisect_left(away_dates, candidate_date)
    if ai < len(away_dates) and away_dates[ai] == candidate_date:
        return False

    if not _check_rest_days(match.home_team, candidate_date, state, MIN_REST_DAYS_LOCAL):
        return False
    if not _check_rest_days(match.away_team, candidate_date, state, MIN_REST_DAYS_LOCAL):
        return False

    if not _check_streak(match.home_team, candidate_date, "H", state):
        return False
    if not _check_streak(match.away_team, candidate_date, "A", state):
        return False

    if not _check_caf_buffer(match.home_team, candidate_date, data.caf_dates_by_team, caf_teams):
        return False
    if not _check_caf_buffer(match.away_team, candidate_date, data.caf_dates_by_team, caf_teams):
        return False

    return True


def _promote_final_round_batch(
    accepted: List[ScheduledMatch],
    queued_matches: Dict[int, ScheduledMatch],
) -> List[ScheduledMatch]:
    if not (
        ENFORCE_FINAL_ROUND_SINGLE_DAY
        and FINAL_ROUND_SHARED_DATE_IN_FINAL_SCHEDULE
        and any(is_final_round(match.round_num) for match in queued_matches.values())
    ):
        return []

    batch_by_match_idx: Dict[int, ScheduledMatch] = {
        match.match_idx: match
        for match in queued_matches.values()
        if is_final_round(match.round_num)
    }
    for match in accepted:
        if is_final_round(match.round_num):
            batch_by_match_idx[match.match_idx] = match

    accepted[:] = [match for match in accepted if not is_final_round(match.round_num)]
    for match_idx in list(queued_matches):
        if is_final_round(queued_matches[match_idx].round_num):
            queued_matches.pop(match_idx)

    return sorted(batch_by_match_idx.values(), key=lambda match: match.match_idx)


def _candidate_dates_for_final_round(
    batch_matches: List[ScheduledMatch],
    slot_dates: List[date],
) -> List[date]:
    if not batch_matches:
        return []

    first_date = min(match.date for match in batch_matches)
    unique_dates = {
        slot_date
        for slot_date in slot_dates
        if slot_date is not None and slot_date >= first_date
    }
    return sorted(
        unique_dates,
        key=lambda candidate_date: (
            abs((candidate_date - first_date).days),
            candidate_date,
        ),
    )


def _repair_final_round_batch_legacy(
    batch_matches: List[ScheduledMatch],
    data: LeagueData,
    state: _OccupiedState,
    slot_dates: List[date],
    slot_weeks: List[int],
    slot_tiers_list: List[int],
    slot_day_ids: List[str],
    slot_day_names: List[str],
    slot_datetimes: List[object],
    caf_teams: Set[str],
) -> Tuple[List[ScheduledMatch], List[ScheduledMatch]]:
    if not batch_matches:
        return [], []

    print(
        f"[caf_repair] Final-round batch repair: {len(batch_matches)} matches "
        "must share one date."
    )

    for candidate_date in _candidate_dates_for_final_round(batch_matches, slot_dates):
        slot_indices = [
            slot_idx
            for slot_idx, slot_date in enumerate(slot_dates)
            if slot_date == candidate_date
        ]
        if not slot_indices:
            continue

        week_nums = {slot_weeks[slot_idx] for slot_idx in slot_indices}
        if len(week_nums) != 1:
            continue
        week_num = next(iter(week_nums))

        if (
            state.date_load.get(candidate_date, 0) + len(batch_matches)
            > FINAL_ROUND_MAX_MATCHES_PER_DAY
        ):
            continue
        if (
            state.week_load.get(week_num, 0) + len(batch_matches)
            > HARD_MAX_MATCHES_PER_WEEK
        ):
            continue

        if any(
            not _match_can_play_on_date(match, candidate_date, data, state, caf_teams)
            for match in batch_matches
        ):
            continue

        match_slot_options: Dict[int, List[int]] = {}
        for match in batch_matches:
            feasible_slots = [
                slot_idx
                for slot_idx in slot_indices
                if slot_idx not in state.venue_slots.get(match.venue, set())
                and state.slot_usage.get(slot_idx, 0) < FINAL_ROUND_MAX_MATCHES_PER_SLOT
            ]
            if not feasible_slots:
                break
            match_slot_options[match.match_idx] = feasible_slots

        if len(match_slot_options) != len(batch_matches):
            continue

        model = cp_model.CpModel()
        y: Dict[Tuple[int, int], cp_model.IntVar] = {}
        for match in batch_matches:
            for slot_idx in match_slot_options[match.match_idx]:
                y[(match.match_idx, slot_idx)] = model.NewBoolVar(
                    f"fr_{match.match_idx}_{slot_idx}"
                )

        for match in batch_matches:
            model.Add(
                sum(
                    y[(match.match_idx, slot_idx)]
                    for slot_idx in match_slot_options[match.match_idx]
                ) == 1
            )

        for slot_idx in slot_indices:
            vars_in_slot = [
                y[(match.match_idx, slot_idx)]
                for match in batch_matches
                if (match.match_idx, slot_idx) in y
            ]
            if vars_in_slot:
                model.Add(
                    state.slot_usage.get(slot_idx, 0) + sum(vars_in_slot)
                    <= FINAL_ROUND_MAX_MATCHES_PER_SLOT
                )

        for slot_idx in slot_indices:
            venue_groups: Dict[str, List[cp_model.IntVar]] = defaultdict(list)
            for match in batch_matches:
                var = y.get((match.match_idx, slot_idx))
                if var is not None:
                    venue_groups[match.venue].append(var)
            for vars_in_venue_slot in venue_groups.values():
                if len(vars_in_venue_slot) > 1:
                    model.Add(sum(vars_in_venue_slot) <= 1)

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = REPAIR_SOLVER_TIME_LIMIT_S
        solver.parameters.num_workers = 4
        status = solver.Solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            continue

        repaired: List[ScheduledMatch] = []
        for match in batch_matches:
            chosen_slot = next(
                slot_idx
                for slot_idx in match_slot_options[match.match_idx]
                if solver.Value(y[(match.match_idx, slot_idx)]) == 1
            )
            repaired.append(
                ScheduledMatch(
                    match_idx=match.match_idx,
                    round_num=match.round_num,
                    home_team=match.home_team,
                    away_team=match.away_team,
                    venue=match.venue,
                    match_tier=match.match_tier,
                    slot_idx=chosen_slot,
                    day_id=slot_day_ids[chosen_slot],
                    date=slot_dates[chosen_slot],
                    date_time=slot_datetimes[chosen_slot],
                    week_num=slot_weeks[chosen_slot],
                    day_name=slot_day_names[chosen_slot],
                    slot_tier=slot_tiers_list[chosen_slot],
                    travel_km=match.travel_km,
                    is_forced_venue=match.is_forced_venue,
                )
            )

        print(
            "[caf_repair] Final-round batch repaired on "
            f"{candidate_date}."
        )
        return repaired, []

    print("[caf_repair] Final-round batch has no common feasible repair date.")
    return [], sorted(batch_matches, key=lambda match: match.match_idx)


def _repair_final_round_batch_with_stadium_gap(
    batch_matches: List[ScheduledMatch],
    data: LeagueData,
    state: _OccupiedState,
    slot_dates: List[date],
    slot_weeks: List[int],
    slot_tiers_list: List[int],
    slot_day_ids: List[str],
    slot_day_names: List[str],
    slot_datetimes: List[object],
    caf_teams: Set[str],
    teams_dict: Dict[str, dict],
) -> Tuple[List[ScheduledMatch], List[ScheduledMatch]]:
    if not batch_matches:
        return [], []

    print(
        f"[caf_repair] Final-round batch repair: {len(batch_matches)} matches "
        "must share one date."
    )

    for candidate_date in _candidate_dates_for_final_round(batch_matches, slot_dates):
        slot_indices = [
            slot_idx
            for slot_idx, slot_date in enumerate(slot_dates)
            if slot_date == candidate_date
        ]
        if not slot_indices:
            continue

        week_nums = {slot_weeks[slot_idx] for slot_idx in slot_indices}
        if len(week_nums) != 1:
            continue
        week_num = next(iter(week_nums))

        if (
            state.date_load.get(candidate_date, 0) + len(batch_matches)
            > FINAL_ROUND_MAX_MATCHES_PER_DAY
        ):
            continue
        if (
            state.week_load.get(week_num, 0) + len(batch_matches)
            > HARD_MAX_MATCHES_PER_WEEK
        ):
            continue

        if any(
            not _match_can_play_on_date(match, candidate_date, data, state, caf_teams)
            for match in batch_matches
        ):
            continue

        match_assignment_options: Dict[int, List[Tuple[int, str, bool, bool, int]]] = {}
        for match in batch_matches:
            options = get_venue_options(
                match.home_team,
                match.away_team,
                teams_dict,
                data.sec_rules,
            )
            feasible_assignments: List[Tuple[int, str, bool, bool, int]] = []
            for slot_idx in slot_indices:
                if state.slot_usage.get(slot_idx, 0) >= FINAL_ROUND_MAX_MATCHES_PER_SLOT:
                    continue
                for venue in options.allowed_venues:
                    if slot_idx in state.venue_slots.get(venue, set()):
                        continue
                    is_forced = options.is_forced_only
                    is_alt = (not is_forced) and venue != options.primary_venue
                    maintenance_violation = 0
                    if (
                        not is_forced
                        and not _check_stadium_service_gap(venue, candidate_date, state)
                    ):
                        maintenance_violation = 1
                    feasible_assignments.append(
                        (slot_idx, venue, is_forced, is_alt, maintenance_violation)
                    )

            if not feasible_assignments:
                break
            match_assignment_options[match.match_idx] = feasible_assignments

        if len(match_assignment_options) != len(batch_matches):
            continue

        model = cp_model.CpModel()
        y: Dict[Tuple[int, int, str], cp_model.IntVar] = {}
        objective_terms = []
        for match in batch_matches:
            for slot_idx, venue, _is_forced, is_alt, maintenance_violation in (
                match_assignment_options[match.match_idx]
            ):
                key = (match.match_idx, slot_idx, venue)
                y[key] = model.NewBoolVar(f"fr_{match.match_idx}_{slot_idx}_{venue}")
                if maintenance_violation:
                    objective_terms.append(y[key] * 1_000)
                if is_alt:
                    objective_terms.append(y[key] * 10)

        for match in batch_matches:
            model.Add(
                sum(
                    y[(match.match_idx, slot_idx, venue)]
                    for slot_idx, venue, _is_forced, _is_alt, _maintenance in (
                        match_assignment_options[match.match_idx]
                    )
                ) == 1
            )

        for slot_idx in slot_indices:
            vars_in_slot = [
                y[(match.match_idx, candidate_slot, venue)]
                for match in batch_matches
                for candidate_slot, venue, _is_forced, _is_alt, _maintenance in (
                    match_assignment_options[match.match_idx]
                )
                if candidate_slot == slot_idx
            ]
            if vars_in_slot:
                model.Add(
                    state.slot_usage.get(slot_idx, 0) + sum(vars_in_slot)
                    <= FINAL_ROUND_MAX_MATCHES_PER_SLOT
                )

        venue_slot_groups: Dict[Tuple[str, int], List[cp_model.IntVar]] = defaultdict(list)
        for match in batch_matches:
            for slot_idx, venue, _is_forced, _is_alt, _maintenance in (
                match_assignment_options[match.match_idx]
            ):
                venue_slot_groups[(venue, slot_idx)].append(
                    y[(match.match_idx, slot_idx, venue)]
                )
        for vars_in_venue_slot in venue_slot_groups.values():
            if len(vars_in_venue_slot) > 1:
                model.Add(sum(vars_in_venue_slot) <= 1)

        if objective_terms:
            model.Minimize(sum(objective_terms))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = REPAIR_SOLVER_TIME_LIMIT_S
        solver.parameters.num_workers = 4
        status = solver.Solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            continue

        repaired: List[ScheduledMatch] = []
        for match in batch_matches:
            for slot_idx, venue, is_forced, _is_alt, _maintenance in (
                match_assignment_options[match.match_idx]
            ):
                if solver.Value(y[(match.match_idx, slot_idx, venue)]) != 1:
                    continue
                away_home_stadium = teams_dict.get(match.away_team, {}).get(
                    "Home_Stadium_ID",
                    "",
                )
                travel = data.dist_matrix.get(away_home_stadium, {}).get(venue, 0.0)
                repaired.append(
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
                        slot_tier=slot_tiers_list[slot_idx],
                        travel_km=travel,
                        is_forced_venue=is_forced,
                    )
                )
                break

        print(
            "[caf_repair] Final-round batch repaired on "
            f"{candidate_date}."
        )
        return repaired, []

    print("[caf_repair] Final-round batch has no common feasible repair date.")
    return [], sorted(batch_matches, key=lambda match: match.match_idx)


def caf_repair(
    accepted: List[ScheduledMatch],
    violations: List[CAFViolation],
    data: LeagueData,
) -> Tuple[List[ScheduledMatch], List[ScheduledMatch]]:
    if MIN_STADIUM_SERVICE_GAP_DAYS <= 0:
        return _caf_repair_legacy(accepted, violations, data)
    return _caf_repair_with_stadium_gap(accepted, violations, data)


def _caf_repair_legacy(
    accepted: List[ScheduledMatch],
    violations: List[CAFViolation],
    data: LeagueData,
) -> Tuple[List[ScheduledMatch], List[ScheduledMatch]]:
    print("[caf_repair] Starting repair phase...")
    t0 = time.time()

    slots = data.usable_slots
    slot_dates: List[date] = list(slots["_date"])
    slot_weeks: List[int] = list(slots["Week_Num"].fillna(0).astype(int))
    slot_tiers_list: List[int] = list(compute_slot_tiers(slots))
    slot_day_ids: List[str] = list(slots["Day_ID"].fillna(""))
    slot_day_names: List[str] = list(slots["Day_name"].fillna(""))
    slot_datetimes = list(
        slots["Date time"] if "Date time" in slots.columns else [None] * len(slots)
    )

    caf_teams = _collect_caf_teams(data)

    queued_matches: Dict[int, ScheduledMatch] = {}
    for violation in violations:
        queued_matches[violation.match.match_idx] = violation.match

    final_round_batch = _promote_final_round_batch(accepted, queued_matches)
    state = _build_state(accepted)

    queued_list = list(queued_matches.values()) + final_round_batch
    print(f"[caf_repair] {len(queued_list)} unique matches to repair.")

    match_valid_slots: Dict[int, List[Tuple[int, int]]] = {}
    for match in queued_list:
        valid = _find_valid_slots(match, data, state, slot_dates, slot_weeks, caf_teams)
        ranked = sorted(valid, key=lambda slot_idx: abs((slot_dates[slot_idx] - match.date).days))
        match_valid_slots[match.match_idx] = [
            (slot_idx, abs((slot_dates[slot_idx] - match.date).days))
            for slot_idx in ranked
        ]

    _write_repair_slot_counts(queued_list, match_valid_slots)

    repaired: List[ScheduledMatch] = []
    unresolved: List[ScheduledMatch] = []

    if final_round_batch:
        repaired_batch, unresolved_batch = _repair_final_round_batch_legacy(
            final_round_batch,
            data,
            state,
            slot_dates,
            slot_weeks,
            slot_tiers_list,
            slot_day_ids,
            slot_day_names,
            slot_datetimes,
            caf_teams,
        )
        repaired.extend(repaired_batch)
        unresolved.extend(unresolved_batch)
        for repaired_match in repaired_batch:
            _update_state(
                state,
                repaired_match,
                repaired_match.slot_idx,
                repaired_match.date,
                repaired_match.week_num,
            )

    queued_sorted = sorted(
        queued_list,
        key=lambda match: (
            len(match_valid_slots.get(match.match_idx, [])),
            match.round_num,
            match.match_idx,
        ),
    )
    remaining = [match for match in queued_sorted if match.match_idx in queued_matches]

    for pass_num in range(1, 4):
        print(
            f"[caf_repair] Repair pass {pass_num}: {len(remaining)} matches pending."
        )
        if not remaining:
            break

        placed_this_pass = []
        still_unresolved = []

        for match in remaining:
            valid = _find_valid_slots(match, data, state, slot_dates, slot_weeks, caf_teams)
            if not valid:
                still_unresolved.append(match)
                continue

            ranked = sorted(valid, key=lambda slot_idx: abs((slot_dates[slot_idx] - match.date).days))
            best_slot = ranked[0]
            travel = match.travel_km

            repaired_match = ScheduledMatch(
                match_idx=match.match_idx,
                round_num=match.round_num,
                home_team=match.home_team,
                away_team=match.away_team,
                venue=match.venue,
                match_tier=match.match_tier,
                slot_idx=best_slot,
                day_id=slot_day_ids[best_slot],
                date=slot_dates[best_slot],
                date_time=slot_datetimes[best_slot],
                week_num=slot_weeks[best_slot],
                day_name=slot_day_names[best_slot],
                slot_tier=slot_tiers_list[best_slot],
                travel_km=travel,
                is_forced_venue=match.is_forced_venue,
            )
            repaired.append(repaired_match)
            placed_this_pass.append(match.match_idx)

            _update_state(
                state,
                repaired_match,
                best_slot,
                slot_dates[best_slot],
                slot_weeks[best_slot],
            )

            displacement = abs((slot_dates[best_slot] - match.date).days)
            print(
                f"  [repair pass {pass_num}] REPAIRED: match {match.match_idx} "
                f"({match.home_team} vs {match.away_team}) moved from {match.date} "
                f"to {slot_dates[best_slot]} (+{displacement} days)"
            )

        remaining = still_unresolved
        print(
            f"  [repair pass {pass_num}] Placed {len(placed_this_pass)}, "
            f"{len(remaining)} still unresolved."
        )

        if not placed_this_pass:
            break

    for match in remaining:
        unresolved.append(match)
        print(
            f"  [repair] UNRESOLVED: match {match.match_idx} "
            f"({match.home_team} vs {match.away_team}, R{match.round_num})"
        )

    elapsed = time.time() - t0
    print(
        f"[caf_repair] Done in {elapsed:.1f}s: "
        f"{len(repaired)} repaired, {len(unresolved)} unresolved."
    )

    _write_repair_status(repaired, unresolved, elapsed)
    return repaired, unresolved


def _caf_repair_with_stadium_gap(
    accepted: List[ScheduledMatch],
    violations: List[CAFViolation],
    data: LeagueData,
) -> Tuple[List[ScheduledMatch], List[ScheduledMatch]]:
    print(
        "[caf_repair] Starting repair phase with stadium service gap "
        f"({MIN_STADIUM_SERVICE_GAP_DAYS} days)..."
    )
    t0 = time.time()

    slots = data.usable_slots
    slot_dates: List[date] = list(slots["_date"])
    slot_weeks: List[int] = list(slots["Week_Num"].fillna(0).astype(int))
    slot_tiers_list: List[int] = list(compute_slot_tiers(slots))
    slot_day_ids: List[str] = list(slots["Day_ID"].fillna(""))
    slot_day_names: List[str] = list(slots["Day_name"].fillna(""))
    slot_datetimes = list(
        slots["Date time"] if "Date time" in slots.columns else [None] * len(slots)
    )

    caf_teams = _collect_caf_teams(data)
    teams_dict = build_team_lookup(data)

    queued_matches: Dict[int, ScheduledMatch] = {}
    for violation in violations:
        queued_matches[violation.match.match_idx] = violation.match

    final_round_batch = _promote_final_round_batch(accepted, queued_matches)
    state = _build_state(accepted)

    queued_list = list(queued_matches.values()) + final_round_batch
    print(f"[caf_repair] {len(queued_list)} unique matches to repair.")

    match_valid_slots: Dict[int, List[Tuple[int, int]]] = {}
    for match in queued_list:
        valid = _find_valid_assignments(
            match,
            data,
            state,
            slot_dates,
            slot_weeks,
            caf_teams,
            teams_dict,
        )
        ranked = sorted(
            valid,
            key=lambda item: (
                abs((slot_dates[item[0]] - match.date).days),
                item[4],  # maintenance_violation
                1 if item[3] else 0,  # is_alt
            ),
        )
        match_valid_slots[match.match_idx] = [
            (slot_idx, abs((slot_dates[slot_idx] - match.date).days))
            for slot_idx, _venue, _is_forced, _is_alt, _maintenance in ranked
        ]

    _write_repair_slot_counts(queued_list, match_valid_slots)

    repaired: List[ScheduledMatch] = []
    unresolved: List[ScheduledMatch] = []

    if final_round_batch:
        repaired_batch, unresolved_batch = _repair_final_round_batch_with_stadium_gap(
            final_round_batch,
            data,
            state,
            slot_dates,
            slot_weeks,
            slot_tiers_list,
            slot_day_ids,
            slot_day_names,
            slot_datetimes,
            caf_teams,
            teams_dict,
        )
        repaired.extend(repaired_batch)
        unresolved.extend(unresolved_batch)
        for repaired_match in repaired_batch:
            _update_state(
                state,
                repaired_match,
                repaired_match.slot_idx,
                repaired_match.date,
                repaired_match.week_num,
            )

    queued_sorted = sorted(
        queued_list,
        key=lambda match: (
            len(match_valid_slots.get(match.match_idx, [])),
            match.round_num,
            match.match_idx,
        ),
    )
    remaining = [match for match in queued_sorted if match.match_idx in queued_matches]

    for pass_num in range(1, 4):
        print(
            f"[caf_repair] Repair pass {pass_num}: {len(remaining)} matches pending."
        )
        if not remaining:
            break

        placed_this_pass = []
        still_unresolved = []

        for match in remaining:
            valid = _find_valid_assignments(
                match,
                data,
                state,
                slot_dates,
                slot_weeks,
                caf_teams,
                teams_dict,
            )
            if not valid:
                still_unresolved.append(match)
                continue

            ranked = sorted(
                valid,
                key=lambda item: (
                    abs((slot_dates[item[0]] - match.date).days),
                    item[4],
                    1 if item[3] else 0,
                ),
            )
            best_slot, best_venue, is_forced, _is_alt, _maintenance = ranked[0]
            away_home_stadium = teams_dict.get(match.away_team, {}).get("Home_Stadium_ID", "")
            travel = data.dist_matrix.get(away_home_stadium, {}).get(best_venue, 0.0)

            repaired_match = ScheduledMatch(
                match_idx=match.match_idx,
                round_num=match.round_num,
                home_team=match.home_team,
                away_team=match.away_team,
                venue=best_venue,
                match_tier=match.match_tier,
                slot_idx=best_slot,
                day_id=slot_day_ids[best_slot],
                date=slot_dates[best_slot],
                date_time=slot_datetimes[best_slot],
                week_num=slot_weeks[best_slot],
                day_name=slot_day_names[best_slot],
                slot_tier=slot_tiers_list[best_slot],
                travel_km=travel,
                is_forced_venue=is_forced,
            )
            repaired.append(repaired_match)
            placed_this_pass.append(match.match_idx)

            _update_state(
                state,
                repaired_match,
                best_slot,
                slot_dates[best_slot],
                slot_weeks[best_slot],
            )

            displacement = abs((slot_dates[best_slot] - match.date).days)
            print(
                f"  [repair pass {pass_num}] REPAIRED: match {match.match_idx} "
                f"({match.home_team} vs {match.away_team}) moved from {match.date} "
                f"to {slot_dates[best_slot]} at {best_venue} (+{displacement} days)"
            )

        remaining = still_unresolved
        print(
            f"  [repair pass {pass_num}] Placed {len(placed_this_pass)}, "
            f"{len(remaining)} still unresolved."
        )

        if not placed_this_pass:
            break

    for match in remaining:
        unresolved.append(match)
        print(
            f"  [repair] UNRESOLVED: match {match.match_idx} "
            f"({match.home_team} vs {match.away_team}, R{match.round_num})"
        )

    elapsed = time.time() - t0
    print(
        f"[caf_repair] Done in {elapsed:.1f}s: "
        f"{len(repaired)} repaired, {len(unresolved)} unresolved."
    )

    _write_repair_status(repaired, unresolved, elapsed)
    return repaired, unresolved


def _write_repair_slot_counts(
    queued: List[ScheduledMatch],
    valid_slots: Dict[int, List[Tuple[int, int]]],
) -> None:
    os.makedirs(PHASES_DIR, exist_ok=True)
    path = os.path.join(PHASES_DIR, "08_repair_feasible_slot_counts.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["match_idx", "round", "home", "away", "original_date", "feasible_slot_count"]
        )
        for match in queued:
            writer.writerow(
                [
                    match.match_idx,
                    match.round_num,
                    match.home_team,
                    match.away_team,
                    match.date,
                    len(valid_slots.get(match.match_idx, [])),
                ]
            )


def _write_repair_status(
    repaired: List[ScheduledMatch],
    unresolved: List[ScheduledMatch],
    elapsed: float,
    skipped: bool = False,
) -> None:
    os.makedirs(PHASES_DIR, exist_ok=True)
    path = os.path.join(PHASES_DIR, "09_repair_solver_status.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "skipped": skipped,
                "repaired_count": len(repaired),
                "unresolved_count": len(unresolved),
                "elapsed_s": round(elapsed, 2),
                "stadium_service_gap_days": MIN_STADIUM_SERVICE_GAP_DAYS,
            },
            f,
            indent=2,
        )


def write_repair_skipped_status(reason: str) -> None:
    os.makedirs(PHASES_DIR, exist_ok=True)
    path = os.path.join(PHASES_DIR, "09_repair_solver_status.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "skipped": True,
                "reason": reason,
                "repaired_count": 0,
                "unresolved_count": 0,
                "elapsed_s": 0.0,
                "stadium_service_gap_days": MIN_STADIUM_SERVICE_GAP_DAYS,
            },
            f,
            indent=2,
        )
