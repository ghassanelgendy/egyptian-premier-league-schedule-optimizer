"""CP-SAT assignment: each fixture -> one slot; stadium + team conflict."""
from __future__ import annotations

from dataclasses import dataclass

from ortools.sat.python import cp_model


@dataclass(frozen=True)
class Match:
    idx: int
    round_idx: int
    home: str
    away: str
    venue: str
    travel_cost: float


def solve_assignment(
    matches: list[Match],
    slot_meta: list[dict],
    feasible: list[list[int]],
    time_limit_s: float = 120.0,
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

    for t in range(len(slot_meta)):
        for team in all_teams:
            ms = [
                m
                for m in range(len(matches))
                if team in (matches[m].home, matches[m].away) and t in feasible[m]
            ]
            if len(ms) > 1:
                model.Add(sum(x[(m, t)] for m in ms) <= 1)

        ms_all = [m for m in range(len(matches)) if t in feasible[m]]
        venues_at_t: dict[str, list[int]] = {}
        for m in ms_all:
            v = matches[m].venue
            venues_at_t.setdefault(v, []).append(m)
        for _v, ms2 in venues_at_t.items():
            if len(ms2) > 1:
                model.Add(sum(x[(m, t)] for m in ms2) <= 1)

    obj = []
    for m, slots in enumerate(feasible):
        c = int(round(matches[m].travel_cost * 10))
        c = max(c, 1)
        for t in slots:
            obj.append(c * x[(m, t)])
    model.Minimize(sum(obj))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)
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