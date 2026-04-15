"""Slot-tier and match-tier computation."""

from __future__ import annotations

from datetime import datetime
from typing import Union

import pandas as pd


# Weekend days in the Egyptian calendar context (Friday/Saturday)
_WEEKEND_DAYS = {"FRI", "SAT"}


def slot_tier(day_name: str, kickoff: Union[datetime, pd.Timestamp, None]) -> int:
    """Return 1 (best), 2, or 3 for a calendar slot.

    Tier 1: weekend evening (FRI/SAT, kickoff >= 19:00)
    Tier 2: weekend afternoon OR weekday evening (>= 19:00)
    Tier 3: weekday afternoon / early
    """
    is_weekend = str(day_name).strip().upper() in _WEEKEND_DAYS
    hour = 12  # default if time is missing
    if kickoff is not None and not pd.isna(kickoff):
        try:
            hour = kickoff.hour
        except AttributeError:
            hour = 12

    is_evening = hour >= 19

    if is_weekend and is_evening:
        return 1
    if is_weekend or is_evening:
        return 2
    return 3


def match_tier(home_tier: int, away_tier: int) -> int:
    """Return 1 (top), 2, or 3 based on both teams' league tiers.

    1 vs 1 -> 1    1 vs 2 -> 1
    1 vs 3 -> 2    2 vs 2 -> 2
    2 vs 3 -> 3    3 vs 3 -> 3
    """
    best = min(home_tier, away_tier)
    worst = max(home_tier, away_tier)
    if best == 1 and worst <= 2:
        return 1
    if worst <= 2 or (best == 1 and worst == 3):
        return 2
    return 3


def compute_slot_tiers(slots: pd.DataFrame) -> pd.Series:
    """Add a Slot_Tier column based on Day_name and Date time."""
    return slots.apply(
        lambda row: slot_tier(
            row.get("Day_name", ""),
            row.get("Date time"),
        ),
        axis=1,
    )
