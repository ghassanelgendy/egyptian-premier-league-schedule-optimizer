# Model explanation — Egyptian Premier League schedule optimizer

This document explains **what kind of optimization model** this project uses, **what it optimizes**, **which rules are hard vs soft**, and **how the pipeline phases relate to outputs**. It aligns with [PRD.md](PRD.md) v2.0 and the code in `schedule_optimizer/`.

---

## 1. What type of model is it?

**Binary assignment** on a bipartite-like structure (fixtures → slots), solved with **Google OR-Tools CP-SAT**:

- Variables `x[m,t] ∈ {0,1}`: fixture `m` uses slot row `t`.
- **Sparse:** only feasible `(m,t)` pairs are created.
- **Constraints:** mostly linear inequalities on sums of Booleans; **home/away streak** uses an `AddAutomaton` over discretized per-day symbols.
- **Objective (phase 2):** single linear minimize = travel + several penalty terms (see §3).

Fixtures come from a **double round-robin** pattern; the optimizer **assigns times**, not the pairing graph. DRR **order / seed** is chosen to maximize **strict-week feasible slot counts** before solving (see PRD §4.7).

---

## 2. Decision variables and domains

- **`x[m,t]`** — see above.
- **Venue** is **not** a decision variable: fixed from security matrix or home stadium before solve.
- **`feasible[m]`** — list of slot indices allowed for `m`. Built from:
  - FIFA / SuperCup flags and FIFA union dates,
  - per-team blackout dates (continental blockers ± buffer, CAF workbook dates for CL/CC, FIFA in season),
  - CAF slot flag vs `Cont_Flag`,
  - **either** same calendar week as round `r` (**strict**), **or** any of the 34 eligible weeks (**postponed** / relaxed H5).

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
