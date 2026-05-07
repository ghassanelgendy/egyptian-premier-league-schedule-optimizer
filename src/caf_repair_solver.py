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

from src.constants import (
    HARD_MAX_MATCHES_PER_WEEK,
    MAX_CONSECUTIVE_HOME,
    MAX_MATCHES_PER_DAY,
    MIN_REST_DAYS_CAF,
    MIN_REST_DAYS_LOCAL,
    MIN_STADIUM_SERVICE_GAP_DAYS,
    PHASES_DIR,
)
from src.baseline_solver import ScheduledMatch
from src.caf_audit import CAFViolation
from src.data_loader import LeagueData
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

        if state.slot_usage.get(slot_idx, 0) > 0:
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
) -> List[Tuple[int, str, bool, bool]]:
    valid: List[Tuple[int, str, bool, bool]] = []
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

        if state.slot_usage.get(slot_idx, 0) > 0:
            continue
        if state.week_load.get(slot_weeks[slot_idx], 0) >= HARD_MAX_MATCHES_PER_WEEK:
            continue

        for venue in options.allowed_venues:
            is_forced = options.is_forced_only
            is_alt = (not is_forced) and venue != options.primary_venue

            if slot_idx in state.venue_slots.get(venue, set()):
                continue
            if (not is_forced) and (not _check_stadium_service_gap(venue, slot_date, state)):
                continue

            valid.append((slot_idx, venue, is_forced, is_alt))

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

    caf_teams = {
        row["Team_ID"]
        for _, row in data.teams.iterrows()
        if row["Cont_Flag"] in ("CL", "CC")
    }

    state = _build_state(accepted)

    queued_matches: Dict[int, ScheduledMatch] = {}
    for violation in violations:
        queued_matches[violation.match.match_idx] = violation.match

    queued_list = list(queued_matches.values())
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

    queued_sorted = sorted(
        queued_list,
        key=lambda match: (
            len(match_valid_slots.get(match.match_idx, [])),
            match.round_num,
            match.match_idx,
        ),
    )

    repaired: List[ScheduledMatch] = []
    unresolved: List[ScheduledMatch] = []
    remaining = queued_sorted

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

    caf_teams = {
        row["Team_ID"]
        for _, row in data.teams.iterrows()
        if row["Cont_Flag"] in ("CL", "CC")
    }
    teams_dict = build_team_lookup(data)

    state = _build_state(accepted)

    queued_matches: Dict[int, ScheduledMatch] = {}
    for violation in violations:
        queued_matches[violation.match.match_idx] = violation.match

    queued_list = list(queued_matches.values())
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
                1 if item[3] else 0,
            ),
        )
        match_valid_slots[match.match_idx] = [
            (slot_idx, abs((slot_dates[slot_idx] - match.date).days))
            for slot_idx, _venue, _is_forced, _is_alt in ranked
        ]

    _write_repair_slot_counts(queued_list, match_valid_slots)

    queued_sorted = sorted(
        queued_list,
        key=lambda match: (
            len(match_valid_slots.get(match.match_idx, [])),
            match.round_num,
            match.match_idx,
        ),
    )

    repaired: List[ScheduledMatch] = []
    unresolved: List[ScheduledMatch] = []
    remaining = queued_sorted

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
                    1 if item[3] else 0,
                ),
            )
            best_slot, best_venue, is_forced, _is_alt = ranked[0]
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
