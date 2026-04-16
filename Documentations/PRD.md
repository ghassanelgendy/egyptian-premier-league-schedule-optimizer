# Product Requirements Document (PRD)

## Egyptian Premier League Schedule Optimizer

**Version:** 3.0
**Status:** Full product and model requirements for the current Streamlit application and CAF-aware scheduling pipeline.
**Last updated:** 2026-04-16
**Authoritative model inputs:** `data/Data_Model.xlsx` and `data/expanded_calendar.xlsx` only.

---

## 1. Purpose

The product builds and reviews a full Egyptian Premier League schedule from committed workbook data. It must generate a double round-robin fixture framework, assign fixtures to real calendar slots, audit CAF conflicts, repair affected matches where possible, and expose the result through an operational Streamlit UI.

The application must support both model execution and schedule inspection:

- run the full scheduling pipeline from the UI,
- tweak model variables before a run,
- inspect final, baseline, and repaired schedules,
- view matches by team, head-to-head pair, round, month, and day,
- visualize season travel distance by team,
- explain why a calendar day has no selected match,
- browse and download generated artifacts.

The scheduling approach is a structured baseline-plus-repair flow:

1. Load and normalize the two authoritative Excel workbooks.
2. Generate a seeded double round-robin fixture framework with valid home/away patterns.
3. Build dynamic chronological round windows from playable non-FIFA calendar slots.
4. Solve a CAF-aware baseline CP-SAT model inside strict round windows.
5. Audit remaining CAF conflicts.
6. If CAF violations exist, remove CAF-conflicting matches into a postponement queue.
7. If CAF violations exist, repair queued matches into later free CAF-safe slots when possible.
8. If no CAF violations exist, skip repair and write a skipped repair status.
9. Write final schedule, diagnostics, and validation reports.
10. Present all outputs in the Streamlit UI.

---

## 2. Source of Truth and Data Policy

The model must use only:

| File | Required use |
|---|---|
| `data/Data_Model.xlsx` | Teams, stadiums, distance matrix, security rules, forced venues, team tiers, CAF participation flags. |
| `data/expanded_calendar.xlsx` | Slot universe, dates, kickoff times, week numbers, FIFA flags, CAF blockers, Ramadan/calendar fields. |

The pipeline must not use these as model inputs:

- previous `output/*` artifacts,
- `output/phases/*` artifacts,
- generated CSV mirrors,
- past-season datasets,
- scraped files,
- web data,
- manually edited fixture outputs.

Generated outputs are inspection artifacts only. They may be displayed or downloaded by the UI, but they must never drive a new solver run.

---

## 3. Input Requirements

### 3.1 `data/Data_Model.xlsx`

Required sheets and columns:

| Sheet | Required columns |
|---|---|
| `team_data` | `Team_ID`, `Team_Name`, `Gov_ID`, `Gov_Name`, `Home_Stadium_ID`, `Alt_Stadium_ID`, `Tier`, `Cont_Flag` |
| `Stadiums` | `Stadium_ID`, `Stadium_Name`, `Gov_ID`, `City`, `Is_Floodlit` |
| `dist_Matrix` | `Origin` plus stadium ID columns |
| `Sec_Matrix` | `home_team_ID`, `away_team_ID`, `banned_venue1_ID`, `banned_venue2_ID`, `forced_venue_ID` |

Normalization rules:

- IDs are stripped and uppercased.
- `Cont_Flag` values `CL` and `CC` identify CAF-participating teams.
- Empty `Cont_Flag` values mean the team is not CAF-participating.
- `forced_venue_ID`, when present for a home/away pair, overrides the home stadium.
- Distances are looked up from the away team's home stadium to the assigned venue.

### 3.2 `data/expanded_calendar.xlsx`

Required sheets:

| Sheet | Required use |
|---|---|
| `expanded_calendar` | Primary slot universe. |
| `expanded _calendar_table` | Secondary calendar table; may be used for validation/fallback if normalized. |
| `FIFA_DAYS1` | Authoritative FIFA-date expansion. |
| `cont_blockers_updated1` | Authoritative team-specific CAF blockers. |
| `unique_CAF_dates` | CAF date list for calendar diagnostics and cross-checks. |

The main slot universe must include or be normalizable to:

- `Day_ID`
- `Date`
- `_date` derived from `Date`
- `Date time`
- `Week_Num`
- `Day_name`
- `Is_FIFA` when present
- `Is_CAF` when present
- CAF/FIFA label fields when present

### 3.3 FIFA Day Definition

FIFA dates are the union of:

- slot rows where `Is_FIFA == 1`,
- dates listed in `FIFA_DAYS1`,
- dates with non-empty FIFA label fields such as `FIFA_DAY` or `FIFA_DAYS`.

No league match may be scheduled on a FIFA date in any phase.

### 3.4 CAF Blocker Definition

CAF blockers come from:

- `cont_blockers_updated1`,
- `unique_CAF_dates`,
- CAF labels or `Is_CAF` flags where useful for diagnostics.

Team-specific blockers are used by the solver and repair logic. Unique CAF dates are also shown in the calendar UI to explain CAF-blocked days.

---

## 4. Tunable Model Variables

The Streamlit sidebar must expose all current model variables that can be changed before a run. Changes apply to the current Streamlit session and are patched into imported solver modules before executing the pipeline.

### 4.1 League Shape

| Variable | Default | Meaning |
|---|---:|---|
| `NUM_TEAMS` | 18 | Number of league teams. Must match workbook team count. |
| `NUM_ROUNDS` | 34 | Double round-robin rounds. Expected value is `(NUM_TEAMS - 1) * 2`. |
| `MATCHES_PER_ROUND` | 9 | Matches per abstract round. Expected value is `NUM_TEAMS / 2`. |

### 4.2 Rest and Streak Rules

| Variable | Default | Meaning |
|---|---:|---|
| `MIN_REST_DAYS_LOCAL` | 3 | Full rest days between league matches. Dates must be at least 4 calendar days apart. |
| `MIN_REST_DAYS_CAF` | 3 | Full rest days between league and CAF matches. Dates must be at least 4 calendar days apart. |
| `PREFERRED_REST_DAYS_CAF` | 5 | Preferred CAF buffer where code paths consume it. |
| `MAX_CONSECUTIVE_HOME` | 2 | Max consecutive home matches in played/team sequence. |
| `MAX_CONSECUTIVE_AWAY` | 2 | Max consecutive away matches in played/team sequence. |

### 4.3 Capacity Rules

| Variable | Default | Meaning |
|---|---:|---|
| `HARD_MIN_MATCHES_PER_WEEK` | 6 | Hard lower week target retained for model configuration; current baseline treats small week fragments softly. |
| `HARD_MAX_MATCHES_PER_WEEK` | 18 | Hard cap on league matches in a calendar week. |
| `SOFT_MIN_MATCHES_PER_WEEK` | 6 | Soft lower target for weekly load balance. |
| `SOFT_MAX_MATCHES_PER_WEEK` | 12 | Soft upper target for weekly load balance. |
| `MAX_MATCHES_PER_DAY` | 3 | Hard cap on league matches scheduled on one calendar date. |
| `MAX_MATCHES_PER_SLOT` | 2 | Hard cap on league matches assigned to the same kickoff slot in baseline. Repair uses only empty slots. |

### 4.4 Objective Weights

| Variable | Default | Meaning |
|---|---:|---|
| `W_ROUND_ORDER` | 100 | Penalty for deviation from nominal round/week placement. |
| `W_WEEK_UNDERLOAD` | 50 | Penalty below soft weekly load target. |
| `W_WEEK_OVERLOAD` | 50 | Penalty above soft weekly load target. |
| `W_TRAVEL` | 1 | Per-kilometer travel penalty. |
| `W_TIER_MISMATCH` | 20 | Penalty for mismatch between match tier and slot tier. |
| `W_CAF_PREFERRED` | 10 | Preferred CAF rest weight where code paths consume it. |

