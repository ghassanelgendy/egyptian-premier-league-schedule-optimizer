"""Build per-match feasible slot sets — full season, with CAF buffer pruning."""

from __future__ import annotations

import csv
import os
from datetime import date, timedelta
from typing import Dict, List, Set

from src.constants import MIN_REST_DAYS_CAF, PHASES_DIR
from src.data_loader import LeagueData
from src.fixture_generator import Match


def build_domains(
    data: LeagueData,
    matches: List[Match],
) -> Dict[int, List[int]]:
    """For each match, return the list of usable-slot row indices it can use.

    Pruning applied:
      - FIFA-date exclusion (already done in usable_slots)
      - CAF buffer: for matches involving a CAF team, exclude slots within
        5 calendar days (bidirectional) of any of that team's CAF dates.
    """
    slots = data.usable_slots
    n_usable = len(slots)
    slot_dates: List[date] = list(slots["_date"])

    # Identify CAF teams
    caf_teams: Set[str] = set()
    for _, row in data.teams.iterrows():
        if row["Cont_Flag"] in ("CL", "CC"):
            caf_teams.add(row["Team_ID"])

    # Pre-compute blocked slot indices per CAF team
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

    all_indices = list(range(n_usable))
    all_set = set(all_indices)

    domains: Dict[int, List[int]] = {}
    for m in matches:
        forbidden: Set[int] = set()
        for team_id in (m.home_team, m.away_team):
            if team_id in blocked_by_team:
                forbidden |= blocked_by_team[team_id]
        if forbidden:
            domains[m.match_idx] = sorted(all_set - forbidden)
        else:
            domains[m.match_idx] = all_indices

    _write_domain_csv(matches, domains)
    return domains


def _write_domain_csv(
    matches: List[Match],
    domains: Dict[int, List[int]],
) -> None:
    os.makedirs(PHASES_DIR, exist_ok=True)
    path = os.path.join(PHASES_DIR, "05_baseline_feasible_slot_counts.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "match_idx", "round", "home", "away", "feasible_slot_count",
        ])
        for m in matches:
            writer.writerow([
                m.match_idx, m.round_num, m.home_team, m.away_team,
                len(domains[m.match_idx]),
            ])
