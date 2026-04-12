# Model explanation — Egyptian Premier League schedule optimizer

This document explains **what kind of optimization model** this project uses, **what it optimizes**, **which rules it enforces**, and **how the pieces fit together**. It aligns with the product requirements in [PRD.md](PRD.md) and the implementation in `schedule_optimizer/`.

---

## 1. What type of model is it?

The implementation is a **binary-constrained discrete optimization model** solved with **Google OR-Tools CP-SAT** (constraint programming / SAT-based solver with linear objective over Booleans).

In academic terms it sits next to **integer linear programming (ILP)** and **mixed-integer programming (MIP)**:

- **Decision variables** are **0/1** (each match either is or is not assigned to a particular calendar slot).
- **Constraints** are linear (sums of Booleans with bounds: equalities and inequalities).
- **Objective** is a **linear** function of those variables (here, effectively **minimize total travel proxy** in kilometers).

So you can describe it as: **a 0–1 assignment model with a linear objective**, commonly called a **multi-dimensional assignment** or **scheduling assignment** structure. CP-SAT is used instead of a generic MILP branch-and-cut solver because it is strong at **logical feasibility** and **large sparse** Boolean models.

The **fixtures** (who plays whom and who is home in each round) are **fixed in advance** by a **double round-robin (DRR)** pattern; the optimizer **does not** choose the pairing matrix. It only **assigns each known fixture to a time slot** that respects calendar and operational rules.

---

## 2. What are the decision variables?

For each league fixture `m` and each feasible calendar slot `t` (a row of the expanded calendar: date, time, flags, week number), the model defines a binary:

- **`x[m,t] = 1`** if fixture `m` is played in slot `t`, else **0**.

Only **feasible** `(m,t)` pairs are created (sparse model): e.g. slot must belong to the correct **calendar week** mapped to that round, must not be on FIFA / Super Cup / blocked continental dates for the teams involved, etc.

The **venue** for fixture `m` is **not** a separate variable: it is **derived from data** (home stadium, or a **forced neutral** stadium from the security matrix when that row applies).

---

## 3. Objectives (what we optimize)

### 3.1 Primary objective (implemented)

**Minimize total travel proxy (kilometers)** in the league schedule.

For each fixture, a **cost** is computed **before** optimization from the distance matrix:

- For home team `h`, away team `a`, and venue stadium `V` (from teams + security rules):

`c_m = d(HomeStadium(h), V) + d(HomeStadium(a), V)`

where `d(·,·)` is driving distance (km) from `Stadium_Distance_Matrix.xlsx`.

In the **current** build, `c_m` depends only on the **fixture** (home, away, derived venue), **not** on which acceptable slot `t` within the allowed week is chosen. So the total sum of all `c_m` over matches is **the same for every complete feasible assignment** of matches to slots. The CP-SAT model still **minimizes** that sum; in practice the engine is finding a **feasible** timetable under stadium and blackout rules, while the travel terms remain a **linear objective in the ILP sense** and can later be extended with **slot-dependent** costs (for example TV tier weights per kickoff time).

*Note:* richer goals (rest balance, away-break patterns, weighted TV tiers) are described in the PRD as **future** extensions.

### 3.2 Reporting only (not in the solver objective)

**`Slot_tier`** (1 = best weekend prime window, 3 = other) is computed **after** the solve from `Day_name` and clock time of the assigned slot — used for analysis and UI, not as a weighted term in the current objective.

---

## 4. Constraints (hard rules)

All of the following are **hard** in the shipped model (no slack variables):

| # | Rule | Meaning |
|---|------|--------|
| 1 | **Double round-robin structure** | Every team plays every other team **twice** per season with **home/away** reversed between halves; **34** rounds for 18 teams. Pairings per round come from a **circle / Berger** schedule, not from the solver. |
| 2 | **One slot per fixture** | Each of the 306 fixtures is assigned **exactly one** slot from the expanded calendar. |
| 3 | **Round ↔ calendar week** | Abstract round `r` is mapped to a **specific** `Week_Num` from your calendar data: the first **34** calendar weeks (chronologically) that have **at least nine** usable slots after FIFA/SuperCup exclusions. Every match in round `r` must use a slot with that `Week_Num`. |
| 4 | **FIFA / international dates** | No match in slots flagged **`Is_FIFA`**, nor on dates listed in the FIFA spreadsheets (union of dates). |
| 5 | **Super Cup pause** | No match in slots with **`Is_SuperCup == 1`**. |
| 6 | **Continental slot flag** | Teams with **`Cont_Flag`** in {CL, CC} cannot play league matches in slots with **`Is_CAF == 1`**. |
| 7 | **Continental blockers + buffer** | From merged `cont_blockers` tables: for each row, anchor date from `Day_ID` on the calendar; that `team_id` cannot play on anchor ± **B** days (`B` default **1**, configurable; `EPL_CAF_BUFFER_DAYS` / UI slider). |
| 8 | **Security / venue** | If a pairing appears in the security sheet with a **forced** stadium, that fixture must use that venue; otherwise the venue is the home club’s **home stadium** from `teams_data`. |
| 9 | **No stadium double-booking** | At the **same** kickoff slot (`Date_time`), **at most one** match may use a given **venue** stadium ID (covers shared home grounds). |
| 10 | **No player/team double-booking** | At the same kickoff slot, a team can appear in **at most one** match. |
| 11 | **Data-only inputs** | Teams, stadiums, distances, calendars, blockers, and security rules all come from your **Excel/CSV** under `data/` — the solver does not invent clubs or venues. |

---

## 5. How the pipeline works (step by step)

1. **Load** all configured spreadsheets and CSVs (`load_everything`).
2. **Build** per-team **date blackouts** (FIFA union, continental buffers, etc.).
3. **Select** the **34 calendar weeks** that have enough non-blocked slots for nine simultaneous kickoffs.
4. **Generate** the **306 fixtures** with home/away and round index (`double_round_robin`).
5. For each fixture, compute **venue** and **travel cost** from the distance matrix and security rules.
6. For each fixture, list **feasible slots** (same calendar week as its round, and not blocked for either club).
7. **Build CP-SAT**: variables `x[m,t]` only for feasible pairs; add constraints (sections 4.9–4.10 and uniqueness per match).
8. **Solve** with a time limit; if **OPTIMAL** or **FEASIBLE**, export `optimized_schedule.csv` with **`Travel_km`** and **`Slot_tier`**.

---

## 6. How this relates to the graduation / PRD narrative

The project report and presentation describe **integer linear programming (ILP)** as the framing discipline. The implemented engine is **the same mathematical family** (Boolean linear constraints + linear objective), instantiated in **CP-SAT** for robustness and maintainability. The **business rules** (FIFA, CAF, security, stadium sharing, DRR) are exactly the **constraints**; **travel** is the main **objective** encoded today.

---

## 7. References (internal)

- [PRD.md](PRD.md) — formal inputs, outputs, and constraint IDs.
- [CODE_DOCUMENTATION.md](CODE_DOCUMENTATION.md) — module-level implementation map.
- `schedule_optimizer/pipeline.py` — end-to-end orchestration.
- `schedule_optimizer/cp_sat_model.py` — CP-SAT model definition.
