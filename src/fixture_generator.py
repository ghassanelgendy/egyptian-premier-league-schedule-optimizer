"""Double round-robin fixture generation with valid home/away patterns."""

from __future__ import annotations

import csv
import os
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ortools.sat.python import cp_model

from src.constants import MATCHES_PER_ROUND, NUM_ROUNDS, NUM_TEAMS, PHASES_DIR
from src.data_loader import LeagueData, SecRule


@dataclass
class Match:
    match_idx: int
    round_num: int          # 1-based abstract round
    home_team: str
    away_team: str
    venue: str
    match_tier: int = 0     # filled after construction


def _get_forced_venue(
    home: str, away: str, sec_rules: List[SecRule]
) -> Optional[str]:
    for rule in sec_rules:
        if rule.home_team_id == home and rule.away_team_id == away:
            if rule.forced_venue_id:
                return rule.forced_venue_id
    return None


def _resolve_venue(
    home: str,
    away: str,
    teams_dict: Dict[str, dict],
    sec_rules: List[SecRule],
) -> str:
    forced = _get_forced_venue(home, away, sec_rules)
    if forced:
        return forced
    return teams_dict[home]["Home_Stadium_ID"]


def generate_drr(data: LeagueData, seed: int) -> List[Match]:
    """Generate a full 306-match double round-robin by seeded draw.

    Pairings are produced by the circle method on a shuffled team list. Home/away
    orientation is solved before Match objects are created, so every team gets a
    valid season pattern instead of relying on the slot solver to repair streaks.
    """
    rng = random.Random(seed)

    team_ids = sorted(data.teams["Team_ID"].tolist())
    rng.shuffle(team_ids)

    teams_dict: Dict[str, dict] = {}
    for _, row in data.teams.iterrows():
        teams_dict[row["Team_ID"]] = {
            "Home_Stadium_ID": row["Home_Stadium_ID"],
            "Tier": int(row["Tier"]),
        }

    n = len(team_ids)
    assert n == NUM_TEAMS and n % 2 == 0

    fixed = team_ids[0]
    rotating = team_ids[1:]

    first_leg_pairings: List[List[Tuple[str, str]]] = []

    for _ in range(n - 1):
        round_pairings: List[Tuple[str, str]] = []
        current = [fixed] + rotating

        for i in range(n // 2):
            round_pairings.append((current[i], current[n - 1 - i]))

        first_leg_pairings.append(round_pairings)
        rotating = [rotating[-1]] + rotating[:-1]

    first_leg_rounds = _orient_pairings_with_valid_patterns(
        first_leg_pairings,
        sorted(data.teams["Team_ID"].tolist()),
        seed,
    )

    from src.tiers import match_tier as compute_match_tier

    matches: List[Match] = []
    idx = 0

    for r_idx, round_matches in enumerate(first_leg_rounds):
        round_num = r_idx + 1
        for home, away in round_matches:
            venue = _resolve_venue(home, away, teams_dict, data.sec_rules)
            mt = compute_match_tier(teams_dict[home]["Tier"], teams_dict[away]["Tier"])
            matches.append(Match(
                match_idx=idx,
                round_num=round_num,
                home_team=home,
                away_team=away,
                venue=venue,
                match_tier=mt,
            ))
            idx += 1

    for r_idx, round_matches in enumerate(first_leg_rounds):
        round_num = r_idx + 1 + (n - 1)
        for home, away in round_matches:
            new_home, new_away = away, home
            venue = _resolve_venue(new_home, new_away, teams_dict, data.sec_rules)
            mt = compute_match_tier(
                teams_dict[new_home]["Tier"], teams_dict[new_away]["Tier"]
            )
            matches.append(Match(
                match_idx=idx,
                round_num=round_num,
                home_team=new_home,
                away_team=new_away,
                venue=venue,
                match_tier=mt,
            ))
            idx += 1

    _validate_drr(matches, sorted(data.teams["Team_ID"].tolist()))
    _write_fixture_csv(matches)
    _write_home_away_patterns(matches, sorted(data.teams["Team_ID"].tolist()))

    return matches


def _orient_pairings_with_valid_patterns(
    first_leg_pairings: List[List[Tuple[str, str]]],
    team_ids: List[str],
    seed: int,
) -> List[List[Tuple[str, str]]]:
    """Orient first-leg pairings so every team's 34-round H/A pattern is valid."""

    attempts = [
        {"rolling_five": True, "balanced_edges": True},
        {"rolling_five": True, "balanced_edges": False},
        {"rolling_five": False, "balanced_edges": False},
    ]

    for opts in attempts:
        oriented = _solve_orientation(first_leg_pairings, team_ids, seed, **opts)
        if oriented is not None:
            return oriented

    raise RuntimeError("Could not generate a valid home/away pattern framework")


def _solve_orientation(
    first_leg_pairings: List[List[Tuple[str, str]]],
    team_ids: List[str],
    seed: int,
    rolling_five: bool,
    balanced_edges: bool,
) -> Optional[List[List[Tuple[str, str]]]]:
    """Solve first-leg home/away orientation for the fixed DRR pairings."""

    model = cp_model.CpModel()

    # x[(r, i)] = 1 means pair[0] is home in first leg; 0 means pair[1] is home.
    x: Dict[Tuple[int, int], cp_model.IntVar] = {}
    for r, round_pairings in enumerate(first_leg_pairings):
        for i, _ in enumerate(round_pairings):
            x[(r, i)] = model.NewBoolVar(f"ha_r{r + 1}_m{i}")

    home_by_team_round: Dict[str, List[object]] = {
        tid: [None] * NUM_ROUNDS for tid in team_ids
    }

    for r, round_pairings in enumerate(first_leg_pairings):
        for i, (a, b) in enumerate(round_pairings):
            var = x[(r, i)]
            home_by_team_round[a][r] = var
            home_by_team_round[b][r] = 1 - var

            second_r = r + NUM_TEAMS - 1
            home_by_team_round[a][second_r] = 1 - var
            home_by_team_round[b][second_r] = var

    for team_id, pattern in home_by_team_round.items():
        if any(expr is None for expr in pattern):
            raise RuntimeError(f"Internal fixture error: incomplete pattern for {team_id}")

        model.Add(sum(pattern) == NUM_TEAMS - 1)

        for r in range(NUM_ROUNDS - 2):
            window = pattern[r:r + 3]
            model.Add(sum(window) >= 1)
            model.Add(sum(window) <= 2)

        if rolling_five:
            for r in range(NUM_ROUNDS - 4):
                window = pattern[r:r + 5]
                model.Add(sum(window) >= 2)
                model.Add(sum(window) <= 3)

        if balanced_edges:
            model.Add(pattern[0] + pattern[1] == 1)
            model.Add(pattern[-2] + pattern[-1] == 1)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 15
    solver.parameters.num_workers = 8
    solver.parameters.random_seed = seed

    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    oriented: List[List[Tuple[str, str]]] = []
    for r, round_pairings in enumerate(first_leg_pairings):
        oriented_round: List[Tuple[str, str]] = []
        for i, (a, b) in enumerate(round_pairings):
            if solver.Value(x[(r, i)]) == 1:
                oriented_round.append((a, b))
            else:
                oriented_round.append((b, a))
        oriented.append(oriented_round)

    return oriented


def _validate_drr(matches: List[Match], team_ids: List[str]) -> None:
    """Verify the DRR is complete and valid."""
    assert len(matches) == NUM_ROUNDS * MATCHES_PER_ROUND, (
        f"Expected {NUM_ROUNDS * MATCHES_PER_ROUND} matches, got {len(matches)}"
    )

    ordered_pairs = set()
    for m in matches:
        pair = (m.home_team, m.away_team)
        assert pair not in ordered_pairs, f"Duplicate ordered pair: {pair}"
        ordered_pairs.add(pair)

    assert len(ordered_pairs) == NUM_TEAMS * (NUM_TEAMS - 1), (
        f"Expected {NUM_TEAMS * (NUM_TEAMS - 1)} ordered pairs, "
        f"got {len(ordered_pairs)}"
    )

    for tid in team_ids:
        home_count = sum(1 for m in matches if m.home_team == tid)
        away_count = sum(1 for m in matches if m.away_team == tid)
        assert home_count == NUM_TEAMS - 1, (
            f"Team {tid}: {home_count} home (expected {NUM_TEAMS - 1})"
        )
        assert away_count == NUM_TEAMS - 1, (
            f"Team {tid}: {away_count} away (expected {NUM_TEAMS - 1})"
        )

    for r in range(1, NUM_ROUNDS + 1):
        round_matches = [m for m in matches if m.round_num == r]
        assert len(round_matches) == MATCHES_PER_ROUND, (
            f"Round {r}: {len(round_matches)} matches (expected {MATCHES_PER_ROUND})"
        )
        teams_in_round = set()
        for m in round_matches:
            assert m.home_team not in teams_in_round, (
                f"Round {r}: {m.home_team} appears twice"
            )
            assert m.away_team not in teams_in_round, (
                f"Round {r}: {m.away_team} appears twice"
            )
            teams_in_round.add(m.home_team)
            teams_in_round.add(m.away_team)


def _write_fixture_csv(matches: List[Match]) -> None:
    os.makedirs(PHASES_DIR, exist_ok=True)
    path = os.path.join(PHASES_DIR, "04_fixture_framework.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "match_idx", "round", "home_team", "away_team", "venue", "match_tier",
        ])
        for m in matches:
            writer.writerow([
                m.match_idx, m.round_num, m.home_team, m.away_team,
                m.venue, m.match_tier,
            ])


