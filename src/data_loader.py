"""Load and validate the two authoritative Excel workbooks."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Set

import pandas as pd

from src.constants import (
    DATA_MODEL_PATH,
    EXPANDED_CALENDAR_PATH,
    NUM_TEAMS,
    OUTPUT_DIR,
    PHASES_DIR,
)


@dataclass
class SecRule:
    home_team_id: str
    away_team_id: str
    banned_venue1_id: str
    banned_venue2_id: str
    forced_venue_id: str


@dataclass
class LeagueData:
    teams: pd.DataFrame
    stadiums: pd.DataFrame
    dist_matrix: Dict[str, Dict[str, float]]
    sec_rules: List[SecRule]

    slots: pd.DataFrame
    usable_slots: pd.DataFrame          # FIFA-filtered
    fifa_dates: Set[date]
    caf_blockers: pd.DataFrame
    caf_dates_by_team: Dict[str, List[date]]
    unique_caf_dates: Set[date]


def _norm_id(val) -> str:
    if pd.isna(val):
        return ""
    return str(val).strip().upper()


def _parse_date(val) -> date | None:
    if pd.isna(val):
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    try:
        return pd.Timestamp(val).date()
    except Exception:
        return None


def _load_data_model(path: str) -> tuple[pd.DataFrame, pd.DataFrame, dict, list]:
    """Read Data_Model.xlsx and return (teams, stadiums, dist_matrix, sec_rules)."""
    xls = pd.ExcelFile(path, engine="openpyxl")

    required_sheets = {"team_data", "Stadiums", "dist_Matrix", "Sec_Matrix"}
    missing = required_sheets - set(xls.sheet_names)
    if missing:
        raise ValueError(f"Data_Model.xlsx missing sheets: {missing}")

    # --- teams ---
    teams = pd.read_excel(xls, "team_data")
    for col in ("Team_ID", "Team_Name", "Gov_ID", "Gov_Name",
                "Home_Stadium_ID", "Alt_Stadium_ID", "Tier", "Cont_Flag"):
        if col not in teams.columns:
            raise ValueError(f"team_data missing column: {col}")
    teams["Team_ID"] = teams["Team_ID"].apply(_norm_id)
    teams["Home_Stadium_ID"] = teams["Home_Stadium_ID"].apply(_norm_id)
    teams["Alt_Stadium_ID"] = teams["Alt_Stadium_ID"].apply(_norm_id)
    teams["Cont_Flag"] = teams["Cont_Flag"].apply(
        lambda v: _norm_id(v) if pd.notna(v) else ""
    )

    if len(teams) != NUM_TEAMS:
        raise ValueError(f"Expected {NUM_TEAMS} teams, got {len(teams)}")

    # --- stadiums ---
    stadiums = pd.read_excel(xls, "Stadiums")
    for col in ("Stadium_ID", "Stadium_Name", "Gov_ID", "City", "Is_Floodlit"):
        if col not in stadiums.columns:
            raise ValueError(f"Stadiums missing column: {col}")
    stadiums["Stadium_ID"] = stadiums["Stadium_ID"].apply(_norm_id)

    stadium_ids = set(stadiums["Stadium_ID"])
    for _, row in teams.iterrows():
        if row["Home_Stadium_ID"] not in stadium_ids:
            raise ValueError(
                f"Team {row['Team_ID']} Home_Stadium_ID "
                f"'{row['Home_Stadium_ID']}' not in Stadiums"
            )

    # --- distance matrix ---
    dist_df = pd.read_excel(xls, "dist_Matrix")
    dist_df.rename(columns={dist_df.columns[0]: "Origin"}, inplace=True)
    dist_df["Origin"] = dist_df["Origin"].apply(_norm_id)
    dist_matrix: Dict[str, Dict[str, float]] = {}
    for _, row in dist_df.iterrows():
        origin = row["Origin"]
        dist_matrix[origin] = {}
        for col in dist_df.columns[1:]:
            dest = _norm_id(col)
            dist_matrix[origin][dest] = float(row[col]) if pd.notna(row[col]) else 0.0

    # --- security rules ---
    sec_df = pd.read_excel(xls, "Sec_Matrix")
    sec_rules: List[SecRule] = []
    for _, row in sec_df.iterrows():
        sec_rules.append(SecRule(
            home_team_id=_norm_id(row.get("home_team_ID", "")),
            away_team_id=_norm_id(row.get("away_team_ID", "")),
            banned_venue1_id=_norm_id(row.get("banned_venue1_ID", "")),
            banned_venue2_id=_norm_id(row.get("banned_venue2_ID", "")),
            forced_venue_id=_norm_id(row.get("forced_venue_ID", "")),
        ))

    return teams, stadiums, dist_matrix, sec_rules


def _load_expanded_calendar(path: str) -> tuple[
    pd.DataFrame, set, pd.DataFrame, dict, set
]:
    """Read expanded_calendar.xlsx and return
    (slots, fifa_dates, caf_blockers, caf_dates_by_team, unique_caf_dates).
    """
    xls = pd.ExcelFile(path, engine="openpyxl")

    # Locate sheets (handle the space in 'expanded _calendar_table')
    sheet_names = xls.sheet_names
    main_sheet = None
    for s in sheet_names:
        if s.replace(" ", "") == "expanded_calendar" and "table" not in s.lower():
            main_sheet = s
            break
    if main_sheet is None:
        for s in sheet_names:
            if s.strip() == "expanded_calendar":
                main_sheet = s
                break
    if main_sheet is None:
        raise ValueError("expanded_calendar.xlsx missing 'expanded_calendar' sheet")

    fifa_sheet = None
    for s in sheet_names:
        if "FIFA_DAYS" in s.upper():
            fifa_sheet = s
            break

    caf_sheet = None
    for s in sheet_names:
        if "cont_blockers" in s.lower():
            caf_sheet = s
            break

    unique_caf_sheet = None
    for s in sheet_names:
        if "unique_caf" in s.lower():
            unique_caf_sheet = s
            break

    # --- main slot table ---
    slots = pd.read_excel(xls, main_sheet)
    if "Date" not in slots.columns:
        raise ValueError(f"Sheet '{main_sheet}' missing 'Date' column")
    slots["Date"] = pd.to_datetime(slots["Date"], errors="coerce")
    slots["_date"] = slots["Date"].apply(lambda d: d.date() if pd.notna(d) else None)

    if "Date time" in slots.columns:
        slots["Date time"] = pd.to_datetime(slots["Date time"], errors="coerce")

    for col in ("Day_ID", "Week_Num", "Day_name"):
        if col not in slots.columns:
            raise ValueError(f"Sheet '{main_sheet}' missing '{col}' column")

    slots["Week_Num"] = pd.to_numeric(slots["Week_Num"], errors="coerce").astype("Int64")

    # --- FIFA dates (union of three sources) ---
    fifa_dates: Set[date] = set()

    # Source 1: Is_FIFA == 1
    if "Is_FIFA" in slots.columns:
        mask = slots["Is_FIFA"] == 1
        fifa_dates |= set(slots.loc[mask, "_date"].dropna())

    # Source 2: FIFA_DAYS1 sheet
    if fifa_sheet:
        fifa_df = pd.read_excel(xls, fifa_sheet)
        date_col = None
        for c in fifa_df.columns:
            if "date" in c.lower():
                date_col = c
                break
        if date_col:
            fifa_df[date_col] = pd.to_datetime(fifa_df[date_col], errors="coerce")
            fifa_dates |= set(
                d.date() for d in fifa_df[date_col].dropna()
            )

    # Source 3: non-empty FIFA label columns
    for col in ("FIFA_DAY", "FIFA_DAYS"):
        if col in slots.columns:
            mask = slots[col].notna() & (slots[col].astype(str).str.strip() != "")
            fifa_dates |= set(slots.loc[mask, "_date"].dropna())

    # --- CAF blockers ---
    caf_blockers = pd.DataFrame()
    caf_dates_by_team: Dict[str, List[date]] = {}

    if caf_sheet:
        caf_blockers = pd.read_excel(xls, caf_sheet)
        # Normalise column names
        col_map = {}
        for c in caf_blockers.columns:
            cl = c.lower().strip()
            if "team" in cl and "id" in cl:
                col_map[c] = "team_id"
            elif cl in ("caf_date", "date"):
                col_map[c] = "caf_date"
            elif "competition" in cl:
                col_map[c] = "competition_name"
            elif cl == "round":
                col_map[c] = "round"
            elif cl == "location":
                col_map[c] = "location"
            elif "date_id" in cl:
                col_map[c] = "date_id"
        caf_blockers.rename(columns=col_map, inplace=True)

        if "caf_date" in caf_blockers.columns:
            caf_blockers["caf_date"] = pd.to_datetime(
                caf_blockers["caf_date"], errors="coerce"
            )
            caf_blockers["_caf_date"] = caf_blockers["caf_date"].apply(
                lambda d: d.date() if pd.notna(d) else None
            )
        elif "date_id" in caf_blockers.columns:
            # Parse date from Day_ID format like D_20260914
            caf_blockers["_caf_date"] = caf_blockers["date_id"].apply(
                lambda v: _parse_date_id(v)
            )

        if "team_id" in caf_blockers.columns:
            caf_blockers["team_id"] = caf_blockers["team_id"].apply(_norm_id)

        for _, row in caf_blockers.iterrows():
            tid = row.get("team_id", "")
            d = row.get("_caf_date")
            if tid and d:
                caf_dates_by_team.setdefault(tid, []).append(d)

        for tid in caf_dates_by_team:
            caf_dates_by_team[tid] = sorted(set(caf_dates_by_team[tid]))

    # --- unique CAF dates ---
    unique_caf_dates: Set[date] = set()
    if unique_caf_sheet:
        ucaf = pd.read_excel(xls, unique_caf_sheet)
        date_col = None
        for c in ucaf.columns:
            if "date" in c.lower() and "id" not in c.lower():
                date_col = c
                break
        if date_col is None:
            for c in ucaf.columns:
                if "date_id" in c.lower():
                    date_col = c
                    break
        if date_col:
            if "date_id" in (date_col or "").lower():
                unique_caf_dates = set(
                    _parse_date_id(v) for v in ucaf[date_col].dropna()
                    if _parse_date_id(v) is not None
                )
            else:
                ucaf[date_col] = pd.to_datetime(ucaf[date_col], errors="coerce")
                unique_caf_dates = set(
                    d.date() for d in ucaf[date_col].dropna()
                )

    return slots, fifa_dates, caf_blockers, caf_dates_by_team, unique_caf_dates



def _parse_date_id(val) -> date | None:
    """Parse a Day_ID like 'D_20260914' into a date."""
    if pd.isna(val):
        return None
    s = str(val).strip()
    if s.startswith("D_") and len(s) == 10:
        try:
            return date(int(s[2:6]), int(s[6:8]), int(s[8:10]))
        except ValueError:
            return None
    return None


def load_data() -> LeagueData:
    """Main entry point: load both workbooks, validate, return LeagueData."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(PHASES_DIR, exist_ok=True)

    teams, stadiums, dist_matrix, sec_rules = _load_data_model(DATA_MODEL_PATH)
    slots, fifa_dates, caf_blockers, caf_dates_by_team, unique_caf_dates = (
        _load_expanded_calendar(EXPANDED_CALENDAR_PATH)
    )

    # Filter usable slots (remove FIFA)
    usable_slots = slots[~slots["_date"].isin(fifa_dates)].copy()
    usable_slots = usable_slots[usable_slots["_date"].notna()].copy()
    usable_slots.reset_index(drop=True, inplace=True)


    data = LeagueData(
        teams=teams,
        stadiums=stadiums,
        dist_matrix=dist_matrix,
        sec_rules=sec_rules,
        slots=slots,
        usable_slots=usable_slots,
        fifa_dates=fifa_dates,
        caf_blockers=caf_blockers,
        caf_dates_by_team=caf_dates_by_team,
        unique_caf_dates=unique_caf_dates,
    )

    _write_load_log(data)
    _write_load_summary(data)

    return data


