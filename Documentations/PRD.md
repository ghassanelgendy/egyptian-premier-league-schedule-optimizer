# Product Requirements Document (PRD)

## Egyptian Premier League Schedule Optimizer

**Version:** 3.3
**Status:** Full product and model requirements for the current Streamlit application, validation dashboard, and CAF-aware scheduling pipeline.
**Last updated:** 2026-05-17
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
- inspect validation, feasibility, fairness, CAF-repair, Monte Carlo, and historical benchmark dashboards,
- browse and download generated artifacts.

The product also supports optional offline analysis modes:

- batch Monte Carlo seed sweeps from the CLI,
- historical benchmark analysis over normalized past-season datasets,
- cached comparison of the current optimized schedule against historical seasons inside the UI.

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
- past-season datasets for optimization decisions,
- scraped files,
- web data,
- manually edited fixture outputs.

Generated outputs are inspection artifacts only. They may be displayed or downloaded by the UI, but they must never drive a new solver run.

Normalized past-season CSVs, historical FIFA/CAF context files, and `dist_matrix.json` may be used only by historical benchmark tooling and analysis scripts. They must never change the optimization model's feasible region or objective inputs.

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
- dates listed in a sheet containing `FIFA_DAYS` in its name (e.g., `FIFA_DAYS1`),
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
| `MIN_DAYS_BETWEEN_ROUNDS` | 1 | Gap between rounds. 1 forbids same-day overlap; 2 adds one idle day between rounds. |

### 4.3 Capacity Rules

| Variable | Default | Meaning |
|---|---:|---|
| `HARD_MIN_MATCHES_PER_WEEK` | 6 | Hard lower week target retained for model configuration. |
| `HARD_MAX_MATCHES_PER_WEEK` | 18 | Hard cap on league matches in a calendar week. |
| `SOFT_MIN_MATCHES_PER_WEEK` | 6 | Soft lower target for weekly load balance. |
| `SOFT_MAX_MATCHES_PER_WEEK` | 12 | Soft upper target for weekly load balance. |
| `MAX_MATCHES_PER_DAY` | 3 | Hard cap on league matches scheduled on one calendar date. |
| `MAX_MATCHES_PER_SLOT` | 2 | Hard cap on league matches assigned to the same kickoff slot. |
| `MIN_STADIUM_SERVICE_GAP_DAYS` | 0 | Service gap between non-forced uses of the same stadium. |

### 4.4 Objective Weights

| Variable | Default | Meaning |
|---|---:|---|
| `W_STADIUM_MAINTENANCE_OVERLAP` | 5,000,000 | Penalty for back-to-back stadium use within service gap. |
| `ALT_STADIUM_RELIEF_PENALTY` | 1,000,000 | Base penalty for using alternate stadium (multiplied by team tier). |
| `OTHER_STADIUM_RELIEF_PENALTY` | 3,000,000 | Base penalty for using a non-home, non-alt fallback stadium (multiplied by team tier). |
| `W_HOME_VENUE_DISPLACEMENT` | 1 | Per-kilometer penalty for moving a home team away from its primary stadium. |
| `W_ROUND_ORDER` | 100 | Penalty for deviation from nominal round/week placement. |
| `W_WEEK_UNDERLOAD` | 50 | Penalty below soft weekly load target. |
| `W_WEEK_OVERLOAD` | 50 | Penalty above soft weekly load target. |
| `W_TRAVEL` | 1 | Per-kilometer travel penalty. |
| `W_TIER_MISMATCH` | 20 | Penalty for mismatch between match tier and slot tier. |
| `W_CAF_PREFERRED` | 10 | Preferred CAF rest weight. |

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
- Non-final rounds start from rolling 5-day base windows.
- Round 34 uses a tail domain: every playable slot from the start of its selected final-round window through the end of the season.
- A candidate window must contain enough slot rows for a round.
- CAF-heavy windows where CAF teams have no CAF-safe slot are skipped.
- Selected windows must be chronological and non-overlapping.
- Exactly `NUM_ROUNDS` baseline windows are required.
- The active non-final-round policy may widen a pressured round window after initial selection:
  - `compact`: expand day-by-day up to 28 days when the round has too few slot rows or one of its matches has too few feasible slots.
  - `epl_relaxed`: expand day-by-day up to 56 days and keep widening until the round reaches a 56-day spillover target or feasibility pressure is relieved.
  - `epl_full`: spill every non-final round from its selected start date through the end of the season.
