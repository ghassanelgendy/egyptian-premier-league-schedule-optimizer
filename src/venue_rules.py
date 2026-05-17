"""Shared venue-selection helpers for baseline scheduling and CAF repair."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from src.data_loader import LeagueData, SecRule


@dataclass(frozen=True)
class VenueOptions:
    primary_venue: str
    alt_venue: str
    forced_venue: str
    banned_venues: Set[str]
    allowed_venues: List[str]

    @property
    def is_forced_only(self) -> bool:
        return bool(self.forced_venue)


@dataclass(frozen=True)
class VenueCandidate:
    venue: str
    is_forced: bool
    is_primary: bool
    is_alt: bool
    is_other: bool
    home_displacement_km: float


def build_team_lookup(data: LeagueData) -> Dict[str, dict]:
    """Build a normalized team lookup used by the solvers."""
    teams_dict: Dict[str, dict] = {}
    for _, row in data.teams.iterrows():
        teams_dict[row["Team_ID"]] = {
            "Home_Stadium_ID": row["Home_Stadium_ID"],
            "Alt_Stadium_ID": row.get("Alt_Stadium_ID", ""),
            "Tier": int(row["Tier"]),
        }
    return teams_dict


def find_sec_rule(
    home: str,
    away: str,
    sec_rules: List[SecRule],
) -> Optional[SecRule]:
    for rule in sec_rules:
        if rule.home_team_id == home and rule.away_team_id == away:
            return rule
    return None


def get_forced_venue(
    home: str,
    away: str,
    sec_rules: List[SecRule],
) -> str:
    rule = find_sec_rule(home, away, sec_rules)
    if rule is None:
        return ""
    return rule.forced_venue_id or ""


def get_venue_options(
    home: str,
    away: str,
    teams_dict: Dict[str, dict],
    sec_rules: List[SecRule],
) -> VenueOptions:
    """Return the allowed venue choices for a home/away pairing.

    Rules:
    - forced venue overrides every other rule
    - otherwise allow the home team's main stadium
    - also allow the alternate stadium if it exists and is distinct
    - banned venues are removed from non-forced candidates
    """
    primary = str(teams_dict[home].get("Home_Stadium_ID", "")).strip().upper()
    alt = str(teams_dict[home].get("Alt_Stadium_ID", "")).strip().upper()
    if alt == primary:
        alt = ""

    rule = find_sec_rule(home, away, sec_rules)
    forced = ""
    banned: Set[str] = set()
    if rule is not None:
        forced = rule.forced_venue_id or ""
        banned = {
            venue
            for venue in (rule.banned_venue1_id, rule.banned_venue2_id)
            if venue
        }

    if forced:
        return VenueOptions(
            primary_venue=primary,
            alt_venue=alt,
            forced_venue=forced,
            banned_venues=banned,
            allowed_venues=[forced],
        )

    ordered = [primary]
    if alt and alt not in ordered:
        ordered.append(alt)

    allowed = [venue for venue in ordered if venue and venue not in banned]
    if not allowed:
        raise RuntimeError(
            f"No allowed venue remains for {home} vs {away}. "
            f"Primary={primary or 'NONE'}, Alt={alt or 'NONE'}, "
            f"Banned={sorted(banned)}"
        )

    return VenueOptions(
        primary_venue=primary,
        alt_venue=alt,
        forced_venue="",
        banned_venues=banned,
        allowed_venues=allowed,
    )


def stadium_distance(
    dist_matrix: Dict[str, Dict[str, float]],
    origin: str,
    dest: str,
) -> float:
    origin = str(origin or "").strip().upper()
    dest = str(dest or "").strip().upper()
    if not origin or not dest or origin == dest:
        return 0.0
    if origin in dist_matrix and dest in dist_matrix[origin]:
        return float(dist_matrix[origin][dest])
    if dest in dist_matrix and origin in dist_matrix[dest]:
        return float(dist_matrix[dest][origin])
    return 1_000_000.0


def get_ranked_venue_candidates(
    home: str,
    away: str,
    teams_dict: Dict[str, dict],
    sec_rules: List[SecRule],
    stadium_ids: List[str],
    dist_matrix: Dict[str, Dict[str, float]],
    *,
    allow_other_stadiums: bool,
) -> List[VenueCandidate]:
    """Return ordered venue candidates for one home/away pairing.

    Ordering:
    1. forced venue when defined
    2. primary home venue
    3. alternate home venue
    4. other stadiums sorted by proximity to the primary home venue
    """
    options = get_venue_options(home, away, teams_dict, sec_rules)
    primary = options.primary_venue
    alt = options.alt_venue

    if options.is_forced_only:
        return [
            VenueCandidate(
                venue=options.forced_venue,
                is_forced=True,
                is_primary=options.forced_venue == primary,
                is_alt=options.forced_venue == alt,
                is_other=options.forced_venue not in {primary, alt},
                home_displacement_km=stadium_distance(
                    dist_matrix,
                    primary,
                    options.forced_venue,
                ),
            )
        ]

    candidates: List[VenueCandidate] = []
    seen: Set[str] = set()

    def add_candidate(venue: str, *, is_primary: bool, is_alt: bool, is_other: bool) -> None:
        normalized = str(venue or "").strip().upper()
        if not normalized or normalized in seen or normalized in options.banned_venues:
            return
        candidates.append(
            VenueCandidate(
                venue=normalized,
                is_forced=False,
                is_primary=is_primary,
                is_alt=is_alt,
                is_other=is_other,
                home_displacement_km=stadium_distance(dist_matrix, primary, normalized),
            )
        )
        seen.add(normalized)

    add_candidate(primary, is_primary=True, is_alt=False, is_other=False)
    add_candidate(alt, is_primary=False, is_alt=True, is_other=False)

    if allow_other_stadiums:
        others = []
        for venue in stadium_ids:
            normalized = str(venue or "").strip().upper()
            if not normalized or normalized in seen or normalized in options.banned_venues:
                continue
            others.append(normalized)
        others.sort(
            key=lambda venue: (
                stadium_distance(dist_matrix, primary, venue),
                venue,
            )
        )
        for venue in others:
            add_candidate(venue, is_primary=False, is_alt=False, is_other=True)

    return candidates
