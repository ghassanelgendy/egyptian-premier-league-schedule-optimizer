"""Random double round-robin fixture generation using the circle method."""

from __future__ import annotations

import csv
import os
import random
from collections import defaultdict
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
    _fix_ha_streaks(matches, teams_dict, data.sec_rules)
    _write_fixture_csv(matches)

    return matches


def _count_ha_streak_violations(matches: List[Match]) -> int:
    """Count total number of streak triples (team, round-i) across all teams."""
    all_ids = list({m.home_team for m in matches} | {m.away_team for m in matches})
    total = 0
    for tid in all_ids:
        seq = sorted(
            [(m.round_num, m.home_team == tid)
             for m in matches
             if m.home_team == tid or m.away_team == tid],
            key=lambda t: t[0],
        )
        for i in range(len(seq) - 2):
            if seq[i][1] == seq[i + 1][1] == seq[i + 2][1]:
                total += 1
    return total


def _find_streak_match_idxs(matches: List[Match], team_id: str) -> List[int]:
    """Return match_idxs of ALL matches involved in streaks for team_id."""
    seq = sorted(
        [(m.round_num, m.match_idx, m.home_team == team_id)
         for m in matches
         if m.home_team == team_id or m.away_team == team_id],
        key=lambda t: t[0],
    )
    bad: set = set()
    for i in range(len(seq) - 2):
        if seq[i][2] == seq[i + 1][2] == seq[i + 2][2]:
            bad.add(seq[i][1])
            bad.add(seq[i + 1][1])
            bad.add(seq[i + 2][1])
    return list(bad)


def _swap_match_ha(
    matches: List[Match],
    list_idx: int,
    teams_dict: Dict[str, dict],
    sec_rules: List[SecRule],
    compute_match_tier,
) -> None:
    """In-place swap home/away for matches[list_idx]."""
    m = matches[list_idx]
    nh, na = m.away_team, m.home_team
    matches[list_idx] = Match(
        match_idx=m.match_idx,
        round_num=m.round_num,
        home_team=nh,
        away_team=na,
        venue=_resolve_venue(nh, na, teams_dict, sec_rules),
        match_tier=compute_match_tier(teams_dict[nh]["Tier"], teams_dict[na]["Tier"]),
    )


