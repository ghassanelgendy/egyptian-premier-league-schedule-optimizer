"""Shared helpers for the final-round single-day scheduling rule."""

from __future__ import annotations

from datetime import date
from typing import Iterable, List, TypeVar

from src.constants import (
    ENFORCE_FINAL_ROUND_SINGLE_DAY,
    FINAL_ROUND_MAX_MATCHES_PER_DAY,
    FINAL_ROUND_MAX_MATCHES_PER_SLOT,
    FINAL_ROUND_NUM,
    MATCHES_PER_ROUND,
    MAX_MATCHES_PER_DAY,
    MAX_MATCHES_PER_SLOT,
)

T = TypeVar("T")


def is_final_round(round_num: int) -> bool:
    """Return whether a round is the enforced one-day final round."""
    return ENFORCE_FINAL_ROUND_SINGLE_DAY and round_num == FINAL_ROUND_NUM


def collect_final_round_matches(matches: Iterable[T]) -> List[T]:
    """Return all matches that belong to the enforced final round."""
    return [
        match
        for match in matches
        if is_final_round(int(getattr(match, "round_num", 0)))
    ]


def get_valid_final_round_shared_date(matches: Iterable[object]) -> date | None:
    """Return the relaxed-cap date when the published final round is valid.

    The relaxed day and slot caps are only valid when all final-round matches
    are present and share exactly one calendar date in the published schedule.
    """
    final_round_matches = collect_final_round_matches(matches)
    if len(final_round_matches) != MATCHES_PER_ROUND:
        return None

    dates = {
        getattr(match, "date", None)
        for match in final_round_matches
        if getattr(match, "date", None) is not None
    }
    if len(dates) != 1:
        return None
    return next(iter(dates))


def allowed_matches_on_date(
    match_date: date,
    valid_final_round_date: date | None,
) -> int:
    """Return the allowed daily load for a specific calendar date."""
    if valid_final_round_date is not None and match_date == valid_final_round_date:
        return FINAL_ROUND_MAX_MATCHES_PER_DAY
    return MAX_MATCHES_PER_DAY


def allowed_matches_in_slot(
    slot_date: date,
    valid_final_round_date: date | None,
) -> int:
    """Return the allowed same-kickoff load for a slot on a given date."""
    if valid_final_round_date is not None and slot_date == valid_final_round_date:
        return FINAL_ROUND_MAX_MATCHES_PER_SLOT
    return MAX_MATCHES_PER_SLOT