### 4.5 Solver Limits

| Variable | Default | Meaning |
|---|---:|---|
| `BASELINE_SOLVER_TIME_LIMIT_S` | 600 | CP-SAT baseline solve time limit. |
| `REPAIR_SOLVER_TIME_LIMIT_S` | 60 | Repair phase time limit/configuration value. |

---

## 5. Fixture Generation

The fixture framework must be generated before slot assignment.

Requirements:

- 18-team double round-robin.
- 34 abstract rounds.
- 9 matches per round.
- Every ordered pair appears exactly once.
- Every unordered pair appears twice, home and away.
- Each team plays exactly once per abstract round before postponements.
- Home/away orientation is solved before slot scheduling.

Home/away pattern requirements:

- Each team has 17 home and 17 away matches.
- No team has more than two consecutive home or away matches in abstract round order.
- Rolling five-match windows should contain two or three home matches where feasible.
- Season edges should avoid two consecutive home or away matches where feasible.
- Second-leg matches reverse first-leg home/away.

Generated artifacts:

- `output/phases/04_fixture_framework.csv`
- `output/phases/04_home_away_patterns.csv`

---

## 6. Round Window Construction

The model must not map round number directly to calendar week number.

Round windows are built from playable slot dates:

- FIFA dates are removed first.
- Candidate windows are chronological date ranges from usable slots.
- Current implementation uses rolling 5-day windows.
- A candidate window must contain enough slot rows for a round.
- CAF-heavy windows where CAF teams have no CAF-safe slot are skipped.
- Selected windows must be chronological and non-overlapping.
- Exactly `NUM_ROUNDS` baseline windows are required.

Output:

- `output/phases/03_round_windows.csv`

---

## 7. Baseline Solver

The baseline solver assigns generated fixtures to concrete calendar slots using CP-SAT.

### 7.1 Baseline Hard Constraints

| ID | Constraint |
|---|---|
| H1 | Every generated fixture is assigned exactly once. |
| H2 | No league match is assigned to a FIFA date. FIFA dates are removed from usable slots before solving. |
| H3 | Baseline match domains are restricted to their selected round window. |
| H4 | A team cannot play more than one league match on the same calendar date. |
| H5 | A venue cannot host more than one match in the same slot. |
| H6 | A kickoff slot cannot exceed `MAX_MATCHES_PER_SLOT`. |
| H7 | A calendar date cannot exceed `MAX_MATCHES_PER_DAY` league matches. Default cap is 3. |
| H8 | A team must have at least `MIN_REST_DAYS_LOCAL` full rest days between league matches. |
| H9 | Non-postponed baseline rounds must be strictly chronological: Round `R+1` cannot start before Round `R` has finished. |
| H10 | Forced venue rules from `Sec_Matrix` must be respected by fixture generation. |
| H11 | CAF teams must avoid known CAF dates and the hard CAF buffer when feasible inside the round window. |

If CAF-safe slots do not exist inside a strict round window for a match, the domain builder may relax the CAF filter for that match so the baseline remains complete. Such matches must then be caught by CAF audit and moved to the postponement queue.

### 7.2 Baseline Soft Objectives

The baseline objective minimizes:

- deviation from nominal round/week order,
- weekly underload below `SOFT_MIN_MATCHES_PER_WEEK`,
- weekly overload above `SOFT_MAX_MATCHES_PER_WEEK`,
- travel distance weighted by `W_TRAVEL`,
- match-tier versus slot-tier mismatch weighted by `W_TIER_MISMATCH`.

Hard feasibility always outranks soft preferences.

Output:

- `output/optimized_schedule_pre_caf.csv`
- `output/phases/05_baseline_feasible_slot_counts.csv`
- `output/phases/06_baseline_solver_status.json`

---

## 8. CAF Audit

