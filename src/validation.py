"""Final schedule validation artifacts."""

from __future__ import annotations

import csv
import os
from collections import defaultdict
from datetime import date
from typing import Dict, List, Set, Tuple

from src.baseline_solver import ScheduledMatch
from src.constants import (
    MATCHES_PER_ROUND,
    MAX_MATCHES_PER_DAY,
    MIN_REST_DAYS_CAF,
    MIN_REST_DAYS_LOCAL,
    NUM_ROUNDS,
    NUM_TEAMS,
    PHASES_DIR,
)
from src.data_loader import LeagueData


def write_validation_reports(
    accepted: List[ScheduledMatch],
    repaired: List[ScheduledMatch],
    unresolved: List[ScheduledMatch],
    data: LeagueData,
) -> None:
    """Write final validation reports under output/phases."""

    os.makedirs(PHASES_DIR, exist_ok=True)

    all_matches = sorted(
        list(accepted) + list(repaired),
        key=lambda sm: (sm.date, str(sm.date_time), sm.round_num, sm.match_idx),
    )
    repaired_ids = {sm.match_idx for sm in repaired}

    issues: List[Dict[str, object]] = []
    sequence_rows = _build_team_sequence_rows(all_matches, repaired_ids, data, issues)

    _validate_completeness(all_matches, unresolved, issues)
    _validate_fifa(all_matches, data, issues)
    _validate_daily_load(all_matches, issues)
    _validate_venue_slots(all_matches, issues)
    _validate_global_round_order(accepted, issues)
    _validate_caf_buffers(all_matches, data, issues)

    _write_team_sequence(sequence_rows)
    _write_validation_report(issues)


