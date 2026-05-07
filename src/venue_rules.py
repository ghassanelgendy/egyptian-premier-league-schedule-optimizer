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
