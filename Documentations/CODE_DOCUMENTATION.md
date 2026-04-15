# Code documentation — every feature

This document describes **every package, module, UI surface, and runtime artifact** in the Egyptian Premier League Schedule Optimizer repository. It complements the product specification in [PRD.md](PRD.md).

---

## 1. Repository layout

| Path | Purpose |
|------|---------|
| [schedule_optimizer/](schedule_optimizer/) | Core optimization library (data load, DRR, CP-SAT, pipeline, CLI). |
| [ui/](ui/) | Streamlit web application (dashboard, model explanation tab, data browser, schedule view, embedded docs). |
| [Documentations/MODEL_EXPLANATION.md](Documentations/MODEL_EXPLANATION.md) | Plain-language description of model type, objectives, constraints, and pipeline (also shown in the **Model explanation** app tab). |
| [data/](data/) | Authoritative Excel inputs (see PRD). |
| [output/](output/) | Schedule CSVs, `data_load_log.txt`, and [output/phases/](output/phases/) audit tables (see PRD §3.2). |
| [Documentations/](Documentations/) | PRD, this file, presentation PDF, etc. |
| [scripts/](scripts/) | Legacy/auxiliary scripts (scrapers, distance helpers); not used by the Streamlit UI. |
| [past seasons data/](past seasons%20data/) | Historical schedules (optional preview in UI). |

---

## 2. Package `schedule_optimizer`

### 2.1 [`__init__.py`](schedule_optimizer/__init__.py)

- Declares package version string `__version__`.

### 2.2 [`__main__.py`](schedule_optimizer/__main__.py)

- Entry when running `python -m schedule_optimizer`.
- Invokes `run.main()` and exits with its return code.

### 2.3 [`paths.py`](schedule_optimizer/paths.py)

- **`REPO_ROOT`**: repository root (`Path(__file__).resolve().parents[1]`).
- **`DATA`**: `REPO_ROOT / "data"`.
- **`SOURCES`**: `DATA / "Sources"`.
- **`OUTPUT`**: `REPO_ROOT / "output"`.

### 2.4 [`normalize.py`](schedule_optimizer/normalize.py)

| Function | Behavior |
|----------|----------|
| `strip_team_id(raw)` | Strips whitespace, removes internal spaces, uppercases; returns `None` for empty/NaN-like values. |
| `normalize_stadium_id(raw)` | Uppercases, maps known aliases to distance-matrix IDs (e.g. `HARAS_HODOOD`→`HARAS`, `GHAZL_MAHALLA`→`MAHALLA`, `KHALED_BICHARA`→`EL_GOUNA`, `BORGARAB`→`BORG_ARAB`, `ISMALIA`→`ISMAILIA_ST`). |

### 2.5 [`load_data.py`](schedule_optimizer/load_data.py)

| Symbol | Description |
|--------|-------------|
| `LoadLog` | Accumulates string lines; `write(path)` persists the log. |
| `load_everything(log)` | Opens the **two authoritative** PRD inputs only: `data/Data_Model.xlsx` and `data/expanded_calendar.xlsx` (required tables/sheets described in PRD §2). All teams, stadiums, distances, security/forced-venue rules, and calendar slot rows are derived from those two workbooks only. |
| `slot_date_series(slots)` | Parses `Date` column to normalized pandas datetimes. |
| `build_team_date_blackout(..., caf_buffer_days=1)` | Per-team **date** set derived from the detailed blocker/FIFA expansion tables inside `data/expanded_calendar.xlsx` (see PRD §2.2.2), joined to `expanded_calendar_table` by `Day_ID` and expanded ±`caf_buffer_days` as configured. |
| `eligible_calendar_weeks(slots, fifa_dates)` | Weeks where count of slots with `Is_FIFA!=1`, `Is_SuperCup!=1`, and date not in FIFA union ≥ 9; sorted chronologically by week’s minimum date. |
| `dist_lookup(dist, a, b)` | Symmetric km lookup in pre-built dict from matrix sheet. |
| `venue_for_fixture(home, away, teams, security)` | If security row has `forced_venue`, use it; else home’s `Home_Stadium`. |
| `slot_tier(day_name, dt)` | Returns 1/2/3 from weekend + hour rules (PRD §5.2). |

### 2.6 [`round_robin.py`](schedule_optimizer/round_robin.py)

| Symbol | Description |
|--------|-------------|
| `Fixture` | Dataclass: `round_idx`, `home`, `away`. |
| `double_round_robin(team_ids)` | Circle method for `n−1` rounds; second half repeats pairings with **swapped** home/away. Produces `n×(n−1)` fixtures for even `n`. |
| `double_round_robin_randomized(..., shuffle_teams=True)` | Randomized Berger / circle method. If `shuffle_teams=False`, uses the caller’s `team_ids` order (pipeline passes teams sorted by blackout size). |

### 2.7 [`day_ledger.py`](schedule_optimizer/day_ledger.py)

| Symbol | Description |
|--------|-------------|
| `build_day_ledger(slots, fifa_union_dates)` | One row per calendar date in the expanded calendar: slot counts, `Slots_league_eligible`, FIFA union flag — feeds `output/phases/03b_season_day_ledger.csv` and the UI **Full calendar** tab. |

