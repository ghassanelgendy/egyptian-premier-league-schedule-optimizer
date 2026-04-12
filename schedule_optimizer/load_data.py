"""Load all PRD-listed inputs; build derived sets (no synthetic sport rows)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .normalize import normalize_stadium_id, strip_team_id
from .paths import DATA, SOURCES


@dataclass
class LoadLog:
    lines: list[str] = field(default_factory=list)

    def add(self, msg: str) -> None:
        self.lines.append(msg)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(self.lines), encoding="utf-8")


def _read_excel(path: Path, sheet: str | int = 0) -> pd.DataFrame:
    return pd.read_excel(path, sheet_name=sheet)


def _read_all_sheets(path: Path) -> dict[str, pd.DataFrame]:
    xl = pd.ExcelFile(path)
    return {sh: pd.read_excel(path, sheet_name=sh) for sh in xl.sheet_names}


def load_everything(log: LoadLog) -> dict:
    out: dict = {}

    dm_path = DATA / "Data_Model.xlsx"
    dm = _read_all_sheets(dm_path)
    log.add(f"Data_Model.xlsx sheets={list(dm.keys())}")
    out["data_model"] = dm

    exp_path = DATA / "expanded_calendar.xlsx"
    exp_all = _read_all_sheets(exp_path)
    log.add(f"expanded_calendar.xlsx sheets={list(exp_all.keys())}")
    out["expanded_calendar_book"] = exp_all
    cal = exp_all["expanded_calendar"].copy()
    log.add(f"expanded_calendar rows={len(cal)}")
    out["slots"] = cal

    csv_path = SOURCES / "expanded_calendar.csv"
    csv_cal = pd.read_csv(csv_path)
    log.add(f"expanded_calendar.csv rows={len(csv_cal)}")
    if len(csv_cal) != len(cal):
        log.add(f"WARN: expanded_calendar row count xlsx={len(cal)} csv={len(csv_cal)}")

    cal_main = _read_excel(SOURCES / "calendar.xlsx", "MAINCALENDAR")
    log.add(f"calendar.xlsx MAINCALENDAR rows={len(cal_main)}")
    out["maincalendar"] = cal_main

    teams = _read_excel(SOURCES / "teams_data.xlsx", "Teams")
    teams["Team_ID"] = teams["Team_ID"].map(strip_team_id)
    teams = teams.dropna(subset=["Team_ID"])
    teams["Home_Stadium"] = teams["Home_Stadium"].map(normalize_stadium_id)
    teams["Alt_Stadium"] = teams["Alt_Stadium"].map(normalize_stadium_id)
    log.add(f"teams_data.xlsx Teams rows={len(teams)}")
    out["teams"] = teams.set_index("Team_ID", drop=False)
    dm_teams = dm["team_data"]
    if len(dm_teams) != len(teams):
        log.add(f"WARN: Data_Model team_data rows={len(dm_teams)} vs teams_data={len(teams)}")

    stadiums = _read_excel(SOURCES / "stadiums.xlsx", "Stadiums")
    stadiums["Stadium_ID"] = stadiums["Stadium_ID"].map(normalize_stadium_id)
    stadiums = stadiums.dropna(subset=["Stadium_ID"])
    log.add(f"stadiums.xlsx Stadiums rows={len(stadiums)}")
    out["stadiums"] = stadiums.set_index("Stadium_ID", drop=False)

    sec = _read_excel(SOURCES / "security matrix.xlsx", "Sec_Matrix")
    sec.columns = [str(c).strip().replace(" ", "_") for c in sec.columns]
    if "forced_venue" not in sec.columns:
        for c in list(sec.columns):
            if "forced" in c.lower():
                sec.rename(columns={c: "forced_venue"}, inplace=True)
    sec["home_team_ID"] = sec["home_team_ID"].map(strip_team_id)
    sec["away_team_ID"] = sec["away_team_ID"].map(strip_team_id)
    for col in ("banned_venue1_ID", "banned_venue2_ID", "forced_venue"):
        if col in sec.columns:
            sec[col] = sec[col].map(normalize_stadium_id)
    log.add(f"security matrix Sec_Matrix rows={len(sec)}")
    out["security"] = sec

    mat = _read_excel(SOURCES / "Stadium_Distance_Matrix.xlsx", "Sheet1")
    origin_col = "Origin"
    cols = [c for c in mat.columns if c != origin_col]
    dist: dict[tuple[str, str], float] = {}
    for _, row in mat.iterrows():
        o = normalize_stadium_id(row[origin_col])
        if not o:
            continue
        for c in cols:
            d = normalize_stadium_id(c)
            if d:
                dist[(o, d)] = float(row[c])
    log.add(f"Stadium_Distance_Matrix entries={len(dist)}")
    out["dist_km"] = dist

    colmat = _read_excel(SOURCES / "Stadium_Distances_Columns.xlsx", "Sheet1")
    log.add(f"Stadium_Distances_Columns rows={len(colmat)} cols={list(colmat.columns)[:6]}...")

    fifa_dates: set[date] = set()
    fifa_wb = _read_all_sheets(SOURCES / "FIFA_Days_UPDATED.xlsx")
    log.add(f"FIFA_Days_UPDATED sheets={list(fifa_wb.keys())}")
    for sh, df in fifa_wb.items():
        if "Date" in df.columns:
            for v in pd.to_datetime(df["Date"], errors="coerce").dropna():
                fifa_dates.add(v.date())

    fifa2_path = SOURCES / "FIFA Days.xlsx"
    fifa2 = _read_excel(fifa2_path, "International Break Schedule Ta")
    log.add(f"FIFA Days.xlsx International Break rows={len(fifa2)}")
    if "Date" in fifa2.columns:
        for v in pd.to_datetime(fifa2["Date"], errors="coerce").dropna():
            fifa_dates.add(v.date())
    log.add(f"union FIFA calendar dates={len(fifa_dates)}")
    out["fifa_dates"] = fifa_dates

    cl = _read_excel(SOURCES / "CAF CL.xlsx", "CAF CL")
    cc = _read_excel(SOURCES / "CAF CC.xlsx", "CAF CC")
    cl_dates = {pd.to_datetime(x).date() for x in pd.to_datetime(cl["Date"], errors="coerce").dropna()}
    cc_dates = {pd.to_datetime(x).date() for x in pd.to_datetime(cc["Date"], errors="coerce").dropna()}
    log.add(f"CAF CL dates={len(cl_dates)} CAF CC dates={len(cc_dates)}")
    out["caf_cl_dates"] = cl_dates
    out["caf_cc_dates"] = cc_dates

    blk_frames = []
    bt = _read_all_sheets(SOURCES / "cont_blockers_table.xlsx")
    log.add(f"cont_blockers_table sheets={list(bt.keys())}")
    for sh, df in bt.items():
        blk_frames.append(df.copy())
    blk_frames.append(pd.read_csv(SOURCES / "cont_blockers_csv.csv"))
    blockers = pd.concat(blk_frames, ignore_index=True)
    blockers.drop_duplicates(
        subset=[c for c in ["date_id", "team_id", "competition_name", "round"] if c in blockers.columns],
        inplace=True,
    )
    log.add(f"merged continental blockers rows={len(blockers)}")
    out["blockers"] = blockers

    log.add("All PRD input files touched.")
    return out


def slot_date_series(slots: pd.DataFrame) -> pd.Series:
    if "Date" not in slots.columns:
        raise ValueError("expanded_calendar must have Date")
    return pd.to_datetime(slots["Date"], errors="coerce").dt.normalize()


def build_team_date_blackout(
    teams: pd.DataFrame,
    slots: pd.DataFrame,
    blockers: pd.DataFrame,
    fifa_dates: set[date],
    caf_cl_dates: set[date],
    caf_cc_dates: set[date],
    log: LoadLog,
    *,
    caf_buffer_days: int = 1,
) -> dict[str, set[date]]:
    """Map team_id -> set of dates on which they cannot play."""
    slot_dates = slot_date_series(slots)
    day_id_to_date: dict[str, date] = {}
    for i in range(len(slots)):
        did = str(slots.iloc[i]["Day_ID"])
        d = slot_dates.iloc[i]
        if pd.isna(d):
            continue
        day_id_to_date[did] = d.date()

    black: dict[str, set[date]] = {tid: set() for tid in teams.index}

    # CAF CL/CC workbook dates are loaded for audit; continental hard blackouts
    # use cont_blockers (+/-3) and slot-level Is_CAF (expanded_calendar) in the solver.

    for _, row in blockers.iterrows():
        tid = strip_team_id(row.get("team_id"))
        did = row.get("date_id")
        if not tid or tid not in black:
            continue
        anchor = day_id_to_date.get(str(did))
        if anchor is None:
            log.add(f"WARN: blocker date_id {did} not in calendar Day_ID map")
            continue
        for k in range(-caf_buffer_days, caf_buffer_days + 1):
            black[tid].add(anchor + timedelta(days=k))

    return black


def global_date_blackout(slots: pd.DataFrame, fifa_dates: set[date]) -> set[date]:
    dts = set(slot_date_series(slots).dt.date.dropna().tolist())
    return set(fifa_dates) & dts


def dist_lookup(dist: dict[tuple[str, str], float], a: str, b: str) -> float:
    if a == b:
        return 0.0
    key = (a, b)
    if key in dist:
        return dist[key]
    keyr = (b, a)
    if keyr in dist:
        return dist[keyr]
    raise KeyError(f"No distance for ({a!r}, {b!r})")


def venue_for_fixture(
    home: str,
    away: str,
    teams: pd.DataFrame,
    security: pd.DataFrame,
) -> str:
    for _, row in security.iterrows():
        if row["home_team_ID"] == home and row["away_team_ID"] == away:
            fv = row.get("forced_venue")
            if fv is not None and str(fv).strip() != "" and str(fv) != "nan":
                v = normalize_stadium_id(fv)
                if v:
                    return v
    v = teams.loc[home, "Home_Stadium"]
    if not v:
        raise ValueError(f"Team {home} has no Home_Stadium")
    return str(v)


def eligible_calendar_weeks(slots: pd.DataFrame, fifa_union_dates: set[date]) -> list[int]:
    sdt = slot_date_series(slots)
    flags = (slots["Is_FIFA"].fillna(0).astype(int) != 1) & (slots["Is_SuperCup"].fillna(0).astype(int) != 1)
    date_ok = ~sdt.dt.date.isin(fifa_union_dates)
    ok = flags & date_ok
    tmp = slots.assign(_ok=ok, _date=sdt.dt.date)
    usable = tmp.groupby("Week_Num")["_ok"].sum()
    weeks = [int(w) for w, c in usable.items() if c >= 9]
    week_min_date = tmp.groupby("Week_Num")["_date"].min()
    weeks.sort(key=lambda w: week_min_date.loc[w])
    return weeks


def slot_tier(day_name: str, dt) -> int:
    h = pd.to_datetime(dt).hour if not pd.isna(pd.to_datetime(dt, errors="coerce")) else 12
    dn = str(day_name).strip().upper()[:3]
    if dn in ("FRI", "SAT", "SUN"):
        return 1 if h >= 20 else 2
    return 3