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
    max_matches_per_slot: int = 2,
    w_slot_overlap: int = 1_000_000,
    w_tier_mismatch: int = 1_000,
    w_top_tier_non_prime_day: int = 5_000,
    w_postpone_week_distance: int = 50_000,
    w_t1vst1_not_prime_night: int = 50_000_000,
) -> tuple[dict[int, int], int, str, float | None]:
    """feasible[m] = list of slot indices allowed for match m."""
    model = cp_model.CpModel()
    x: dict[tuple[int, int], cp_model.IntVar] = {}
    for m, slots in enumerate(feasible):
        for t in slots:
            x[(m, t)] = model.NewBoolVar(f"x_m{m}_t{t}")

    for m, slots in enumerate(feasible):
        model.Add(sum(x[(m, t)] for t in slots) == 1)

    all_teams = sorted({tm for m in matches for tm in (m.home, m.away)})

    # One match per slot is preferred; allow 2 if needed.
    for t in range(len(slot_meta)):
        ms_all = [m for m in range(len(matches)) if t in feasible[m]]
        if ms_all:
            model.Add(sum(x[(m, t)] for m in ms_all) <= max_matches_per_slot)

        for team in all_teams:
            ms = [
                m
                for m in range(len(matches))
                if team in (matches[m].home, matches[m].away) and t in feasible[m]
            ]
            if len(ms) > 1:
                model.Add(sum(x[(m, t)] for m in ms) <= 1)

        venues_at_t: dict[str, list[int]] = {}
        for m in ms_all:
            v = matches[m].venue
            venues_at_t.setdefault(v, []).append(m)
        for _v, ms2 in venues_at_t.items():
            if len(ms2) > 1:
                model.Add(sum(x[(m, t)] for m in ms2) <= 1)

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

    # Max 2 consecutive HOME or AWAY matches in scheduled time order (gaps do NOT reset).
    #
    # We model each team’s season as a sequence over all distinct Date_ord values:
    #   0 = no match that date, 1 = home, 2 = away.
    # Gaps (0) do NOT reset the H/A streak, so streak is over consecutive *played* matches.
    # DFA states:
    # 0 start/none, 1 H1, 2 H2, 3 A1, 4 A2
    transitions = []
    # From start/none
    transitions += [(0, 0, 0), (0, 1, 1), (0, 2, 3)]
    # From H1
    transitions += [(1, 0, 1), (1, 1, 2), (1, 2, 3)]
    # From H2 (cannot take another HOME)
    transitions += [(2, 0, 2), (2, 2, 3)]
    # From A1
    transitions += [(3, 0, 3), (3, 2, 4), (3, 1, 1)]
    # From A2 (cannot take another AWAY)
    transitions += [(4, 0, 4), (4, 1, 1)]
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
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {}, status, st, None

    assign: dict[int, int] = {}
    for m, slots in enumerate(feasible):
        for t in slots:
            if solver.Value(x[(m, t)]) == 1:
                assign[m] = t
                break
    objective_value = float(solver.ObjectiveValue())
    return assign, status, st, objective_value