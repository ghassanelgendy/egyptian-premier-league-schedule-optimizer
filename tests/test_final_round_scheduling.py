from __future__ import annotations

import unittest
from datetime import date, datetime, time, timedelta

import pandas as pd

from src.baseline_solver import ScheduledMatch, solve_baseline
from src.caf_audit import CAFViolation
from src.caf_repair_solver import caf_repair
from src.constants import FINAL_ROUND_NUM, MATCHES_PER_ROUND, NUM_ROUNDS
from src.data_loader import LeagueData, SecRule
from src.fixture_generator import Match
from src.slot_domain import build_domains
from src.validation import (
    _validate_daily_load,
    _validate_final_round_same_slot,
    _validate_slot_load,
)


def _slot_row(
    match_date: date,
    week_num: int,
    slot_suffix: str,
    hour: int = 19,
    day_name: str = "SAT",
) -> dict:
    kickoff = datetime.combine(match_date, time(hour=hour))
    return {
        "Date": pd.Timestamp(match_date),
        "_date": match_date,
        "Week_Num": week_num,
        "Day_name": day_name,
        "Day_ID": f"D_{match_date:%Y%m%d}_{slot_suffix}",
        "Date time": pd.Timestamp(kickoff),
    }


def _make_league_data(
    team_ids: list[str],
    slot_rows: list[dict],
    home_stadium_by_team: dict[str, str] | None = None,
    alt_stadium_by_team: dict[str, str] | None = None,
    tier_by_team: dict[str, int] | None = None,
    caf_dates_by_team: dict[str, list[date]] | None = None,
    extra_stadium_ids: list[str] | None = None,
    dist_matrix_override: dict[str, dict[str, float]] | None = None,
    sec_rules: list[SecRule] | None = None,
) -> LeagueData:
    caf_dates_by_team = caf_dates_by_team or {}
    alt_stadium_by_team = alt_stadium_by_team or {}
    tier_by_team = tier_by_team or {}
    home_stadium_by_team = home_stadium_by_team or {
        team_id: f"ST_{team_id}"
        for team_id in team_ids
    }

    teams = pd.DataFrame([
        {
            "Team_ID": team_id,
            "Home_Stadium_ID": home_stadium_by_team[team_id],
            "Alt_Stadium_ID": alt_stadium_by_team.get(team_id, ""),
            "Tier": tier_by_team.get(team_id, 3),
            "Cont_Flag": "CL" if team_id in caf_dates_by_team else "",
        }
        for team_id in team_ids
    ])
    unique_stadiums = set(home_stadium_by_team.values())
    unique_stadiums |= {venue for venue in alt_stadium_by_team.values() if venue}
    unique_stadiums |= set(extra_stadium_ids or [])
    unique_stadiums = sorted(unique_stadiums)
    stadiums = pd.DataFrame([
        {
            "Stadium_ID": stadium_id,
            "Stadium_Name": stadium_id,
            "Gov_ID": "",
            "City": "",
            "Is_Floodlit": 1,
        }
        for stadium_id in unique_stadiums
    ])

    if dist_matrix_override is None:
        dist_matrix = {
            stadium_id: {
                other_id: 0.0
                for other_id in unique_stadiums
            }
            for stadium_id in unique_stadiums
        }
    else:
        dist_matrix = dist_matrix_override
    slots = pd.DataFrame(slot_rows).reset_index(drop=True)

    return LeagueData(
        teams=teams,
        stadiums=stadiums,
        dist_matrix=dist_matrix,
        sec_rules=sec_rules or [],
        slots=slots.copy(),
        usable_slots=slots.copy(),
        fifa_dates=set(),
        caf_blockers=pd.DataFrame(),
        caf_dates_by_team={team_id: sorted(set(dates)) for team_id, dates in caf_dates_by_team.items()},
        unique_caf_dates={d for dates in caf_dates_by_team.values() for d in dates},
    )