- The round-window artifact must reflect the effective policy-adjusted start/end dates that were actually used to build domains.

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
| H3 | Baseline match domains are restricted to their selected round window. For Round 34, the selected window is the final-round tail domain. |
| H4 | A team cannot play more than one league match on the same calendar date. |
| H5 | A venue cannot host more than one match in the same slot. |
| H6 | A kickoff slot cannot exceed `MAX_MATCHES_PER_SLOT`, except on the chosen Round 34 shared slot where the special final-round slot cap applies. |
| H7 | A calendar date cannot exceed `MAX_MATCHES_PER_DAY` league matches, except on the chosen Round 34 date where the special final-round day cap applies. |
| H8 | A team must have at least `MIN_REST_DAYS_LOCAL` full rest days between league matches. |
| H9 | Non-postponed baseline rounds must respect the minimum gap: Round `R+1` must start at least `MIN_DAYS_BETWEEN_ROUNDS` calendar days after Round `R` ends. |
| H10 | Forced venue rules from `Sec_Matrix` must be respected in the strict baseline model. |
| H11 | CAF teams must avoid known CAF dates and the hard CAF buffer when feasible inside the round window. |
| H12 | All Round 34 matches must share exactly one calendar date and one kickoff slot. |

If CAF-safe slots do not exist inside a strict round window for a match, the domain builder may relax the CAF filter for that match so the baseline remains complete. Such matches must then be caught by CAF audit and moved to the postponement queue.

### 7.1.1 Final Round Publication Rule

The current product enforces a one-slot final round for `Round 34` only.

- The rule applies to the final published schedule, not just the pre-CAF baseline.
- The solver must not create synthetic dates or synthetic kickoff slots.
- Every Round 34 match must use one shared real slot from the Round 34 tail domain, so the whole round kicks off simultaneously.
- The only global constraints that may be relaxed for the final round are:
  - same-date match count,
  - same-kickoff match count on the chosen shared slot.
- Venue-slot exclusivity remains hard, so the same stadium still cannot host two matches in the same slot.
- If the strict full-season model cannot satisfy the Round 34 shared-slot rule together with the normal last-round venue, tier, rest, CAF, and round-gap rules, it must trigger the dedicated Round 34 rescue model before escalating to a looser non-final domain policy.

### 7.1.2 Final Round Rescue Model

When the strict baseline solve is infeasible and Round 34 exists, the baseline phase must retry within the same domain attempt using a dedicated last-round rescue model.

Rescue sequence:

1. Solve Rounds 1-33 under the current domain policy with normal strict baseline rules.
2. Freeze that partial schedule.
3. Solve Round 34 as one shared-slot batch over the real Round 34 tail window.

Round 34 rescue hard rules:

- banned venues from `Sec_Matrix` remain banned,
- one real shared slot must be chosen for all Round 34 matches,
- one team cannot play two league matches on the same calendar date,
- one venue cannot host two matches in the same shared slot,
- the special Round 34 day cap and Round 34 slot cap still apply.

Round 34 rescue soft relaxations:

- forced venue requirement,
- Tier 1 shared-slot requirement,
- local league rest gap,
- CAF date/buffer proximity,
- Round 33 to Round 34 gap,
- weekly hard cap,
- non-forced stadium service gap.

Optimization priority inside the rescue model:

1. Keep the round feasible without using banned venues or splitting the shared slot.
2. Minimize the number and severity of Round 34-only rule relaxations.
3. Protect higher-tier matches at better venues first.
4. Then minimize travel, tier mismatch, and round-drift cost.

### 7.1.3 Final Round Venue Fallback

The simultaneous Round 34 slot can create stadium contention when multiple home teams share the same `Home_Stadium_ID` and `Alt_Stadium_ID`.

For Round 34 rescue assignments, the solver must consider venue candidates in this preference order:

1. primary home stadium
2. alternate home stadium
3. nearest other free stadium from `Stadiums`

Rules:

