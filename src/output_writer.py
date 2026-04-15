"""Write all output CSV files and the final optimized schedule."""

from __future__ import annotations

import csv
import os
from collections import defaultdict
from typing import Dict, List

from src.baseline_solver import ScheduledMatch
from src.caf_audit import CAFViolation
from src.constants import OUTPUT_DIR


def write_pre_caf_schedule(baseline: List[ScheduledMatch]) -> None:
    """Write output/optimized_schedule_pre_caf.csv — full baseline before CAF."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, "optimized_schedule_pre_caf.csv")
    _write_schedule_csv(path, baseline, postponed_set=set())
    print(f"[output] Wrote {path} ({len(baseline)} rows)")


def write_final_schedule(
    accepted: List[ScheduledMatch],
    repaired: List[ScheduledMatch],
    violations: List[CAFViolation],
) -> None:
    """Write output/optimized_schedule.csv — final after CAF repair."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Build violation info lookup for postponed matches
    violation_info: Dict[int, CAFViolation] = {}
    for v in violations:
        if v.match.match_idx not in violation_info:
            violation_info[v.match.match_idx] = v

    repaired_set = {sm.match_idx for sm in repaired}

    # Combine accepted + repaired
    all_matches = list(accepted) + list(repaired)
    all_matches.sort(key=lambda sm: (sm.date, sm.round_num))

    path = os.path.join(OUTPUT_DIR, "optimized_schedule.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Round", "Calendar_Week_Num", "Day_ID", "Date", "Date_time",
            "Home_Team_ID", "Away_Team_ID", "Venue_Stadium_ID",
            "Travel_km", "Slot_tier", "Home_Tier", "Away_Tier", "Match_Tier",
            "Is_FIFA", "Is_CAF",
            "Postponed", "Postponement_Status", "Postponement_Reason",
        ])
        for sm in all_matches:
            is_postponed = sm.match_idx in repaired_set
            v = violation_info.get(sm.match_idx)
            status = ""
            reason = ""
            if is_postponed and v:
                status = "REPAIRED"
                reason = v.violation_reason

            writer.writerow([
                sm.round_num, sm.week_num, sm.day_id, sm.date, sm.date_time,
                sm.home_team, sm.away_team, sm.venue,
                sm.travel_km, sm.slot_tier, "", "", sm.match_tier,
                "False", "False",
                is_postponed, status, reason,
            ])

    print(f"[output] Wrote {path} ({len(all_matches)} rows)")


def write_rescheduled_matches(repaired: List[ScheduledMatch]) -> None:
    """Write output/caf_rescheduled_matches.csv."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, "caf_rescheduled_matches.csv")
    _write_schedule_csv(path, repaired, postponed_set={sm.match_idx for sm in repaired})
    print(f"[output] Wrote {path} ({len(repaired)} rows)")


def write_unresolved(unresolved: List[ScheduledMatch]) -> None:
    """Write output/unresolved_caf_postponements.csv."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, "unresolved_caf_postponements.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Round", "Home_Team_ID", "Away_Team_ID",
            "Original_Date", "Venue_Stadium_ID", "Match_Tier",
            "Status",
        ])
        for sm in unresolved:
            writer.writerow([
                sm.round_num, sm.home_team, sm.away_team,
                sm.date, sm.venue, sm.match_tier,
                "UNRESOLVED",
            ])
    print(f"[output] Wrote {path} ({len(unresolved)} rows)")


def write_week_round_map(
    accepted: List[ScheduledMatch],
    repaired: List[ScheduledMatch],
) -> None:
    """Write output/week_round_map.csv."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    all_matches = list(accepted) + list(repaired)

    round_weeks: Dict[int, set] = defaultdict(set)
    for sm in all_matches:
        round_weeks[sm.round_num].add(sm.week_num)

    path = os.path.join(OUTPUT_DIR, "week_round_map.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Round", "Calendar_Weeks", "Match_Count"])
        for r in sorted(round_weeks.keys()):
            weeks = sorted(round_weeks[r])
            count = sum(1 for sm in all_matches if sm.round_num == r)
            writer.writerow([r, ";".join(str(w) for w in weeks), count])

    print(f"[output] Wrote {path}")


def _write_schedule_csv(
    path: str,
    matches: List[ScheduledMatch],
    postponed_set: set,
) -> None:
    matches_sorted = sorted(matches, key=lambda sm: (sm.date, sm.round_num))
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Round", "Calendar_Week_Num", "Day_ID", "Date", "Date_time",
            "Home_Team_ID", "Away_Team_ID", "Venue_Stadium_ID",
            "Travel_km", "Slot_tier", "Match_Tier",
            "Postponed",
        ])
        for sm in matches_sorted:
            writer.writerow([
                sm.round_num, sm.week_num, sm.day_id, sm.date, sm.date_time,
                sm.home_team, sm.away_team, sm.venue,
                sm.travel_km, sm.slot_tier, sm.match_tier,
                sm.match_idx in postponed_set,
            ])
