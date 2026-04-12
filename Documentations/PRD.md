# Product Requirements Document (PRD)

## Egyptian Premier League Schedule Optimizer — Optimization Phase

**Version:** 1.0  
**Aligned with:** [presentation.pdf](presentation.pdf), Phase I documentation, and all committed data files under `data/` and `data/Sources/`.  
**Solver:** Google OR-Tools CP-SAT (0–1 integer programming / constraint programming formulation).

---

## 1. Purpose

Build a **single, reproducible pipeline** that:

1. **Loads every** specified spreadsheet/CSV (no synthetic teams, stadiums, fixtures, or distances).
2. Constructs a **double round-robin (DRR)** fixture list for the teams present in `teams_data.xlsx`.
3. Assigns each league fixture to **exactly one** time slot from `expanded_calendar.xlsx`, respecting **hard constraints** derived from the data.
4. **Minimizes** a linear **travel proxy** objective computed only from `Stadium_Distance_Matrix.xlsx`.
5. Exports **`optimized_schedule.csv`** including **`Travel_km`** and **`Slot_tier`** per row.

If no assignment satisfies all hard constraints, the program **must exit with a non-zero status**, print a concise **infeasibility** explanation, and **must not** fabricate calendar rows, teams, or distances.

---

## 2. Inputs (Authoritative Files)

All paths are relative to the repository root. The loader **must open each file at least once** and record row counts in a load log.

| # | Path | Required sheets / usage |
|---|------|-------------------------|
| 1 | `data/Data_Model.xlsx` | Sheets: `team_data`, `Stadiums`, `dist_Matrix`, `Sec_Matrix` — **cross-check** against Sources; not used to override Sources if conflict (Sources win for optimization; mismatch raises warning). |
| 2 | `data/expanded_calendar.xlsx` | Sheets: all (read for completeness). **Slot universe:** sheet `expanded_calendar` only. |
| 3 | `data/Sources/calendar.xlsx` | Sheet `MAINCALENDAR` — season structure cross-check vs expanded calendar. |
| 4 | `data/Sources/CAF CL.xlsx` | Sheet `CAF CL` — **loaded and logged**; continental windows for CL clubs are enforced via **`Is_CAF` on slots** (expanded calendar) plus **cont blockers** (H11), not by blanketing every CL sheet date (that combination was infeasible with the current blocker density). |
| 5 | `data/Sources/CAF CC.xlsx` | Sheet `CAF CC` — same as row 4 for CC clubs. |
| 6 | `data/Sources/cont_blockers_table.xlsx` | Sheets: `cont_blockers_updated`, `cont_blockers` — merged with CSV (union, dedupe on `date_id` + `team_id` + `competition_name` + `round`). |
| 7 | `data/Sources/cont_blockers_csv.csv` | Same schema as blocker table; merged as above. |
| 8 | `data/Sources/expanded_calendar.csv` | Loaded; compared to `expanded_calendar.xlsx` row count (warning on mismatch). |
| 9 | `data/Sources/FIFA_Days_UPDATED.xlsx` | Sheets: `FIFA_DAYS`, `FIFA_Days_UPDATED` — **union** of calendar dates for global FIFA blackout (see §4.2.2). |
| 10 | `data/Sources/FIFA Days.xlsx` | Sheet `International Break Schedule Ta` — **union** into FIFA dates. |
| 11 | `data/Sources/security matrix.xlsx` | Sheet `Sec_Matrix` — venue rules for listed pairings. |
| 12 | `data/Sources/stadiums.xlsx` | Sheet `Stadiums` — metadata; rows with null `Stadium_ID` dropped. |
| 13 | `data/Sources/teams_data.xlsx` | Sheet `Teams` — authoritative team list and `Home_Stadium` / `Alt_Stadium` / `Cont_Flag`. |
| 14 | `data/Sources/Stadium_Distance_Matrix.xlsx` | Sheet `Sheet1` — authoritative **Origin → column stadium** distances (km). |
| 15 | `data/Sources/Stadium_Distances_Columns.xlsx` | Sheet `Sheet1` — loaded; **spot-check** consistency with matrix (sample symmetric pair); warnings only unless hard failure on NaN core cells. |

---

## 3. Outputs

### 3.1 Primary artifact: `output/optimized_schedule.csv`

One row per **scheduled match** (306 rows for 18 teams).

