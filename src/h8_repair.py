"""Post-processing hard repair for H8 (max 2 consecutive home or away).

Strategy (applied in order until a net reduction in violations is found):
  1. SWAP: exchange the middle match's slot with a same-team opposite-direction
     match that sits outside the streak window and passes H4/H5/H7/CAF.
  2. OPEN-SLOT MOVE: relocate the middle match to an unoccupied calendar slot
     outside the streak window that passes H4/H7/CAF for both teams.

Swapping preserves each team's set of played dates for the swapping team.
Moving to an open slot does not (both teams gain a new date), so full H4/H7/CAF
checks are needed for both teams.
"""

from __future__ import annotations

import pandas as pd
from datetime import date
from typing import Dict, List, Optional, Set, Tuple

from src.constants import MIN_REST_DAYS_LOCAL, MIN_REST_DAYS_CAF
from src.data_loader import LeagueData
from src.baseline_solver import ScheduledMatch
from src.tiers import compute_slot_tiers


# ---------------------------------------------------------------------------
# Team sequence helpers
# ---------------------------------------------------------------------------

def _team_seq(schedule: List[ScheduledMatch], team_id: str) -> List[int]:
    """Return schedule indices for `team_id`, sorted chronologically."""
    idxs = [
        i for i, sm in enumerate(schedule)
        if sm.home_team == team_id or sm.away_team == team_id
    ]
    return sorted(idxs, key=lambda i: schedule[i].date)


# ---------------------------------------------------------------------------
# Violation detection
# ---------------------------------------------------------------------------

def find_h8_violations(
    schedule: List[ScheduledMatch],
) -> List[Tuple[str, int, int, int]]:
    """Return (team_id, idx_a, idx_b, idx_c) for every H8 violation.

    idx_a/b/c are indices into `schedule` where the team's a-th, b-th, and
    c-th consecutive played matches are all in the same direction.
    """
    all_teams = sorted(
        {sm.home_team for sm in schedule} | {sm.away_team for sm in schedule}
    )
    violations: List[Tuple[str, int, int, int]] = []
    for team_id in all_teams:
        seq = _team_seq(schedule, team_id)
        for k in range(len(seq) - 2):
            ia, ib, ic = seq[k], seq[k + 1], seq[k + 2]
            ha = schedule[ia].home_team == team_id
            hb = schedule[ib].home_team == team_id
            hc = schedule[ic].home_team == team_id
            if ha == hb == hc:
                violations.append((team_id, ia, ib, ic))
    return violations


def count_h8_violations(schedule: List[ScheduledMatch]) -> int:
    return len(find_h8_violations(schedule))


# ---------------------------------------------------------------------------
# Constraint helpers
# ---------------------------------------------------------------------------

def _dates_for_team(
    schedule: List[ScheduledMatch],
    team_id: str,
    exclude_idxs: Set[int],
) -> Set[date]:
    return {
        sm.date
        for i, sm in enumerate(schedule)
        if i not in exclude_idxs
        and (sm.home_team == team_id or sm.away_team == team_id)
    }


def _ok_h4_h7_caf(
    new_date: date,
    existing_dates: Set[date],
    caf_dates: List[date],
    rest_local: int = MIN_REST_DAYS_LOCAL,
    rest_caf: int = MIN_REST_DAYS_CAF,
) -> bool:
    """True iff `new_date` satisfies H4, H7 (local rest), and CAF rest days."""
    if new_date in existing_dates:
        return False
    for d in existing_dates:
        if abs((new_date - d).days) <= rest_local:
            return False
    for d in caf_dates:
        if abs((new_date - d).days) <= rest_caf:
            return False
    return True


def _venue_free(
    schedule: List[ScheduledMatch],
    venue: str,
    slot_idx: int,
    exclude_idxs: Set[int],
) -> bool:
    for i, sm in enumerate(schedule):
        if i in exclude_idxs:
            continue
        if sm.slot_idx == slot_idx and sm.venue == venue:
            return False
    return True


# ---------------------------------------------------------------------------
# Strategy 1: swap with same-team opposite-direction match
# ---------------------------------------------------------------------------