def _build_baseline_inputs() -> tuple[LeagueData, list[Match], dict[int, list[int]]]:
    base_date = date(2026, 1, 1)
    slot_rows: list[dict] = []
    matches: list[Match] = []
    domains: dict[int, list[int]] = {}

    home_stadium_by_team = {
        "A": "VA",
        "B": "VB",
    }
    alt_stadium_by_team: dict[str, str] = {}
    tier_by_team: dict[str, int] = {"A": 3, "B": 3}

    for round_num in range(1, NUM_ROUNDS):
        slot_idx = len(slot_rows)
        match_date = base_date + timedelta(days=(round_num - 1) * 4)
        slot_rows.append(_slot_row(match_date, round_num, f"R{round_num}"))
        matches.append(Match(
            match_idx=len(matches),
            round_num=round_num,
            home_team="A",
            away_team="B",
            venue="VA",
            match_tier=3,
        ))
        domains[matches[-1].match_idx] = [slot_idx]

    final_date = base_date + timedelta(days=(NUM_ROUNDS - 1) * 4)
    final_slot_0 = len(slot_rows)
    slot_rows.append(_slot_row(final_date, NUM_ROUNDS, "FR_A", hour=19))
    final_slot_1 = len(slot_rows)
    slot_rows.append(_slot_row(final_date, NUM_ROUNDS, "FR_B", hour=21))

    special_home_teams = {"F0": 1, "F2": 2, "F4": 4}
    for team_id, tier in special_home_teams.items():
        home_stadium_by_team[team_id] = "VF_HOME"
        alt_stadium_by_team[team_id] = "VF_ALT"
        tier_by_team[team_id] = tier

    final_teams = [f"F{i}" for i in range(MATCHES_PER_ROUND * 2)]
    for idx in range(MATCHES_PER_ROUND):
        home_team = final_teams[idx * 2]
        away_team = final_teams[idx * 2 + 1]
        home_stadium_by_team.setdefault(home_team, f"VF_{idx}")
        home_stadium_by_team[away_team] = home_stadium_by_team[home_team]
        tier_by_team.setdefault(home_team, 3)
        tier_by_team[away_team] = 3

    for idx in range(MATCHES_PER_ROUND):
        home_team = final_teams[idx * 2]
        away_team = final_teams[idx * 2 + 1]
        venue = home_stadium_by_team[home_team]
        matches.append(Match(
            match_idx=len(matches),
            round_num=FINAL_ROUND_NUM,
            home_team=home_team,
            away_team=away_team,
            venue=venue,
            match_tier=3,
        ))
        domains[matches[-1].match_idx] = [final_slot_0, final_slot_1]

    stadium_ids = {
        *home_stadium_by_team.values(),
        *alt_stadium_by_team.values(),
        "VF_NEAR",
    }
    stadium_ids = {stadium_id for stadium_id in stadium_ids if stadium_id}
    dist_matrix = {
        stadium_id: {
            other_id: 0.0 if stadium_id == other_id else 1_000.0
            for other_id in stadium_ids
        }
        for stadium_id in stadium_ids
    }
    dist_matrix["VF_HOME"]["VF_ALT"] = 5.0
    dist_matrix["VF_ALT"]["VF_HOME"] = 5.0
    dist_matrix["VF_HOME"]["VF_NEAR"] = 10.0
    dist_matrix["VF_NEAR"]["VF_HOME"] = 10.0
    dist_matrix["VF_ALT"]["VF_NEAR"] = 7.0
    dist_matrix["VF_NEAR"]["VF_ALT"] = 7.0

    data = _make_league_data(
        ["A", "B", *final_teams],
        slot_rows,
        home_stadium_by_team=home_stadium_by_team,
        alt_stadium_by_team=alt_stadium_by_team,
        tier_by_team=tier_by_team,
        extra_stadium_ids=["VF_NEAR"],
        dist_matrix_override=dist_matrix,
    )
    return data, matches, domains