### 2.8 [`phases_dir.py`](schedule_optimizer/phases_dir.py)

| Symbol | Description |
|--------|-------------|
| `phases_dir()` | Returns `OUTPUT / "phases"` for consistent audit paths. |

### 2.9 [`cp_sat_model.py`](schedule_optimizer/cp_sat_model.py)

| Symbol | Description |
|--------|-------------|
| `Match` | Includes `postpone_weight_mult` (default `1.0`, higher for CL/CC matches from pipeline). |
| `solve_assignment(...)` | CP-SAT: assignment + team/venue caps + rest + H/A automaton; optional **multi-term** linear objective when `optimize=True` (travel, tier mismatch, top-tier weekend, T1vT1 prime night, postponement with per-match mult, slot overload). Phase 1 calls with `optimize=False`. Returns `(assign_dict, cp_status, status_name, objective_value \| None)`. |

### 2.10 [`pipeline.py`](schedule_optimizer/pipeline.py)

| Symbol | Description |
|--------|-------------|
| `OptimizationResult` | Same as before; `stats` may include `drr_strict_domain_min`, `drr_strict_domain_sum`, `cont_postpone_objective_mult`, `drr_selection`. |
| `run_optimization(...)` | Orchestrates the full pipeline and writes `output/phases/*` when `write_outputs=True`. Generates the DRR fixture list in-memory (either via fixture-round CP-SAT or a scored-seed fallback), converts fixtures → `Match` + `feasible` domains, then runs two CP-SAT assignment phases with `07`/`08` JSON metadata. |

### 2.11 [`run.py`](schedule_optimizer/run.py)

- CLI: reads `EPL_CAF_BUFFER_DAYS`, calls `run_optimization(write_outputs=True)`, prints message, returns exit code.

---

## 3. Package `ui` (Streamlit)

### 3.1 Running the UI

```bash
pip install -r requirements.txt
python -m streamlit run ui/app.py
```

The first line of `app.py` inserts `REPO_ROOT` on `sys.path` so `import schedule_optimizer` resolves when the script lives in `ui/`.

### 3.2 [`app.py`](ui/app.py) — screens and behaviors

| Feature | Description |
|---------|-------------|
| **Page config** | Wide layout, ⚽ icon, title “EPL Schedule Optimizer”. |
| **Custom CSS** | Dark gradient background, card-style metrics, sidebar styling. |
| **Sidebar · CAF buffer slider** | Integer 0–5 days each side of each `cont_blockers` anchor (passed to `run_optimization`). |
| **Sidebar · CAF buffer** | Slider passed as `caf_buffer_days`. |
| **Sidebar · Solver & DRR** | Phase 1/2 time limits, DRR tries + optional seed, continental postpone multiplier, write-outputs toggle. |
| **Sidebar · CP-SAT objective weights** | `max_matches_per_slot`, `w_slot_overlap`, `w_tier_mismatch`, `w_top_tier_non_prime_day`, `w_postpone_week_distance`, `w_t1vst1_not_prime_night` passed into `run_optimization`. |
| **Sidebar · Run optimization** | Invokes `run_optimization(..., progress_cb=...)` with all sidebar values; stores `OptimizationResult` in `st.session_state["last_result"]`. |
| **Tab · Dashboard** | Club picker, club season, H2H, simulation metrics; expanders for slot-tier distribution, feasible-slot stats, **DRR / continental weighting** from `last_result.stats`. |
| **Tab · Full calendar** | Month selector + `calendar_board.render_month_calendar` / `render_day_detail` using `output/phases/03b_season_day_ledger.csv` + active schedule. |
| **Tab · Model explanation** | Renders `Documentations/MODEL_EXPLANATION.md` via `st.markdown`. |
| **Tab · Data library** | Checkbox to add `past seasons data/` root. Lists all `.xlsx`/`.csv` under chosen roots. Select file → if CSV, `load_csv` preview; if Excel, sheet picker then `load_excel_sheet` preview (max 400 rows). |
| **Tab · Schedule** | Reads `output/optimized_schedule.csv` if present; multiselect filter on `Round`; dataframe + download button. |
| **Tab · Code documentation** | Renders this markdown file (`CODE_DOCUMENTATION.md`) via `st.markdown`. |
| **`_schedule_dataframe()`** | Returns the active schedule: in-memory `last_result.schedule_df` after a successful run, otherwise reads `output/optimized_schedule.csv`. |
| **`_team_list()`** | Builds `(Team_ID, Team_Name)` pairs from `teams_data` (skips blank IDs). |
| **`_club_button()`** | Wraps `st.button` with `type="primary"` if selected else `"secondary"` (falls back without `type` on older Streamlit). |
| **`_render_club_picker()`** | Six-column grid; caption (club name) above each button; updates `st.session_state["dashboard_club"]`. |
| **`_club_season_table(sched, club_id)`** | Filters to rows where the club is home or away; adds `H_A` and `Opponent`; sorts by `Date_time`. |
| **`_head_to_head_table(sched, team_a, team_b)`** | Rows where `(Home==a and Away==b)` or `(Home==b and Away==a)`; sorted by `Date_time`. |

