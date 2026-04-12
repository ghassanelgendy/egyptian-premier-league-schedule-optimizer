"""Double round-robin construction (circle method)."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class Fixture:
    round_idx: int  # 0 .. 2*(n-1)-1
    home: str
    away: str


def double_round_robin(team_ids: list[str]) -> list[Fixture]:
    """First (n-1) rounds: circle method; second (n-1) rounds: swap home/away."""
    n = len(team_ids)
    if n % 2 != 0:
        raise ValueError("n must be even for this scheduler")
    rota = team_ids[:]
    rounds: list[list[tuple[str, str]]] = []
    for _ in range(n - 1):
        rnd = []
        for i in range(n // 2):
            a, b = rota[i], rota[n - 1 - i]
            rnd.append((a, b))
        rounds.append(rnd)
        rota = [rota[0]] + [rota[-1]] + rota[1 : n - 1]

    fixtures: list[Fixture] = []
    for r, rnd in enumerate(rounds):
        for a, b in rnd:
            fixtures.append(Fixture(r, a, b))
    offset = n - 1
    for r, rnd in enumerate(rounds):
        for a, b in rnd:
            fixtures.append(Fixture(offset + r, b, a))
    return fixtures
