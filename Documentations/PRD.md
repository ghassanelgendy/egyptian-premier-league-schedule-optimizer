# Product Requirements Document (PRD)

## Egyptian Premier League Schedule Optimizer — Optimization Phase

**Version:** 2.0 (implementation-aligned)  
**Aligned with:** [presentation.pdf](presentation.pdf), committed data under `data/` and `data/Sources/`, and the code in `schedule_optimizer/` + `ui/`.  
**Solver:** Google OR-Tools **CP-SAT** (`cp_model.CpModel` + `CpSolver`): 0–1 assignment with linear objective and logical constraints.

**Audience:** Product owners, engineers, and **downstream AI implementers** (this document is intended to be sufficient to re-implement or extend the system without reading the whole repo first).

---

## 1. Purpose

Build a **single, reproducible pipeline** that:

1. **Loads every** specified spreadsheet/CSV (no synthetic teams, stadiums, fixtures, or distances).
2. Constructs a **double round-robin (DRR)** fixture list for the teams in `teams_data.xlsx`, with **fixture ordering** chosen to maximize **strict-week feasibility** before CP-SAT (see §4.7).
3. Assigns each league fixture to **exactly one** time slot from `expanded_calendar`, respecting **hard** model constraints and **data-derived** feasible domains.
4. **Optimizes** a **scalarized linear objective** (travel + TV / tier / postponement / slot-overload penalties — §5).
5. Writes **auditable phase artifacts** under `output/phases/` (§3.3) so every major step has machine-readable output.
6. Exposes a **Streamlit UI** including a **full-season calendar** that explains each day using **only** derived ledger data + the active schedule (§10).

If no assignment satisfies the model, the program **exits non-zero**, logs a concise reason, and **must not** invent calendar rows, teams, or distances.

---

## 2. Inputs (Authoritative Files)

All paths are relative to the repository root. The loader **must open each file at least once** and record row counts in `output/data_load_log.txt`.

| # | Path | Required sheets / usage |
|---|------|-------------------------|
| 1 | `data/Data_Model.xlsx` | Sheets: `team_data`, `Stadiums`, `dist_Matrix`, `Sec_Matrix` — **cross-check** against Sources; Sources win for optimization; mismatch → warning. |
| 2 | `data/expanded_calendar.xlsx` | Sheets: all (read for completeness). **Slot universe:** sheet `expanded_calendar` only. |
| 3 | `data/Sources/calendar.xlsx` | Sheet `MAINCALENDAR` — season structure cross-check. |
| 4 | `data/Sources/CAF CL.xlsx` | Sheet `CAF CL` — logged; CL teams get workbook dates in **team blackouts** (see `load_data.build_team_date_blackout`). |
| 5 | `data/Sources/CAF CC.xlsx` | Sheet `CAF CC` — same for CC. |
| 6 | `data/Sources/cont_blockers_table.xlsx` | Sheets merged with CSV. |
| 7 | `data/Sources/cont_blockers_csv.csv` | Merged blockers. |
| 8 | `data/Sources/expanded_calendar.csv` | Row-count cross-check vs xlsx. |
| 9 | `data/Sources/FIFA_Days_UPDATED.xlsx` | Union into FIFA dates. |
| 10 | `data/Sources/FIFA Days.xlsx` | Union into FIFA dates. |
| 11 | `data/Sources/security matrix.xlsx` | Sheet `Sec_Matrix` — forced venue rules. |
| 12 | `data/Sources/stadiums.xlsx` | Metadata. |
| 13 | `data/Sources/teams_data.xlsx` | Sheet `Teams` — `Team_ID`, `Home_Stadium`, `Cont_Flag`, `Tier`, etc. |
| 14 | `data/Sources/Stadium_Distance_Matrix.xlsx` | Authoritative km matrix. |
| 15 | `data/Sources/Stadium_Distances_Columns.xlsx` | Spot-check / warnings. |

---

## 3. Outputs

### 3.1 Primary schedule artifacts