def _try_swap(
    schedule: List[ScheduledMatch],
    idx_mid: int,
    idx_cand: int,
    d_first: date,
    d_last: date,
    caf_dates_by_team: Dict[str, List[date]],
) -> bool:
    """Attempt to swap slot assignments of schedule[idx_mid] and schedule[idx_cand].

    Applies the swap in-place and returns True on success, False otherwise.
    """
    sm_mid = schedule[idx_mid]
    sm_cand = schedule[idx_cand]

    new_date_mid = sm_cand.date
    new_date_cand = sm_mid.date

    if d_first < new_date_mid < d_last:
        return False

    exclude = {idx_mid, idx_cand}

    for team_id, new_date in [
        (sm_mid.home_team, new_date_mid),
        (sm_mid.away_team, new_date_mid),
        (sm_cand.home_team, new_date_cand),
        (sm_cand.away_team, new_date_cand),
    ]:
        existing = _dates_for_team(schedule, team_id, exclude)
        caf_dates = caf_dates_by_team.get(team_id, [])
        if not _ok_h4_h7_caf(new_date, existing, caf_dates):
            return False

    if not _venue_free(schedule, sm_mid.venue, sm_cand.slot_idx, exclude):
        return False
    if not _venue_free(schedule, sm_cand.venue, sm_mid.slot_idx, exclude):
        return False

    (
        sm_mid.slot_idx, sm_cand.slot_idx,
        sm_mid.day_id, sm_cand.day_id,
        sm_mid.date, sm_cand.date,
        sm_mid.date_time, sm_cand.date_time,
        sm_mid.week_num, sm_cand.week_num,
        sm_mid.day_name, sm_cand.day_name,
        sm_mid.slot_tier, sm_cand.slot_tier,
    ) = (
        sm_cand.slot_idx, sm_mid.slot_idx,
        sm_cand.day_id, sm_mid.day_id,
        sm_cand.date, sm_mid.date,
        sm_cand.date_time, sm_mid.date_time,
        sm_cand.week_num, sm_mid.week_num,
        sm_cand.day_name, sm_mid.day_name,
        sm_cand.slot_tier, sm_mid.slot_tier,
    )
    return True


def _undo_swap(schedule: List[ScheduledMatch], idx_a: int, idx_b: int) -> None:
    """Undo a swap by swapping back (same operation — swap is its own inverse)."""
    sm_a, sm_b = schedule[idx_a], schedule[idx_b]
    (
        sm_a.slot_idx, sm_b.slot_idx,
        sm_a.day_id, sm_b.day_id,
        sm_a.date, sm_b.date,
        sm_a.date_time, sm_b.date_time,
        sm_a.week_num, sm_b.week_num,
        sm_a.day_name, sm_b.day_name,
        sm_a.slot_tier, sm_b.slot_tier,
    ) = (
        sm_b.slot_idx, sm_a.slot_idx,
        sm_b.day_id, sm_a.day_id,
        sm_b.date, sm_a.date,
        sm_b.date_time, sm_a.date_time,
        sm_b.week_num, sm_a.week_num,
        sm_b.day_name, sm_a.day_name,
        sm_b.slot_tier, sm_a.slot_tier,
    )


# ---------------------------------------------------------------------------
# Strategy 2: move to an unoccupied calendar slot
# ---------------------------------------------------------------------------

def _try_open_slot_move(
    schedule: List[ScheduledMatch],
    idx_mid: int,
    d_first: date,
    d_last: date,
    open_slots: List[dict],
    caf_dates_by_team: Dict[str, List[date]],
) -> Optional[dict]:
    """Try to move schedule[idx_mid] to an unoccupied slot outside the streak window.

    Returns the old slot-field dict (for undo) if a valid slot is found and
    the move is applied, or None if no valid open slot exists.
    """
    sm = schedule[idx_mid]
    exclude = {idx_mid}

    home_existing = _dates_for_team(schedule, sm.home_team, exclude)
    away_existing = _dates_for_team(schedule, sm.away_team, exclude)
    home_caf = caf_dates_by_team.get(sm.home_team, [])
    away_caf = caf_dates_by_team.get(sm.away_team, [])

    used_slots = {s.slot_idx for s in schedule}

    for sl in open_slots:
        new_date = sl['slot_date']
        new_si = sl['slot_idx']

        if d_first < new_date < d_last:
            continue
        if new_si in used_slots:
            continue
        if not _venue_free(schedule, sm.venue, new_si, exclude):
            continue
        if not _ok_h4_h7_caf(new_date, home_existing, home_caf):
            continue
        if not _ok_h4_h7_caf(new_date, away_existing, away_caf):
            continue

        # Save old state for potential undo
        old_state = {
            'slot_idx': sm.slot_idx,
            'day_id': sm.day_id,
            'date': sm.date,
            'date_time': sm.date_time,
            'week_num': sm.week_num,
            'day_name': sm.day_name,
            'slot_tier': sm.slot_tier,
        }
        # Apply move
        sm.slot_idx = new_si
        sm.day_id = sl['day_id']
        sm.date = new_date
        sm.date_time = sl['date_time']
        sm.week_num = sl['week_num']
        sm.day_name = sl['day_name']
        sm.slot_tier = sl['slot_tier']
        return old_state

    return None


def _undo_open_slot_move(schedule: List[ScheduledMatch], idx_mid: int, old_state: dict) -> None:
    sm = schedule[idx_mid]
    for k, v in old_state.items():
        setattr(sm, k, v)