def _build_team_sequence_rows(
    matches: List[ScheduledMatch],
    repaired_ids: Set[int],
    data: LeagueData,
    issues: List[Dict[str, object]],
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    team_ids = sorted(data.teams["Team_ID"].tolist())

    for team_id in team_ids:
        team_matches = [
            sm for sm in matches
            if sm.home_team == team_id or sm.away_team == team_id
        ]
        team_matches.sort(key=lambda sm: (sm.date, str(sm.date_time), sm.round_num))

        prev_date: date | None = None
        prev_non_postponed_round: int | None = None
        streak_side = ""
        streak_len = 0
        sequence: List[str] = []

        for idx, sm in enumerate(team_matches, start=1):
            side = "H" if sm.home_team == team_id else "A"
            opponent = sm.away_team if sm.home_team == team_id else sm.home_team
            is_postponed = sm.match_idx in repaired_ids

            if side == streak_side:
                streak_len += 1
            else:
                streak_side = side
                streak_len = 1

            gap = "" if prev_date is None else (sm.date - prev_date).days
            rest_violation = isinstance(gap, int) and gap < MIN_REST_DAYS_LOCAL + 1
            streak_violation = streak_len > 2

            round_inversion = False
            inversion_previous_round = prev_non_postponed_round
            if not is_postponed:
                if (
                    prev_non_postponed_round is not None
                    and sm.round_num < prev_non_postponed_round
                ):
                    round_inversion = True
                prev_non_postponed_round = sm.round_num

            sequence.append(side)
            rolling5_home_count = ""
            rolling5_violation = False
            if len(sequence) >= 5:
                rolling5_home_count = sequence[-5:].count("H")
                rolling5_violation = rolling5_home_count not in (2, 3)

            if rest_violation:
                _add_issue(
                    issues,
                    "ERROR",
                    "TEAM_REST",
                    team_id,
                    sm.round_num,
                    sm.date,
                    f"{team_id} has only {gap} days since its previous league match",
                )
            if streak_violation:
                _add_issue(
                    issues,
                    "ERROR",
                    "TEAM_HOME_AWAY_STREAK",
                    team_id,
                    sm.round_num,
                    sm.date,
                    f"{team_id} has {streak_len} consecutive {side} matches",
                )
            if round_inversion:
                _add_issue(
                    issues,
                    "ERROR",
                    "TEAM_ROUND_ORDER",
                    team_id,
                    sm.round_num,
                    sm.date,
                    (
                        f"{team_id} plays non-postponed round {sm.round_num} after "
                        f"round {inversion_previous_round}"
                    ),
                )
            if rolling5_violation:
                _add_issue(
                    issues,
                    "WARN",
                    "TEAM_ROLLING5_BALANCE",
                    team_id,
                    sm.round_num,
                    sm.date,
                    (
                        f"{team_id} has {rolling5_home_count} home matches in the "
                        "latest five-match window"
                    ),
                )

            rows.append({
                "Team_ID": team_id,
                "Sequence_Index": idx,
                "Round": sm.round_num,
                "Date": sm.date,
                "Date_time": sm.date_time,
                "Side": side,
                "Opponent": opponent,
                "Home_Team_ID": sm.home_team,
                "Away_Team_ID": sm.away_team,
                "Venue_Stadium_ID": sm.venue,
                "Postponed": is_postponed,
                "Gap_Days_From_Previous": gap,
                "Streak_Length": streak_len,
                "Streak_Violation": streak_violation,
                "Rolling5_Home_Count": rolling5_home_count,
                "Rolling5_Balance_Violation": rolling5_violation,
                "Round_Inversion": round_inversion,
            })

            prev_date = sm.date

    return rows


def _validate_completeness(
    matches: List[ScheduledMatch],
    unresolved: List[ScheduledMatch],
    issues: List[Dict[str, object]],
) -> None:
    expected = NUM_ROUNDS * MATCHES_PER_ROUND
    total_known = len(matches) + len(unresolved)
    if total_known != expected:
        _add_issue(
            issues,
            "ERROR",
            "FIXTURE_COUNT",
            "",
            "",
            "",
            f"Expected {expected} played/unresolved fixtures, got {total_known}",
        )

    ordered_pairs = {(sm.home_team, sm.away_team) for sm in matches + unresolved}
    expected_pairs = NUM_TEAMS * (NUM_TEAMS - 1)
    if len(ordered_pairs) != expected_pairs:
        _add_issue(
            issues,
            "ERROR",
            "ORDERED_PAIR_COUNT",
            "",
            "",
            "",
            f"Expected {expected_pairs} ordered pairs, got {len(ordered_pairs)}",
        )

    if unresolved:
        _add_issue(
            issues,
            "WARN",
            "UNRESOLVED_POSTPONEMENTS",
            "",
            "",
            "",
            (
                f"{len(unresolved)} CAF-postponed fixtures remain unresolved; "
                "played-sequence validation is for the accepted/repaired schedule only"
            ),
        )


def _validate_fifa(
    matches: List[ScheduledMatch],
    data: LeagueData,
    issues: List[Dict[str, object]],
) -> None:
    for sm in matches:
        if sm.date in data.fifa_dates:
            _add_issue(
                issues,
                "ERROR",
                "FIFA_DATE",
                "",
                sm.round_num,
                sm.date,
                f"{sm.home_team} vs {sm.away_team} is scheduled on a FIFA date",
            )


def _validate_venue_slots(
    matches: List[ScheduledMatch],
    issues: List[Dict[str, object]],
) -> None:
    by_venue_slot: Dict[Tuple[str, int], List[ScheduledMatch]] = defaultdict(list)
    for sm in matches:
        by_venue_slot[(sm.venue, sm.slot_idx)].append(sm)

    for (venue, slot_idx), group in by_venue_slot.items():
        if len(group) > 1:
            _add_issue(
                issues,
                "ERROR",
                "VENUE_SLOT_CONFLICT",
                "",
                "",
                group[0].date,
                f"{venue} has {len(group)} matches in slot index {slot_idx}",
            )


def _validate_daily_load(
    matches: List[ScheduledMatch],
    issues: List[Dict[str, object]],
) -> None:
    by_date: Dict[date, List[ScheduledMatch]] = defaultdict(list)
    for sm in matches:
        by_date[sm.date].append(sm)

    for match_date, group in by_date.items():
        if len(group) > MAX_MATCHES_PER_DAY:
            _add_issue(
                issues,
                "ERROR",
                "DAILY_MATCH_CAP",
                "",
                "",
                match_date,
                (
                    f"{len(group)} matches are scheduled on {match_date}; "
                    f"maximum allowed is {MAX_MATCHES_PER_DAY}"
                ),
            )


def _validate_global_round_order(
    accepted: List[ScheduledMatch],
    issues: List[Dict[str, object]],
) -> None:
    by_round: Dict[int, List[ScheduledMatch]] = defaultdict(list)
    for sm in accepted:
        by_round[sm.round_num].append(sm)

    for round_num in range(1, NUM_ROUNDS):
        current = by_round.get(round_num, [])
        nxt = by_round.get(round_num + 1, [])
        if not current or not nxt:
            continue
        current_latest = max((sm.date, str(sm.date_time)) for sm in current)
        next_earliest = min((sm.date, str(sm.date_time)) for sm in nxt)
        if current_latest > next_earliest:
            _add_issue(
                issues,
                "ERROR",
                "GLOBAL_ROUND_ORDER",
                "",
                round_num + 1,
                next_earliest[0],
                (
                    f"Non-postponed round {round_num + 1} starts before "
                    f"round {round_num} has finished"
                ),
            )


def _validate_caf_buffers(
    matches: List[ScheduledMatch],
    data: LeagueData,
    issues: List[Dict[str, object]],
) -> None:
    caf_teams = {
        row["Team_ID"]
        for _, row in data.teams.iterrows()
        if row["Cont_Flag"] in ("CL", "CC")
    }
    required_gap = MIN_REST_DAYS_CAF + 1

    for sm in matches:
        for team_id in (sm.home_team, sm.away_team):
            if team_id not in caf_teams:
                continue
            for caf_date in data.caf_dates_by_team.get(team_id, []):
                gap = abs((sm.date - caf_date).days)
                if gap < required_gap:
                    _add_issue(
                        issues,
                        "ERROR",
                        "CAF_BUFFER",
                        team_id,
                        sm.round_num,
                        sm.date,
                        (
                            f"{team_id} league match is {gap} days from CAF date "
                            f"{caf_date}; need at least {required_gap}"
                        ),
                    )


def _write_team_sequence(rows: List[Dict[str, object]]) -> None:
    path = os.path.join(PHASES_DIR, "10_team_sequence_validation.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        if not rows:
            return
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_validation_report(issues: List[Dict[str, object]]) -> None:
    path = os.path.join(PHASES_DIR, "10_final_validation_report.csv")
    fields = ["Severity", "Check", "Team_ID", "Round", "Date", "Detail"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        if not issues:
            writer.writerow({
                "Severity": "PASS",
                "Check": "ALL",
                "Team_ID": "",
                "Round": "",
                "Date": "",
                "Detail": "No validation issues found",
            })
        else:
            writer.writerows(issues)


def _add_issue(
    issues: List[Dict[str, object]],
    severity: str,
    check: str,
    team_id: object,
    round_num: object,
    match_date: object,
    detail: str,
) -> None:
    issues.append({
        "Severity": severity,
        "Check": check,
        "Team_ID": team_id,
        "Round": round_num,
        "Date": match_date,
        "Detail": detail,
    })