| Column | Type | Definition |
|--------|------|------------|
| `Round` | int | Abstract league round **1…34** (DRR second half). |
| `Calendar_Week_Num` | int | `Week_Num` from `expanded_calendar` for the chosen slot (data field). |
| `Day_ID` | str | From calendar row. |
| `Date` | date | From calendar row. |
| `Date_time` | datetime | From calendar `Date time`. |
| `Home_Team_ID` | str | Home side of fixture. |
| `Away_Team_ID` | str | Away side of fixture. |
| `Venue_Stadium_ID` | str | Stadium hosting the match: forced neutral from security if applicable, else home club `Home_Stadium`. |
| `Travel_km` | float | **Sum** of `distance(Home_Stadium(home), Venue)` + `distance(Home_Stadium(away), Venue)` from `Stadium_Distance_Matrix.xlsx` (diagonal = 0). If a club’s home stadium ID is missing from the matrix, **fail validation** before solve. |
| `Slot_tier` | int | **1 = highest commercial desirability**, **3 = lowest**, derived **only** from `Day_name` and clock hour of `Date time` on the assigned slot (see §5.2). No external tier table unless later added to data. |
| `Is_FIFA` | int | Echo from slot (0/1). |
| `Is_CAF` | int | Echo from slot. |
| `Is_SuperCup` | int | Echo from slot. |

### 3.2 Secondary artifacts

- `output/data_load_log.txt` — list of files, sheets, row counts, merge notes, warnings (e.g. xlsx vs csv row diff).
- `output/week_round_map.csv` — mapping `Round` → `Calendar_Week_Num` (the 34 calendar weeks selected from data for the 34 DRR rounds).

---

## 4. Hard Constraints (Must All Hold)

### 4.1 League structure