After baseline solving, the system audits CAF constraints.

A baseline match is a CAF violation if:

- it is too close to a CAF date for either CAF-participating team,
- it conflicts with team-specific CAF blocker data,
- it violates the hard CAF buffer before or after a CAF fixture.

CAF buffer:

- Applies only to teams with `Cont_Flag` in `CL` or `CC`.
- Same-day CAF and league match is forbidden.
- A league match must be at least `MIN_REST_DAYS_CAF + 1` calendar days away from each relevant CAF match.
- Default hard gap is 4 calendar days apart.
- Preferred gap is 6 calendar days apart where supported.

Audit outputs:

- accepted baseline matches,
- CAF violations,
- `output/phases/07_caf_audit.csv`.

---

## 9. CAF Repair

The repair phase removes violating baseline matches from the accepted schedule and tries to reinsert each queued match into a later valid slot.

### 9.1 Free Slot Definition

For repair, a free slot means:

- the slot is in the usable non-FIFA slot universe,
- the slot date is on or after the original baseline match date,
- no accepted league match already occupies that exact slot row,
- the venue is free in that slot,
- the slot has valid date, time, day ID, and week metadata.

Repair is stricter than baseline slot capacity. A repair slot must be empty even if `MAX_MATCHES_PER_SLOT` would otherwise allow multiple matches.

### 9.2 Repair Feasibility Rules

| Rule | Requirement |
|---|---|
| R1 | Slot is not a FIFA date. |
| R2 | Slot date is not before the original match date. |
| R3 | Date load is below `MAX_MATCHES_PER_DAY`. Default cap is 3. |
| R4 | Neither team already has an accepted league match on the candidate date. |
| R5 | Both teams satisfy local league rest rules against all accepted matches. |
| R6 | Venue is free in the candidate slot. |
| R7 | Inserting the match does not create a home/away streak violation. |
| R8 | CAF teams satisfy the hard CAF buffer in both directions. |
| R9 | Calendar week load is below `HARD_MAX_MATCHES_PER_WEEK`. |

Repair strategy:

- Deduplicate CAF violations by match.
- Count feasible repair slots per queued match.
- Process most-constrained matches first.
- Rank candidate slots by displacement from the original date.
- Use a multi-pass greedy placement so later state changes are considered.
- Skip the repair phase entirely when the audit returns zero violations.

Repair outputs:

- `output/caf_postponement_queue.csv`
- `output/caf_rescheduled_matches.csv`
- `output/unresolved_caf_postponements.csv`
- `output/phases/08_repair_feasible_slot_counts.csv`
- `output/phases/09_repair_solver_status.json`

---

## 10. Final Schedule and Validation

The final schedule is:

`accepted baseline matches + successfully repaired matches`

Queued matches that cannot be repaired remain in `output/unresolved_caf_postponements.csv`.

Final validation must check:

- fixture completeness,
- ordered pair count,
- unresolved postponement warning,
- no FIFA-date matches,
- daily match cap (`MAX_MATCHES_PER_DAY`),
- venue-slot conflicts,
- non-postponed global round order,
- CAF buffers,
- per-team rest gaps,
- per-team home/away streaks,
- rolling five-match balance warnings,
- team round inversions for non-postponed played sequence.

Validation outputs:

- `output/phases/10_final_validation_report.csv`
- `output/phases/10_team_sequence_validation.csv`

---

## 11. Output Files

### 11.1 Primary Outputs

| File | Purpose |
|---|---|
| `output/optimized_schedule_pre_caf.csv` | Full baseline schedule before CAF repair. |
| `output/caf_postponement_queue.csv` | CAF-violating matches removed from baseline and their repair status. |
| `output/caf_rescheduled_matches.csv` | Successfully repaired CAF-postponed matches. |
| `output/unresolved_caf_postponements.csv` | Queued matches that could not be placed. |
| `output/optimized_schedule.csv` | Final accepted schedule after repair. |
| `output/week_round_map.csv` | Round-to-calendar-week mapping. |
| `output/data_load_log.txt` | Data load and workbook summary. |

