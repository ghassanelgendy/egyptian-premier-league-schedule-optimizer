"""Build per-match feasible slot sets with CAF-aware round windows."""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Set

from src.constants import MATCHES_PER_ROUND, MIN_REST_DAYS_CAF, NUM_ROUNDS, PHASES_DIR
from src.data_loader import LeagueData
from src.fixture_generator import Match


@dataclass(frozen=True)
class RoundWindow:
    round_num: int
    start_date: date
    end_date: date
    week_nums: str
    slot_indices: List[int]


ROUND_WINDOW_DAYS = 5


def build_domains(
    data: LeagueData,
    matches: List[Match],
) -> Dict[int, List[int]]:
    """For each match, return the list of usable-slot row indices it can use.

    Pruning applied:
      - FIFA-date exclusion (already done in usable_slots)
      - a strict monotonic baseline round window
      - CAF buffer exclusion for known CAF-participating teams

    CAF repair is the only phase that may move a match outside its original
    round window.
    """
    slots = data.usable_slots
    n_usable = len(slots)
    slot_dates: List[date] = list(slots["_date"])

    round_windows = build_round_windows(data)
    caf_teams: Set[str] = set()
    for _, row in data.teams.iterrows():
        if row["Cont_Flag"] in ("CL", "CC"):
            caf_teams.add(row["Team_ID"])

    buffer_days = MIN_REST_DAYS_CAF + 1  # 5 calendar days apart
    blocked_by_team: Dict[str, Set[int]] = {}
    for team_id in caf_teams:
        blocked: Set[int] = set()
        caf_dates = data.caf_dates_by_team.get(team_id, [])
        for caf_d in caf_dates:
            for si in range(n_usable):
                sd = slot_dates[si]
                if sd is None:
                    continue
                if abs((sd - caf_d).days) < buffer_days:
                    blocked.add(si)
        blocked_by_team[team_id] = blocked

    all_indices = set(range(n_usable))
    domains: Dict[int, List[int]] = {}
    caf_relaxed_matches: Set[int] = set()
    for m in matches:
        forbidden: Set[int] = set()
        for team_id in (m.home_team, m.away_team):
            forbidden |= blocked_by_team.get(team_id, set())

        filtered = all_indices - forbidden
        if not filtered and forbidden:
            # This should be rare with full-season domains, but keep the run
            # diagnosable if a team's CAF calendar blocks the whole season.
            domains[m.match_idx] = sorted(all_indices)
            caf_relaxed_matches.add(m.match_idx)
        else:
            domains[m.match_idx] = sorted(filtered)

    _write_round_windows_csv(round_windows)
    _write_domain_csv(matches, domains, round_windows, caf_relaxed_matches)
    return domains


def build_round_windows(data: LeagueData) -> List[RoundWindow]:
    """Build 34 chronological baseline round windows from playable slot weeks.

    Windows are rolling date ranges, not calendar weeks. A five-day candidate is
    eligible if it has enough non-FIFA slot rows for a full round and every CAF
    team has at least one CAF-safe slot somewhere inside it. This lets the
    league use midweek/weekend cadence while skipping FIFA and CAF-heavy gaps.
    """
    slots = data.usable_slots.copy()
    slots = slots[slots["_date"].notna()].copy()
    if slots.empty:
        raise ValueError("No usable non-FIFA slots are available")

    caf_teams: Set[str] = set()
    for _, row in data.teams.iterrows():
        if row["Cont_Flag"] in ("CL", "CC"):
            caf_teams.add(row["Team_ID"])

    candidates: List[tuple[date, date, List[int]]] = []
    all_dates = sorted(set(slots["_date"]))
    for start_d in all_dates:
        end_d = start_d + timedelta(days=ROUND_WINDOW_DAYS - 1)
        group = slots[(slots["_date"] >= start_d) & (slots["_date"] <= end_d)]
        if len(group) < MATCHES_PER_ROUND:
            continue
        if not _window_has_caf_safe_capacity(group, data, caf_teams):
            continue
        candidates.append((start_d, end_d, list(group.index)))

    selected: List[tuple[date, date, List[int]]] = []
    last_end: date | None = None
    for candidate in candidates:
        start_d, end_d, _ = candidate
        if last_end is not None and start_d <= last_end:
            continue
        selected.append(candidate)
        last_end = end_d
        if len(selected) == NUM_ROUNDS:
            break

    if len(selected) < NUM_ROUNDS:
        raise ValueError(
            f"Need {NUM_ROUNDS} playable round windows, got {len(selected)}"
        )

    windows: List[RoundWindow] = []
    for round_idx, (start_d, end_d, indices) in enumerate(
        selected,
        start=1,
    ):
        week_nums = sorted(
            set(slots.loc[indices, "Week_Num"].fillna(0).astype(int).tolist())
        )
        windows.append(RoundWindow(
            round_num=round_idx,
            start_date=start_d,
            end_date=end_d,
            week_nums=";".join(str(w) for w in week_nums),
            slot_indices=indices,
        ))

    return windows


def _window_has_caf_safe_capacity(
    group,
    data: LeagueData,
    caf_teams: Set[str],
) -> bool:
    if not caf_teams:
        return True

    required_gap = MIN_REST_DAYS_CAF + 1
    for team_id in caf_teams:
        safe_count = 0
        caf_dates = data.caf_dates_by_team.get(team_id, [])
        for d in group["_date"]:
            if all(abs((d - caf_d).days) >= required_gap for caf_d in caf_dates):
                safe_count += 1
        if safe_count == 0:
            return False
    return True


def _write_round_windows_csv(round_windows: List[RoundWindow]) -> None:
    os.makedirs(PHASES_DIR, exist_ok=True)
    path = os.path.join(PHASES_DIR, "03_round_windows.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Round",
            "Start_Date",
            "End_Date",
            "Calendar_Weeks",
            "Slot_Count",
        ])
        for rw in round_windows:
            writer.writerow([
                rw.round_num,
                rw.start_date,
                rw.end_date,
                rw.week_nums,
                len(rw.slot_indices),
            ])


def _write_domain_csv(
    matches: List[Match],
    domains: Dict[int, List[int]],
    round_windows: List[RoundWindow],
    caf_relaxed_matches: Set[int],
) -> None:
    os.makedirs(PHASES_DIR, exist_ok=True)
    path = os.path.join(PHASES_DIR, "05_baseline_feasible_slot_counts.csv")
    window_by_round = {rw.round_num: rw for rw in round_windows}

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "match_idx",
            "round",
            "home",
            "away",
            "round_window_start",
            "round_window_end",
            "round_window_slot_count",
            "feasible_slot_count",
            "caf_filter_relaxed_for_repair",
        ])
        for m in matches:
            rw = window_by_round[m.round_num]
            writer.writerow([
                m.match_idx,
                m.round_num,
                m.home_team,
                m.away_team,
                rw.start_date,
                rw.end_date,
                len(rw.slot_indices),
                len(domains[m.match_idx]),
                m.match_idx in caf_relaxed_matches,
            ])
