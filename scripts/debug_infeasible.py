from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

# Ensure repo root is on sys.path when running as a script.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from schedule_optimizer.load_data import (
    LoadLog,
    build_team_date_blackout,
    eligible_calendar_weeks,
    load_everything,
    slot_date_series,
)
from schedule_optimizer.normalize import strip_team_id
from schedule_optimizer.round_robin import double_round_robin


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--caf-buffer-days", type=int, default=4)
    ap.add_argument("--home", type=str, default="AHL")
    ap.add_argument("--away", type=str, default="PHA")
    args = ap.parse_args()

    caf_buffer_days = int(args.caf_buffer_days)
    home = strip_team_id(args.home)
    away = strip_team_id(args.away)

    log = LoadLog()
    data = load_everything(log)
    teams = data["teams"]
    slots = data["slots"].reset_index(drop=True)
    blockers = data["blockers"]
    fifa_dates = data["fifa_dates"]

    black = build_team_date_blackout(
        teams,
        slots,
        blockers,
        fifa_dates,
        data["caf_cl_dates"],
        data["caf_cc_dates"],
        log,
        caf_buffer_days=caf_buffer_days,
    )

    sdt = slot_date_series(slots)
    season_dates = {d.date() for d in sdt.dropna()}
    fifa_in_season = fifa_dates & season_dates
    for tid in black:
        black[tid].update(fifa_in_season)

    eligible = eligible_calendar_weeks(slots, fifa_dates)
    if len(eligible) < 34:
        print(f"Not enough eligible weeks: {len(eligible)}")
        return 2

    week_for_round = {r: eligible[r] for r in range(34)}

    team_ids = [strip_team_id(x) for x in teams["Team_ID"].tolist()]
    team_ids = [t for t in team_ids if t]
    frs = double_round_robin(team_ids)

    fx = next((f for f in frs if f.home == home and f.away == away), None)
    if fx is None:
        print(f"Fixture not found: {home} vs {away}")
        return 2

    week = int(week_for_round[fx.round_idx])
    print(f"Fixture: {fx.home} vs {fx.away}")
    print(f"Round_idx (0-based): {fx.round_idx}  => Round (1-based): {fx.round_idx + 1}")
    print(f"Mapped Week_Num: {week}")

    week_slots = slots[slots["Week_Num"].astype(int) == week].copy()
    week_slots["_date"] = pd.to_datetime(week_slots["Date"], errors="coerce").dt.date
    week_slots["_dt"] = pd.to_datetime(week_slots["Date time"], errors="coerce")
    week_slots["_Is_FIFA"] = week_slots["Is_FIFA"].fillna(0).astype(int)
    week_slots["_Is_CAF"] = week_slots["Is_CAF"].fillna(0).astype(int)
    week_slots["_Is_SuperCup"] = week_slots["Is_SuperCup"].fillna(0).astype(int)

    def cont_flag(tid: str) -> str | None:
        if tid not in teams.index:
            return None
        cf = teams.loc[tid, "Cont_Flag"]
        if pd.isna(cf):
            return None
        s = str(cf).strip().upper()
        return s if s else None

    cf_home = cont_flag(home)
    cf_away = cont_flag(away)
    print(f"Cont_Flag: {home}={cf_home!r}, {away}={cf_away!r}")

    reasons: list[str] = []
    for _, row in week_slots.iterrows():
        d = row["_date"]
        if pd.isna(row["_dt"]) or d is None or pd.isna(pd.to_datetime(row["Date"], errors="coerce")):
            reasons.append("bad_date")
            continue
        if row["_Is_FIFA"] == 1:
            reasons.append("Is_FIFA_flag")
            continue
        if row["_Is_SuperCup"] == 1:
            reasons.append("Is_SuperCup_flag")
            continue
        if d in fifa_in_season:
            reasons.append("FIFA_union_date")
            continue
        if d in black.get(home, set()) or d in black.get(away, set()):
            who = []
            if d in black.get(home, set()):
                who.append(home)
            if d in black.get(away, set()):
                who.append(away)
            reasons.append("team_blackout:" + "+".join(who))
            continue
        if row["_Is_CAF"] == 1 and (
            (cf_home in ("CL", "CC")) or (cf_away in ("CL", "CC"))
        ):
            reasons.append("Is_CAF_slot_for_cont_team")
            continue
        reasons.append("OK")

    week_slots["_reason"] = reasons
    print("\nReason counts:")
    print(week_slots["_reason"].value_counts().to_string())

    week_dates = sorted({d for d in week_slots["_date"].dropna().tolist()})
    print("\nWeek dates:")
    print(week_dates)

    print(f"\n{home} blackout dates within week:")
    print(sorted(set(week_dates) & black.get(home, set())))
    print(f"\n{away} blackout dates within week:")
    print(sorted(set(week_dates) & black.get(away, set())))

    cols = ["Day_ID", "Date", "Date time", "Day_name", "Is_FIFA", "Is_CAF", "Is_SuperCup", "_reason"]
    print("\nSample week slots (up to 30):")
    print(week_slots[cols].head(30).to_string(index=False))

    ok = (week_slots["_reason"] == "OK").sum()
    return 0 if ok > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

