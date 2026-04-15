# Model explanation — Egyptian Premier League schedule optimizer

This document explains **what kind of optimization model** this project uses, **what it optimizes**, **which rules are hard vs soft**, and **how the pipeline phases relate to outputs**. It aligns with [PRD.md](PRD.md) v2.0 and the code in `schedule_optimizer/`.

---

## 1. What type of model is it?

**Binary assignment** on a bipartite-like structure (fixtures → slots), solved with **Google OR-Tools CP-SAT**:

- Variables `x[m,t] ∈ {0,1}`: fixture `m` uses slot row `t`.
- **Sparse:** only feasible `(m,t)` pairs are created.
- **Constraints:** mostly linear inequalities on sums of Booleans; **home/away streak** uses an `AddAutomaton` over discretized per-day symbols.
- **Objective (phase 2):** single linear minimize = travel + several penalty terms (see §3).

Fixtures come from a **double round-robin** pattern. The pipeline mostly **assigns times** to a pre-built fixture list, where the DRR fixture list is chosen either by a **fixture-round CP-SAT** model (when enabled) or by a **scored-seed fallback** that maximizes strict-week feasible slot counts (PRD §4.7).

### 1.1 Upgraded methodology (recommended)

To reliably obtain at least one optimized schedule, the methodology should be decomposed into **two CP-SAT models** with different responsibilities:

1. **Fixture-round CP-SAT (pairings by round):** decide which opponent each team plays in each round (and home/away), subject to DRR and fairness constraints.
2. **Slot assignment CP-SAT (dates/times):** assign each decided fixture to an exact calendar slot, using explicit postponement decisions and soft objectives.

This prevents the slot assignment model from being forced to “repair” a structurally bad fixture-round ordering only via postponements.

---

## 2. Decision variables and domains

- **`x[m,t]`** — slot assignment, see above.
- **Venue** is **not** a decision variable: fixed from `sec_matrix` (forced venue when present) or the home team’s stadium ID from `team_data` before solve.
- **`feasible[m]`** — list of slot indices allowed for `m`. Built from:
  - FIFA / SuperCup flags and FIFA union dates,
  - per-team blackout dates derived from the detailed blocker/FIFA expansion tables inside `data/expanded_calendar.xlsx` (joined by `Day_ID` and expanded by a configurable buffer),
  - CAF/FIFA/Ramadan/SuperCup slot flags from `expanded_calendar_table`,
  - **either** same calendar week as round `r` (**strict**), **or** any of the 34 eligible weeks (**postponed** / relaxed H5).

In the upgraded methodology, Phase 1 introduces an additional binary structure:

- **`y[i,j,r]`** — fixture-round decision: team `i` hosts team `j` in round `r`.

Phase 1 produces the fixture list, then Phase 2 consumes that list as its `matches[]` input.

**Important implementation note (how DRR reaches CP-SAT):** the slot-assignment solver does **not** read DRR back from `output/phases/04_drr_selection.json`. That file is an **audit artifact** describing how the DRR was chosen. The solver consumes DRR via the pipeline’s in-memory objects:

- `frs`: list of DRR fixtures (round, home, away)
- `matches`: list of `Match` derived from `frs`
- `feasible`: per-match list of allowed slot indices

CP-SAT then creates Boolean variables only for feasible edges \((m,t)\) where \(t \in feasible[m]\).

---

## 3. Objectives (phase 2 only)

Phase 1 (`optimize=False`) finds **any** feasible timetable **without** minimizing the weighted sum.

Phase 2 minimizes:

1. **Travel proxy** — `10 × Travel_km` (integer-rounded) per fixture (independent of which acceptable slot in domain).
2. **Slot overload** — penalize second match on same slot index (`w_slot_overlap`).
3. **Tier mismatch** — slot worse than match minimum tier.
4. **Top-tier weekend** — tier-1 matches prefer Fri/Sat (`w_top_tier_non_prime_day`).
5. **Tier1 vs Tier1 prime night** — prefer Fri/Sat **and** latest kickoff that calendar date (`w_t1vst1_not_prime_night`). **Soft** — feasibility wins if calendar forces it.
6. **Postponement** — penalize assignment away from nominal `Week_order`, scaled by `postpone_weight_mult` (**higher** for matches involving `Cont_Flag ∈ {CL,CC}`) so continental teams are **less** likely to be pushed off-week.

### 3.2 Match_Tier (derived from team tiers)

Each fixture has a **Match_Tier** derived from the two teams’ `Tier` values in `team_data` (PRD §5.1). Interpretation: **1 is the best/premium** and **3 is the lowest priority**; the optimizer should assign **better slots** (lower `Slot_tier`) to lower Match_Tier.

Required derivation table:

| Teams | Match_Tier |
|------|------------|
| 1 vs 1 | 1 |
| 1 vs 2 | 1 |
| 1 vs 3 | 2 |
| 2 vs 2 | 2 |
| 2 vs 3 | 3 |
| 3 vs 3 | 3 |

### 3.1 Explicit postponement decision (recommended)

Instead of repeated “relax one match and retry” loops, represent postponement directly:

- Define `is_postponed[m] = 1` if the chosen slot’s `Week_order` differs from `orig_week_order` for match `m`.
- Add a large penalty `big_weight * is_postponed[m]` (in addition to the existing week-distance penalty).

This gives CP-SAT the power to choose *which* matches to postpone with full global context.

---

## 4. Hard constraints (inside CP-SAT)

| Theme | Rule |
|-------|------|
| Assignment | Exactly one `t` per `m` from `feasible[m]`. |
| Teams | ≤1 match per team per slot index. |
| Venues | ≤1 match per venue per slot index. |
| Capacity | ≤2 matches per slot index globally (soft overload discourages 2). |
| Rest | No team plays on three consecutive calendar ordinals if any of those days could host them (2-day rest rule). |
| H/A streak | Automaton: max **2** consecutive home or away in **played** order by date (gaps do not reset). |

Blackouts and week filters are enforced by **shrinking `feasible[m]`**, not duplicated as redundant linear rows.

### 4.1 Fixture-round hard constraints (Phase 1, recommended)

For the fixture-round model:

- Each team plays exactly once per round.
- Each ordered pair (i hosts j) occurs exactly once across the season.
- Home/away streak cap: at most 2 consecutive home or away matches (over rounds).

---

## 5. Pipeline outputs (for debugging / UI)

See PRD §3.2. Notably **`03b_season_day_ledger.csv`** powers the Streamlit **Full calendar** explanations without guessing.

---

## 6. Relation to “ILP” narrative

Same mathematical family as integer linear programming (Boolean + linear constraints + linear objective). CP-SAT is used for maintainability and strong performance on this structure.

---

## 7. References

- [PRD.md](PRD.md)  
- [CODE_DOCUMENTATION.md](CODE_DOCUMENTATION.md)  
- `schedule_optimizer/cp_sat_model.py`, `schedule_optimizer/pipeline.py`, `schedule_optimizer/day_ledger.py`  