- in the strict baseline model, forced venues still override every fallback rule,
- in the Round 34 rescue model only, forced venue becomes a top preference rather than a hard requirement,
- the fallback search is restricted to Round 34 only; it is not a global all-round venue-relaxation rule,
- "nearest" is measured from the home team's primary stadium using the stadium distance matrix,
- banned venues from `Sec_Matrix` remain disallowed,
- if multiple home teams contend for the same primary and alternate venues in Round 34, the objective must prefer keeping the higher-tier match at the primary venue, then the next-best match at the alternate venue, and only then displace the lower-tier match to the nearest other free stadium,
- if venue choices are otherwise indifferent, the solver must prefer the option with the better total optimization score.

### 7.1.4 Baseline Domain Fallback Strategy

The baseline pipeline must retry infeasible solves with progressively looser non-final round policies:

1. `compact`
2. `epl_relaxed`
3. `epl_full`

Rules:

- the first solve may reuse already-built compact domains,
- within each domain attempt, the strict baseline model runs first and the Round 34 rescue model runs second if strict Round 34 rules make the attempt infeasible,
- each later attempt must rebuild domains under the looser policy,
- the pipeline must stop retrying as soon as one policy returns a feasible baseline,
- if all three policies fail, the baseline phase must report infeasibility and stop before CAF audit/repair.

`output/phases/06_baseline_solver_status.json` must retain normal solver metadata and, when the retry wrapper is used, add:

- `domain_policy`
- `domain_attempt`
- `domain_attempt_count`
- `domain_fallback_used`
- `solver_mode`
- `final_round_rescue_attempted`
- `final_round_rescue_used`
- `strict_attempt`
- `final_round_rescue_candidate_slot_count`
- `final_round_rescue_relaxations`

### 7.2 Baseline Soft Objectives

The baseline objective minimizes the following (higher weights = higher priority):

| Objective | Logic | Weight (Penalty) |
|---|---|---|
| **ALT_STADIUM_DISPLACEMENT** | Penalty for moving a team to its `Alt_Stadium_ID`. Scales by team tier (Tier 1: 10M, Tier 2: 5M, Tier 3: 2M, Tier 4: 1M). | 1,000,000 * Tier_Weight |
| **OTHER_STADIUM_DISPLACEMENT** | Penalty for moving a team to a non-home, non-alt fallback stadium. Scales by team tier. | 3,000,000 * Tier_Weight |
| **HOME_VENUE_DISPLACEMENT** | Penalty per km between the primary home stadium and the assigned fallback venue. | 1 per km |
| **STADIUM_MAINTENANCE** | Avoid scheduling matches at the same venue within `MIN_STADIUM_SERVICE_GAP_DAYS`. | 5,000,000 per overlap |
| **ROUND_ORDER** | Penalty per match shifted from its nominal week. | 100 per week-diff |
| **WEEK_LOAD** | Penalty per match above/below soft week caps. | 50 per match |
| **TRAVEL** | Penalty per km traveled by the away team. | 1 per km |
| **TIER_MISMATCH** | Penalty for placing a Tier-X match in a Tier-Y slot. | 20 * |X-Y| |

#### 7.2.1 Tiered Venue Priority Resolution
To prevent lower-tier matches from indiscriminately displacing higher-tier teams from their primary stadiums, the venue-displacement penalties are tier-weighted.

**Conflict Scenarios:**
- **Tier 1 vs. Tier 3 Clash:** Displacing Tier 3 costs 2M. Accepting a maintenance overlap costs 5M. The solver will displace the Tier 3 team.
- **Tier 1 vs. Tier 1 Clash:** Displacing Tier 1 costs 10M. Accepting a maintenance overlap costs 5M. The solver will allow the back-to-back matches at the primary stadium (UEFA 48-hour style).
- **Round 34 Shared-Slot Clash (3 teams share one home and one alt venue):** The highest-tier match keeps the primary venue, the next-best match uses the alternate venue, and the lowest-tier match is displaced to the nearest other free stadium when feasible.

Hard feasibility always outranks soft preferences.

#### 7.2.2 Round 34 Rescue Penalty Layers

When the dedicated Round 34 rescue model is active, it keeps the normal travel, round-order, tier-mismatch, alternate-venue, other-stadium, and home-displacement penalties, then adds higher-priority rescue penalties for:

