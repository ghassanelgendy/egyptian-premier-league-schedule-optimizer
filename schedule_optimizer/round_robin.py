"""Double round-robin construction (circle method)."""
from __future__ import annotations
from dataclasses import dataclass
import random


@dataclass(frozen=True)
class Fixture:
    round_idx: int  # 0 .. 2*(n-1)-1
    home: str
    away: str


def double_round_robin(team_ids: list[str], *, round_flips: list[bool] | None = None) -> list[Fixture]:
    """
    First (n-1) rounds: circle method; second (n-1) rounds: swap home/away.

    If ``round_flips`` is provided (length n-1), round r in the first half will
    have all pairings swapped (home<->away) when round_flips[r] is True.
    """
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
        flip = bool(round_flips[r]) if round_flips is not None else False
        for a, b in rnd:
            fixtures.append(Fixture(r, b, a) if flip else Fixture(r, a, b))
    offset = n - 1
    for r, rnd in enumerate(rounds):
        flip = bool(round_flips[r]) if round_flips is not None else False
        for a, b in rnd:
            # Second half is always the opposite of the first half.
            fixtures.append(Fixture(offset + r, a, b) if flip else Fixture(offset + r, b, a))
    return fixtures


def _max_home_away_streak_ok(
    fixtures: list[Fixture],
    team_ids: list[str],
    *,
    max_streak: int = 2,
    scope: str = "half",
) -> bool:
    """
    True if no team has >max_streak consecutive HOME or AWAY.

    scope:
    - "season": enforce across all rounds 0..2*(n-1)-1
    - "half": enforce separately within rounds [0..n-2] and [n-1..2*(n-1)-1]
    """
    n_rounds = max((f.round_idx for f in fixtures), default=-1) + 1
    # team -> list[bool] where True=home, False=away
    ha: dict[str, list[bool]] = {t: [False] * n_rounds for t in team_ids}
    for f in fixtures:
        if f.home in ha:
            ha[f.home][f.round_idx] = True
        if f.away in ha:
            ha[f.away][f.round_idx] = False
    def _ok(seq: list[bool]) -> bool:
        streak = 1
        for i in range(1, len(seq)):
            if seq[i] == seq[i - 1]:
                streak += 1
                if streak > max_streak:
                    return False
            else:
                streak = 1
        return True

    if scope not in ("season", "half"):
        scope = "half"

    half = n_rounds // 2
    for _t, seq in ha.items():
        if scope == "season":
            if not _ok(seq):
                return False
        else:
            if not (_ok(seq[:half]) and _ok(seq[half:])):
                return False
    return True


def double_round_robin_randomized(
    team_ids: list[str],
    *,
    seed: int | None = None,
    max_tries: int = 2000,
    max_streak: int = 2,
    streak_scope: str = "half",
    shuffle_teams: bool = True,
) -> list[Fixture]:
    """
    Randomize the DRR by shuffling the initial circle-method rotation (unless ``shuffle_teams`` is False).

    Note: home/away streak constraints are enforced in the CP-SAT assignment
    over the *scheduled* sequence (by Date_ord). This generator only randomizes
    pairings order/orientation.
    """
    rng = random.Random(seed)
    n = len(team_ids)
    if n % 2 != 0:
        raise ValueError("n must be even for this scheduler")

    def _pairings_circle(order: list[str]) -> list[list[tuple[str, str]]]:
        rota = order[:]
        rounds: list[list[tuple[str, str]]] = []
        for _ in range(n - 1):
            rnd = []
            for i in range(n // 2):
                a, b = rota[i], rota[n - 1 - i]
                rnd.append((a, b))
            rounds.append(rnd)
            rota = [rota[0]] + [rota[-1]] + rota[1 : n - 1]
        return rounds

    for _ in range(max_tries):
        base = team_ids[:]
        if shuffle_teams:
            rng.shuffle(base)
        rounds = _pairings_circle(base)

        # First half: randomize orientation per fixture.
        first_half: list[list[tuple[str, str]]] = []
        for rnd in rounds:
            oriented = []
            for a, b in rnd:
                oriented.append((a, b) if rng.getrandbits(1) else (b, a))
            first_half.append(oriented)

        # Second half: same pairings with swapped home/away, but *round order is randomized*.
        offset = n - 1
        perm = list(range(offset))
        rng.shuffle(perm)
        second_half = [[(away, home) for (home, away) in first_half[r]] for r in perm]

        fixtures: list[Fixture] = []
        for r, rnd in enumerate(first_half):
            for home, away in rnd:
                fixtures.append(Fixture(r, home, away))
        for r2, rnd in enumerate(second_half):
            for home, away in rnd:
                fixtures.append(Fixture(offset + r2, home, away))

        return fixtures

    # Should never reach here.
    return double_round_robin(team_ids)