def _build_repair_case(
    include_neutral_fallback: bool,
) -> tuple[LeagueData, list[ScheduledMatch], list[CAFViolation], date]:
    base_date = date(2026, 1, 1)
    slot_rows: list[dict] = []
    accepted: list[ScheduledMatch] = []
    home_stadium_by_team = {
        "A": "VR_HOME",
        "B": "VR_HOME",
    }
    alt_stadium_by_team: dict[str, str] = {}
    tier_by_team: dict[str, int] = {"A": 3, "B": 3}

    for round_num in range(1, NUM_ROUNDS):
        match_date = base_date + timedelta(days=(round_num - 1) * 4)
        slot_idx = len(slot_rows)
        slot_rows.append(_slot_row(match_date, round_num, f"R{round_num}"))
        accepted.append(ScheduledMatch(
            match_idx=len(accepted),
            round_num=round_num,
            home_team="A",
            away_team="B",
            venue=home_stadium_by_team["A"],
            match_tier=3,
            slot_idx=slot_idx,
            day_id=slot_rows[-1]["Day_ID"],
            date=match_date,
            date_time=slot_rows[-1]["Date time"],
            week_num=round_num,
            day_name=slot_rows[-1]["Day_name"],
            slot_tier=2,
            travel_km=0.0,
            is_forced_venue=False,
        ))

    original_final_date = base_date + timedelta(days=(NUM_ROUNDS - 1) * 4)
    original_slot_0 = len(slot_rows)
    slot_rows.append(_slot_row(original_final_date, NUM_ROUNDS, "FR_A", hour=19))
    original_slot_1 = len(slot_rows)
    slot_rows.append(_slot_row(original_final_date, NUM_ROUNDS, "FR_B", hour=21))

    special_home_teams = {"R0": 1, "R2": 2, "R4": 4}
    for team_id, tier in special_home_teams.items():
        home_stadium_by_team[team_id] = "VR_HOME"
        alt_stadium_by_team[team_id] = "VR_ALT"
        tier_by_team[team_id] = tier

    final_teams = [f"R{i}" for i in range(MATCHES_PER_ROUND * 2)]
    for idx in range(MATCHES_PER_ROUND):
        home_team = final_teams[idx * 2]
        away_team = final_teams[idx * 2 + 1]
        home_stadium_by_team.setdefault(home_team, f"VR_{idx}")
        home_stadium_by_team[away_team] = home_stadium_by_team[home_team]
        tier_by_team.setdefault(home_team, 3)
        tier_by_team[away_team] = 3

    round_34_matches: list[ScheduledMatch] = []
    for idx in range(MATCHES_PER_ROUND):
        home_team = final_teams[idx * 2]
        away_team = final_teams[idx * 2 + 1]
        venue = home_stadium_by_team[home_team]
        slot_idx = original_slot_1 if idx == 1 else original_slot_0
        scheduled = ScheduledMatch(
            match_idx=len(accepted),
            round_num=FINAL_ROUND_NUM,
            home_team=home_team,
            away_team=away_team,
            venue=venue,
            match_tier=3,
            slot_idx=slot_idx,
            day_id=slot_rows[slot_idx]["Day_ID"],
            date=original_final_date,
            date_time=slot_rows[slot_idx]["Date time"],
            week_num=NUM_ROUNDS,
            day_name=slot_rows[slot_idx]["Day_name"],
            slot_tier=2,
            travel_km=0.0,
            is_forced_venue=False,
        )
        accepted.append(scheduled)
        round_34_matches.append(scheduled)

    repaired_final_date = original_final_date + timedelta(days=6)
    slot_rows.append(
        _slot_row(repaired_final_date, NUM_ROUNDS + 1, "ALT_SHARED", hour=20)
    )

    violating_match = round_34_matches[0]
    violations = [
        CAFViolation(
            match=violating_match,
            affected_team_id=violating_match.home_team,
            conflicting_caf_date=original_final_date + timedelta(days=2),
            conflicting_caf_competition="CAF",
            conflicting_caf_round="QF",
            conflict_direction="POST",
            violation_reason="Synthetic CAF conflict for final-round repair test",
        )
    ]

    extra_stadium_ids = ["VR_NEAR"] if include_neutral_fallback else []
    stadium_ids = {
        *home_stadium_by_team.values(),
        *alt_stadium_by_team.values(),
        *extra_stadium_ids,
    }
    stadium_ids = {stadium_id for stadium_id in stadium_ids if stadium_id}
    dist_matrix = {
        stadium_id: {
            other_id: 0.0 if stadium_id == other_id else 1_000.0
            for other_id in stadium_ids
        }
        for stadium_id in stadium_ids
    }
    if "VR_ALT" in dist_matrix and "VR_HOME" in dist_matrix:
        dist_matrix["VR_HOME"]["VR_ALT"] = 5.0
        dist_matrix["VR_ALT"]["VR_HOME"] = 5.0
    if include_neutral_fallback:
        dist_matrix["VR_HOME"]["VR_NEAR"] = 10.0
        dist_matrix["VR_NEAR"]["VR_HOME"] = 10.0
        dist_matrix["VR_ALT"]["VR_NEAR"] = 7.0
        dist_matrix["VR_NEAR"]["VR_ALT"] = 7.0

    data = _make_league_data(
        ["A", "B", *final_teams],
        slot_rows,
        home_stadium_by_team=home_stadium_by_team,
        alt_stadium_by_team=alt_stadium_by_team,
        tier_by_team=tier_by_team,
        caf_dates_by_team={
            violating_match.home_team: [original_final_date + timedelta(days=2)]
        },
        extra_stadium_ids=extra_stadium_ids,
        dist_matrix_override=dist_matrix,
    )
    return data, accepted, violations, repaired_final_date


