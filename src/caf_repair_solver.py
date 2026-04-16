"""CAF repair: search entire season for nearest valid slot per postponed match."""

from __future__ import annotations

import bisect
import csv
import json
import os
import time
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional, Set, Tuple

from ortools.sat.python import cp_model

from src.constants import (
    HARD_MAX_MATCHES_PER_WEEK,
    MAX_CONSECUTIVE_AWAY,
    MAX_CONSECUTIVE_HOME,
    MAX_MATCHES_PER_DAY,
    MIN_REST_DAYS_CAF,
    MIN_REST_DAYS_LOCAL,
    PHASES_DIR,
    REPAIR_SOLVER_TIME_LIMIT_S,
    SOFT_MAX_MATCHES_PER_WEEK,
    W_TIER_MISMATCH,
)
from src.baseline_solver import ScheduledMatch
from src.caf_audit import CAFViolation
from src.data_loader import LeagueData
from src.tiers import compute_slot_tiers


@dataclass
class _OccupiedState:
    """Mutable state tracking what's already scheduled."""
    team_dates: Dict[str, List[date]]
    team_sequence: Dict[str, List[Tuple[date, str]]]  # (date, 'H'/'A')
    venue_slots: Dict[str, Set[int]]
    week_load: Dict[int, int]
    date_load: Dict[date, int]
    slot_usage: Dict[int, int]    # matches assigned per slot index
    assigned_dates: Set[date]     # dates with at least one match


def _build_state(accepted: List[ScheduledMatch]) -> _OccupiedState:
    team_dates: Dict[str, List[date]] = defaultdict(list)
    team_sequence: Dict[str, List[Tuple[date, str]]] = defaultdict(list)
    venue_slots: Dict[str, Set[int]] = defaultdict(set)
    week_load: Dict[int, int] = defaultdict(int)
    date_load: Dict[date, int] = defaultdict(int)
    slot_usage: Dict[int, int] = defaultdict(int)

    for sm in accepted:
        team_dates[sm.home_team].append(sm.date)
        team_dates[sm.away_team].append(sm.date)
        team_sequence[sm.home_team].append((sm.date, "H"))
        team_sequence[sm.away_team].append((sm.date, "A"))
        venue_slots[sm.venue].add(sm.slot_idx)
        week_load[sm.week_num] += 1
        date_load[sm.date] += 1
        slot_usage[sm.slot_idx] += 1

    for tid in team_dates:
        team_dates[tid].sort()
    for tid in team_sequence:
        team_sequence[tid].sort(key=lambda x: x[0])

    assigned_dates = set()
    for sm in accepted:
        assigned_dates.add(sm.date)

    return _OccupiedState(
        team_dates=dict(team_dates),
        team_sequence=dict(team_sequence),
        venue_slots=dict(venue_slots),
        week_load=dict(week_load),
        date_load=dict(date_load),
        slot_usage=dict(slot_usage),
        assigned_dates=assigned_dates,
    )


def _check_rest_days(
    team_id: str, candidate_date: date, state: _OccupiedState, gap: int
) -> bool:
    """Check that candidate_date is >= (gap+1) calendar days from all team matches."""
    dates = state.team_dates.get(team_id, [])
    if not dates:
        return True
    idx = bisect.bisect_left(dates, candidate_date)
    # Check neighbor before
    if idx > 0:
        prev = dates[idx - 1]
        if (candidate_date - prev).days < gap + 1:
            return False
    # Check neighbor after
    if idx < len(dates):
        nxt = dates[idx]
        if nxt == candidate_date:
            return False
        if (nxt - candidate_date).days < gap + 1:
            return False
    return True