### 3.3 [`calendar_board.py`](ui/calendar_board.py)

| Symbol | Description |
|--------|-------------|
| `load_day_ledger_csv` | Reads `03b_season_day_ledger.csv` with parsed `Date`. |
| `schedule_rows_for_date` | Filters schedule `DataFrame` to one calendar date. |
| `explain_day_without_matches` | Bullet reasons from ledger columns only. |
| `render_month_calendar` / `render_day_detail` | Streamlit month grid + detail panel. |

### 3.4 [`data_browser.py`](ui/data_browser.py)

| Function | Description |
|----------|-------------|
| `repo_root()` | Parent of `ui/` (repository root). |
| `list_tabular_files(roots, extensions)` | Unique sorted paths from recursive `rglob` over given roots. |
| `load_excel_sheet(path, sheet, nrows)` | `pandas.read_excel` preview. |
| `load_csv(path, nrows)` | `pandas.read_csv` preview. |
| `excel_sheet_names(path)` | Sheet names via `pd.ExcelFile`. |
| `describe_path(path)` | Relative path, suffix, file size. |

---

## 4. Outputs (`output/`)

| File | Producer | Contents |
|------|----------|----------|
| `optimized_schedule.csv` | `pipeline.run_optimization` | Final optimized schedule. |
| `optimized_schedule_phase1.csv` | same | Feasible-only pass. |
| `optimized_schedule_phase2.csv` | same | Copy of final after phase 2. |
| `week_round_map.csv` | same | Round → `Calendar_Week_Num`. |
| `postponed_or_infeasible_matches.csv` | same (when applicable) | Postponement diagnostics. |
| `data_load_log.txt` | `LoadLog` | Human-readable log. |
| `phases/*` | same | See PRD §3.2 (`01`…`08` + `03b`). |

---

## 5. Environment variables

| Variable | Used by | Meaning |
|----------|---------|---------|
| `EPL_CAF_BUFFER_DAYS` | `run.py`, UI default | Continental anchor ±buffer (days). |
| `EPL_DRR_SEED` | `pipeline` | Fixed DRR seed; skips multi-try scoring. |
| `EPL_DRR_TRIES` | `pipeline` | Number of seeds to score (default 12). |
| `EPL_PHASE2_TIME_LIMIT_S` | `pipeline` | Optional CP-SAT phase 2 time limit (seconds). |
| `EPL_CONT_POSTPONE_MULT` | `pipeline` / `cp_sat_model` | Postponement penalty multiplier for CL/CC matches (default 4). |
| `EPL_PHASE1_TIME_LIMIT_S` | `pipeline` | CP-SAT phase 1 time limit (default 30s). |

---

## 6. Dependencies ([requirements.txt](requirements.txt))

- **pandas / openpyxl**: Excel + CSV I/O.
- **ortools**: CP-SAT solver.
- **streamlit**: Web UI.

---

## 7. Execution flow (high level)

```mermaid
flowchart TD
  LD[load_everything]
  BL[build_team_date_blackout]
  EW[eligible_calendar_weeks]
  DL[build_day_ledger + slot_meta]
  FX[DRR fixture generation<br/>(fixture-round CP-SAT or scored-seed fallback)]
  FZ[feasible domains]
  P1[CP-SAT phase 1]
  P2[CP-SAT phase 2]
  PH[output/phases audit]
  OUT[schedule CSVs]
  LD --> BL
  LD --> EW
  LD --> DL
  BL --> FX
  EW --> FX
  DL --> PH
  FX --> FZ
  DL --> FZ
  FZ --> P1
  P1 --> P2
  P1 --> PH
  P2 --> OUT
  P2 --> PH
```

### 7.1 Methodology upgrade roadmap (why optimization may fail today)

If you cannot obtain even a single optimized schedule, the highest-impact improvements are methodological:

- **Fixture-round optimization before slot assignment**: choose the DRR by round using a dedicated CP-SAT model (pairings + home/away + fairness), instead of sampling random DRR seeds and then locking fixtures into bad weeks.
- **Explicit postponements in CP-SAT**: replace the relax/retry loop in `pipeline.py` with an `is_postponed[m]` decision and a strong penalty term in `cp_sat_model.py`, so CP-SAT chooses which matches to relax in one solve.
- **Greedy feasibility correctness**: align greedy rest-day checks with CP-SAT rest rules; the current greedy implementation can over-reject valid schedules by effectively blocking too many days.

These upgrades are specified in detail in [`Documentations/PRD.md`](Documentations/PRD.md) §4.2.1–§4.2.2 and §4.8.

---

## 8. Extension points

- Hard **T1 vs T1 prime-night** constraint (today: large soft penalty only).
- Gurobi / IIS for infeasibility diagnostics.
- Stronger joint **round+slot** co-optimization (today: assignment with fixed DRR).

---

## 9. Version

Aligned with PRD v2.0, `output/phases/` audit trail, and Full calendar UI.
