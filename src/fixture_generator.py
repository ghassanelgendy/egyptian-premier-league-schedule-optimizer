"""Random double round-robin fixture generation using the circle method."""

from __future__ import annotations

import csv
import os
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

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
    """Generate a full 306-match double round-robin by random draw.

    Uses the circle method on a randomly shuffled team list, with
    random home/away coin-flips for the first leg.
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

    # Circle method: fix team_ids[0], rotate the rest
    fixed = team_ids[0]
    rotating = team_ids[1:]

    first_leg_rounds: List[List[Tuple[str, str]]] = []

    for r in range(n - 1):
        round_matches: List[Tuple[str, str]] = []

        current = [fixed] + rotating

        for i in range(n // 2):
            t1 = current[i]
            t2 = current[n - 1 - i]
            # Random coin-flip for home/away
            if rng.random() < 0.5:
                round_matches.append((t1, t2))
            else:
                round_matches.append((t2, t1))

        first_leg_rounds.append(round_matches)

        # Rotate: move last element to front of rotating list
        rotating = [rotating[-1]] + rotating[:-1]

    # Build all 306 matches
    from src.tiers import match_tier as compute_match_tier

    matches: List[Match] = []
    idx = 0

    # First leg: rounds 1–17
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

    # Second leg: rounds 18–34 (home/away swapped)
    for r_idx, round_matches in enumerate(first_leg_rounds):
        round_num = r_idx + 1 + (n - 1)
        for home, away in round_matches:
            # Swap home/away for second leg
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

    _validate_drr(matches, team_ids)
    _write_fixture_csv(matches)

    return matches


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
