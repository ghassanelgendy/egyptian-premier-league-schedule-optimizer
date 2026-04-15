"""CP-SAT assignment: each fixture -> one slot; stadium + team conflict."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Any

from ortools.sat.python import cp_model


@dataclass(frozen=True)
class Match:
    idx: int
    round_idx: int
    home: str
    away: str
    venue: str
    travel_cost: float
    match_tier: int | None = None
    orig_week_order: int | None = None
    is_t1_vs_t1: bool = False
    #: Multiplier on ``w_postpone_week_distance`` when match is moved off its nominal week (>=1).
    postpone_weight_mult: float = 1.0


def solve_assignment(
    matches: list[Match],
    slot_meta: list[dict],
    feasible: list[list[int]],
    time_limit_s: float | None = 120.0,
    *,
    optimize: bool = True,
    stop_after_first_solution: bool = False,
    on_solution: Callable[[dict[str, Any]], None] | None = None,
    hints: dict[int, int] | None = None,
    max_matches_per_slot: int = 2,
    w_slot_overlap: int = 1_000_000,
    w_tier_mismatch: int = 1_000,
    w_top_tier_non_prime_day: int = 5_000,
    w_postpone_week_distance: int = 50_000,
    w_postpone_fixed: int = 5_000_000,
    w_t1vst1_not_prime_night: int = 50_000_000,
) -> tuple[dict[int, int], int, str, float | None, dict[str, Any]]:
    """feasible[m] = list of slot indices allowed for match m."""
    model = cp_model.CpModel()
    x: dict[tuple[int, int], cp_model.IntVar] = {}
    for m, slots in enumerate(feasible):
        for t in slots:
            x[(m, t)] = model.NewBoolVar(f"x_m{m}_t{t}")

    # Warm start hints (best-effort; ignored if edge not present).
    if hints:
        for m, t in hints.items():
            try:
                key = (int(m), int(t))
            except Exception:
                continue
            var = x.get(key)
            if var is not None:
                model.AddHint(var, 1)

    for m, slots in enumerate(feasible):
        model.Add(sum(x[(m, t)] for t in slots) == 1)

    all_teams = sorted({tm for m in matches for tm in (m.home, m.away)})

    # Slot load / team conflicts / venue conflicts.
    #
    # IMPORTANT: build constraints sparsely by iterating over feasible (m,t) edges once.
    # The previous implementation used nested loops over (slot x team x matches),
    # which can become extremely expensive and can dominate runtime.
    slot_terms: dict[int, list[cp_model.IntVar]] = {}
    team_slot_terms: dict[tuple[str, int], list[cp_model.IntVar]] = {}
    venue_slot_terms: dict[tuple[str, int], list[cp_model.IntVar]] = {}
    for (m, t), var in x.items():
        slot_terms.setdefault(t, []).append(var)
        mm = matches[m]
        if mm.home:
            team_slot_terms.setdefault((mm.home, t), []).append(var)
        if mm.away:
            team_slot_terms.setdefault((mm.away, t), []).append(var)
        if mm.venue:
            venue_slot_terms.setdefault((mm.venue, t), []).append(var)

    # Allow up to N matches per slot (default 2).
    for t, vs in slot_terms.items():
        if len(vs) > 1:
            model.Add(sum(vs) <= max_matches_per_slot)
        else:
            # Single variable also respects the cap implicitly (x in {0,1}).
            pass

    # Team cannot play two matches in the same slot.
    for (_team, t), vs in team_slot_terms.items():
        if len(vs) > 1:
            model.Add(sum(vs) <= 1)

    # Only one match per venue per slot.
    for (_venue, t), vs in venue_slot_terms.items():
        if len(vs) > 1:
            model.Add(sum(vs) <= 1)

    # Team cannot play two matches on same day, nor on consecutive days.
    # Requires slot_meta[t]["Date_ord"] to be an ordinal int (date.toordinal()).
    per_team_date: dict[tuple[str, int], list[cp_model.IntVar]] = {}
    for m, slots in enumerate(feasible):
        mm = matches[m]
        for t in slots:
            ordv = slot_meta[t].get("Date_ord")
            if ordv is None:
                continue
            try:
                ord_i = int(ordv)
            except Exception:
                continue
            per_team_date.setdefault((mm.home, ord_i), []).append(x[(m, t)])
            per_team_date.setdefault((mm.away, ord_i), []).append(x[(m, t)])

    for team in all_teams:
        ords = sorted({ord_i for (tm, ord_i) in per_team_date.keys() if tm == team})
        for ord_i in ords:
            vs = per_team_date.get((team, ord_i), [])
            if vs:
                model.Add(sum(vs) <= 1)
            # at least 2 days rest between matches:
            # no match on ord_i with ord_i+1 nor ord_i+2.
            vs1 = per_team_date.get((team, ord_i + 1), [])
            vs2 = per_team_date.get((team, ord_i + 2), [])
            if vs and (vs1 or vs2):
                model.Add(sum(vs) + sum(vs1) + sum(vs2) <= 1)

    # Max 2 consecutive HOME or AWAY matches in scheduled time order.
    #
    # We model each team’s season as a sequence over all distinct Date_ord values:
    #   0 = no match that date, 1 = home, 2 = away.
    # Gaps (0) reset the H/A streak, matching typical league fairness rules.
    # DFA states:
    # 0 start/none, 1 H1, 2 H2, 3 A1, 4 A2
    transitions = []
    # From start/none
    transitions += [(0, 0, 0), (0, 1, 1), (0, 2, 3)]
    # From H1
    transitions += [(1, 0, 0), (1, 1, 2), (1, 2, 3)]
    # From H2 (cannot take another HOME)
    transitions += [(2, 0, 0), (2, 2, 3)]
    # From A1
    transitions += [(3, 0, 0), (3, 2, 4), (3, 1, 1)]
    # From A2 (cannot take another AWAY)
    transitions += [(4, 0, 0), (4, 1, 1)]
    final_states = [0, 1, 2, 3, 4]

    # Build (team, date_ord) -> list of x vars once (O(#x)).
    home_terms_by_team_date: dict[tuple[str, int], list[cp_model.IntVar]] = {}
    away_terms_by_team_date: dict[tuple[str, int], list[cp_model.IntVar]] = {}
    for m, slots in enumerate(feasible):
        mm = matches[m]
        for t in slots:
            ordv = slot_meta[t].get("Date_ord")
            if ordv is None:
                continue
            try:
                ord_i = int(ordv)
            except Exception:
                continue
            if mm.home:
                home_terms_by_team_date.setdefault((mm.home, ord_i), []).append(x[(m, t)])
            if mm.away:
                away_terms_by_team_date.setdefault((mm.away, ord_i), []).append(x[(m, t)])

    for team in all_teams:
        # Only include dates where this team could possibly be scheduled (reduces model size).
        date_ords_team = sorted(
            {ord_i for (tm, ord_i) in home_terms_by_team_date.keys() if tm == team}
            | {ord_i for (tm, ord_i) in away_terms_by_team_date.keys() if tm == team}
        )
        symbols: list[cp_model.IntVar] = []
        for ord_i in date_ords_team:
            home_terms = home_terms_by_team_date.get((team, ord_i), [])
            away_terms = away_terms_by_team_date.get((team, ord_i), [])

            home_sum = model.NewIntVar(0, 1, f"ha_home_{team}_{ord_i}")
            away_sum = model.NewIntVar(0, 1, f"ha_away_{team}_{ord_i}")
            model.Add(home_sum == sum(home_terms) if home_terms else home_sum == 0)
            model.Add(away_sum == sum(away_terms) if away_terms else away_sum == 0)
            model.Add(home_sum + away_sum <= 1)

            sym = model.NewIntVar(0, 2, f"ha_sym_{team}_{ord_i}")
            model.AddAllowedAssignments(
                [home_sum, away_sum, sym],
                [(0, 0, 0), (1, 0, 1), (0, 1, 2)],
            )
            symbols.append(sym)

        if symbols:
            model.AddAutomaton(symbols, 0, final_states, transitions)

    obj: list[cp_model.LinearExpr] = []

    # Penalize overloaded slots (2 matches in same slot).
    if max_matches_per_slot >= 2:
        overload_bools: list[cp_model.IntVar] = []
        for t in range(len(slot_meta)):
            ms_all = [m for m in range(len(matches)) if t in feasible[m]]
            if not ms_all:
                continue
            y = model.NewIntVar(0, max_matches_per_slot, f"slot_load_{t}")
            model.Add(y == sum(x[(m, t)] for m in ms_all))
            b2 = model.NewBoolVar(f"slot_overload_{t}")
            model.Add(y >= 2).OnlyEnforceIf(b2)
            model.Add(y <= 1).OnlyEnforceIf(b2.Not())
            overload_bools.append(b2)
        if overload_bools:
            obj.append(w_slot_overlap * sum(overload_bools))

    for m, slots in enumerate(feasible):
        c = int(round(matches[m].travel_cost * 10))
        c = max(c, 1)
        for t in slots:
            if optimize:
                obj.append(c * x[(m, t)])

            # Tier penalty when slot is worse than match tier.
            mt = matches[m].match_tier
            st = slot_meta[t].get("Slot_tier")
            if mt is not None and st is not None:
                try:
                    mt_i = int(mt)
                    st_i = int(st)
                    if st_i > mt_i:
                        if optimize:
                            obj.append(int(w_tier_mismatch * (st_i - mt_i)) * x[(m, t)])
                except Exception:
                    pass

            # Prime day preference for top-tier matches: prefer Friday/Saturday.
            # (Soft objective; hard constraints still enforced elsewhere.)
            mt = matches[m].match_tier
            if mt is not None:
                try:
                    mt_i = int(mt)
                except Exception:
                    mt_i = None
                if mt_i == 1:
                    dn = str(slot_meta[t].get("Day_name", "")).strip().upper()[:3]
                    if dn not in ("FRI", "SAT"):
                        if optimize:
                            obj.append(int(w_top_tier_non_prime_day) * x[(m, t)])

            # Prime-night weekend slot preference for Tier1 vs Tier1 matches.
            if matches[m].is_t1_vs_t1:
                if int(slot_meta[t].get("Is_Prime_Night", 0) or 0) != 1:
                    if optimize:
                        obj.append(int(w_t1vst1_not_prime_night) * x[(m, t)])

            # Prefer the nearest feasible week when postponed (soft objective).
            ow = matches[m].orig_week_order
            tw = slot_meta[t].get("Week_order")
            if ow is not None and tw is not None:
                try:
                    ow_i = int(ow)
                    tw_i = int(tw)
                    if tw_i != ow_i:
                        if optimize:
                            mult = float(matches[m].postpone_weight_mult)
                            obj.append(
                                int(float(w_postpone_week_distance) * mult * abs(tw_i - ow_i)) * x[(m, t)]
                            )
                except Exception:
                    pass

        # Explicit postponement variable: is_postponed[m] = 1 if assigned week != nominal week.
        ow = matches[m].orig_week_order
        if ow is not None and optimize and w_postpone_fixed > 0:
            try:
                ow_i = int(ow)
            except Exception:
                ow_i = None
            if ow_i is not None:
                post_terms: list[cp_model.IntVar] = []
                for t in slots:
                    tw = slot_meta[t].get("Week_order")
                    try:
                        tw_i = int(tw) if tw is not None else None
                    except Exception:
                        tw_i = None
                    if tw_i is None:
                        continue
                    if tw_i != ow_i:
                        post_terms.append(x[(m, t)])
                if post_terms:
                    is_post = model.NewBoolVar(f"is_postponed_m{m}")
                    model.Add(sum(post_terms) == is_post)
                    obj.append(int(w_postpone_fixed) * is_post)
    if optimize and obj:
        model.Minimize(sum(obj))

    solver = cp_model.CpSolver()
    if time_limit_s is not None:
        solver.parameters.max_time_in_seconds = float(time_limit_s)
    if stop_after_first_solution:
        solver.parameters.stop_after_first_solution = True
    solver.parameters.num_search_workers = 8

    class _Cb(cp_model.CpSolverSolutionCallback):
        def __init__(self) -> None:
            super().__init__()
            self._n = 0

        def OnSolutionCallback(self) -> None:
            self._n += 1
            if on_solution is None:
                return
            try:
                on_solution(
                    {
                        "solutions": int(self._n),
                        "objective": float(self.ObjectiveValue()) if optimize else None,
                        "best_bound": float(self.BestObjectiveBound()) if optimize else None,
                    }
                )
            except Exception:
                pass

    cb = _Cb() if on_solution is not None else None
    if cb is None:
        status = solver.Solve(model)
    else:
        # OR-Tools Python API compatibility:
        # - Newer versions: SolveWithSolutionCallback(model, cb)
        # - Older versions: Solve(model, cb)
        if hasattr(solver, "SolveWithSolutionCallback"):
            status = solver.SolveWithSolutionCallback(model, cb)  # type: ignore[attr-defined]
        else:
            status = solver.Solve(model, cb)
    st = solver.StatusName(status)
    stats: dict[str, Any] = {
        "status": st,
        "cp_status": int(status),
        "optimize": bool(optimize),
        "stop_after_first_solution": bool(stop_after_first_solution),
        "time_limit_s": float(time_limit_s) if time_limit_s is not None else None,
        "objective_value": float(solver.ObjectiveValue()) if optimize and status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None,
        "best_bound": float(solver.BestObjectiveBound()) if optimize else None,
        "num_x_vars": int(len(x)),
        "num_matches": int(len(matches)),
        "num_slots": int(len(slot_meta)),
        "response_stats": str(solver.ResponseStats()).strip(),
    }
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {}, status, st, None, stats

    assign: dict[int, int] = {}
    for m, slots in enumerate(feasible):
        for t in slots:
            if solver.Value(x[(m, t)]) == 1:
                assign[m] = t
                break
    objective_value = float(solver.ObjectiveValue())
    return assign, status, st, objective_value, stats