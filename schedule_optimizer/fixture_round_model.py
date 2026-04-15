"""CP-SAT model for choosing fixture pairings by round (double round-robin)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Any

from ortools.sat.python import cp_model


@dataclass(frozen=True)
class FixtureRoundSolution:
    """One complete double round-robin (home/away decided) by abstract round."""

    # (round_idx, home_team_id, away_team_id)
    fixtures: list[tuple[int, str, str]]
    objective: int | None


def solve_fixture_rounds(
    *,
    team_ids: list[str],
    rounds: int,
    # penalty[(home, away, round_idx)] -> non-negative integer.
    penalty: dict[tuple[str, str, int], int],
    time_limit_s: float | None = 15.0,
    max_solutions: int = 1,
    on_solution: Callable[[dict[str, Any]], None] | None = None,
) -> list[FixtureRoundSolution]:
    """
    Decide a double round-robin schedule by round using CP-SAT.

    Hard constraints (v1):
    - Each team plays exactly once per round.
    - Each ordered pairing (i hosts j) occurs exactly once across the season.
    - No team has 3 consecutive HOME or 3 consecutive AWAY over rounds.

    Objective:
    - Minimize sum of provided penalties for chosen (home,away,round) arcs.
    """
    if rounds <= 0:
        return []
    teams = list(team_ids)
    n = len(teams)
    if n < 2 or (n % 2) != 0:
        raise ValueError("team_ids must contain an even number of teams >= 2")
    if rounds != 2 * (n - 1):
        # The model can work with other sizes, but DRR assumes exactly 2*(n-1).
        raise ValueError(f"rounds must be 2*(n-1) for DRR, got rounds={rounds} n={n}")

    model = cp_model.CpModel()

    # y[(i,j,r)] == 1 iff team i hosts team j in round r (i != j).
    y: dict[tuple[int, int, int], cp_model.IntVar] = {}
    for r in range(rounds):
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                y[(i, j, r)] = model.NewBoolVar(f"y_h{i}_a{j}_r{r}")

    # Each team plays exactly once per round (either home or away).
    for r in range(rounds):
        for i in range(n):
            home_sum = sum(y[(i, j, r)] for j in range(n) if j != i)
            away_sum = sum(y[(j, i, r)] for j in range(n) if j != i)
            model.Add(home_sum + away_sum == 1)

    # Each ordered pair occurs exactly once in the season.
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            model.Add(sum(y[(i, j, r)] for r in range(rounds)) == 1)

    # No more than 2 consecutive home or away over rounds.
    # Let home[i,r] = sum_j y[i,j,r] (0/1) and away[i,r] = sum_j y[j,i,r] (0/1).
    for i in range(n):
        for r in range(rounds - 2):
            home3 = (
                sum(y[(i, j, r)] for j in range(n) if j != i)
                + sum(y[(i, j, r + 1)] for j in range(n) if j != i)
                + sum(y[(i, j, r + 2)] for j in range(n) if j != i)
            )
            away3 = (
                sum(y[(j, i, r)] for j in range(n) if j != i)
                + sum(y[(j, i, r + 1)] for j in range(n) if j != i)
                + sum(y[(j, i, r + 2)] for j in range(n) if j != i)
            )
            model.Add(home3 <= 2)
            model.Add(away3 <= 2)

    # Objective: sum of penalties.
    obj_terms: list[cp_model.LinearExpr] = []
    for r in range(rounds):
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                p = int(penalty.get((teams[i], teams[j], r), 0))
                if p:
                    obj_terms.append(p * y[(i, j, r)])
    if obj_terms:
        model.Minimize(sum(obj_terms))

    class _Collector(cp_model.CpSolverSolutionCallback):
        def __init__(self) -> None:
            super().__init__()
            self.solutions: list[FixtureRoundSolution] = []

        def on_solution_callback(self) -> None:
            fixtures: list[tuple[int, str, str]] = []
            for r in range(rounds):
                for i in range(n):
                    for j in range(n):
                        if i == j:
                            continue
                        if self.Value(y[(i, j, r)]) == 1:
                            fixtures.append((r, teams[i], teams[j]))
            sol = FixtureRoundSolution(fixtures=fixtures, objective=int(self.ObjectiveValue()) if obj_terms else None)
            self.solutions.append(sol)
            if on_solution is not None:
                try:
                    on_solution(
                        {
                            "solutions": len(self.solutions),
                            "objective": sol.objective,
                        }
                    )
                except Exception:
                    pass
            if len(self.solutions) >= max(1, int(max_solutions)):
                self.StopSearch()

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 8
    if time_limit_s is not None:
        solver.parameters.max_time_in_seconds = float(time_limit_s)

    cb = _Collector()
    # OR-Tools Python API compatibility:
    # - Newer versions: SolveWithSolutionCallback(model, cb)
    # - Older versions: Solve(model, cb)
    if hasattr(solver, "SolveWithSolutionCallback"):
        status = solver.SolveWithSolutionCallback(model, cb)  # type: ignore[attr-defined]
    else:
        status = solver.Solve(model, cb)
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) and cb.solutions:
        # Solutions are returned in the order they were found (usually improving objective).
        return cb.solutions[: max(1, int(max_solutions))]
    return []