- breaking a strict forced-venue assignment,
- assigning a Tier 1 derby to a non-Tier-1 slot,
- shortening local rest around Round 34,
- shortening CAF buffer around Round 34,
- shrinking the Round 33 -> Round 34 gap,
- overflowing the weekly hard cap,
- reusing a non-forced venue inside the stadium service gap.

These rescue penalties are applied only to Round 34 and only after the strict model has failed under the same domain attempt.

Output:

- `output/optimized_schedule_pre_caf.csv`
- `output/phases/05_baseline_feasible_slot_counts.csv`
- `output/phases/06_baseline_solver_status.json`

---

## 8. CAF Audit

After baseline solving, the system audits CAF constraints. 

### 8.1 Proactive Pruning vs. Safety Net Architecture
The system uses a two-tier defense against CAF conflicts:
1. **Tier 1: Proactive Pruning (Phase 3a):** The domain builder automatically removes CAF-conflicting slots from each match's options. If a valid baseline solution is found, it is usually 100% CAF-safe by design.
2. **Tier 2: Safety Net (Phase 4 & 5):** If a match has *no* CAF-safe slots within its strict 5-day round window, the domain builder "relaxes" the filter to allow a baseline solution. The **CAF Audit** is the safety net that catches these intentionally allowed violations and moves them to the **CAF Repair** phase for rescheduling.

**Note:** If the Audit reports "0 violations," it means the Proactive Pruning was successful and no matches required postponement.

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

The repair phase removes violating baseline matches from the accepted schedule and tries to reinsert queued matches into later valid slots. If any Round 34 match enters repair, the full final round must be treated as one shared-slot repair batch.

### 9.1 Free Slot Definition

For repair, a free slot means:

- the slot is in the usable non-FIFA slot universe,
- the slot date is on or after the original baseline match date,
- the slot still respects the applicable same-slot load cap,
- the venue is free in that slot,
- the slot has valid date, time, day ID, and week metadata.

Repair uses the same global day and slot caps as baseline, except that Round 34 may use the dedicated final-round caps on its chosen shared slot/date.

### 9.2 Repair Feasibility Rules

| Rule | Requirement |
|---|---|
| R1 | Slot is not a FIFA date. |
| R2 | Slot date is not before the original match date. |
| R3 | Date load is below the applicable daily cap. Default cap is `MAX_MATCHES_PER_DAY`; Round 34 may use the dedicated final-round day cap on its shared slot/date. |
| R4 | Neither team already has an accepted league match on the candidate date. |
| R5 | Both teams satisfy local league rest rules against all accepted matches. |
| R6 | Venue is free in the candidate slot, even when the slot still has capacity for other venues. |
| R7 | Inserting the match does not create a home/away streak violation. |
| R8 | CAF teams satisfy the hard CAF buffer in both directions. |
| R9 | Calendar week load is below `HARD_MAX_MATCHES_PER_WEEK`. |
| R10 | If `MIN_STADIUM_SERVICE_GAP_DAYS > 0`, non-forced repair candidates must respect the same stadium maintenance window. Repair may switch a non-forced match to the alternate stadium or, for Round 34, to the nearest other free stadium; forced venues remain exempt. |

### 9.3 Final Round Batch Repair

If any `Round 34` match is postponed into CAF repair:

- every Round 34 match is removed from the accepted published schedule and promoted into one repair batch,
- the repair search must choose one common replacement slot for the entire round,
- rest-day rules, CAF buffers, home/away streak rules, week caps, and venue-slot exclusivity remain hard,
- the shared replacement slot may use the final-round day cap and final-round same-kickoff cap,
- Round 34 venue reassignment follows the same priority order as baseline: primary home venue, alternate venue, then nearest other free stadium,
- if no common feasible slot exists, the repair phase must leave the full Round 34 batch unresolved,
- it must never repair only part of Round 34 onto another slot or date.

Repair strategy:

- Deduplicate CAF violations by match.
- Count feasible repair slots per queued match.
- Process most-constrained matches first.
- Rank candidate shared slots by displacement from the original date.
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
- Round 34 appears on exactly one calendar date and one kickoff slot in the final published schedule,
- daily match cap (`MAX_MATCHES_PER_DAY`) except on the valid Round 34 shared date,
- same-kickoff slot cap (`MAX_MATCHES_PER_SLOT`) except on the valid Round 34 shared slot,
- venue-slot conflicts,
- non-forced stadium maintenance gaps when enabled,
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

