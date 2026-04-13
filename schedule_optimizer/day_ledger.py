"""Per-calendar-date facts derived only from expanded calendar + FIFA union (for UI / PRD)."""
from __future__ import annotations

from datetime import date

import pandas as pd

from .load_data import slot_date_series


def build_day_ledger(slots: pd.DataFrame, fifa_union_dates: set[date]) -> pd.DataFrame:
    """
    One row per calendar date that appears in ``slots`` ``Date``/parsed slot datetime.

    Columns are used by the Streamlit calendar to explain days with **no** league rows.
    """
    sdt = slot_date_series(slots)
    dcol = sdt.dt.date
    rows_out: list[dict] = []
    for d in sorted({pd.Timestamp(x).date() for x in dcol.dropna().tolist()}):
        mask = dcol == d
        sub = slots.loc[mask].copy()
        n = int(len(sub))
        if n == 0:
            continue
        is_fifa_date = bool(d in fifa_union_dates)
        fifa_flag = int((sub.get("Is_FIFA", 0).fillna(0).astype(int) == 1).sum())
        supercup = int((sub.get("Is_SuperCup", 0).fillna(0).astype(int) == 1).sum())
        date_ok = d not in fifa_union_dates
        league_eligible_mask = (
            (sub.get("Is_FIFA", 0).fillna(0).astype(int) != 1)
            & (sub.get("Is_SuperCup", 0).fillna(0).astype(int) != 1)
            & date_ok
        )
        n_league_eligible = int(league_eligible_mask.sum())
        caf_slots = int((sub.get("Is_CAF", 0).fillna(0).astype(int) == 1).sum())
        rows_out.append(
            {
                "Date": d,
                "Slot_rows": n,
                "Slots_FIFA_flag": fifa_flag,
                "Slots_SuperCup_flag": supercup,
                "Slots_Is_CAF_flag": caf_slots,
                "Slots_league_eligible": n_league_eligible,
                "Is_FIFA_union_date": int(is_fifa_date),
            }
        )
    return pd.DataFrame(rows_out).sort_values("Date").reset_index(drop=True)