| File | When | Contents |
|------|------|----------|
| `output/optimized_schedule.csv` | Successful end-to-end run | One row per match: round, week, IDs, `Date`, `Date_time`, venue, `Travel_km`, `Slot_tier`, tier columns, `Is_FIFA` / `Is_CAF` / `Is_SuperCup`, `Postponed` flag. |
| `output/optimized_schedule_phase1.csv` | After CP-SAT phase 1 | Feasible assignment (objective not minimized). |
| `output/optimized_schedule_phase2.csv` | After CP-SAT phase 2 | Optimized assignment. |
| `output/week_round_map.csv` | Success | Maps abstract `Round` 1…34 → `Calendar_Week_Num` = `W[r]`. |
| `output/postponed_or_infeasible_matches.csv` | When any fixture used postponement domain or on some failures | Diagnostic columns including strict vs postponed feasible slot counts. |
| `output/data_load_log.txt` | Always on attempted run | Human-readable log. |

### 3.2 Per-phase audit folder: `output/phases/`

Each file is written when `write_outputs=True` (Streamlit and default CLI). **Another AI** should treat this folder as the **ground truth** for what the pipeline actually did.

| File | Phase | Description |
|------|-------|-------------|
| `01_load_summary.json` | After inputs resolved | Slot row count, team count, eligible week count, loaded dict keys. |
| `02_blackout_summary.csv` | After blackouts | Per-team count of blackout calendar dates (sorted descending). |
| `03_eligible_calendar_weeks.csv` | After week filter | Ordered list of 34 `Calendar_Week_Num` values `W[0]…W[33]`. |
| `03b_season_day_ledger.csv` | After slot metadata | **One row per calendar date** in the expanded calendar season span: slot counts, `Slots_league_eligible`, FIFA union flag — used by UI calendar explanations. |
| `04_drr_selection.json` | After DRR generation | Either `{mode: fixed_seed, seed, score}` or `{mode: scored_tries, tries, best_score_min_sum}`. |
| `05_fixtures_pre_solve.csv` | After DRR | All fixtures (index, round, home, away) before CP-SAT. |
| `06_feasible_slot_counts.csv` | After feasible domains | Per fixture: strict-domain length, postponed-domain length, relaxed flag. |
| `07_phase1_feasibility.json` | After CP-SAT phase 1 | Solver status, time limit, wall time, row count. |
| `08_phase2_optimize.json` | After CP-SAT phase 2 | Solver status, optional time limit, wall time, objective. |

---

## 4. Methodology (Operations Research)

### 4.1 Problem class

- **Decision:** binary `x[m,t] = 1` iff fixture `m` is assigned to slot index `t`.
- **Feasibility:** only edges `(m,t)` with `t` in `feasible[m]` are created (sparse graph).
- **Solver:** CP-SAT supports Boolean linear constraints + linear objective + structures like `AddAutomaton`.

### 4.2 End-to-end phases (runtime order)

1. **Load & validate** (`load_everything`) → `01_load_summary.json`.
2. **Blackouts** per team (`build_team_date_blackout` + FIFA dates in season) → `02_blackout_summary.csv`.
3. **Eligible weeks** (≥9 usable slots/week after H6–H8) → need 34 weeks else **fail** → `03_eligible_calendar_weeks.csv`.
4. **Slot metadata** + **prime night** flag (Fri/Sat **and** latest `Date time` on that calendar date) + `03b_season_day_ledger.csv`.
5. **DRR fixtures** (§4.7) → `04_drr_selection.json`, `05_fixtures_pre_solve.csv`.
6. **Feasible domains** per fixture (strict week = `W[round]`; else postponed = any eligible week) → `06_feasible_slot_counts.csv`.
7. **CP-SAT phase 1:** any feasible solution, `stop_after_first_solution`, **no objective terms** (`optimize=False`), time limit `EPL_PHASE1_TIME_LIMIT_S` (default 30s) → `optimized_schedule_phase1.csv`, `07_phase1_feasibility.json`.
8. **CP-SAT phase 2:** minimize full objective (`optimize=True`), optional `time_limit_s` from caller → `optimized_schedule.csv`, `08_phase2_optimize.json`.