def _check_streak(
    team_id: str, candidate_date: date, direction: str, state: _OccupiedState
) -> bool:
    """Check that inserting a match doesn't create 3+ consecutive same-direction."""
    seq = state.team_sequence.get(team_id, [])
    if not seq:
        return True

    # Insert into sequence
    insert_idx = bisect.bisect_left([s[0] for s in seq], candidate_date)

    # Get the 2 matches before and 2 after the insertion point
    window_start = max(0, insert_idx - MAX_CONSECUTIVE_HOME)
    window_end = min(len(seq), insert_idx + MAX_CONSECUTIVE_HOME)

    # Build local sequence around insertion point
    local = list(seq[window_start:insert_idx])
    local.append((candidate_date, direction))
    local.extend(seq[insert_idx:window_end])

    # Check for 3+ consecutive same direction
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
    """Check bidirectional CAF buffer: >= 5 calendar days apart."""
    if team_id not in caf_teams:
        return True
    caf_dates = caf_dates_by_team.get(team_id, [])
    if not caf_dates:
        return True

    required_gap = MIN_REST_DAYS_CAF + 1  # 5 calendar days

    idx = bisect.bisect_left(caf_dates, candidate_date)
    # Check previous CAF date
    if idx > 0:
        prev_caf = caf_dates[idx - 1]
        if (candidate_date - prev_caf).days < required_gap:
            return False
    # Check next CAF date
    if idx < len(caf_dates):
        next_caf = caf_dates[idx]
        if next_caf == candidate_date:
            return False
        if (next_caf - candidate_date).days < required_gap:
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
    """Return all usable slot indices that satisfy R1–R7 for this match."""
    valid = []
    n_slots = len(slot_dates)

    home = match.home_team
    away = match.away_team
    venue = match.venue

    home_dir = "H"
    away_dir = "A"

    for si in range(n_slots):
        d = slot_dates[si]
        if d is None:
            continue
        if d < match.date:
            continue
        if state.date_load.get(d, 0) >= MAX_MATCHES_PER_DAY:
            continue

        # R1: not FIFA — already filtered in usable_slots

        # R2: neither team plays on that date
        home_dates = state.team_dates.get(home, [])
        hi = bisect.bisect_left(home_dates, d)
        if hi < len(home_dates) and home_dates[hi] == d:
            continue
        away_dates = state.team_dates.get(away, [])
        ai = bisect.bisect_left(away_dates, d)
        if ai < len(away_dates) and away_dates[ai] == d:
            continue

        # R3: rest days (league-to-league)
        if not _check_rest_days(home, d, state, MIN_REST_DAYS_LOCAL):
            continue
        if not _check_rest_days(away, d, state, MIN_REST_DAYS_LOCAL):
            continue

        # R4: venue free
        if si in state.venue_slots.get(venue, set()):
            continue

        # R5: streak
        if not _check_streak(home, d, home_dir, state):
            continue
        if not _check_streak(away, d, away_dir, state):
            continue

        # R6: CAF buffer
        if not _check_caf_buffer(home, d, data.caf_dates_by_team, caf_teams):
            continue
        if not _check_caf_buffer(away, d, data.caf_dates_by_team, caf_teams):
            continue

        # R7: venue is already correct (set at fixture construction)

        # R_SLOT: repair slots must be completely free, not merely under capacity.
        if state.slot_usage.get(si, 0) > 0:
            continue

        # R_WEEK: week load — at most HARD_MAX per week
        if state.week_load.get(slot_weeks[si], 0) >= HARD_MAX_MATCHES_PER_WEEK:
            continue

        valid.append(si)

    return valid


def _update_state(
    state: _OccupiedState,
    match: ScheduledMatch,
    slot_idx: int,
    slot_date: date,
    slot_week: int,
) -> None:
    """Update occupied state after placing a repaired match."""
    for tid in (match.home_team, match.away_team):
        dates = state.team_dates.setdefault(tid, [])
        bisect.insort(dates, slot_date)

    seq_home = state.team_sequence.setdefault(match.home_team, [])
    bisect.insort(seq_home, (slot_date, "H"))
    seq_away = state.team_sequence.setdefault(match.away_team, [])
    bisect.insort(seq_away, (slot_date, "A"))

    state.venue_slots.setdefault(match.venue, set()).add(slot_idx)
    state.week_load[slot_week] = state.week_load.get(slot_week, 0) + 1
    state.date_load[slot_date] = state.date_load.get(slot_date, 0) + 1
    state.slot_usage[slot_idx] = state.slot_usage.get(slot_idx, 0) + 1