def _fix_ha_streaks(
    matches: List[Match],
    teams_dict: Dict[str, dict],
    sec_rules: List[SecRule],
    max_iters: int = 2000,
) -> None:
    """Eliminate H/A streaks of 3+ in round order for every team.

    Uses a best-improvement local search: for each candidate swap (a match
    involved in any current streak, plus its leg-1/leg-2 mirror), apply the
    swap, measure the new total violation count, and keep the swap that
    reduces violations the most.  Falls back to a random swap if no improving
    move exists.
    """
    from src.tiers import match_tier as compute_match_tier

    all_ids = sorted({m.home_team for m in matches} | {m.away_team for m in matches})

    # Build round-to-listindex map (both legs)
    def mirror_list_idx(list_idx: int) -> Optional[int]:
        """Return list-index of the leg-mirror of matches[list_idx]."""
        m = matches[list_idx]
        leg1_round = m.round_num if m.round_num <= 17 else m.round_num - 17
        leg2_round = leg1_round + 17
        mirror_round = leg2_round if m.round_num == leg1_round else leg1_round
        for i, mr in enumerate(matches):
            if (mr.round_num == mirror_round
                    and mr.home_team == m.away_team
                    and mr.away_team == m.home_team):
                return i
        return None

    current_violations = _count_ha_streak_violations(matches)

    for iteration in range(max_iters):
        if current_violations == 0:
            break

        # Collect candidate swap indices: all matches in any current streak
        candidate_idxs: set = set()
        for tid in all_ids:
            for midx in _find_streak_match_idxs(matches, tid):
                # find list index of this match
                for li, m in enumerate(matches):
                    if m.match_idx == midx:
                        candidate_idxs.add(li)
                        break

        if not candidate_idxs:
            break

        best_delta = 0
        best_move = None  # (list_idx, mirror_list_idx or None)

        for li in candidate_idxs:
            mi = mirror_list_idx(li)
            # Evaluate: swap li (and mi)
            _swap_match_ha(matches, li, teams_dict, sec_rules, compute_match_tier)
            if mi is not None:
                _swap_match_ha(matches, mi, teams_dict, sec_rules, compute_match_tier)

            new_v = _count_ha_streak_violations(matches)
            delta = current_violations - new_v

            # Undo swap
            _swap_match_ha(matches, li, teams_dict, sec_rules, compute_match_tier)
            if mi is not None:
                _swap_match_ha(matches, mi, teams_dict, sec_rules, compute_match_tier)

            if delta > best_delta:
                best_delta = delta
                best_move = (li, mi)

        if best_move is not None:
            li, mi = best_move
            _swap_match_ha(matches, li, teams_dict, sec_rules, compute_match_tier)
            if mi is not None:
                _swap_match_ha(matches, mi, teams_dict, sec_rules, compute_match_tier)
            current_violations -= best_delta
        else:
            # No single-swap improves — try all 2-swap combinations to escape
            cand_list = sorted(candidate_idxs)
            best2_delta = 0
            best2_move = None
            for ci in range(len(cand_list)):
                for cj in range(ci + 1, len(cand_list)):
                    li1, li2 = cand_list[ci], cand_list[cj]
                    mi1 = mirror_list_idx(li1)
                    mi2 = mirror_list_idx(li2)
                    # Apply both swaps
                    _swap_match_ha(matches, li1, teams_dict, sec_rules, compute_match_tier)
                    if mi1 is not None:
                        _swap_match_ha(matches, mi1, teams_dict, sec_rules, compute_match_tier)
                    _swap_match_ha(matches, li2, teams_dict, sec_rules, compute_match_tier)
                    if mi2 is not None:
                        _swap_match_ha(matches, mi2, teams_dict, sec_rules, compute_match_tier)
                    new_v = _count_ha_streak_violations(matches)
                    delta2 = current_violations - new_v
                    # Undo
                    _swap_match_ha(matches, li1, teams_dict, sec_rules, compute_match_tier)
                    if mi1 is not None:
                        _swap_match_ha(matches, mi1, teams_dict, sec_rules, compute_match_tier)
                    _swap_match_ha(matches, li2, teams_dict, sec_rules, compute_match_tier)
                    if mi2 is not None:
                        _swap_match_ha(matches, mi2, teams_dict, sec_rules, compute_match_tier)
                    if delta2 > best2_delta:
                        best2_delta = delta2
                        best2_move = (li1, mi1, li2, mi2)

            if best2_move is not None:
                li1, mi1, li2, mi2 = best2_move
                _swap_match_ha(matches, li1, teams_dict, sec_rules, compute_match_tier)
                if mi1 is not None:
                    _swap_match_ha(matches, mi1, teams_dict, sec_rules, compute_match_tier)
                _swap_match_ha(matches, li2, teams_dict, sec_rules, compute_match_tier)
                if mi2 is not None:
                    _swap_match_ha(matches, mi2, teams_dict, sec_rules, compute_match_tier)
                current_violations -= best2_delta
            else:
                # Still stuck — random single swap to escape
                li = cand_list[iteration % len(cand_list)]
                mi = mirror_list_idx(li)
                _swap_match_ha(matches, li, teams_dict, sec_rules, compute_match_tier)
                if mi is not None:
                    _swap_match_ha(matches, mi, teams_dict, sec_rules, compute_match_tier)
                current_violations = _count_ha_streak_violations(matches)

    if current_violations > 0:
        remaining = [
            tid for tid in all_ids if _find_streak_match_idxs(matches, tid)
        ]
        print(
            f"[fixture] WARNING: H/A streak fix did not fully converge "
            f"({current_violations} violations remain). Teams: {remaining}"
        )
    else:
        print("[fixture] H/A streak fix: all teams have valid H/A sequences.")


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