Inside each CP-SAT phase, **dynamic repair:** if the model is infeasible, relax one fixture at a time from **strict week** to **postponed week** domain (lowest strict-domain size first) and re-solve until feasible or exhausted.

### 4.3 Hard constraints (CP-SAT, given domains)

| ID | Rule |
|----|------|
| H4 | Exactly **one** chosen slot per fixture (from its current `feasible[m]`). |
| H13 | At most **one** match per **venue** per slot index `t` among matches that could share `t`. |
| H14 | At most **one** match per **team** per slot index `t`. |
| — | At most **`max_matches_per_slot`** (default **2**) matches per slot index **global** capacity. |
| H-rest | **Two calendar days rest:** if a team plays on date ordinal `d`, it cannot play on `d+1` or `d+2` (e.g. Sunday → next match Wednesday). |
| H-HA | **Home/away streak:** in **played-match order** by date, **no more than 2** consecutive HOME and **no more than 2** consecutive AWAY (hard automaton; gaps do not reset streak). |

All **FIFA / SuperCup / team blackout / CAF-slot** rules are enforced by **excluding** bad slots from `feasible[m]` (pre-solve), not as separate CP-SAT linear rows.

### 4.4 Hard vs relaxed (business rules)

| Rule | Strict mode | Relaxed mode |
|------|-------------|--------------|
| **H5 — Round ↔ calendar week** | Fixture `m` in round `r` may use only slots with `Week_Num == W[r]`. | **Postponement:** if strict domain empty (or dynamic repair), `m` may use any slot whose `Week_Num` is in the **34 eligible weeks** set. |
| **Double slot usage** | Prefer **one** match per slot index. | Model allows **up to 2**; **soft** penalty `w_slot_overlap` discourages the second. |

### 4.5 Soft objectives (Phase 2 only, `optimize=True`)

All are linear penalties summed into one `Minimize`:

| Term | Meaning |
|------|---------|
| Travel | `round(Travel_km × 10)` per assignment (fixture cost independent of slot today). |
| Tier mismatch | If `Slot_tier` > `Match_Tier`, add `w_tier_mismatch × (Slot_tier − Match_Tier)`. |
| Top-tier weekend | If `Match_Tier == 1` and day not Fri/Sat, add `w_top_tier_non_prime_day`. |
| **T1 vs T1 prime night** | If both tiers are 1 and slot is not **prime night** (Fri/Sat + latest kickoff that date), add `w_t1vst1_not_prime_night`. **Soft only** — not a hard ban. |
| Postponement distance | If assigned `Week_order` ≠ nominal `orig_week_order`, add `w_postpone_week_distance × abs(diff) × postpone_weight_mult`. |
| Slot overload | If 2 matches share a slot index, add `w_slot_overlap`. |

**Continental-aware weighting:** `postpone_weight_mult = EPL_CONT_POSTPONE_MULT` (default **4.0**) when **either** team has `Cont_Flag ∈ {CL, CC}`; else `1.0`. This **prioritizes** keeping continental teams on their nominal league week when possible (higher cost to slide them to other weeks).

Default weights are defined in `schedule_optimizer/cp_sat_model.py:solve_assignment` and passed from `pipeline.py`.

### 4.6 Calendar week selection (unchanged logic)

- **usable(w)** = slots in week `w` not blocked by FIFA flag, SuperCup flag, or FIFA union calendar date.
- Eligible weeks: `usable(w) ≥ 9`; sort by min date in week; take first **34**.
- If `< 34` eligible weeks → **fail before CP-SAT**.

### 4.7 DRR fixture ordering (implementation requirement)

**Pairing structure** remains a **double round-robin** (each pair twice, reversed half).

**Team order for the circle method:** sort `Team_ID` by **descending** `|blackout_dates|` so **more constrained** teams anchor the generator order.