def _write_home_away_patterns(matches: List[Match], team_ids: List[str]) -> None:
    os.makedirs(PHASES_DIR, exist_ok=True)
    path = os.path.join(PHASES_DIR, "04_home_away_patterns.csv")

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Team_ID",
            "Pattern",
            "Home_Count",
            "Away_Count",
            "Max_Home_Streak",
            "Max_Away_Streak",
            "Rolling5_Balance_Violations",
        ])
        for team_id in sorted(team_ids):
            sequence = []
            for r in range(1, NUM_ROUNDS + 1):
                round_matches = [
                    m for m in matches
                    if m.round_num == r and (
                        m.home_team == team_id or m.away_team == team_id
                    )
                ]
                if len(round_matches) != 1:
                    raise RuntimeError(
                        f"Team {team_id} has {len(round_matches)} matches in round {r}"
                    )
                m = round_matches[0]
                sequence.append("H" if m.home_team == team_id else "A")

            writer.writerow([
                team_id,
                "".join(sequence),
                sequence.count("H"),
                sequence.count("A"),
                _max_streak(sequence, "H"),
                _max_streak(sequence, "A"),
                _rolling5_violations(sequence),
            ])


def _max_streak(sequence: List[str], value: str) -> int:
    best = 0
    current = 0
    for item in sequence:
        if item == value:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _rolling5_violations(sequence: List[str]) -> int:
    violations = 0
    for i in range(len(sequence) - 4):
        home_count = sequence[i:i + 5].count("H")
        if home_count not in (2, 3):
            violations += 1
    return violations