def _write_load_log(data: LeagueData) -> None:
    path = os.path.join(OUTPUT_DIR, "data_load_log.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("=== Data Load Log ===\n\n")
        f.write(f"Data_Model.xlsx: {DATA_MODEL_PATH}\n")
        f.write(f"  team_data:   {len(data.teams)} rows\n")
        f.write(f"  Stadiums:    {len(data.stadiums)} rows\n")
        f.write(f"  dist_Matrix: {len(data.dist_matrix)} origins\n")
        f.write(f"  Sec_Matrix:  {len(data.sec_rules)} rules\n\n")
        f.write(f"expanded_calendar.xlsx: {EXPANDED_CALENDAR_PATH}\n")
        f.write(f"  Total slots:    {len(data.slots)} rows\n")
        f.write(f"  FIFA dates:     {len(data.fifa_dates)}\n")
        f.write(f"  Usable slots:   {len(data.usable_slots)} (after FIFA removal)\n")
        f.write(f"  CAF blockers:   {len(data.caf_blockers)} rows\n")
        f.write(f"  CAF teams:      {list(data.caf_dates_by_team.keys())}\n")
        f.write(f"  Unique CAF dates: {len(data.unique_caf_dates)}\n\n")
        f.write("Validation: PASSED\n")


def _write_load_summary(data: LeagueData) -> None:
    path = os.path.join(PHASES_DIR, "01_load_summary.json")
    summary = {
        "data_model_path": DATA_MODEL_PATH,
        "expanded_calendar_path": EXPANDED_CALENDAR_PATH,
        "team_count": len(data.teams),
        "stadium_count": len(data.stadiums),
        "dist_matrix_origins": len(data.dist_matrix),
        "sec_rules_count": len(data.sec_rules),
        "total_slot_count": len(data.slots),
        "fifa_date_count": len(data.fifa_dates),
        "usable_slot_count": len(data.usable_slots),
        "caf_blocker_count": len(data.caf_blockers),
        "caf_teams": list(data.caf_dates_by_team.keys()),
        "unique_caf_date_count": len(data.unique_caf_dates),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
