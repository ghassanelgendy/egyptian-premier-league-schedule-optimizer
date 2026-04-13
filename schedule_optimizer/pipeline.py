"""Callable optimization pipeline (CLI and UI)."""
from __future__ import annotations

import os
import json
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

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
from .day_ledger import build_day_ledger
from .normalize import strip_team_id
from .paths import OUTPUT
from .phases_dir import phases_dir
from .round_robin import double_round_robin_randomized


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
    time_limit_s: float | None = None,
    write_outputs: bool = True,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
) -> OptimizationResult:
    """
    Run full load + build + CP-SAT + optional CSV export.

    ``caf_buffer_days`` defaults from env ``EPL_CAF_BUFFER_DAYS`` or ``1``.
    """
    t0 = time.perf_counter()
    log = LoadLog()
    def _progress(stage: str, **data: Any) -> None:
        if progress_cb is None:
            return
        try:
            progress_cb({"stage": stage, "t": time.perf_counter() - t0, **data})
        except Exception:
            pass
    if caf_buffer_days is None:
        caf_buffer_days = int(os.environ.get("EPL_CAF_BUFFER_DAYS", "1"))
    log.add("CAF blocker buffer days each side: " + str(caf_buffer_days))

    if time_limit_s is None:
        tls = os.environ.get("EPL_PHASE2_TIME_LIMIT_S")
        if tls is not None and str(tls).strip() != "":
            time_limit_s = float(tls)

    data = load_everything(log)
    _progress("loaded_inputs")
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
    _progress("built_blackouts")

    eligible = eligible_calendar_weeks(slots, fifa_dates)
    _progress("eligible_weeks", count=len(eligible))
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
    eligible_weeks_set = set(int(w) for w in eligible)
    week_order_for_weeknum = {int(w): i for i, w in enumerate(eligible)}

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

    ph_root = phases_dir()
    if write_outputs:
        ph_root.mkdir(parents=True, exist_ok=True)
        (ph_root / "01_load_summary.json").write_text(
            json.dumps(
                {
                    "slot_rows": int(len(slots)),
                    "team_count": int(len(team_ids)),
                    "eligible_week_count": int(len(eligible)),
                    "inputs_loaded_keys": sorted(str(k) for k in data.keys()),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        pd.DataFrame(
            [{"Team_ID": t, "Blackout_date_count": len(black.get(t, set()))} for t in team_ids]
        ).sort_values("Blackout_date_count", ascending=False).to_csv(ph_root / "02_blackout_summary.csv", index=False)
        pd.DataFrame(
            [{"eligible_index": i, "Calendar_Week_Num": int(w)} for i, w in enumerate(eligible)]
        ).to_csv(ph_root / "03_eligible_calendar_weeks.csv", index=False)

    # Mark "prime night" slots: Friday/Saturday AND latest time within that calendar date.
    dt_series = pd.to_datetime(slots["Date time"], errors="coerce")
    date_series = pd.to_datetime(slots["Date"], errors="coerce").dt.date
    day_series = slots.get("Day_name", pd.Series([""] * len(slots))).astype(str).str.strip().str.upper().str[:3]
    max_dt_by_date: dict[object, object] = {}
    for i in range(len(slots)):
        d = date_series.iloc[i]
        dt = dt_series.iloc[i]
        if pd.isna(d) or pd.isna(dt):
            continue
        cur = max_dt_by_date.get(d)
        if cur is None or dt > cur:
            max_dt_by_date[d] = dt

    slot_meta: list[dict] = []
    for i in range(len(slots)):
        row = slots.iloc[i]
        stier = slot_tier(str(row.get("Day_name", "")), row["Date time"])
        dnorm = sdt.iloc[i]
        date_ord = int(dnorm.date().toordinal()) if not pd.isna(dnorm) else None
        d = date_series.iloc[i]
        dt = dt_series.iloc[i]
        dn = day_series.iloc[i]
        is_prime_night = (
            (dn in ("FRI", "SAT"))
            and (not pd.isna(d))
            and (not pd.isna(dt))
            and (max_dt_by_date.get(d) == dt)
        )
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
                "Slot_tier": int(stier),
                "Date_ord": date_ord,
                "Week_order": week_order_for_weeknum.get(int(row["Week_Num"])),
                "Is_Prime_Night": int(1 if is_prime_night else 0),
            }
        )

    day_ledger_df = build_day_ledger(slots, fifa_dates)
    if write_outputs:
        day_ledger_df.to_csv(ph_root / "03b_season_day_ledger.csv", index=False)

    def slot_ok_for_match(m: Match, t: int, *, allow_postponed: bool = False) -> bool:
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
        if not allow_postponed:
            if sm["Week_Num"] != week_for_round[m.round_idx]:
                return False
        else:
            # Postponed match: can be scheduled in any eligible week (dynamic repair).
            w = int(sm["Week_Num"])
            if w not in eligible_weeks_set:
                return False
        return True

    ordered_team_ids = sorted(team_ids, key=lambda tid: len(black.get(tid, set())), reverse=True)
    cont_postpone_mult = float(os.environ.get("EPL_CONT_POSTPONE_MULT", "4.0"))

    def _postpone_weight_mult(home: str, away: str) -> float:
        for tid in (home, away):
            if tid not in teams.index:
                continue
            cf = teams.loc[tid, "Cont_Flag"] if "Cont_Flag" in teams.columns else None
            if cf is None or pd.isna(cf):
                continue
            if str(cf).strip().upper() in ("CL", "CC"):
                return cont_postpone_mult
        return 1.0

    def _drr_strict_domain_score(frs_list: list) -> tuple[int, int]:
        """(min_strict_feasible_slots, sum) for a candidate DRR — higher tuple is better (lexicographic)."""
        cand: list[Match] = []
        for k, fx in enumerate(frs_list):
            try:
                v = venue_for_fixture(fx.home, fx.away, teams, sec)
            except Exception:
                return (-10**9, -10**9)
            # Travel not used by slot_ok; skip matrix lookups here for speed (validated later).
            c = 0.0
            ht = int(teams.loc[fx.home, "Tier"]) if "Tier" in teams.columns and fx.home in teams.index else None
            at = int(teams.loc[fx.away, "Tier"]) if "Tier" in teams.columns and fx.away in teams.index else None
            mt = int(min(ht, at)) if ht is not None and at is not None else None
            ow = int(week_order_for_weeknum[int(week_for_round[fx.round_idx])])
            is_t1vst1 = bool(ht == 1 and at == 1)
            cand.append(
                Match(
                    k,
                    fx.round_idx,
                    fx.home,
                    fx.away,
                    v,
                    c,
                    mt,
                    ow,
                    is_t1vst1,
                    _postpone_weight_mult(fx.home, fx.away),
                )
            )
        counts = [len([t for t in range(len(slot_meta)) if slot_ok_for_match(mm, t)]) for mm in cand]
        return (min(counts), sum(counts))

    seed_env = os.environ.get("EPL_DRR_SEED")
    seed = int(seed_env) if seed_env is not None and str(seed_env).strip() != "" else None
    drr_tries = int(os.environ.get("EPL_DRR_TRIES", "12"))
    drr_pick: dict[str, Any]
    if seed is not None:
        frs = double_round_robin_randomized(
            ordered_team_ids, seed=seed, max_streak=2, streak_scope="half", shuffle_teams=False
        )
        drr_pick = {"mode": "fixed_seed", "seed": int(seed), "score": list(_drr_strict_domain_score(frs))}
    else:
        best: tuple[int, int] | None = None
        best_frs = None
        for s in range(max(1, drr_tries)):
            frs_try = double_round_robin_randomized(
                ordered_team_ids, seed=s, max_streak=2, streak_scope="half", shuffle_teams=False
            )
            sc = _drr_strict_domain_score(frs_try)
            if best is None or sc > best:
                best = sc
                best_frs = frs_try
        frs = best_frs
        drr_pick = {"mode": "scored_tries", "tries": int(drr_tries), "best_score_min_sum": list(best or [0, 0])}

    if write_outputs:
        (ph_root / "04_drr_selection.json").write_text(json.dumps(drr_pick, indent=2), encoding="utf-8")

    _progress("generated_fixtures", fixtures=len(frs))
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
        ht = int(teams.loc[fx.home, "Tier"]) if "Tier" in teams.columns and fx.home in teams.index else None
        at = int(teams.loc[fx.away, "Tier"]) if "Tier" in teams.columns and fx.away in teams.index else None
        mt = None
        if ht is not None and at is not None:
            mt = int(min(ht, at))
        ow = int(week_order_for_weeknum[int(week_for_round[fx.round_idx])])
        is_t1vst1 = bool(ht == 1 and at == 1)
        matches.append(
            Match(
                k,
                fx.round_idx,
                fx.home,
                fx.away,
                v,
                c,
                mt,
                ow,
                is_t1vst1,
                _postpone_weight_mult(fx.home, fx.away),
            )
        )

    if write_outputs:
        pd.DataFrame(
            [
                {
                    "fixture_index": k,
                    "round_idx_0": fx.round_idx,
                    "Home_Team_ID": fx.home,
                    "Away_Team_ID": fx.away,
                }
                for k, fx in enumerate(frs)
            ]
        ).to_csv(ph_root / "05_fixtures_pre_solve.csv", index=False)

    feasible: list[list[int]] = []
    strict_slots: list[list[int]] = []
    post_slots: list[list[int]] = []
    relaxed_to_postpone: list[bool] = []
    postponed_rows: list[dict[str, object]] = []
    for m in matches:
        ok_slots_strict = [t for t in range(len(slot_meta)) if slot_ok_for_match(m, t)]
        ok_slots_post = [t for t in range(len(slot_meta)) if slot_ok_for_match(m, t, allow_postponed=True)]
        strict_slots.append(ok_slots_strict)
        post_slots.append(ok_slots_post)
        if ok_slots_strict:
            feasible.append(ok_slots_strict)
            relaxed_to_postpone.append(False)
            continue

        # If strict-week slots are empty, postpone this match into later eligible weeks.
        feasible.append(ok_slots_post)
        relaxed_to_postpone.append(True)

        # Diagnose WHY strict-week was infeasible (reason counts over that week).
        w0 = int(week_for_round[m.round_idx])
        strict_week_slots = [t for t in range(len(slot_meta)) if int(slot_meta[t]["Week_Num"]) == w0]
        strict_reason_counts: dict[str, int] = {}
        for t in strict_week_slots:
            sm = slot_meta[t]
            # Mirror slot_ok_for_match strict checks, but record first-failing reason.
            if sm["Is_FIFA"] == 1:
                r = "Is_FIFA_flag"
            elif sm["Is_SuperCup"] == 1:
                r = "Is_SuperCup_flag"
            else:
                d = sdt.iloc[t]
                if pd.isna(d):
                    r = "bad_date"
                else:
                    d0 = d.date()
                    if d0 in fifa_in_season:
                        r = "FIFA_union_date"
                    elif d0 in black[m.home] or d0 in black[m.away]:
                        who = []
                        if d0 in black[m.home]:
                            who.append("home")
                        if d0 in black[m.away]:
                            who.append("away")
                        r = "team_blackout:" + "+".join(who)
                    elif sm["Is_CAF"] == 1:
                        blocked = False
                        for tid in (m.home, m.away):
                            cf = teams.loc[tid, "Cont_Flag"]
                            if pd.isna(cf):
                                continue
                            cf = str(cf).strip().upper()
                            if cf in ("CL", "CC"):
                                blocked = True
                                break
                        r = "Is_CAF_slot_for_cont_team" if blocked else "OK"
                    else:
                        r = "OK"
            strict_reason_counts[r] = strict_reason_counts.get(r, 0) + 1

        top_reason = None
        if strict_reason_counts:
            top_reason = sorted(strict_reason_counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

        # "Before postponing" candidate: best-looking datetime in the original week,
        # even if blocked. This is for reporting only.
        candidate_t = None
        if strict_week_slots:
            def _cand_key(t: int) -> tuple:
                sm = slot_meta[t]
                dn = str(sm.get("Day_name", "")).strip().upper()[:3]
                is_weekend = 1 if dn in ("FRI", "SAT") else 0
                # prefer lower Slot_tier, then weekend, then earlier datetime
                dt = pd.to_datetime(sm.get("Date_time"), errors="coerce")
                dt_key = dt.value if not pd.isna(dt) else 2**63 - 1
                return (int(sm.get("Slot_tier", 9)), -is_weekend, dt_key)

            candidate_t = min(strict_week_slots, key=_cand_key)
        cand_sm = slot_meta[candidate_t] if candidate_t is not None else {}

        row: dict[str, object] = {
            "Home_Team_ID": m.home,
            "Away_Team_ID": m.away,
            "Round_idx_0_based": int(m.round_idx),
            "Round_1_based": int(m.round_idx) + 1,
            "Original_Week_Num": int(week_for_round[m.round_idx]),
            "Strict_feasible_slots": 0,
            "Postponed_feasible_slots": int(len(ok_slots_post)),
            "Postponed": bool(len(ok_slots_post) > 0),
            "Infeasible_reason_top": top_reason,
            "Infeasible_reason_counts_json": json.dumps(strict_reason_counts, ensure_ascii=False),
            "Candidate_Date_time_before_postpone": cand_sm.get("Date_time"),
            "Candidate_Weekday_before_postpone": cand_sm.get("Day_name"),
            "Candidate_Slot_tier_before_postpone": cand_sm.get("Slot_tier"),
            "Assigned_Date_time_after_postpone": None,
            "Assigned_Weekday_after_postpone": None,
            "Assigned_Week_Num_after_postpone": None,
        }
        postponed_rows.append(row)

        if not ok_slots_post:
            msg = f"INFEASIBLE even after postponement: match {m.home} vs {m.away} round {m.round_idx} has zero feasible slots."
            log.add(msg)
            if write_outputs:
                OUTPUT.mkdir(parents=True, exist_ok=True)
                pd.DataFrame(postponed_rows).to_csv(OUTPUT / "postponed_or_infeasible_matches.csv", index=False)
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
                    "postponed_matches": len([r for r in postponed_rows if r.get("Postponed")]),
                    "still_infeasible_matches": len([r for r in postponed_rows if not r.get("Postponed")]),
                },
            )

    if write_outputs:
        pd.DataFrame(
            [
                {
                    "fixture_index": m.idx,
                    "strict_feasible_slots": len(strict_slots[m.idx]),
                    "postponed_feasible_slots": len(post_slots[m.idx]),
                    "relaxed_to_postpone": bool(relaxed_to_postpone[m.idx]),
                }
                for m in matches
            ]
        ).to_csv(ph_root / "06_feasible_slot_counts.csv", index=False)

    drr_score_final = _drr_strict_domain_score(frs)
    log.add(f"DRR strict-domain score (min,sum)={list(drr_score_final)}")

    def build_schedule_df(assign: dict[int, int]) -> pd.DataFrame:
        rows = []
        for m in matches:
            t = assign[m.idx]
            sm = slot_meta[t]
            row = slots.iloc[t]
            tier = slot_tier(str(row.get("Day_name", "")), row["Date time"])
            home_tier = (
                int(teams.loc[m.home, "Tier"]) if "Tier" in teams.columns and m.home in teams.index else None
            )
            away_tier = (
                int(teams.loc[m.away, "Tier"]) if "Tier" in teams.columns and m.away in teams.index else None
            )
            match_tier = None
            if home_tier is not None and away_tier is not None:
                match_tier = int(min(home_tier, away_tier))
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
                    "Home_Tier": home_tier,
                    "Away_Tier": away_tier,
                    "Match_Tier": match_tier,
                    "Is_FIFA": sm["Is_FIFA"],
                    "Is_CAF": sm["Is_CAF"],
                    "Is_SuperCup": sm["Is_SuperCup"],
                    "Postponed": bool(
                        len(postponed_rows) > 0
                        and any(
                            (r["Home_Team_ID"] == m.home)
                            and (r["Away_Team_ID"] == m.away)
                            and (int(r["Round_idx_0_based"]) == int(m.round_idx))
                            and bool(r["Postponed"])
                            for r in postponed_rows
                        )
                    ),
                }
            )
        out_df = pd.DataFrame(rows)
        out_df.sort_values(["Round", "Date_time", "Home_Team_ID"], inplace=True)
        return out_df

    def dynamic_solve(
        *,
        phase: int,
        stop_first: bool,
        tl_s: float | None,
        optimize: bool,
    ) -> tuple[dict[int, int], str, float | None]:
        assign: dict[int, int] = {}
        st = "UNKNOWN"
        obj_scaled: float | None = None
        for _iter in range(len(matches) + 1):
            _progress(
                "solving",
                phase=phase,
                iter=int(_iter),
                relaxed_matches=int(sum(1 for x in relaxed_to_postpone if x)),
                stop_after_first=bool(stop_first),
                optimize=bool(optimize),
            )
            assign, _status, st, obj_scaled = solve_assignment(
                matches,
                slot_meta,
                feasible,
                time_limit_s=tl_s,
                optimize=optimize,
                stop_after_first_solution=stop_first,
                on_solution=(
                    (lambda ev, ph=phase: _progress("solution", phase=ph, **ev))
                    if progress_cb is not None
                    else None
                ),
                max_matches_per_slot=2,
                w_slot_overlap=1_000_000,
                w_tier_mismatch=1_000,
                w_top_tier_non_prime_day=5_000,
                w_postpone_week_distance=50_000,
            )
            if assign:
                _progress("solve_done", phase=phase, status=st, objective=obj_scaled)
                return assign, st, obj_scaled

            candidates = [
                (i, len(strict_slots[i]))
                for i in range(len(matches))
                if (not relaxed_to_postpone[i]) and len(strict_slots[i]) > 0
            ]
            if not candidates:
                break
            i_min = sorted(candidates, key=lambda x: (x[1], x[0]))[0][0]
            feasible[i_min] = post_slots[i_min]
            relaxed_to_postpone[i_min] = True
            _progress("relaxed_match", phase=phase, match_idx=int(i_min), new_domain=int(len(post_slots[i_min])))

        return {}, st, obj_scaled

    # Phase 1: get a feasible schedule quickly and write it.
    phase1_limit = float(os.environ.get("EPL_PHASE1_TIME_LIMIT_S", "30"))
    t_phase1 = time.perf_counter()
    assign1, st1, obj1 = dynamic_solve(phase=1, stop_first=True, tl_s=phase1_limit, optimize=False)
    phase1_time_s = time.perf_counter() - t_phase1
    if not assign1:
        msg = f"CP-SAT failed in phase 1 (feasibility): {st1}"
        log.add(msg)
        if write_outputs:
            OUTPUT.mkdir(parents=True, exist_ok=True)
            if postponed_rows:
                pd.DataFrame(postponed_rows).to_csv(OUTPUT / "postponed_or_infeasible_matches.csv", index=False)
            log.write(OUTPUT / "data_load_log.txt")
        return OptimizationResult(
            False,
            3,
            msg,
            log_lines=log.lines,
            solver_status=st1,
            wall_time_s=time.perf_counter() - t0,
        )

    out_df_phase1 = build_schedule_df(assign1)
    if write_outputs:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        out_df_phase1.to_csv(OUTPUT / "optimized_schedule_phase1.csv", index=False)
        (ph_root / "07_phase1_feasibility.json").write_text(
            json.dumps(
                {
                    "phase": 1,
                    "solver_status": st1,
                    "time_limit_s": phase1_limit,
                    "wall_time_s": round(phase1_time_s, 4),
                    "schedule_rows": int(len(out_df_phase1)),
                    "objective_internal_units": obj1,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    # Phase 2: optimize (unlimited by default).
    t_phase2 = time.perf_counter()
    assign2, st2, obj2 = dynamic_solve(phase=2, stop_first=False, tl_s=time_limit_s, optimize=True)
    phase2_time_s = time.perf_counter() - t_phase2
    if not assign2:
        msg = f"CP-SAT failed in phase 2 (optimize): {st2}"
        log.add(msg)
        if write_outputs:
            OUTPUT.mkdir(parents=True, exist_ok=True)
            if postponed_rows:
                pd.DataFrame(postponed_rows).to_csv(OUTPUT / "postponed_or_infeasible_matches.csv", index=False)
            log.write(OUTPUT / "data_load_log.txt")
        return OptimizationResult(
            False,
            3,
            msg,
            log_lines=log.lines,
            solver_status=st2,
            wall_time_s=time.perf_counter() - t0,
        )

    out_df = build_schedule_df(assign2)
    st = st2
    obj_scaled = obj2

    # Fill assigned datetime/weekday for postponed matches table.
    if postponed_rows:
        key_to_row = {(r["Home_Team_ID"], r["Away_Team_ID"], int(r["Round_idx_0_based"])): r for r in postponed_rows}
        for m in matches:
            k = (m.home, m.away, int(m.round_idx))
            if k not in key_to_row:
                continue
            t = assign2[m.idx]
            sm = slot_meta[t]
            rr = key_to_row[k]
            rr["Assigned_Date_time_after_postpone"] = sm.get("Date_time")
            rr["Assigned_Weekday_after_postpone"] = sm.get("Day_name")
            rr["Assigned_Week_Num_after_postpone"] = sm.get("Week_Num")
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
        "phase1_time_s": phase1_time_s,
        "phase2_time_s": phase2_time_s,
        "drr_strict_domain_min": int(drr_score_final[0]),
        "drr_strict_domain_sum": int(drr_score_final[1]),
        "cont_postpone_objective_mult": cont_postpone_mult,
        "drr_selection": drr_pick,
    }

    if write_outputs:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        out_df.to_csv(OUTPUT / "optimized_schedule_phase2.csv", index=False)
        out_df.to_csv(OUTPUT / "optimized_schedule.csv", index=False)
        week_df.to_csv(OUTPUT / "week_round_map.csv", index=False)
        if postponed_rows:
            pd.DataFrame(postponed_rows).to_csv(OUTPUT / "postponed_or_infeasible_matches.csv", index=False)
        (ph_root / "08_phase2_optimize.json").write_text(
            json.dumps(
                {
                    "phase": 2,
                    "solver_status": st2,
                    "time_limit_s": time_limit_s,
                    "wall_time_s": round(phase2_time_s, 4),
                    "schedule_rows": int(len(out_df)),
                    "objective_internal_units": obj_scaled,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        log.add(
            f"OK: wrote {OUTPUT / 'optimized_schedule.csv'} rows={len(out_df)} solver={st} "
            f"(phase1={st1} phase2={st2})"
        )
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