Notes:

- `output/phases/03_round_windows.csv` must record the effective round-window start, end, week span, and slot count after the active non-final policy is applied.
- `output/phases/05_baseline_feasible_slot_counts.csv` must record round-window bounds, slot counts, feasible slot counts, and whether CAF filtering was relaxed for a match.
- `output/phases/06_baseline_solver_status.json` must record solver status, objective, wall time, stadium-gap configuration, fallback-attempt metadata when fallback retries were used, and final-round rescue metadata when the dedicated Round 34 rescue model was attempted.

### 11.5 Optional Batch and Analysis Outputs

| File | Purpose |
|---|---|
| `output/multi_run/monte_carlo_results.csv` | Aggregated metrics for batch seed sweeps run via `python main.py --runs N [--parallel M]`. |

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
3. `Validate & Insights`
4. `Artifacts`
5. `Browse files`

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

- show phase status for load, fixture generation, initial compact domain build, baseline solve with EPL fallback retries, CAF audit, CAF repair, and output writing,
- when strict Round 34 rules fail, show that the run is retrying with the dedicated Round 34 rescue model before moving to the next non-final domain policy,
- show CAF repair only when audit returns violations; otherwise show a skipped message,
- mirror stdout in a live text area,
- apply sidebar model variables before running,
- write all primary and validation outputs after a successful run,
- report infeasible baseline status clearly after fallback retries are exhausted,
- surface the winning fallback domain policy when the baseline solves under `epl_relaxed` or `epl_full`.

### 12.4 Validate & Insights

The UI must provide a read-only analysis workspace that loads artifacts on demand and does not mutate solver outputs.

Sub-tabs:

1. `Overview`
2. `Constraint Compliance`
3. `Feasibility & Solver Pressure`
4. `CAF & Repair`
5. `Fairness & Operational Insights`
6. `Monte Carlo Analysis`
7. `Historical Comparison`

Requirements:

- `Overview` summarizes final schedule health, validation issue counts, solver statuses, unresolved postponements, season span, and other run-level metrics.
- `Constraint Compliance` groups validation findings by family and severity using final validation and sequence artifacts.
- `Feasibility & Solver Pressure` reads round-window and feasible-slot diagnostics to expose tight rounds, window span, and solver pressure.
- `CAF & Repair` summarizes audit findings, queue size, repaired matches, unresolved matches, and repair status.
- `Fairness & Operational Insights` shows travel spread, rest-gap spread, venue load share, round span, monthly match volume, and clickable detail tables.
- `Monte Carlo Analysis` reads `output/multi_run/monte_carlo_results.csv` when present and shows best seed, best objective, minimum validation errors, objective distribution, travel distribution, and raw run rows.
- `Historical Comparison` uses cached historical benchmark logic plus normalized past-season data to compare the optimized schedule against recent Egyptian Premier League seasons on waste-gap and home/away-streak metrics.
- The historical view must include a methodology/assumptions expander explaining the benchmark assumptions.
- If a required artifact is missing, each dashboard tab must show an informative empty state instead of failing.