**Seed selection:** unless `EPL_DRR_SEED` is set (fixed reproducibility), evaluate up to `EPL_DRR_TRIES` (default **12**) random seeds with `shuffle_teams=False` on that ordered list. Score each candidate by **lexicographic** `(min_strict_feasible_slots, sum_strict_feasible_slots)` where strict means slots obeying H5 + all blackout rules. **Pick the best** tuple. Persist in `04_drr_selection.json`.

This satisfies the product intent: **who plays whom in which abstract round** is not sacred — it should adapt to **future / season-long unavailability** density.

---

## 5. Slot_tier (reporting + objective)

Same hour/day rules as v1 PRD §5.2 for `Slot_tier` **computation**. The solver also uses tier mismatch and top-tier weekend terms (§4.5).

---

## 6. UI Requirements (Streamlit)

### 6.1 Existing surfaces

- Sidebar: **CAF buffer** slider, **Run optimization** with live solver progress JSON.
- Tabs: Dashboard (club grid, club season, H2H, metrics), Data library, Schedule table + download, embedded Markdown docs.

### 6.2 Full calendar tab (mandatory behavior)

- **Month selector** over all `(year, month)` present in `03b_season_day_ledger.csv`.
- **Month grid** of days; clicking a **day** shows a **detail panel**:
  - If **`optimized_schedule.csv`** (or in-memory result) has rows for that `Date`: show those rows (Round, Date_time, teams, venue, travel, flags).
  - Else: show **bullet reasons** derived **only** from the ledger row: e.g. FIFA union date, no league-eligible slots, or eligible slots exist but solver placed no match that day.

No fabricated reasons — if ledger is missing, UI must say the user must run the pipeline once.

---

## 7. Environment Variables

| Variable | Default | Meaning |
|----------|---------|---------|
| `EPL_CAF_BUFFER_DAYS` | `1` | ±days around continental anchors (CLI default if UI not used). |
| `EPL_DRR_SEED` | unset | If set, skip multi-try scoring and use this seed only. |
| `EPL_DRR_TRIES` | `12` | Number of DRR seeds to score when `EPL_DRR_SEED` unset. |
| `EPL_PHASE2_TIME_LIMIT_S` | unset | If set, CP-SAT phase 2 `max_time_in_seconds` (else unlimited). |
| `EPL_CONT_POSTPONE_MULT` | `4.0` | Multiplier on postponement penalty for CL/CC matches. |
| `EPL_PHASE1_TIME_LIMIT_S` | `30` | CP-SAT phase 1 time limit (seconds). |

---

## 8. ID Normalization

Same as v1 PRD (strip, uppercase, known stadium aliases). Fail fast if matrix missing required IDs.

---

## 9. Non-Goals

- Broadcaster pairwise requests not in security matrix.
- Dynamic weather rescheduling.
- Egypt Cup / Super Cup **fixture generation** (only `Is_SuperCup` pause).
- Player-level call-ups beyond FIFA union + `Is_FIFA`.

---

## 10. Acceptance Criteria

1. `pip install -r requirements.txt` + `python -m schedule_optimizer` produces `output/optimized_schedule.csv` on a clean clone with bundled data (or exits with a logged **infeasible** reason).
2. Load log proves every input in §2 was opened.
3. Successful run writes **all** §3.2 phase files (when `write_outputs=True`).
4. `python -m streamlit run ui/app.py` → **Full calendar** tab reads `03b_season_day_ledger.csv` and explains days without matches using ledger columns only.
5. CP-SAT failure exits non-zero and preserves partial logs / diagnostics where implemented.

---

## 11. References

- `schedule_optimizer/pipeline.py` — orchestration and phase writers.  
- `schedule_optimizer/cp_sat_model.py` — CP-SAT model.  
- `schedule_optimizer/day_ledger.py` — `03b` builder.  
- `ui/app.py`, `ui/calendar_board.py` — UI.  
- OR-Tools CP-SAT: https://developers.google.com/optimization/cp/cp_solver  
