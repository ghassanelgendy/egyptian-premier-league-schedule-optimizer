"""Callable optimization pipeline (CLI and UI)."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd

from .cp_sat_model import Match, solve_assignment
from .load_data import (
    LoadLog,
    build_team_date_blackout,
    dist_lookup,
    eligible_calendar_weeks,
    load_everything,
    slot_date_series,
    slot_tier,
    venue_for_fixture,
)
from .normalize import strip_team_id
from .paths import OUTPUT
from .round_robin import double_round_robin


@dataclass
class OptimizationResult:
    """Outcome of one optimization run."""

    success: bool
    exit_code: int
    message: str
    schedule_df: pd.DataFrame | None = None
    week_round_df: pd.DataFrame | None = None
    log_lines: list[str] = field(default_factory=list)
    solver_status: str | None = None
    objective_scaled: float | None = None
    wall_time_s: float = 0.0
    stats: dict[str, Any] = field(default_factory=dict)


def run_optimization(
    *,
    caf_buffer_days: int | None = None,
    time_limit_s: float = 180.0,
    write_outputs: bool = True,
) -> OptimizationResult:
    """
    Run full load + build + CP-SAT + optional CSV export.

    ``caf_buffer_days`` defaults from env ``EPL_CAF_BUFFER_DAYS`` or ``1``.
    """
    t0 = time.perf_counter()
    log = LoadLog()
    if caf_buffer_days is None:
        caf_buffer_days = int(os.environ.get("EPL_CAF_BUFFER_DAYS", "1"))
    log.add("CAF blocker buffer days each side: " + str(caf_buffer_days))

    data = load_everything(log)
    teams = data["teams"]
    slots = data["slots"].reset_index(drop=True)
    sec = data["security"]
    dist = data["dist_km"]
    fifa_dates: set[date] = data["fifa_dates"]
    blockers = data["blockers"]

    sdt = slot_date_series(slots)
    season_dates = {d.date() for d in sdt.dropna()}
    fifa_in_season = fifa_dates & season_dates

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
    for tid in black:
        black[tid].update(fifa_in_season)

    eligible = eligible_calendar_weeks(slots, fifa_dates)
    if len(eligible) < 34:
        msg = f"INFEASIBLE: only {len(eligible)} calendar weeks with>=9 usable slots (need 34)."
        log.add(msg)
        if write_outputs:
            log.write(OUTPUT / "data_load_log.txt")
        return OptimizationResult(
            False,
            2,
            msg,
            log_lines=log.lines,
            wall_time_s=time.perf_counter() - t0,
        )

    week_for_round = {r: eligible[r] for r in range(34)}

    team_ids = [strip_team_id(x) for x in teams["Team_ID"].tolist()]
    team_ids = [t for t in team_ids if t]
    if len(team_ids) % 2:
        msg = "INFEASIBLE: odd number of teams."
        log.add(msg)
        if write_outputs:
            log.write(OUTPUT / "data_load_log.txt")
        return OptimizationResult(
            False,
            2,
            msg,
            log_lines=log.lines,
            wall_time_s=time.perf_counter() - t0,
        )

    frs = double_round_robin(team_ids)
    matches: list[Match] = []
    for k, fx in enumerate(frs):
        v = venue_for_fixture(fx.home, fx.away, teams, sec)
        try:
            c = dist_lookup(dist, teams.loc[fx.home, "Home_Stadium"], v) + dist_lookup(
                dist, teams.loc[fx.away, "Home_Stadium"], v
            )
        except KeyError as e:
            msg = f"INFEASIBLE: distance missing {e}"
            log.add(msg)
            if write_outputs:
                log.write(OUTPUT / "data_load_log.txt")
            return OptimizationResult(
                False,
                2,
                str(e),
                log_lines=log.lines,
                wall_time_s=time.perf_counter() - t0,
            )
        matches.append(Match(k, fx.round_idx, fx.home, fx.away, v, c))

    slot_meta: list[dict] = []
    for i in range(len(slots)):
        row = slots.iloc[i]
        slot_meta.append(
            {
                "idx": i,
                "Week_Num": int(row["Week_Num"]),
                "Day_ID": str(row["Day_ID"]),
                "Date": row["Date"],
                "Date_time": row["Date time"],
                "Day_name": row.get("Day_name", ""),
                "Is_FIFA": int(row.get("Is_FIFA", 0) or 0),
                "Is_CAF": int(row.get("Is_CAF", 0) or 0),
                "Is_SuperCup": int(row.get("Is_SuperCup", 0) or 0),
            }
        )

    def slot_ok_for_match(m: Match, t: int) -> bool:
        sm = slot_meta[t]
        if sm["Is_FIFA"] == 1 or sm["Is_SuperCup"] == 1:
            return False
        d = sdt.iloc[t]
        if pd.isna(d):
            return False
        d0 = d.date()
        if d0 in fifa_in_season:
            return False
        if d0 in black[m.home] or d0 in black[m.away]:
            return False
        if sm["Is_CAF"] == 1:
            for tid in (m.home, m.away):
                cf = teams.loc[tid, "Cont_Flag"]
                if pd.isna(cf):
                    continue
                cf = str(cf).strip().upper()
                if cf in ("CL", "CC"):
                    return False
        if sm["Week_Num"] != week_for_round[m.round_idx]:
            return False
        return True

    feasible: list[list[int]] = []
    for m in matches:
        ok_slots = [t for t in range(len(slot_meta)) if slot_ok_for_match(m, t)]
        feasible.append(ok_slots)
        if not ok_slots:
            msg = f"INFEASIBLE: match {m.home} vs {m.away} round {m.round_idx} has zero feasible slots."
            log.add(msg)
            if write_outputs:
                log.write(OUTPUT / "data_load_log.txt")
            return OptimizationResult(
                False,
                2,
                msg,
                log_lines=log.lines,
                wall_time_s=time.perf_counter() - t0,
                stats={
                    "feasible_slots_min": min((len(f) for f in feasible), default=0),
                    "matches_built": len(matches),
                },
            )

    assign, status, st, obj_scaled = solve_assignment(
        matches, slot_meta, feasible, time_limit_s=time_limit_s
    )
    if not assign:
        msg = f"CP-SAT failed: {st}"
        log.add(msg)
        if write_outputs:
            log.write(OUTPUT / "data_load_log.txt")
        return OptimizationResult(
            False,
            3,
            msg,
            log_lines=log.lines,
            solver_status=st,
            wall_time_s=time.perf_counter() - t0,
        )

    rows = []
    for m in matches:
        t = assign[m.idx]
        sm = slot_meta[t]
        row = slots.iloc[t]
        tier = slot_tier(str(row.get("Day_name", "")), row["Date time"])
        rows.append(
            {
                "Round": int(m.round_idx) + 1,
                "Calendar_Week_Num": sm["Week_Num"],
                "Day_ID": sm["Day_ID"],
                "Date": row["Date"],
                "Date_time": row["Date time"],
                "Home_Team_ID": m.home,
                "Away_Team_ID": m.away,
                "Venue_Stadium_ID": m.venue,
                "Travel_km": round(m.travel_cost, 3),
                "Slot_tier": tier,
                "Is_FIFA": sm["Is_FIFA"],
                "Is_CAF": sm["Is_CAF"],
                "Is_SuperCup": sm["Is_SuperCup"],
            }
        )

    out_df = pd.DataFrame(rows)
    out_df.sort_values(["Round", "Date_time", "Home_Team_ID"], inplace=True)
    week_df = pd.DataFrame(
        [{"Round": r + 1, "Calendar_Week_Num": week_for_round[r]} for r in range(34)]
    )

    total_travel = float(out_df["Travel_km"].sum())
    stats: dict[str, Any] = {
        "matches": len(out_df),
        "teams": len(team_ids),
        "rounds": int(out_df["Round"].max()),
        "total_travel_km": total_travel,
        "mean_travel_km_per_match": total_travel / len(out_df),
        "slot_tier_counts": out_df["Slot_tier"].value_counts().sort_index().to_dict(),
        "solver_status": st,
        "objective_internal_units": obj_scaled,
        "objective_approx_travel_km": (obj_scaled / 10.0) if obj_scaled is not None else None,
        "caf_buffer_days": caf_buffer_days,
        "feasible_slots_min": min(len(f) for f in feasible),
        "feasible_slots_max": max(len(f) for f in feasible),
        "feasible_slots_mean": sum(len(f) for f in feasible) / len(feasible),
    }

    if write_outputs:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        out_df.to_csv(OUTPUT / "optimized_schedule.csv", index=False)
        week_df.to_csv(OUTPUT / "week_round_map.csv", index=False)
        log.add(f"OK: wrote {OUTPUT / 'optimized_schedule.csv'} rows={len(out_df)} solver={st}")
        log.write(OUTPUT / "data_load_log.txt")

    wall = time.perf_counter() - t0
    return OptimizationResult(
        True,
        0,
        log.lines[-1] if log.lines else "OK",
        schedule_df=out_df,
        week_round_df=week_df,
        log_lines=log.lines,
        solver_status=st,
        objective_scaled=obj_scaled,
        wall_time_s=wall,
        stats=stats,
    )