def _build_rescue_inputs() -> tuple[LeagueData, list[Match], dict[int, list[int]]]:
    base_date = date(2026, 1, 1)
    slot_rows: list[dict] = []
    matches: list[Match] = []
    domains: dict[int, list[int]] = {}

    home_stadium_by_team = {
        "A": "VA",
        "B": "VB",
    }
    alt_stadium_by_team: dict[str, str] = {}
    tier_by_team: dict[str, int] = {"A": 3, "B": 3}

    for round_num in range(1, NUM_ROUNDS):
        slot_idx = len(slot_rows)
        match_date = base_date + timedelta(days=(round_num - 1) * 4)
        slot_rows.append(_slot_row(match_date, round_num, f"R{round_num}"))
        matches.append(Match(
            match_idx=len(matches),
            round_num=round_num,
            home_team="A",
            away_team="B",
            venue="VA",
            match_tier=3,
        ))
        domains[matches[-1].match_idx] = [slot_idx]

    final_date = base_date + timedelta(days=(NUM_ROUNDS - 1) * 4)
    final_slot_0 = len(slot_rows)
    slot_rows.append(_slot_row(final_date, NUM_ROUNDS, "FR_A", hour=16, day_name="WED"))
    final_slot_1 = len(slot_rows)
    slot_rows.append(_slot_row(final_date, NUM_ROUNDS, "FR_B", hour=18, day_name="WED"))

    special_home_teams = {"F0": 1, "F2": 2, "F4": 4}
    for team_id, tier in special_home_teams.items():
        home_stadium_by_team[team_id] = "VF_HOME"
        alt_stadium_by_team[team_id] = "VF_ALT"
        tier_by_team[team_id] = tier

    final_teams = [f"F{i}" for i in range(MATCHES_PER_ROUND * 2)]
    for idx in range(MATCHES_PER_ROUND):
        home_team = final_teams[idx * 2]
        away_team = final_teams[idx * 2 + 1]
        home_stadium_by_team.setdefault(home_team, f"VF_{idx}")
        home_stadium_by_team[away_team] = home_stadium_by_team[home_team]
        tier_by_team.setdefault(home_team, 3)
        tier_by_team.setdefault(away_team, 3)

    tier_by_team["F1"] = 1
    sec_rules = [
        SecRule("F0", "F1", "VF_BANNED", "", "VF_HOME"),
        SecRule("F2", "F3", "VF_BANNED", "", "VF_HOME"),
        SecRule("F4", "F5", "VF_BANNED", "", "VF_HOME"),
    ]

    for idx in range(MATCHES_PER_ROUND):
        home_team = final_teams[idx * 2]
        away_team = final_teams[idx * 2 + 1]
        venue = home_stadium_by_team[home_team]
        match_tier = 1 if {home_team, away_team} == {"F0", "F1"} else 3
        matches.append(Match(
            match_idx=len(matches),
            round_num=FINAL_ROUND_NUM,
            home_team=home_team,
            away_team=away_team,
            venue=venue,
            match_tier=match_tier,
        ))
        domains[matches[-1].match_idx] = [final_slot_0, final_slot_1]

    stadium_ids = {
        *home_stadium_by_team.values(),
        *alt_stadium_by_team.values(),
        "VF_NEAR",
        "VF_BANNED",
    }
    stadium_ids = {stadium_id for stadium_id in stadium_ids if stadium_id}
    dist_matrix = {
        stadium_id: {
            other_id: 0.0 if stadium_id == other_id else 1_000.0
            for other_id in stadium_ids
        }
        for stadium_id in stadium_ids
    }
    dist_matrix["VF_HOME"]["VF_ALT"] = 5.0
    dist_matrix["VF_ALT"]["VF_HOME"] = 5.0
    dist_matrix["VF_HOME"]["VF_BANNED"] = 1.0
    dist_matrix["VF_BANNED"]["VF_HOME"] = 1.0
    dist_matrix["VF_HOME"]["VF_NEAR"] = 10.0
    dist_matrix["VF_NEAR"]["VF_HOME"] = 10.0
    dist_matrix["VF_ALT"]["VF_NEAR"] = 7.0
    dist_matrix["VF_NEAR"]["VF_ALT"] = 7.0
    dist_matrix["VF_ALT"]["VF_BANNED"] = 2.0
    dist_matrix["VF_BANNED"]["VF_ALT"] = 2.0

    data = _make_league_data(
        ["A", "B", *final_teams],
        slot_rows,
        home_stadium_by_team=home_stadium_by_team,
        alt_stadium_by_team=alt_stadium_by_team,
        tier_by_team=tier_by_team,
        extra_stadium_ids=["VF_NEAR", "VF_BANNED"],
        dist_matrix_override=dist_matrix,
        sec_rules=sec_rules,
    )
    return data, matches, domains


