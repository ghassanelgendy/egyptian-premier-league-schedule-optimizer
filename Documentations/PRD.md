# Product Requirements Document (PRD)

## Egyptian Premier League Schedule Optimizer — Optimization Phase

**Version:** 2.0 (implementation-aligned)  
**Aligned with:** [presentation.pdf](presentation.pdf), committed data under `data/`, and the code in `schedule_optimizer/` + `ui/`.  
**Solver:** Google OR-Tools **CP-SAT** (`cp_model.CpModel` + `CpSolver`): 0–1 assignment with linear objective and logical constraints.

**Audience:** Product owners, engineers, and **downstream AI implementers** (this document is intended to be sufficient to re-implement or extend the system without reading the whole repo first).

---

## 1. Purpose

Build a **single, reproducible pipeline** that:

1. **Loads every** specified spreadsheet (no synthetic teams, stadiums, fixtures, or distances).
2. Constructs a **double round-robin (DRR)** fixture list for the teams in `data/Data_Model.xlsx` → `team_data`, with **fixture ordering** chosen to maximize **strict-week feasibility** before CP-SAT (see §4.7).
3. Assigns each league fixture to **exactly one** time slot from `expanded_calendar`, respecting **hard** model constraints and **data-derived** feasible domains.
4. **Optimizes** a **scalarized linear objective** (travel + TV / tier / postponement / slot-overload penalties — §5).
5. Writes **auditable phase artifacts** under `output/phases/` (§3.3) so every major step has machine-readable output.
6. Exposes a **Streamlit UI** including a **full-season calendar** that explains each day using **only** derived ledger data + the active schedule (§10).

If no assignment satisfies the model, the program **exits non-zero**, logs a concise reason, and **must not** invent calendar rows, teams, or distances.

---

## 2. Inputs (Authoritative Files)

All paths are relative to the repository root. The system is **required** to take its inputs **only** from the two Excel files below (no `data/Sources/*`, no CSV mirrors). The loader **must open both files** and record row counts in `output/data_load_log.txt`.

| # | Path | Required tables / sheets (must be used as-is) |
|---|------|----------------------------------------------|
| 1 | `data/Data_Model.xlsx` | **Tables/sheets:** `team_data`, `Stadiums`, `dist_Matrix`, `sec_matrix`. These contain the authoritative team, stadium, travel distance, and security/forced-venue rules and must be used **as-is** (no cross-checking against any other files). |
| 2 | `data/expanded_calendar.xlsx` | **Tables/sheets:** `expanded_calendar_table` (slot universe), plus the two additional tables that provide the detailed blockers/FIFA-day expansions (currently labeled in the workbook as `cont_blockers_updated1` and `FIFA_DAYS1`). All blackout/FIFA/CAF flags used by the model must be derived from this workbook. |

### 2.1 `data/Data_Model.xlsx` — required tables and columns

#### 2.1.1 `team_data`

Use the data as-is.

Required columns:

- `Team_ID`
- `Team_Name`
- `Gov_ID`
- `Gov_Name`
- `Home_Stadium_ID`
- `Alt_Stadium_ID`
- `Tier`
- `Cont_Flag`

#### 2.1.2 `Stadiums`

Use the data as-is.

Required columns:

- `Stadium_ID`
- `Stadium_Name`
- `Gov_ID`
- `City`
- `Is_Floodlit`

#### 2.1.3 `dist_Matrix`

Distance matrix from each stadium to every other stadium. Use as-is.

Required columns (header row must include these stadium IDs exactly):

- `Origin`
- `30_JUNE`
- `ALEX_STADIUM`
- `AL_SALAM`
- `ARAB_CONT`
- `ARMY_SUEZ_ST`
- `ASWAN`
- `BANI_SWEIF`
- `BORG_ARAB`
- `CAIRO_INTL`
- `EL_GOUNA`
- `FAYOUM`
- `GEHAZ_REYADA`
- `HARAS`
- `ISMAILIA_ST`
- `MAHALLA`
- `MANSOURA`
- `MASRY`
- `MIL_ACAD`
- `MISR`
- `PETRO_SPORT`
- `SUEZ_CANAL`
- `SUEZ_ST`

#### 2.1.4 `sec_matrix`

Rules that ban certain fixtures in certain venues and force an alternative venue. Use as-is.

Required columns:

- `home_team_ID`
- `away_team_ID`
- `banned_venue1_ID`
- `banned_venue2_ID`
- `forced_venue_ID`

### 2.2 `data/expanded_calendar.xlsx` — required tables and columns

#### 2.2.1 `expanded_calendar_table` (slot universe)

This table defines the full season calendar and is the **only** source of scheduling slots.