### 12.5 Artifacts and Browse Files

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
4. Dynamic round windows are selected from non-FIFA playable slots and may expand under `compact`, `epl_relaxed`, or `epl_full` policy.
5. Baseline scheduling creates a complete pre-CAF schedule using either the strict model or the dedicated Round 34 rescue model, or clearly reports infeasibility after domain fallback retries are exhausted.
6. No scheduled league match appears on a FIFA date.
7. Baseline and repair enforce `MAX_MATCHES_PER_DAY` by default, but Round 34 may use the dedicated final-round day cap on its one valid shared slot/date.
8. Baseline and repair enforce `MAX_MATCHES_PER_SLOT` by default, but Round 34 may use the dedicated final-round slot cap on its one valid shared slot.
9. The published Round 34 schedule uses one real shared kickoff slot for all matches.
10. If Round 34 is repaired, the system repairs the full round as one batch on one common slot or leaves the batch unresolved.
11. When Round 34 venue contention occurs, the strict model uses forced venues when required, and the rescue model prefers primary home venue, then alternate venue, then the nearest other free stadium, with higher-tier matches protected first and banned venues always excluded.
12. Team same-day, rest-day, and venue-slot constraints are respected.
13. Known CAF conflicts are audited after baseline.
14. CAF-violating matches are written to the postponement queue.
15. Repair keeps original `Round` metadata and sets repaired matches as postponed in final output.
16. Unrepairable matches are written to unresolved output, not silently dropped.
17. Final validation reports FIFA, CAF, daily cap, venue, rest, streak, completeness, and round-order issues.
18. Final validation reports a hard error if the published Round 34 schedule spans more than one slot or date.
19. UI exposes all tunable variables, including max matches per day.
20. UI defaults to Explore -> Team chooser.
21. UI top-level tabs are `Explore`, `Run & progress`, `Validate & Insights`, `Artifacts`, and `Browse files`.
22. `Validate & Insights` contains overview, compliance, feasibility, CAF/repair, fairness, Monte Carlo, and historical benchmark views.
23. Baseline status output records the effective domain policy, whether fallback retries were used, and whether the dedicated Round 34 rescue model was attempted or used.
24. Monte Carlo analysis renders `output/multi_run/monte_carlo_results.csv` when present and otherwise instructs the user to run batch mode from the CLI.
25. Historical comparison uses normalized past-season benchmark files and cached analysis logic without feeding those datasets back into the optimizer.
26. UI uses the Nile League dark palette and icon.
27. Club icons are normalized to 500x500 and mapped to every current workbook team.
28. The calendar grid shows matches, club icons, and no-match reasons per day.
29. Travel stats visualize total season kilometers by team with club icons.

---

## 14. Non-Goals

- Generating CAF fixtures.
- Editing FIFA dates.
- Pulling live sports, travel, or venue data from the web.
- Treating previous outputs as model inputs.
- Manually inventing teams, stadiums, distances, slots, or security rules.
- Guaranteeing that every queued CAF match can be repaired.

---

## 15. Optional Analysis Modes

The repository includes analysis-only workflows that are outside the core optimization path but part of the current product surface:

- CLI Monte Carlo runs via `python main.py --runs N [--parallel M]`, which checkpoint aggregated results and restore final artifacts for the best-performing seed.
- Historical benchmark scripts `analyze_historical.py` and `analyze_historical_detailed.py`, which study travel and gap behavior in past Egyptian Premier League seasons.
- UI historical comparison backed by `src/historical_engine.py` and `dist_matrix.json`.

These workflows may read normalized historical files under `past seasons data/`, but they must not modify the core optimizer inputs or use historical data to relax or tighten scheduling constraints.

---

## 16. Dashboard Metrics Explained

| Metric | Meaning |
|---|---|
| `Validation issue count` | Count of non-pass rows in `10_final_validation_report.csv`, excluding the all-clear sentinel row. |
| `Away travel range` | Difference between the highest and lowest total away-travel distance across teams in the final schedule. |
| `Top 3 venue share` | Fraction of all scheduled matches hosted by the three busiest venues. |
| `Week span count` | Number of distinct calendar weeks touched by a round, derived from `output/week_round_map.csv`. |
| `Max rest gap` | Largest `Gap_Days_From_Previous` value observed in team-sequence validation output. |
| `Max Waste Gap` | Historical benchmark gap after subtracting FIFA dates and weighted CAF occupancy from idle time between matches. |
| `Best seed` | Monte Carlo winner selected by fewest validation errors, then fewest unresolved matches, then lowest baseline objective, then lowest travel. |

---

## 17. Recent Development Milestones (Last 5 Commits)

Newest to oldest:

- `2f646a2` - Added baseline fallback retries across `compact`, `epl_relaxed`, and `epl_full` policies; refactored round-window/domain construction; surfaced fallback status in runtime artifacts; expanded the Streamlit validation workspace with fairness, Monte Carlo, and improved historical benchmark views.
- `5bec1d0` - Enforced the one-day Round 34 publication rule across baseline solving, CAF repair, and final validation; introduced dedicated final-round caps and shared-date repair behavior.
- `b65ba3c` - Repository housekeeping in `.gitignore`; no product requirement change.
- `15176ad` - Normalized historical league CSVs to improve consistency of benchmark and audit tooling.
- `e7ac63a` - Added historical analysis scripts and `dist_matrix.json` to support reproducible travel/gap benchmarking against past seasons.
