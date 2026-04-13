"""Full-season calendar grid + per-day explanations (data-backed)."""
from __future__ import annotations

import calendar
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


def load_day_ledger_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    df = pd.read_csv(path)
    if "Date" not in df.columns:
        return None
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.date
    return df


def schedule_rows_for_date(sched: pd.DataFrame | None, d: date) -> pd.DataFrame:
    if sched is None or sched.empty or "Date" not in sched.columns:
        return pd.DataFrame()
    s = pd.to_datetime(sched["Date"], errors="coerce").dt.date
    sub = sched.loc[s == d].copy()
    return sub


def explain_day_without_matches(ledger_row: dict[str, Any] | None) -> list[str]:
    """Reasons derived only from ``03b_season_day_ledger.csv`` columns."""
    out: list[str] = []
    if ledger_row is None:
        out.append(
            "There is no row for this date in `output/phases/03b_season_day_ledger.csv`. "
            "That usually means the date is outside the `expanded_calendar` season span."
        )
        return out
    if int(ledger_row.get("Slot_rows", 0) or 0) == 0:
        out.append("Expanded calendar contains no slot rows on this date.")
        return out
    if int(ledger_row.get("Is_FIFA_union_date", 0) or 0) == 1:
        out.append("FIFA / international date (union of FIFA spreadsheets ∩ season dates).")
    if int(ledger_row.get("Slots_FIFA_flag", 0) or 0) > 0:
        out.append(f"Slots flagged Is_FIFA=1 on this date: {int(ledger_row.get('Slots_FIFA_flag', 0))}.")
    if int(ledger_row.get("Slots_SuperCup_flag", 0) or 0) > 0:
        out.append(f"Slots flagged Is_SuperCup=1 on this date: {int(ledger_row.get('Slots_SuperCup_flag', 0))}.")
    elig = int(ledger_row.get("Slots_league_eligible", 0) or 0)
    if elig == 0:
        out.append(
            "No calendar slots are league-eligible on this date (FIFA flag, SuperCup flag, or FIFA union date removes all rows)."
        )
    else:
        out.append(
            f"{elig} league-eligible slot row(s) exist on this date, but **no** fixture was assigned here "
            "in the current `optimized_schedule.csv` (the solver used other dates while respecting constraints)."
        )
    return out


def render_month_calendar(
    *,
    year: int,
    month: int,
    ledger: pd.DataFrame | None,
    sched: pd.DataFrame | None,
    pick_key: str = "calendar_pick",
) -> None:
    """Render a classic month grid; clicking a day number sets session_state[pick_key]."""
    cal = calendar.Calendar(firstweekday=6)
    weeks = cal.monthdatescalendar(year, month)
    dow = ["Sat", "Sun", "Mon", "Tue", "Wed", "Thu", "Fri"]
    st.caption("Click a **day number** to inspect that date (uses saved day ledger + current schedule).")
    hdr = st.columns(7)
    for i, name in enumerate(dow):
        hdr[i].markdown(f"**{name}**")
    for week in weeks:
        cols = st.columns(7)
        for col, d in zip(cols, week):
            if d.month != month:
                col.write("")
                continue
            label = str(d.day)
            if st.button(label, key=f"calbtn_{year}_{month}_{d.day}", use_container_width=True):
                st.session_state[pick_key] = d
            if ledger is not None and not ledger.empty:
                row = ledger.loc[ledger["Date"] == d]
                if not row.empty and int(row.iloc[0].get("Slots_league_eligible", 0) or 0) > 0:
                    col.caption("slots")
                elif not row.empty:
                    col.caption("—")


def render_day_detail(
    *,
    d: date | None,
    ledger: pd.DataFrame | None,
    sched: pd.DataFrame | None,
) -> None:
    if d is None:
        st.info("Pick a day from the grid above.")
        return
    st.subheader(d.isoformat())
    rows = schedule_rows_for_date(sched, d)
    if not rows.empty:
        st.success(f"{len(rows)} scheduled league match row(s) on this date (from schedule).")
        show = [
            c
            for c in (
                "Round",
                "Date_time",
                "Home_Team_ID",
                "Away_Team_ID",
                "Venue_Stadium_ID",
                "Travel_km",
                "Slot_tier",
                "Is_CAF",
                "Is_FIFA",
            )
            if c in rows.columns
        ]
        st.dataframe(rows[show], use_container_width=True, height=min(400, 80 + 40 * len(rows)))
        return
    ledger_row = None
    if ledger is not None and not ledger.empty:
        hit = ledger.loc[ledger["Date"] == d]
        if not hit.empty:
            ledger_row = hit.iloc[0].to_dict()
    for line in explain_day_without_matches(ledger_row):
        st.write(f"- {line}")
