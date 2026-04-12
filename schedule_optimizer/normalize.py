"""Deterministic stadium / team ID normalization (PRD §6)."""
from __future__ import annotations
import re

def strip_team_id(raw: object) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s.lower() == "nan":
        return None
    s = re.sub(r"\s+", "", s)
    return s.upper() or None

_STADIUM_ALIASES: dict[str, str] = {
    "BORGARAB": "BORG_ARAB",
    "ISMALIA": "ISMAILIA_ST",
    "BORGEARAB": "BORG_ARAB",
    "HARAS_HODOOD": "HARAS",
    "GHAZL_MAHALLA": "MAHALLA",
    "KHALED_BICHARA": "EL_GOUNA",
}

def normalize_stadium_id(raw: object) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip().upper()
    if not s or s == "NAN":
        return None
    s = s.replace(" ", "_")
    return _STADIUM_ALIASES.get(s, s)