Required columns (at minimum):

- `Day_ID`
- `Date`
- `Date time`
- `Week_Num`
- `day`
- `month`
- `year`
- `Day_name`
- `Is_FIFA`
- `Is_CAF`
- `Is_Ramadan`
- `Is_SuperCup`
- `FIFA_DAYS`

#### 2.2.2 Additional blocker/FIFA expansion tables

The workbook includes additional tables (currently labeled `cont_blockers_updated1` and `FIFA_DAYS1`) providing expanded details used to derive team/date blackout sets and FIFA-day unions. These must be used from this workbook (no external merges).

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
| `04_drr_selection.json` | After DRR generation | **Audit/debug metadata only** about *how* the DRR fixture list was chosen (e.g. CP-SAT fixture-round vs fallback seed). It is **not** read back as an input by the solver; the DRR fixtures are generated in-memory and passed forward through the pipeline. |
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
5. **Fixture framework (Phase 1-A):** generate a **double round-robin** structure (pairings + home/away) by abstract **round**. In the current implementation this may be chosen by a **fixture-round CP-SAT** model (see §4.2.1) and otherwise falls back to the scored-seed heuristic (§4.7). The resulting DRR fixture list is held **in-memory** as `fixtures` and is also written to `05_fixtures_pre_solve.csv` for audit.
6. **Build CP-SAT inputs:** convert DRR fixtures into `Match` objects and build the sparse feasibility graph `feasible[m]` (strict week = `W[round]`; postponed = any eligible week) → `06_feasible_slot_counts.csv`.
7. **Slot assignment (Phase 1-B / Phase 2):** CP-SAT assigns each match to one slot from its domain by solving over Boolean edges `x[m,t]` **constructed from** the in-memory `matches` + `feasible` lists (see `schedule_optimizer/cp_sat_model.py:solve_assignment`).
   - **Phase 1-B:** feasibility only, `stop_after_first_solution`, **no objective terms** (`optimize=False`), time limit `EPL_PHASE1_TIME_LIMIT_S` (default 30s) → `optimized_schedule_phase1.csv`, `07_phase1_feasibility.json`.
   - **Phase 2:** minimize full objective (`optimize=True`), optional `time_limit_s` from caller → `optimized_schedule.csv`, `08_phase2_optimize.json`.

Inside the current slot assignment flow there is **dynamic repair**: if infeasible, relax one fixture at a time from **strict week** to **postponed week** domain (lowest strict-domain size first) and re-solve until feasible or exhausted. The upgraded methodology replaces this with explicit postponement decision variables (§4.2.2), so CP-SAT chooses what to postpone in one model.

#### 4.2.1 Upgraded methodology: fixture-round CP-SAT (pairings by round)

**Problem:** the slot assignment CP-SAT can only choose *dates* for a given fixture list; if the fixture list is structurally bad (wrong opponents in conflict-heavy weeks), the solver is forced into postponement-heavy search and may never reach an optimized schedule.

**Upgrade:** add a first CP-SAT model that decides the season’s DRR fixture list *by round* using:

- Decision \(y[i,j,r] = 1\) iff team `i` hosts `j` in round `r`.
- Hard constraints:
  - Each team plays exactly once per round.
  - Each ordered pair (i hosts j) occurs exactly once across the season.
  - Each team has at most 2 consecutive home and at most 2 consecutive away matches (over rounds).
- Objective (v1): minimize “expected strict infeasibility” and blackout pressure by penalizing choices that would have few or zero strict-week feasible slots when mapped to `W[r]`.

This model produces a fixture list compatible with `schedule_optimizer.round_robin.Fixture` but is solver-chosen, not sampled by random seeds.

#### 4.2.2 Upgraded methodology: explicit postponement variables (no relax/retry loop)

**Problem:** the current relax/retry loop rebuilds/solves multiple times, expanding domains one match at a time.

**Upgrade:** keep a single slot-assignment CP-SAT model with postponed choices expressed directly:

- Let `x[m,t]` remain the slot assignment variable.
- Define `is_postponed[m] = 1` if the chosen slot week is not the nominal week for match `m`.
- Penalize postponements strongly: `big_weight * is_postponed[m]` plus the existing week-distance penalty.

This allows CP-SAT to decide which fixtures to postpone while globally trading off constraints and objectives.

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

**Important implementation note (how DRR reaches CP-SAT):** the DRR fixtures are **not loaded from** `output/phases/04_drr_selection.json`. That JSON is an **audit artifact**. The solver receives DRR via the pipeline’s in-memory objects:

- `frs`: list of DRR fixtures (round, home, away)
- `matches`: list of `Match` built from `frs`
- `feasible`: per-match list of allowed slot indices

