from __future__ import annotations

import unittest
from datetime import date, datetime, time, timedelta

import pandas as pd

from src.baseline_solver import ScheduledMatch, solve_baseline
from src.caf_audit import CAFViolation
from src.caf_repair_solver import caf_repair
from src.constants import FINAL_ROUND_NUM, MATCHES_PER_ROUND, NUM_ROUNDS
from src.data_loader import LeagueData
from src.fixture_generator import Match
from src.slot_domain import build_domains
from src.validation import (
    _validate_daily_load,
    _validate_final_round_same_day,
    _validate_slot_load,
)


def _slot_row(match_date: date, week_num: int, slot_suffix: str, hour: int = 19) -> dict:
    kickoff = datetime.combine(match_date, time(hour=hour))
    return {
        "Date": pd.Timestamp(match_date),
        "_date": match_date,
        "Week_Num": week_num,
        "Day_name": "SAT",
        "Day_ID": f"D_{match_date:%Y%m%d}_{slot_suffix}",
        "Date time": pd.Timestamp(kickoff),
    }


def _make_league_data(
    team_ids: list[str],
    slot_rows: list[dict],
    home_stadium_by_team: dict[str, str] | None = None,
    caf_dates_by_team: dict[str, list[date]] | None = None,
) -> LeagueData:
    caf_dates_by_team = caf_dates_by_team or {}
    home_stadium_by_team = home_stadium_by_team or {
        team_id: f"ST_{team_id}"
        for team_id in team_ids
    }

    teams = pd.DataFrame([
        {
            "Team_ID": team_id,
            "Home_Stadium_ID": home_stadium_by_team[team_id],
            "Alt_Stadium_ID": "",
            "Tier": 3,
            "Cont_Flag": "CL" if team_id in caf_dates_by_team else "",
        }
        for team_id in team_ids
    ])
    unique_stadiums = sorted(set(home_stadium_by_team.values()))
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

    dist_matrix = {
        stadium_id: {
            other_id: 0.0
            for other_id in unique_stadiums
        }
        for stadium_id in unique_stadiums
    }
    slots = pd.DataFrame(slot_rows).reset_index(drop=True)

    return LeagueData(
        teams=teams,
        stadiums=stadiums,
        dist_matrix=dist_matrix,
        sec_rules=[],
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

    final_teams = [f"F{i}" for i in range(MATCHES_PER_ROUND * 2)]
    for team_id in final_teams:
        home_stadium_by_team[team_id] = f"ST_{team_id}"

    for idx in range(MATCHES_PER_ROUND):
        home_team = final_teams[idx * 2]
        away_team = final_teams[idx * 2 + 1]
        venue = "VF_DUP" if idx in (0, 1) else f"VF_{idx}"
        home_stadium_by_team[home_team] = venue
        matches.append(Match(
            match_idx=len(matches),
            round_num=FINAL_ROUND_NUM,
            home_team=home_team,
            away_team=away_team,
            venue=venue,
            match_tier=3,
        ))
        if idx == 1:
            domains[matches[-1].match_idx] = [final_slot_0, final_slot_1]
        else:
            domains[matches[-1].match_idx] = [final_slot_0]

    data = _make_league_data(
        ["A", "B", *final_teams],
        slot_rows,
        home_stadium_by_team=home_stadium_by_team,
    )
    return data, matches, domains


def _build_repair_case(
    alt_slot_count: int,
) -> tuple[LeagueData, list[ScheduledMatch], list[CAFViolation], date]:
    base_date = date(2026, 1, 1)
    slot_rows: list[dict] = []
    accepted: list[ScheduledMatch] = []
    home_stadium_by_team = {
        "A": "VA",
        "B": "VB",
    }

    for round_num in range(1, NUM_ROUNDS):
        match_date = base_date + timedelta(days=(round_num - 1) * 4)
        slot_idx = len(slot_rows)
        slot_rows.append(_slot_row(match_date, round_num, f"R{round_num}"))
        accepted.append(ScheduledMatch(
            match_idx=len(accepted),
            round_num=round_num,
            home_team="A",
            away_team="B",
            venue="VA",
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

    final_teams = [f"R{i}" for i in range(MATCHES_PER_ROUND * 2)]
    for team_id in final_teams:
        home_stadium_by_team[team_id] = f"ST_{team_id}"

    round_34_matches: list[ScheduledMatch] = []
    for idx in range(MATCHES_PER_ROUND):
        home_team = final_teams[idx * 2]
        away_team = final_teams[idx * 2 + 1]
        venue = "VR_DUP" if idx in (0, 1) else f"VR_{idx}"
        home_stadium_by_team[home_team] = venue
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
    for slot_idx in range(alt_slot_count):
        slot_rows.append(
            _slot_row(repaired_final_date, NUM_ROUNDS + 1, f"ALT_{slot_idx}", hour=19 + (slot_idx * 2))
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
    data = _make_league_data(
        ["A", "B", *final_teams],
        slot_rows,
        home_stadium_by_team=home_stadium_by_team,
        caf_dates_by_team={
            violating_match.home_team: [original_final_date + timedelta(days=2)]
        },
    )
    return data, accepted, violations, repaired_final_date


class FinalRoundSchedulingTests(unittest.TestCase):
    def test_domains_bind_non_final_windows_and_final_round_tail(self) -> None:
        team_ids = [f"T{i}" for i in range(18)]
        slot_rows: list[dict] = []
        start_date = date(2026, 1, 1)
        total_days = (NUM_ROUNDS * 5) + 5

        for day_offset in range(total_days):
            current_date = start_date + timedelta(days=day_offset)
            week_num = 1 + (day_offset // 5)
            slot_rows.append(_slot_row(current_date, week_num, f"{day_offset}_A", hour=18))
            slot_rows.append(_slot_row(current_date, week_num, f"{day_offset}_B", hour=21))

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

    def test_baseline_packs_final_round_into_one_day_without_venue_overlap(self) -> None:
        data, matches, domains = _build_baseline_inputs()
        baseline = solve_baseline(data, matches, domains)

        self.assertIsNotNone(baseline)
        assert baseline is not None

        final_round = [match for match in baseline if match.round_num == FINAL_ROUND_NUM]
        self.assertEqual(len(final_round), MATCHES_PER_ROUND)
        self.assertEqual(len({match.date for match in final_round}), 1)

        duplicate_venue_matches = [match for match in final_round if match.venue == "VF_DUP"]
        self.assertEqual(len(duplicate_venue_matches), 2)
        self.assertNotEqual(
            duplicate_venue_matches[0].slot_idx,
            duplicate_venue_matches[1].slot_idx,
        )

        slot_loads: dict[int, int] = {}
        for match in final_round:
            slot_loads[match.slot_idx] = slot_loads.get(match.slot_idx, 0) + 1
        self.assertGreater(max(slot_loads.values()), 2)

    def test_final_round_repair_moves_whole_round_or_leaves_it_unresolved(self) -> None:
        repair_data, accepted, violations, repaired_date = _build_repair_case(alt_slot_count=2)
        repaired, unresolved = caf_repair(accepted, violations, repair_data)

        self.assertEqual(len(unresolved), 0)
        self.assertEqual(len(repaired), MATCHES_PER_ROUND)
        self.assertEqual(len([match for match in accepted if match.round_num == FINAL_ROUND_NUM]), 0)
        self.assertEqual({match.date for match in repaired}, {repaired_date})

        unresolved_data, accepted_unresolved, violations_unresolved, _ = _build_repair_case(
            alt_slot_count=1
        )
        repaired_unresolved, unresolved_only = caf_repair(
            accepted_unresolved,
            violations_unresolved,
            unresolved_data,
        )

        self.assertEqual(len(repaired_unresolved), 0)
        self.assertEqual(len(unresolved_only), MATCHES_PER_ROUND)

    def test_validation_relaxes_caps_only_for_a_valid_final_round_date(self) -> None:
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
        _validate_final_round_same_day(matches, issues)
        valid_final_round_date = final_date
        _validate_daily_load(matches, issues, valid_final_round_date)
        _validate_slot_load(matches, issues, valid_final_round_date)

        final_round_issues = [issue for issue in issues if issue["Date"] == final_date]
        non_final_issues = [issue for issue in issues if issue["Date"] == non_final_date]

        self.assertEqual(final_round_issues, [])
        self.assertEqual(
            {issue["Check"] for issue in non_final_issues},
            {"DAILY_MATCH_CAP", "SLOT_MATCH_CAP"},
        )


if __name__ == "__main__":
    unittest.main()