### 11.2 Final Schedule Columns

`output/optimized_schedule.csv` must include:

- `Round`
- `Calendar_Week_Num`
- `Day_ID`
- `Date`
- `Date_time`
- `Home_Team_ID`
- `Away_Team_ID`
- `Venue_Stadium_ID`
- `Travel_km`
- `Slot_tier`
- `Home_Tier`
- `Away_Tier`
- `Match_Tier`
- `Is_FIFA`
- `Is_CAF`
- `Postponed`
- `Postponement_Status`
- `Postponement_Reason`

### 11.3 Postponement Queue Columns

`output/caf_postponement_queue.csv` must include:

- `Round`
- `Home_Team_ID`
- `Away_Team_ID`
- `Date`
- `Date_time`
- `Day_ID`
- `Calendar_Week_Num`
- `Venue_Stadium_ID`
- `Violation_Reason`
- `Affected_Team_ID`
- `Conflicting_CAF_Match`
- `Conflicting_CAF_Date`
- `Conflict_Direction`
- `Repair_Feasible_Slot_Count`
- `Repair_Status`

### 11.4 Diagnostic Outputs

| File | Purpose |
|---|---|
| `output/phases/01_load_summary.json` | Workbook and row-count summary. |
| `output/phases/02_fifa_summary.csv` | FIFA dates detected from input data. |
| `output/phases/03_caf_blocker_summary.csv` | CAF blockers grouped by team/date. |
| `output/phases/03_round_windows.csv` | Selected baseline windows. |
| `output/phases/04_fixture_framework.csv` | Generated DRR fixture framework. |
| `output/phases/04_home_away_patterns.csv` | Per-team H/A sequence diagnostics. |
| `output/phases/05_baseline_feasible_slot_counts.csv` | Baseline feasible slot count per match. |
| `output/phases/06_baseline_solver_status.json` | CP-SAT solver result. |
| `output/phases/07_caf_audit.csv` | CAF audit details. |
| `output/phases/08_repair_feasible_slot_counts.csv` | Repair feasible slot counts. |
| `output/phases/09_repair_solver_status.json` | Repair status summary. |
| `output/phases/10_final_validation_report.csv` | Final validation findings. |
| `output/phases/10_team_sequence_validation.csv` | Team sequence validation details. |

---

## 12. Streamlit UI Requirements

The UI must be an operational schedule workspace using the Nile League dark theme:

- dark surface based on `#232126`,
- text color based on `#f8f9f7`,
- purple accent palette based on `#68239e`, `#75409f`, `#8f67ad`, `#ab97ba`, and `#d2cad9`,
- `Nile_League.png` as the page icon and visible brand mark when available,
- club icons from `icons/` normalized to 500x500 PNG assets and mapped deterministically to `Team_ID`,
- active tab indicator is a thin underline only,
- app opens on Explore first,
- Explore opens on Team chooser first.

### 12.1 Top-Level Tabs

Top-level tab order:

1. `Explore`
2. `Run & progress`
3. `Artifacts`
4. `Browse files`

### 12.2 Explore Tab

Explore controls:

- schedule source selector: final schedule, baseline pre-CAF, repaired matches,
- round filter selector: all rounds or Round 1 through Round 34,
- toggle to load authoritative inputs for explanations.

Explore sub-tabs:

1. `Team chooser`
2. `Team vs Team`
3. `Travel stats`
4. `Calendar`
5. `Round filter`

Team chooser:

- select a team,
- show the selected club icon,
- include/exclude home and away matches,
- sort by date or round,
- table of filtered matches,
- CSV download.

Team vs Team:

- select Team A and Team B,
- show both selected club icons,
- show both directions of head-to-head matches,
- CSV download.

Travel stats:

- aggregate `Travel_km` by `Away_Team_ID`,
- include a club icon column,
- show league total travel km,
- show average per team,
- show highest-travel team,
- show away trips counted,
- bar chart of total team km,
- detailed table with total, average, longest trip, and trip count,
- CSV download.

Calendar:

- real month grid with one square per day,
- previous/next month buttons,
- jump-to-month and year controls,
- selected-day inspector,
- each match day shows match labels such as `R1 AHL vs ZAM` with club icons,
- days without selected matches explain why: FIFA, CAF blocked, no playable slot, no selected-round match, or no match,
- month metrics: total matches, match days, FIFA days, CAF dates, slot-days with no matches,
- compact count table,
- busiest dates,
- matches by weekday chart,
- daily status table.

Round filter:

- when all rounds are selected, show match count per round,
- when one round is selected, show only that round's matches.

### 12.3 Run & Progress Tab

The UI must:

- show phase status for load, fixture generation, domain build, baseline solve, CAF audit, CAF repair, and output writing,
- show CAF repair only when audit returns violations; otherwise show a skipped message,
- mirror stdout in a live text area,
- apply sidebar model variables before running,
- write all primary and validation outputs after a successful run,
- report infeasible baseline status clearly.

### 12.4 Artifacts and Browse Files

Artifacts:

- list primary output files,
- list phase diagnostics,
- preview key tables,
- provide download buttons.

Browse files:

- browse any file under `output/` and `output/phases/`,
- show CSVs as dataframes,
- show JSON as structured JSON,
- show text files in text areas.

---

## 13. Acceptance Criteria

1. The model uses only `data/Data_Model.xlsx` and `data/expanded_calendar.xlsx` as authoritative inputs.
2. Fixture generation produces a complete 18-team, 34-round double round-robin framework.
3. Each team has valid home/away pattern diagnostics before slot assignment.
4. Dynamic round windows are selected from non-FIFA playable slots.
5. Baseline scheduling creates a complete pre-CAF schedule or clearly reports infeasibility.
6. No scheduled league match appears on a FIFA date.
7. Baseline and repair enforce `MAX_MATCHES_PER_DAY`; default cap is 3.
8. Baseline enforces `MAX_MATCHES_PER_SLOT`.
9. Repair uses only empty slot rows.
10. Team same-day, rest-day, and venue-slot constraints are respected.
11. Known CAF conflicts are audited after baseline.
12. CAF-violating matches are written to the postponement queue.
13. Repair keeps original `Round` metadata and sets repaired matches as postponed in final output.
14. Unrepairable matches are written to unresolved output, not silently dropped.
15. Final validation reports FIFA, CAF, daily cap, venue, rest, streak, completeness, and round-order issues.
16. UI exposes all tunable variables, including max matches per day.
17. UI defaults to Explore -> Team chooser.
18. UI uses the Nile League dark palette and icon.
19. Club icons are normalized to 500x500 and mapped to every current workbook team.
20. The calendar grid shows matches, club icons, and no-match reasons per day.
21. Travel stats visualize total season kilometers by team with club icons.

---

## 14. Non-Goals

- Generating CAF fixtures.
- Editing FIFA dates.
- Pulling live sports, travel, or venue data from the web.
- Treating previous outputs as model inputs.
- Manually inventing teams, stadiums, distances, slots, or security rules.
- Guaranteeing that every queued CAF match can be repaired.

---

## 15. Known Implementation Notes

- `MAX_MATCHES_PER_DAY` is a hard cap in both baseline and repair.
- Repair currently uses a deterministic greedy multi-pass search, not a second CP-SAT optimization.
- `REPAIR_SOLVER_TIME_LIMIT_S`, `SOFT_MAX_MATCHES_PER_WEEK`, and `W_TIER_MISMATCH` are imported in the repair module for configuration continuity, even though current repair placement is greedy.
- Baseline weekly hard minimum is documented as configurable, but current baseline handles small week fragments through soft balancing.
- The UI patches constants in imported modules at runtime. It does not rewrite `src/constants.py` during a UI run.