CP-SAT then creates variables only for edges \((m,t)\) where \(t \in feasible[m]\), and enforces “exactly one slot per match” and all other constraints on those variables.

This satisfies the product intent: **who plays whom in which abstract round** is not sacred — it should adapt to **future / season-long unavailability** density.

---

## 4.8 “No optimized schedule yet” — primary known causes and fixes

If you “cannot get even 1 optimized schedule”, the typical root causes are:

1. **Input mismatch causing early failure** (before the solver):
   - The run is using any input files other than the two authoritative Excel workbooks in §2. This project is required to load all teams/stadiums/distances/security rules from `data/Data_Model.xlsx` and all calendar + blocker/FIFA expansions from `data/expanded_calendar.xlsx`.
2. **Greedy feasibility phase over-restricts rest days**:
   - In `schedule_optimizer/pipeline.py`, the greedy feasibility stores blocked neighbors (`ordv±1/±2`) and also checks `d±1/±2`, which can reject valid schedules the CP-SAT model would allow. Fix: store **played days only** and keep the ±2-day check.
3. **Structural fixture-round weakness**:
   - Even if slots exist, the current DRR seed scoring is still “sample-and-pick”; it can lock in high-conflict opponent assignments to conflict-heavy weeks. Upgrading to a fixture-round CP-SAT reduces the number of zero-strict-domain fixtures before slot assignment begins.

**Success definition for “first optimized schedule”:**
- A Phase 1 feasible schedule exists (`optimized_schedule_phase1.csv`), and Phase 2 returns `OPTIMAL` or `FEASIBLE` with a finite objective, producing `output/optimized_schedule.csv`.

---

## 5. Slot_tier (reporting + objective)

Same hour/day rules as v1 PRD §5.2 for `Slot_tier` **computation**. The solver also uses tier mismatch and top-tier weekend terms (§4.5).

### 5.1 Match_Tier (derived from teams)

Each fixture has a **Match_Tier** derived deterministically from the two teams’ `Tier` values from `data/Data_Model.xlsx` → `team_data`.

Interpretation:

- **Tier 1 is the highest priority** (should receive the best time slots).
- **Tier 3 is the lowest priority**.
- A **lower numeric tier** means a **better** match (more premium).

Derivation table (Team A tier × Team B tier → Match_Tier):

| Teams | Match_Tier |
|------|------------|
| 1 vs 1 | 1 |
| 1 vs 2 | 1 |
| 1 vs 3 | 2 |
| 2 vs 2 | 2 |
| 2 vs 3 | 3 |
| 3 vs 3 | 3 |

This Match_Tier is then used by the objective:

- **Tier mismatch penalty**: if `Slot_tier > Match_Tier`, penalize proportionally to how much worse the slot is than the match.
- **Top-tier weekend preference**: if `Match_Tier == 1`, prefer Fri/Sat (soft penalty otherwise).

---

## 6. UI Requirements (Streamlit)

### 6.1 Information architecture (required tabs)

The UI must expose the optimizer as an **auditable workflow**: configure → run → inspect schedule → inspect diagnostics → export.

Required tabs:

1. **Run / Overview**
2. **Dashboard**
3. **Full calendar**
4. **Schedule**
5. **Diagnostics**
6. **Data library**
7. **Docs**

### 6.2 Sidebar controls (required)

The sidebar is the single control surface for all run-time knobs. It must include:

- **CAF buffer (days)**: integer slider (0…5). Used when expanding blackout dates around continental blockers.
- **Phase 1 time limit (seconds)**: integer input; default from `EPL_PHASE1_TIME_LIMIT_S`.
- **Phase 2 time limit (seconds)**: optional integer input; default from `EPL_PHASE2_TIME_LIMIT_S` (blank = unlimited).
- **DRR selection**
  - **DRR tries**: integer input (default from `EPL_DRR_TRIES`).
  - **DRR seed**: optional integer input (default from `EPL_DRR_SEED` if set); when provided, the pipeline must be reproducible.
- **Continental postponement multiplier**: float input (default from `EPL_CONT_POSTPONE_MULT`).
- **Objective weights** (Phase 2 only)
  - `max_matches_per_slot` (int; default 2)
  - `w_slot_overlap` (int)
  - `w_tier_mismatch` (int)
  - `w_top_tier_non_prime_day` (int)
  - `w_t1vst1_not_prime_night` (int)
  - `w_postpone_week_distance` (int)
- **Write audit artifacts** toggle: when on, must write `output/phases/*` and the schedule CSVs.
- **Run optimization** primary button.

While a run is in progress:

- Show **live progress** (phase name + key counters) and the latest solver status JSON (Phase 1 then Phase 2).
- After completion, show a compact result badge: `OPTIMAL`, `FEASIBLE`, or `INFEASIBLE/FAILED` with wall time(s).

### 6.3 Run / Overview tab (required)

This tab is the “single pane of glass” summary after a run:

- **KPI tiles**
  - schedule rows produced
  - total travel (sum)
  - postponed match count (if present)
  - count of matches by `Slot_tier` (1/2/3)
- **Run artifacts links**
  - direct links to `output/optimized_schedule.csv`, `output/optimized_schedule_phase1.csv`, `output/week_round_map.csv`
  - links to key phase artifacts in `output/phases/` (`03b`, `06`, `07`, `08`)
- **Download buttons**
  - download the final schedule CSV
  - download diagnostics CSVs when present (e.g. postponed/infeasible)

### 6.4 Dashboard tab (required visualizations)

The dashboard is intended for stakeholders to explore the schedule at club level.

Required elements:

- **Club picker**: grid of buttons (one per team), labeled by team name; selection stored in session state.
- **Club season table** for selected team:
  - Columns: Round, Week, Date/Date_time, Home/Away, Opponent, Venue, Travel_km, Slot_tier, flags (`Is_FIFA`, `Is_CAF`, `Is_SuperCup`, `Postponed`)
  - Sort by `Date_time`
- **Head-to-head table**: pick Team A/B and show their two fixtures.
- **Summary visuals** (at minimum)
  - **Matches per month** bar chart (selected team and/or league-wide)
  - **Home vs away count** for selected team
  - **Travel by opponent or by month** (bar chart)
  - **Slot tier distribution** (stacked bar or pie) for league-wide and selected team

### 6.5 Full calendar tab (mandatory behavior)

- **Month selector** over all `(year, month)` present in `03b_season_day_ledger.csv`.
- **Month grid** of days; clicking a **day** shows a **detail panel**:
  - If **`optimized_schedule.csv`** (or in-memory result) has rows for that `Date`: show those rows (Round, Date_time, teams, venue, travel, flags).
  - Else: show **bullet reasons** derived **only** from the ledger row: e.g. FIFA union date, no league-eligible slots, or eligible slots exist but solver placed no match that day.

No fabricated reasons — if ledger is missing, UI must say the user must run the pipeline once.

The month grid should visually encode:

- days with 1+ scheduled matches (badge showing count)
- days blocked by `Is_FIFA` or `Is_SuperCup` (distinct style)
- days with 0 league-eligible slots (`Slots_league_eligible==0`) (distinct style)

### 6.6 Schedule tab (required)

This tab is the primary exportable table view.

Required elements:

- Load schedule from in-memory result if available, else from `output/optimized_schedule.csv`.
- Filters:
  - Round multi-select
  - Team multi-select (either home or away)
  - Week range filter (optional)
  - Flag filters (optional): FIFA/CAF/SuperCup/Postponed
- Table view + download button (CSV).

### 6.7 Diagnostics tab (required)

This tab exists to help engineers understand feasibility pressure and why postponements happen.

Required elements:

- **Feasible slot counts**: load and render `output/phases/06_feasible_slot_counts.csv`:
  - histogram of strict-domain lengths
  - list of the most constrained fixtures (smallest strict domain)
- **Solver status JSON**:
  - render `07_phase1_feasibility.json` and `08_phase2_optimize.json` as formatted JSON
- **Postponements table**:
  - if `output/postponed_or_infeasible_matches.csv` exists, display and allow download
- **Week utilization**:
  - matches per eligible week (bar chart)
  - slot overload count (how many slots have 2 matches)

### 6.8 Data library tab (required)

Provide a read-only data preview for the two authoritative inputs:

- `data/Data_Model.xlsx`: sheet selector + preview (first N rows)
- `data/expanded_calendar.xlsx`: sheet selector + preview (first N rows)

The Data library must not imply that any other files are used as inputs.

### 6.9 Docs tab (required)

- Render the Markdown docs from `Documentations/`:
  - `PRD.md`
  - `MODEL_EXPLANATION.md`
  - `CODE_DOCUMENTATION.md`

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

- Broadcaster pairwise requests not in `sec_matrix`.
- Dynamic weather rescheduling.
- Egypt Cup / Super Cup **fixture generation** (only `Is_SuperCup` pause).
- Player-level call-ups beyond FIFA union + `Is_FIFA`.

---

## 10. Acceptance Criteria

1. `pip install -r requirements.txt` + `python -m schedule_optimizer` produces `output/optimized_schedule.csv` on a clean clone with bundled data (or exits with a logged **infeasible** reason).
2. Load log proves both authoritative inputs in §2 were opened.
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