def caf_repair(
    accepted: List[ScheduledMatch],
    violations: List[CAFViolation],
    data: LeagueData,
) -> Tuple[List[ScheduledMatch], List[ScheduledMatch]]:
    """Repair postponed matches by searching entire season for nearest valid slot.

    Returns (repaired_matches, unresolved_matches).
    """
    print("[caf_repair] Starting repair phase...")
    t0 = time.time()

    slots = data.usable_slots
    slot_dates: List[date] = list(slots["_date"])
    slot_weeks: List[int] = list(slots["Week_Num"].fillna(0).astype(int))
    slot_tiers_list: List[int] = list(compute_slot_tiers(slots))
    slot_day_ids: List[str] = list(slots["Day_ID"].fillna(""))
    slot_day_names: List[str] = list(slots["Day_name"].fillna(""))
    slot_datetimes = list(
        slots["Date time"] if "Date time" in slots.columns
        else [None] * len(slots)
    )

    # Identify CAF teams
    caf_teams = set()
    for _, row in data.teams.iterrows():
        if row["Cont_Flag"] in ("CL", "CC"):
            caf_teams.add(row["Team_ID"])

    # Build state from accepted matches
    state = _build_state(accepted)

    # Deduplicate violations to unique matches
    queued_matches: Dict[int, ScheduledMatch] = {}
    for v in violations:
        queued_matches[v.match.match_idx] = v.match

    queued_list = list(queued_matches.values())
    print(f"[caf_repair] {len(queued_list)} unique matches to repair.")

    # Step 2+3: find valid slots for each, rank by proximity
    match_valid_slots: Dict[int, List[Tuple[int, int]]] = {}
    for m in queued_list:
        valid = _find_valid_slots(m, data, state, slot_dates, slot_weeks, caf_teams)
        # Rank by proximity to original date
        ranked = sorted(valid, key=lambda si: abs((slot_dates[si] - m.date).days))
        match_valid_slots[m.match_idx] = [(si, abs((slot_dates[si] - m.date).days)) for si in ranked]

    # Write feasible slot counts
    _write_repair_slot_counts(queued_list, match_valid_slots)

    # Step 4: greedy nearest-first, most-constrained match first
    queued_sorted = sorted(
        queued_list,
        key=lambda m: len(match_valid_slots.get(m.match_idx, [])),
    )

    repaired: List[ScheduledMatch] = []
    unresolved: List[ScheduledMatch] = []

    teams_dict = {}
    for _, row in data.teams.iterrows():
        teams_dict[row["Team_ID"]] = {
            "Home_Stadium_ID": row["Home_Stadium_ID"],
            "Tier": int(row["Tier"]),
        }

    # Multi-pass greedy: retry unresolved after each full pass since
    # placements change the state and may open new opportunities.
    remaining = list(queued_sorted)
    max_passes = 5

    for pass_num in range(1, max_passes + 1):
        if not remaining:
            break

        placed_this_pass = []
        still_unresolved = []

        for m in remaining:
            valid = _find_valid_slots(m, data, state, slot_dates, slot_weeks, caf_teams)
            ranked = sorted(valid, key=lambda si: abs((slot_dates[si] - m.date).days))

            if not ranked:
                still_unresolved.append(m)
                continue

            best_si = ranked[0]

            travel = data.dist_matrix.get(
                teams_dict.get(m.away_team, {}).get("Home_Stadium_ID", ""), {}
            ).get(m.venue, 0.0)

            repaired_match = ScheduledMatch(
                match_idx=m.match_idx,
                round_num=m.round_num,
                home_team=m.home_team,
                away_team=m.away_team,
                venue=m.venue,
                match_tier=m.match_tier,
                slot_idx=best_si,
                day_id=slot_day_ids[best_si],
                date=slot_dates[best_si],
                date_time=slot_datetimes[best_si],
                week_num=slot_weeks[best_si],
                day_name=slot_day_names[best_si],
                slot_tier=slot_tiers_list[best_si],
                travel_km=travel,
            )
            repaired.append(repaired_match)
            placed_this_pass.append(repaired_match)

            _update_state(state, m, best_si, slot_dates[best_si], slot_weeks[best_si])

            displacement = abs((slot_dates[best_si] - m.date).days)
            print(f"  [repair pass {pass_num}] REPAIRED: match {m.match_idx} "
                  f"({m.home_team} vs {m.away_team}) "
                  f"moved from {m.date} to {slot_dates[best_si]} "
                  f"(+{displacement} days)")

        remaining = still_unresolved
        print(f"  [repair pass {pass_num}] Placed {len(placed_this_pass)}, "
              f"{len(remaining)} still unresolved.")

        if not placed_this_pass:
            break

    for m in remaining:
        unresolved.append(m)
        print(f"  [repair] UNRESOLVED: match {m.match_idx} "
              f"({m.home_team} vs {m.away_team}, R{m.round_num})")

    elapsed = time.time() - t0
    print(f"[caf_repair] Done in {elapsed:.1f}s: "
          f"{len(repaired)} repaired, {len(unresolved)} unresolved.")

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
        writer.writerow([
            "match_idx", "round", "home", "away",
            "original_date", "feasible_slot_count",
        ])
        for m in queued:
            writer.writerow([
                m.match_idx, m.round_num, m.home_team, m.away_team,
                m.date, len(valid_slots.get(m.match_idx, [])),
            ])


def _write_repair_status(
    repaired: List[ScheduledMatch],
    unresolved: List[ScheduledMatch],
    elapsed: float,
    skipped: bool = False,
) -> None:
    os.makedirs(PHASES_DIR, exist_ok=True)
    path = os.path.join(PHASES_DIR, "09_repair_solver_status.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "skipped": skipped,
            "repaired_count": len(repaired),
            "unresolved_count": len(unresolved),
            "elapsed_s": round(elapsed, 2),
        }, f, indent=2)


def write_repair_skipped_status(reason: str) -> None:
    os.makedirs(PHASES_DIR, exist_ok=True)
    path = os.path.join(PHASES_DIR, "09_repair_solver_status.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "skipped": True,
            "reason": reason,
            "repaired_count": 0,
            "unresolved_count": 0,
            "elapsed_s": 0.0,
        }, f, indent=2)
