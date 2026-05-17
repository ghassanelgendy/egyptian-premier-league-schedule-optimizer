"""Build per-match feasible slot sets with CAF-aware round windows."""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Set

from src.constants import (
    ENFORCE_FINAL_ROUND_SINGLE_DAY,
    FINAL_ROUND_NUM,
    MATCHES_PER_ROUND,
    MIN_REST_DAYS_CAF,
    NON_FINAL_ROUND_BASE_WINDOW_DAYS,
    NON_FINAL_ROUND_EPL_FALLBACK_WINDOW_DAYS,
    NON_FINAL_ROUND_MAX_WINDOW_DAYS,
    NON_FINAL_ROUND_MIN_FEASIBLE_SLOTS_PER_MATCH,
    NON_FINAL_ROUND_MIN_SLOT_COUNT,
    NUM_ROUNDS,
    PHASES_DIR,
)
from src.data_loader import LeagueData
from src.fixture_generator import Match


@dataclass(frozen=True)
class RoundWindow:
    round_num: int
    start_date: date
    end_date: date
    week_nums: str
    slot_indices: List[int]


def build_domains(
    data: LeagueData,
    matches: List[Match],
    non_final_policy: str = "compact",
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
    caf_teams = _collect_caf_teams(data)
    blocked_by_team = _build_blocked_by_team(slot_dates, n_usable, data, caf_teams)
    round_windows = _apply_non_final_policy(
        data,
        matches,
        round_windows,
        blocked_by_team,
        non_final_policy,
    )
    domains, caf_relaxed_matches = _compute_domains_for_windows(
        matches,
        round_windows,
        blocked_by_team,
    )

    _write_round_windows_csv(round_windows)
    _write_domain_csv(matches, domains, round_windows, caf_relaxed_matches)
    return domains


def _apply_non_final_policy(
    data: LeagueData,
    matches: List[Match],
    round_windows: List[RoundWindow],
    blocked_by_team: Dict[str, Set[int]],
    non_final_policy: str,
) -> List[RoundWindow]:
    if non_final_policy == "compact":
        return _expand_non_final_round_windows(
            data,
            matches,
            round_windows,
            blocked_by_team,
            NON_FINAL_ROUND_MAX_WINDOW_DAYS,
            None,
        )
    if non_final_policy == "epl_relaxed":
        return _expand_non_final_round_windows(
            data,
            matches,
            round_windows,
            blocked_by_team,
            NON_FINAL_ROUND_EPL_FALLBACK_WINDOW_DAYS,
            NON_FINAL_ROUND_EPL_FALLBACK_WINDOW_DAYS,
        )
    if non_final_policy == "epl_full":
        return _spill_non_final_round_windows(data, round_windows)
    raise ValueError(f"Unknown non-final round policy: {non_final_policy}")


def build_round_windows(data: LeagueData) -> List[RoundWindow]:
    """Build 34 chronological baseline round windows from playable slot weeks.

    Windows are rolling date ranges, not calendar weeks. Non-final rounds start
    from compact base windows, then the domain builder may extend pressured
    rounds further forward using only real calendar dates. The final round keeps
    its dedicated tail domain.
    """
    slots = data.usable_slots.copy()
    slots = slots[slots["_date"].notna()].copy()
    if slots.empty:
        raise ValueError("No usable non-FIFA slots are available")

    caf_teams = _collect_caf_teams(data)

    candidates: List[tuple[date, date, List[int]]] = []
    all_dates = sorted(set(slots["_date"]))
    for start_d in all_dates:
        end_d = start_d + timedelta(days=NON_FINAL_ROUND_BASE_WINDOW_DAYS - 1)
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

    season_end = max(all_dates)
    windows: List[RoundWindow] = []
    for round_idx, (start_d, end_d, indices) in enumerate(
        selected,
        start=1,
    ):
        effective_end = end_d
        effective_indices = indices
        if ENFORCE_FINAL_ROUND_SINGLE_DAY and round_idx == FINAL_ROUND_NUM:
            tail = slots[slots["_date"] >= start_d]
            effective_end = season_end
            effective_indices = list(tail.index)

        week_nums = sorted(
            set(
                slots.loc[effective_indices, "Week_Num"]
                .fillna(0)
                .astype(int)
                .tolist()
            )
        )
        windows.append(RoundWindow(
            round_num=round_idx,
            start_date=start_d,
            end_date=effective_end,
            week_nums=";".join(str(w) for w in week_nums),
            slot_indices=effective_indices,
        ))

    return windows


def _collect_caf_teams(data: LeagueData) -> Set[str]:
    caf_teams: Set[str] = set()
    for _, row in data.teams.iterrows():
        if row["Cont_Flag"] in ("CL", "CC"):
            caf_teams.add(row["Team_ID"])
    return caf_teams


def _build_blocked_by_team(
    slot_dates: List[date],
    n_usable: int,
    data: LeagueData,
    caf_teams: Set[str],
) -> Dict[str, Set[int]]:
    buffer_days = MIN_REST_DAYS_CAF + 1
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
    return blocked_by_team


def _compute_domains_for_windows(
    matches: List[Match],
    round_windows: List[RoundWindow],
    blocked_by_team: Dict[str, Set[int]],
) -> tuple[Dict[int, List[int]], Set[int]]:
    round_slots_by_round = {
        rw.round_num: set(rw.slot_indices)
        for rw in round_windows
    }
    domains: Dict[int, List[int]] = {}
    caf_relaxed_matches: Set[int] = set()

    for match in matches:
        round_allowed = round_slots_by_round.get(match.round_num, set())
        if not round_allowed:
            raise RuntimeError(
                f"No round window slots found for round {match.round_num}"
            )

        forbidden: Set[int] = set()
        for team_id in (match.home_team, match.away_team):
            forbidden |= blocked_by_team.get(team_id, set())

        filtered = round_allowed - forbidden
        if not filtered and forbidden:
            domains[match.match_idx] = sorted(round_allowed)
            caf_relaxed_matches.add(match.match_idx)
        else:
            domains[match.match_idx] = sorted(filtered)

    return domains, caf_relaxed_matches


def _expand_non_final_round_windows(
    data: LeagueData,
    matches: List[Match],
    round_windows: List[RoundWindow],
    blocked_by_team: Dict[str, Set[int]],
    max_window_days: int,
    target_window_days: int | None,
) -> List[RoundWindow]:
    slots = data.usable_slots
    season_end = max(slots["_date"])
    expanded_windows = list(round_windows)

    matches_by_round: Dict[int, List[Match]] = {}
    for match in matches:
        matches_by_round.setdefault(match.round_num, []).append(match)

    domains, _ = _compute_domains_for_windows(matches, expanded_windows, blocked_by_team)

    for idx, round_window in enumerate(expanded_windows):
        if round_window.round_num == FINAL_ROUND_NUM:
            continue

        round_matches = matches_by_round.get(round_window.round_num, [])
        if not round_matches:
            continue

        max_end = min(
            season_end,
            round_window.start_date + timedelta(days=max_window_days - 1),
        )
        target_end = None
        if target_window_days is not None:
            target_end = min(
                season_end,
                round_window.start_date + timedelta(days=target_window_days - 1),
            )
        current_window = round_window

        while (
            (
                _round_needs_more_slack(current_window, round_matches, domains)
                or (
                    target_end is not None
                    and current_window.end_date < target_end
                )
            )
            and current_window.end_date < max_end
        ):
            current_window = _make_round_window(
                slots,
                current_window.round_num,
                current_window.start_date,
                current_window.end_date + timedelta(days=1),
            )
            expanded_windows[idx] = current_window
            domains, _ = _compute_domains_for_windows(
                matches,
                expanded_windows,
                blocked_by_team,
            )

    return expanded_windows


def _spill_non_final_round_windows(
    data: LeagueData,
    round_windows: List[RoundWindow],
) -> List[RoundWindow]:
    slots = data.usable_slots
    season_end = max(slots["_date"])
    spilled_windows: List[RoundWindow] = []

    for round_window in round_windows:
        if round_window.round_num == FINAL_ROUND_NUM:
            spilled_windows.append(round_window)
            continue
        spilled_windows.append(
            _make_round_window(
                slots,
                round_window.round_num,
                round_window.start_date,
                season_end,
            )
        )

    return spilled_windows


def _round_needs_more_slack(
    round_window: RoundWindow,
    round_matches: List[Match],
    domains: Dict[int, List[int]],
) -> bool:
    if len(round_window.slot_indices) < NON_FINAL_ROUND_MIN_SLOT_COUNT:
        return True

    return any(
        len(domains.get(match.match_idx, [])) < NON_FINAL_ROUND_MIN_FEASIBLE_SLOTS_PER_MATCH
        for match in round_matches
    )


def _make_round_window(
    slots,
    round_num: int,
    start_date: date,
    end_date: date,
) -> RoundWindow:
    group = slots[(slots["_date"] >= start_date) & (slots["_date"] <= end_date)]
    week_nums = sorted(
        set(group["Week_Num"].fillna(0).astype(int).tolist())
    )
    return RoundWindow(
        round_num=round_num,
        start_date=start_date,
        end_date=end_date,
        week_nums=";".join(str(w) for w in week_nums),
        slot_indices=list(group.index),
    )


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