class FinalRoundSchedulingTests(unittest.TestCase):
    def test_domains_bind_non_final_windows_and_final_round_tail(self) -> None:
        team_ids = [f"T{i}" for i in range(18)]
        slot_rows: list[dict] = []
        start_date = date(2026, 1, 1)
        total_days = (NUM_ROUNDS * 5) + 5

        for day_offset in range(total_days):
            current_date = start_date + timedelta(days=day_offset)
            week_num = 1 + (day_offset // 5)
            slot_rows.append(_slot_row(current_date, week_num, f"{day_offset}_A", hour=16))
            slot_rows.append(_slot_row(current_date, week_num, f"{day_offset}_B", hour=19))
            slot_rows.append(_slot_row(current_date, week_num, f"{day_offset}_C", hour=21))

        data = _make_league_data(team_ids, slot_rows)
        matches = [
            Match(0, 10, team_ids[0], team_ids[1], f"ST_{team_ids[0]}", match_tier=3),
            Match(1, FINAL_ROUND_NUM, team_ids[2], team_ids[3], f"ST_{team_ids[2]}", match_tier=3),
        ]

        domains = build_domains(data, matches)
        round_10_dates = {data.usable_slots.loc[idx, "_date"] for idx in domains[0]}
        round_34_dates = {data.usable_slots.loc[idx, "_date"] for idx in domains[1]}

        self.assertEqual(
            round_10_dates,
            {
                start_date + timedelta(days=45 + offset)
                for offset in range(5)
            },
        )
        self.assertEqual(
            round_34_dates,
            {
                start_date + timedelta(days=165 + offset)
                for offset in range(10)
            },
        )

    def test_non_final_round_widens_only_when_base_window_is_too_tight(self) -> None:
        team_ids = [f"T{i}" for i in range(18)]
        slot_rows: list[dict] = []
        start_date = date(2026, 1, 1)
        total_days = (NUM_ROUNDS * 5) + 10
        stressed_slot_counts = {
            45: 2,
            46: 2,
            47: 2,
            48: 2,
            49: 1,
            50: 2,
            51: 2,
        }

        for day_offset in range(total_days):
            current_date = start_date + timedelta(days=day_offset)
            week_num = 1 + (day_offset // 5)
            slot_count = stressed_slot_counts.get(day_offset, 2)
            for slot_num in range(slot_count):
                slot_rows.append(
                    _slot_row(current_date, week_num, f"{day_offset}_{slot_num}", hour=18 + slot_num)
                )

        data = _make_league_data(team_ids, slot_rows)
        matches = [
            Match(0, 10, team_ids[0], team_ids[1], f"ST_{team_ids[0]}", match_tier=3),
        ]

        domains = build_domains(data, matches)
        round_10_dates = sorted({data.usable_slots.loc[idx, "_date"] for idx in domains[0]})

        self.assertEqual(round_10_dates[0], start_date + timedelta(days=45))
        self.assertEqual(round_10_dates[-1], start_date + timedelta(days=52))
        self.assertEqual(len(round_10_dates), 8)

    def test_epl_full_policy_spills_non_final_round_forward_without_touching_final_round(self) -> None:
        team_ids = [f"T{i}" for i in range(18)]
        slot_rows: list[dict] = []
        start_date = date(2026, 1, 1)
        total_days = (NUM_ROUNDS * 5) + 10

        for day_offset in range(total_days):
            current_date = start_date + timedelta(days=day_offset)
            week_num = 1 + (day_offset // 5)
            slot_rows.append(_slot_row(current_date, week_num, f"{day_offset}_A", hour=16))
            slot_rows.append(_slot_row(current_date, week_num, f"{day_offset}_B", hour=19))
            slot_rows.append(_slot_row(current_date, week_num, f"{day_offset}_C", hour=21))

        data = _make_league_data(team_ids, slot_rows)
        matches = [
            Match(0, 10, team_ids[0], team_ids[1], f"ST_{team_ids[0]}", match_tier=3),
            Match(1, FINAL_ROUND_NUM, team_ids[2], team_ids[3], f"ST_{team_ids[2]}", match_tier=3),
        ]

        domains = build_domains(data, matches, non_final_policy="epl_full")
        round_10_dates = {data.usable_slots.loc[idx, "_date"] for idx in domains[0]}
        round_34_dates = {data.usable_slots.loc[idx, "_date"] for idx in domains[1]}

        self.assertEqual(
            round_10_dates,
            {
                start_date + timedelta(days=45 + offset)
                for offset in range(total_days - 45)
            },
        )
        self.assertEqual(
            round_34_dates,
            {
                start_date + timedelta(days=165 + offset)
                for offset in range(total_days - 165)
            },
        )

    def test_epl_relaxed_policy_creates_bounded_spillover_window(self) -> None:
        team_ids = [f"T{i}" for i in range(18)]
        slot_rows: list[dict] = []
        start_date = date(2026, 1, 1)
        total_days = (NUM_ROUNDS * 5) + 10

        for day_offset in range(total_days):
            current_date = start_date + timedelta(days=day_offset)
            week_num = 1 + (day_offset // 5)
            slot_rows.append(_slot_row(current_date, week_num, f"{day_offset}_A", hour=16))
            slot_rows.append(_slot_row(current_date, week_num, f"{day_offset}_B", hour=19))
            slot_rows.append(_slot_row(current_date, week_num, f"{day_offset}_C", hour=21))

        data = _make_league_data(team_ids, slot_rows)
        matches = [
            Match(0, 10, team_ids[0], team_ids[1], f"ST_{team_ids[0]}", match_tier=3),
        ]

        domains = build_domains(data, matches, non_final_policy="epl_relaxed")
        round_10_dates = sorted({data.usable_slots.loc[idx, "_date"] for idx in domains[0]})

        self.assertEqual(round_10_dates[0], start_date + timedelta(days=45))
        self.assertEqual(round_10_dates[-1], start_date + timedelta(days=100))
        self.assertEqual(len(round_10_dates), 56)

    def test_baseline_packs_final_round_into_one_slot_with_tiered_displacement(self) -> None:
        data, matches, domains = _build_baseline_inputs()
        baseline = solve_baseline(data, matches, domains)

        self.assertIsNotNone(baseline)
        assert baseline is not None

        final_round = [match for match in baseline if match.round_num == FINAL_ROUND_NUM]
        self.assertEqual(len(final_round), MATCHES_PER_ROUND)
        self.assertEqual(len({match.date for match in final_round}), 1)
        self.assertEqual(len({match.slot_idx for match in final_round}), 1)

        by_home = {match.home_team: match for match in final_round}
        self.assertEqual(by_home["F0"].venue, "VF_HOME")
        self.assertEqual(by_home["F2"].venue, "VF_ALT")
        self.assertEqual(by_home["F4"].venue, "VF_NEAR")

    def test_baseline_uses_final_round_rescue_for_forced_venue_and_tier1_slot_conflicts(self) -> None:
        data, matches, domains = _build_rescue_inputs()
        baseline = solve_baseline(data, matches, domains)

        self.assertIsNotNone(baseline)
        assert baseline is not None

        final_round = [match for match in baseline if match.round_num == FINAL_ROUND_NUM]
        self.assertEqual(len(final_round), MATCHES_PER_ROUND)
        self.assertEqual(len({match.date for match in final_round}), 1)
        self.assertEqual(len({match.slot_idx for match in final_round}), 1)
        self.assertEqual({match.venue for match in final_round}.intersection({"VF_BANNED"}), set())

        by_home = {match.home_team: match for match in final_round}
        self.assertEqual(by_home["F0"].venue, "VF_HOME")
        self.assertEqual(by_home["F2"].venue, "VF_ALT")
        self.assertEqual(by_home["F4"].venue, "VF_NEAR")

    def test_final_round_repair_moves_whole_round_or_leaves_it_unresolved(self) -> None:
        repair_data, accepted, violations, repaired_date = _build_repair_case(
            include_neutral_fallback=True
        )
        repaired, unresolved = caf_repair(accepted, violations, repair_data)

        self.assertEqual(len(unresolved), 0)
        self.assertEqual(len(repaired), MATCHES_PER_ROUND)
        self.assertEqual(len([match for match in accepted if match.round_num == FINAL_ROUND_NUM]), 0)
        self.assertEqual({match.date for match in repaired}, {repaired_date})
        self.assertEqual(len({match.slot_idx for match in repaired}), 1)

        unresolved_data, accepted_unresolved, violations_unresolved, _ = _build_repair_case(
            include_neutral_fallback=False
        )
        repaired_unresolved, unresolved_only = caf_repair(
            accepted_unresolved,
            violations_unresolved,
            unresolved_data,
        )

        self.assertEqual(len(repaired_unresolved), 0)
        self.assertEqual(len(unresolved_only), MATCHES_PER_ROUND)

    def test_validation_relaxes_caps_only_for_a_valid_final_round_slot(self) -> None:
        final_date = date(2026, 6, 1)
        non_final_date = date(2026, 5, 20)
        matches = [
            ScheduledMatch(
                match_idx=idx,
                round_num=FINAL_ROUND_NUM,
                home_team=f"H{idx}",
                away_team=f"A{idx}",
                venue=f"V{idx}",
                match_tier=3,
                slot_idx=100,
                day_id=f"D_{final_date:%Y%m%d}",
                date=final_date,
                date_time=datetime.combine(final_date, time(hour=20)),
                week_num=40,
                day_name="SAT",
                slot_tier=1,
                travel_km=0.0,
                is_forced_venue=False,
            )
            for idx in range(MATCHES_PER_ROUND)
        ]
        matches.extend([
            ScheduledMatch(
                match_idx=1000 + idx,
                round_num=10,
                home_team=f"XH{idx}",
                away_team=f"XA{idx}",
                venue=f"XV{idx}",
                match_tier=3,
                slot_idx=200,
                day_id=f"D_{non_final_date:%Y%m%d}",
                date=non_final_date,
                date_time=datetime.combine(non_final_date, time(hour=18)),
                week_num=30,
                day_name="WED",
                slot_tier=3,
                travel_km=0.0,
                is_forced_venue=False,
            )
            for idx in range(4)
        ])

        issues: list[dict[str, object]] = []
        _validate_final_round_same_slot(matches, issues)
        valid_final_round_date = final_date
        valid_final_round_slot = 100
        _validate_daily_load(matches, issues, valid_final_round_date)
        _validate_slot_load(matches, issues, valid_final_round_slot)

        final_round_issues = [issue for issue in issues if issue["Date"] == final_date]
        non_final_issues = [issue for issue in issues if issue["Date"] == non_final_date]

        self.assertEqual(final_round_issues, [])
        self.assertEqual(
            {issue["Check"] for issue in non_final_issues},
            {"DAILY_MATCH_CAP", "SLOT_MATCH_CAP"},
        )


if __name__ == "__main__":
    unittest.main()