- **H1 — Team set:** Exactly the set of `Team_ID` values in `teams_data.xlsx` (`Teams`), after dropping null IDs. **n = 18`** is expected; if not 18, the model still builds DRR for the actual **n** (even **n** required; if odd, **fail** with message).
- **H2 — DRR:** Each ordered pair of distinct teams meets **twice** (home and away reversed between halves). Total matches **n × (n − 1)**.
- **H3 — One match per team per round:** For each abstract round **r ∈ {1,…,n_rounds}** with **n_rounds = 2 × (n − 1)** (= 34 for n = 18), each team appears in **exactly one** fixture in that round.
- **H4 — One slot per fixture:** Each fixture is assigned **exactly one** slot from the expanded calendar slot universe.
- **H5 — Calendar week for round:** For each round **r**, a **calendar** `Week_Num` value `W[r]` is chosen **only from the data** (see §4.6). Every fixture in round **r** must be placed in a slot whose `Week_Num` equals `W[r]`.

### 4.2 Time / competition blackouts (slot-level)

Let each slot row have `Date` (date), `Is_FIFA`, `Is_CAF`, `Is_SuperCup` from `expanded_calendar`.

- **H6 — FIFA (calendar flag):** No league match in any slot with **`Is_FIFA == 1`** (all teams).
- **H7 — Super Cup pause:** No league match in any slot with **`Is_SuperCup == 1`** (all teams).
- **H8 — FIFA (explicit date lists):** No league match on any calendar **date** present in the union of:
  - `Date` column from both sheets of `FIFA_Days_UPDATED.xlsx`, and  
  - `Date` from `FIFA Days.xlsx` (`International Break Schedule Ta`),  
  after normalizing to **date** (strip time). Applies to **all teams** (in addition to H6; duplicates are allowed).
- **H9 — CAF “slot reservation” flag:** No league match for teams with **`Cont_Flag == 'CL'`** in slots with **`Is_CAF == 1`**. No league match for teams with **`Cont_Flag == 'CC'`** in slots with **`Is_CAF == 1`**. Teams with null `Cont_Flag` are unrestricted by H9.
- **H10 — CAF workbooks (CL/CC):** Files are read for completeness and logged. **Hard** continental date logic for CL/CC teams is enforced via **H9** (`Is_CAF` on slots) and **H11** (team-specific `cont_blockers`), because applying every `Date` in the CAF CL/CC workbooks as full-day bans for those clubs overlaps almost every gameweek with **H9** and makes the model infeasible on the supplied calendar.
- **H11 — Continental blockers (buffered):** From merged **cont blockers** (`cont_blockers_table.xlsx` + `cont_blockers_csv.csv`): for each row, resolve anchor **calendar date** by joining `date_id` to `Day_ID` on `expanded_calendar` and taking that row’s `Date`. For that `team_id`, ban league matches on all slots whose `Date` lies in **[anchor_date − B, anchor_date + B]** inclusive, where **B** defaults to **1** day (configurable via environment variable **`EPL_CAF_BUFFER_DAYS`**, e.g. `3` for the presentation’s ±3). With **B = 3** and the current blocker density, the model is typically **infeasible**; **B = 1** is the default that still respects “buffer around listed CAF commitments” without over-covering the season.

### 4.3 Stadium / venue

- **H12 — Venue for fixture:** If `(Home_Team_ID, Away_Team_ID)` (after ID normalization) appears in `Sec_Matrix` with a non-empty **forced** venue, the match **must** use that stadium ID (after normalization). Otherwise venue = **`Home_Stadium`** of the home team from `teams_data`.
- **H13 — Stadium sharing / double booking:** For every slot **t** and every physical stadium **S**, **at most one** match assigned to **t** may use venue **S** (includes neutral forced venues).

### 4.4 Team / slot incidence

- **H14 — One match per team per datetime:** For each slot **t** and each team **i**, at most **one** match involving **i** at **t** (follows from unique slot timing; enforced explicitly).

### 4.5 Data validity (pre-solve)

- **H15 — Distance matrix coverage:** For every `Home_Stadium` and `Venue` that can appear, both must exist as **row Origin** and **column** in `Stadium_Distance_Matrix.xlsx` after ID normalization; distance lookup must be finite.

### 4.6 Calendar week selection for rounds (data-driven)

- Let **usable(w)** = number of slots in `expanded_calendar` with `Week_Num == w` and **not** blocked by H6–H8 (FIFA/SuperCup/date union).
- **Eligible weeks** = all `w` with **usable(w) ≥ 9** (nine parallel fixtures per round for 18 teams).
- Sort eligible weeks by **min(Date)** over slots in that week (chronological).
- **W[1],…,W[34]** = the **first 34** eligible weeks in that sorted order.  
- If fewer than **34** eligible weeks exist → **infeasible** (fail before solve).

---

## 5. Objectives (Optimization)

### 5.1 Primary objective (implemented)

**O1 — Minimize total travel proxy (km)**  

For fixture **m** with home **h**, away **a**, venue **V**:

\[
c_m = \mathrm{dist}(\mathrm{HomeStadium}(h), V) + \mathrm{dist}(\mathrm{HomeStadium}(a), V)
\]

Assigning fixture **m** to slot **t** incurs cost **c_m** (independent of **t** in current formulation). **Global objective:** minimize \(\sum_{m,t} x_{m,t} \cdot c_m\) where \(x_{m,t} \in \{0,1\}\).

*Tie-breaking:* CP-SAT minimizes total cost; if multiple optima exist, any optimum is acceptable.

### 5.2 Secondary / reporting — Slot_tier (not in solver objective unless extended)

Computed **after** assignment from slot fields only:

| `Slot_tier` | Rule (deterministic) |
|-------------|----------------------|
| **1** | `Day_name` ∈ {`FRI`, `SAT`, `SUN`} **and** hour of `Date time` ≥ **20** |
| **2** | `Day_name` ∈ {`FRI`, `SAT`, `SUN`} **and** hour < **20** |
| **3** | All other slots |

*(Hours from data’s local `Date time`; no invented tiers.)*

### 5.3 Objectives described in presentation but **not** encoded in v1 solver (future work)

Documented for traceability; **out of scope** for the first optimization release unless added as data-driven weights:

- **O2 — Rest-day balance** between opponents (would need rest variables + multi-round linking).
- **O3 — Away-break minimization** (H–A pattern quality across season).
- **O4 — Simultaneous kick-offs** in final critical rounds (would fix equal `Date_time` within a subset of rounds).
- **O5 — Commercial weighting beyond Slot_tier** (e.g. tier-weighted linear objective).

---

## 6. ID Normalization (Deterministic, Logged)

All IDs trimmed; uppercase for matching.

| Raw (examples) | Normalized |
|----------------|------------|
| `BORGARAB`, `borg_arab` | `BORG_ARAB` if matrix uses `BORG_ARAB` |
| `ISMALIA` | `ISMAILIA_ST` if matrix uses `ISMAILIA_ST` |
| `HARAS_HODOOD` (teams sheet) | `HARAS` (distance matrix row/column) |
| `GHAZL_MAHALLA` | `MAHALLA` |
| `KHALED_BICHARA` | `EL_GOUNA` |
| `Sec_Matrix` column name with leading space | Strip to `forced_venue` |

Forced / banned stadium cells must map to a **column** in the distance matrix after normalization; otherwise **fail** with explicit ID.

---

## 7. Non-Goals (v1)

- TV broadcaster pairwise requests not in security matrix.
- Weather or dynamic rescheduling.
- Egypt Cup / Super Cup **fixture generation** (only hard **pause** via `Is_SuperCup`).
- Player-level international call-ups beyond FIFA date union + `Is_FIFA`.

---

## 8. Acceptance Criteria

1. Fresh clone + `pip install -r requirements.txt` + `python -m schedule_optimizer` produces `output/optimized_schedule.csv` **without** hand-edited inputs beyond the Excel/CSV already in `data/`.
2. Load log proves **every** input file in §2 was read.
3. Output has **exactly** `n × (n − 1)` rows and satisfies H1–H14 when verified by a post-solve checker (included in run).
4. If CP-SAT status is `INFEASIBLE`, process exits **≠ 0** and prints which precondition failed (e.g. fewer than 34 eligible weeks).

---

## 9. References

- Internal: `Documentations/presentation.pdf` (objectives/constraints narrative).  
- OR-Tools CP-SAT: https://developers.google.com/optimization/cp/cp_solver  
