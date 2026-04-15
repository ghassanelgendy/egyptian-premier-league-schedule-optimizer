"""Post-baseline CAF audit: find matches violating CAF buffer rules."""

from __future__ import annotations

import bisect
import csv
import os
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from src.constants import MIN_REST_DAYS_CAF, PHASES_DIR
from src.data_loader import LeagueData
from src.baseline_solver import ScheduledMatch


@dataclass
class CAFViolation:
    match: ScheduledMatch
    affected_team_id: str
    conflicting_caf_date: date
    conflicting_caf_competition: str
    conflicting_caf_round: str
    conflict_direction: str  # PRE, POST, SAME_DAY
    violation_reason: str


def _find_nearest_caf(
    match_date: date,
    caf_dates: List[date],
    direction: str,
) -> Optional[date]:
    """Find nearest CAF date before or after match_date."""
    if direction == "after":
        idx = bisect.bisect_right(caf_dates, match_date)
        return caf_dates[idx] if idx < len(caf_dates) else None
    else:  # before
        idx = bisect.bisect_left(caf_dates, match_date)
        return caf_dates[idx - 1] if idx > 0 else None


def _get_caf_match_info(
    data: LeagueData, team_id: str, caf_date: date
) -> Tuple[str, str]:
    """Look up competition_name and round for a team's CAF date."""
    if data.caf_blockers.empty:
        return ("CAF", "Unknown")
    mask = (data.caf_blockers.get("team_id") == team_id)
    if "_caf_date" in data.caf_blockers.columns:
        mask = mask & (data.caf_blockers["_caf_date"] == caf_date)
    matches = data.caf_blockers[mask]
    if matches.empty:
        return ("CAF", "Unknown")
    row = matches.iloc[0]
    comp = str(row.get("competition_name", "CAF"))
    rnd = str(row.get("round", "Unknown"))
    return (comp, rnd)


def caf_audit(
    baseline: List[ScheduledMatch],
    data: LeagueData,
) -> Tuple[List[ScheduledMatch], List[CAFViolation]]:
    """Scan baseline for CAF violations. Return (accepted, violations)."""

    buffer_days = MIN_REST_DAYS_CAF  # 4 full rest days -> 5 calendar days apart

    # Identify CAF teams
    caf_teams = set()
    for _, row in data.teams.iterrows():
        if row["Cont_Flag"] in ("CL", "CC"):
            caf_teams.add(row["Team_ID"])

    violations: List[CAFViolation] = []
    violation_match_idxs = set()

    for sm in baseline:
        for team_id in (sm.home_team, sm.away_team):
            if team_id not in caf_teams:
                continue

            caf_dates = data.caf_dates_by_team.get(team_id, [])
            if not caf_dates:
                continue

            match_date = sm.date

            # Check SAME_DAY
            if match_date in caf_dates:
                comp, rnd = _get_caf_match_info(data, team_id, match_date)
                violations.append(CAFViolation(
                    match=sm,
                    affected_team_id=team_id,
                    conflicting_caf_date=match_date,
                    conflicting_caf_competition=comp,
                    conflicting_caf_round=rnd,
                    conflict_direction="SAME_DAY",
                    violation_reason=(
                        f"League match on same date as {team_id}'s CAF match "
                        f"({comp} {rnd}) on {match_date}"
                    ),
                ))
                violation_match_idxs.add(sm.match_idx)
                continue

            # Check PRE: league match too close BEFORE a CAF match
            next_caf = _find_nearest_caf(match_date, caf_dates, "after")
            if next_caf is not None:
                gap = (next_caf - match_date).days
                if gap < buffer_days + 1:  # need at least 5 days apart
                    comp, rnd = _get_caf_match_info(data, team_id, next_caf)
                    violations.append(CAFViolation(
                        match=sm,
                        affected_team_id=team_id,
                        conflicting_caf_date=next_caf,
                        conflicting_caf_competition=comp,
                        conflicting_caf_round=rnd,
                        conflict_direction="PRE",
                        violation_reason=(
                            f"League match on {match_date} is only {gap} days before "
                            f"{team_id}'s CAF match ({comp} {rnd}) on {next_caf} "
                            f"(need >= {buffer_days + 1} days apart)"
                        ),
                    ))
                    violation_match_idxs.add(sm.match_idx)
                    continue

            # Check POST: league match too close AFTER a CAF match
            prev_caf = _find_nearest_caf(match_date, caf_dates, "before")
            if prev_caf is not None:
                gap = (match_date - prev_caf).days
                if gap < buffer_days + 1:  # need at least 5 days apart
                    comp, rnd = _get_caf_match_info(data, team_id, prev_caf)
                    violations.append(CAFViolation(
                        match=sm,
                        affected_team_id=team_id,
                        conflicting_caf_date=prev_caf,
                        conflicting_caf_competition=comp,
                        conflicting_caf_round=rnd,
                        conflict_direction="POST",
                        violation_reason=(
                            f"League match on {match_date} is only {gap} days after "
                            f"{team_id}'s CAF match ({comp} {rnd}) on {prev_caf} "
                            f"(need >= {buffer_days + 1} days apart)"
                        ),
                    ))
                    violation_match_idxs.add(sm.match_idx)

    # Split into accepted and violated
    accepted = [sm for sm in baseline if sm.match_idx not in violation_match_idxs]

    print(f"[caf_audit] {len(violations)} violations found across "
          f"{len(violation_match_idxs)} matches.")
    print(f"[caf_audit] {len(accepted)} accepted, "
          f"{len(violation_match_idxs)} queued for repair.")

    _write_queue_csv(violations, data)
    _write_audit_csv(baseline, violation_match_idxs)

    return accepted, violations


def _write_queue_csv(violations: List[CAFViolation], data: LeagueData) -> None:
    os.makedirs("output", exist_ok=True)
    path = os.path.join("output", "caf_postponement_queue.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Round", "Home_Team_ID", "Away_Team_ID",
            "Date", "Date_time", "Day_ID", "Calendar_Week_Num",
            "Venue_Stadium_ID",
            "Violation_Reason", "Affected_Team_ID",
            "Conflicting_CAF_Match", "Conflicting_CAF_Date",
            "Conflict_Direction",
            "Repair_Feasible_Slot_Count", "Repair_Status",
        ])
        seen = set()
        for v in violations:
            sm = v.match
            if sm.match_idx in seen:
                continue
            seen.add(sm.match_idx)
            writer.writerow([
                sm.round_num, sm.home_team, sm.away_team,
                sm.date, sm.date_time, sm.day_id, sm.week_num,
                sm.venue,
                v.violation_reason, v.affected_team_id,
                f"{v.conflicting_caf_competition} {v.conflicting_caf_round}",
                v.conflicting_caf_date,
                v.conflict_direction,
                "",  # filled after repair
                "PENDING",
            ])


def _write_audit_csv(
    baseline: List[ScheduledMatch], violation_idxs: set
) -> None:
    os.makedirs(PHASES_DIR, exist_ok=True)
    path = os.path.join(PHASES_DIR, "07_caf_audit.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "match_idx", "round", "home", "away", "date",
            "caf_violated", "violation_reason",
        ])
        for sm in baseline:
            writer.writerow([
                sm.match_idx, sm.round_num, sm.home_team, sm.away_team,
                sm.date,
                sm.match_idx in violation_idxs,
                "",
            ])