def _build_open_slots(schedule: List[ScheduledMatch], data: LeagueData) -> List[dict]:
    """Build a list of open slot dicts sorted by date."""
    used_slot_idxs = {sm.slot_idx for sm in schedule}
    slots_df = data.usable_slots

    slot_tiers = list(compute_slot_tiers(slots_df))

    open_slots = []
    for si, row in slots_df.iterrows():
        if si in used_slot_idxs:
            continue
        d = row['_date'] if '_date' in row.index else (
            pd.to_datetime(row['Date']).date() if pd.notna(row.get('Date')) else None
        )
        if d is None:
            continue
        open_slots.append({
            'slot_idx': int(si),
            'slot_date': d,
            'day_id': str(row.get('Day_ID', '')),
            'date_time': row.get('Date time'),
            'week_num': int(row.get('Week_Num', 0)) if pd.notna(row.get('Week_Num')) else 0,
            'day_name': str(row.get('Day_name', '')),
            'slot_tier': slot_tiers[si] if si < len(slot_tiers) else 0,
        })
    open_slots.sort(key=lambda x: x['slot_date'])
    return open_slots


# ---------------------------------------------------------------------------
# Main repair loop
# ---------------------------------------------------------------------------

def repair_h8(
    schedule: List[ScheduledMatch],
    data: LeagueData,
    max_iters: int = 1000,
) -> List[ScheduledMatch]:
    """Repair H8 violations using two strategies.

    Strategy 1 — Swap: exchange the middle match's slot with a same-team
    opposite-direction match outside the streak window.
    Strategy 2 — Open-slot move: relocate the middle match to an unoccupied
    calendar slot outside the streak window.

    Both strategies require a net reduction in the total violation count to
    prevent oscillation.  Iteration continues until all violations are resolved
    or no further progress is possible.
    """
    schedule = list(schedule)
    caf_by_team = data.caf_dates_by_team

    # Pre-build open slots list (refreshed whenever we make progress)
    open_slots = _build_open_slots(schedule, data)

    stalled: set = set()

    for iteration in range(max_iters):
        violations = find_h8_violations(schedule)
        if not violations:
            print(f"[h8_repair] All H8 violations resolved after {iteration} moves.")
            return schedule

        # Pick first non-stalled violation; if all stalled, clear and retry
        target = None
        for v in violations:
            if v not in stalled:
                target = v
                break
        if target is None:
            stalled.clear()
            target = violations[0]

        team_id, ia, ib, ic = target
        d_first = schedule[ia].date
        d_last = schedule[ic].date
        is_home_streak = (schedule[ib].home_team == team_id)

        pre_count = len(violations)
        made_progress = False

        seq = _team_seq(schedule, team_id)

        # Try each of the three streak positions (first, middle, last) as the
        # match to relocate.  The window changes depending on which we move:
        #   - move ia: must end up AFTER d_last (or BEFORE d_first)
        #   - move ib: must end up outside (d_first, d_last) — original logic
        #   - move ic: must end up BEFORE d_first (or AFTER d_last)
        # For each candidate position we try both swap and open-slot strategies.

        def _window_for(idx_move: int) -> tuple:
            """Return (d_lo, d_hi) such that idx_move must land OUTSIDE (d_lo, d_hi)."""
            if idx_move == ia:
                # Moving the first: it must land strictly outside [d_first, d_last]
                return (d_first, d_last)
            elif idx_move == ic:
                return (d_first, d_last)
            else:  # ib
                return (d_first, d_last)

        for idx_move in (ib, ia, ic):
            if made_progress:
                break
            sm_move = schedule[idx_move]
            d_move = sm_move.date
            win_lo, win_hi = _window_for(idx_move)

            # ------------------------------------------------------------------
            # Strategy 1: swap with same-team opposite-direction match
            # ------------------------------------------------------------------
            swap_candidates = []
            for idx in seq:
                if idx in (ia, ib, ic):
                    continue
                sm = schedule[idx]
                if (sm.home_team == team_id) == is_home_streak:
                    continue
                d = sm.date
                inside = 1 if (win_lo < d < win_hi) else 0
                distance = abs((d - d_move).days)
                swap_candidates.append((inside, distance, idx))
            swap_candidates.sort()

            for _, _, idx_cand in swap_candidates:
                if _try_swap(schedule, idx_move, idx_cand, win_lo, win_hi, caf_by_team):
                    post_count = len(find_h8_violations(schedule))
                    if post_count < pre_count:
                        made_progress = True
                        stalled.discard(target)
                        open_slots = _build_open_slots(schedule, data)
                        break
                    else:
                        _undo_swap(schedule, idx_move, idx_cand)

            # ------------------------------------------------------------------
            # Strategy 2: move to an open slot (if swap failed)
            # ------------------------------------------------------------------
            if not made_progress:
                old_state = _try_open_slot_move(
                    schedule, idx_move, win_lo, win_hi, open_slots, caf_by_team
                )
                if old_state is not None:
                    post_count = len(find_h8_violations(schedule))
                    if post_count < pre_count:
                        made_progress = True
                        stalled.discard(target)
                        open_slots = _build_open_slots(schedule, data)
                    else:
                        _undo_open_slot_move(schedule, idx_move, old_state)

        if not made_progress:
            stalled.add(target)

    remaining = count_h8_violations(schedule)
    if remaining > 0:
        print(f"[h8_repair] WARNING: {remaining} H8 violation(s) could not be repaired.")
    return schedule
