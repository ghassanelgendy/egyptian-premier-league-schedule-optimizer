# Product Requirements Document (PRD)

## Egyptian Premier League Schedule Optimizer - CAF-Repair Design

**Version:** 2.2  
**Status:** Product and model requirements. This document intentionally describes the required algorithm; implementation may lag behind it.  
**Authoritative inputs:** `data/Data_Model.xlsx` and `data/expanded_calendar.xlsx` only.

---

## 1. Purpose

Build a reproducible scheduling pipeline that creates a full Egyptian Premier League double round-robin timetable from the two committed Excel workbooks only.

The required algorithm is now a two-stage flow:

1. **Baseline scheduling without CAF blockers:** generate a complete feasible league schedule while ignoring CAF blockers completely. FIFA days are never allowed.
2. **CAF audit and repair:** after the baseline table exists, identify matches that violate CAF-aware rules, move them to a separate postponement queue/file, and try to reschedule those postponed matches into free slots that satisfy all hard constraints plus CAF buffers.

The intent is to avoid letting CAF blockers make the core league timetable infeasible too early, while still producing a final CAF-aware schedule whenever free slots exist.

---

## 2. Authoritative Inputs

The system must use only these two files:

| File | Required use |
|---|---|
| `data/Data_Model.xlsx` | Teams, stadiums, distance matrix, and security/forced-venue rules. |
| `data/expanded_calendar.xlsx` | Slot universe, FIFA days, CAF dates/blockers, Ramadan/calendar flags. |

The system must not load `data/Sources/*`, past-season CSVs, generated CSV mirrors, previous `output/*` artifacts, scraped files, or any external data source as model input.

The loader must fail fast if either workbook is missing, unreadable, or missing required sheets/columns. A run log must record both workbook paths, sheet names used, and row counts.

### 2.1 `data/Data_Model.xlsx`

Required sheets:

| Sheet | Required columns |
|---|---|
| `team_data` | `Team_ID`, `Team_Name`, `Gov_ID`, `Gov_Name`, `Home_Stadium_ID`, `Alt_Stadium_ID`, `Tier`, `Cont_Flag` |
| `Stadiums` | `Stadium_ID`, `Stadium_Name`, `Gov_ID`, `City`, `Is_Floodlit` |
| `dist_Matrix` | `Origin` plus one column per stadium ID |
| `Sec_Matrix` | `home_team_ID`, `away_team_ID`, `banned_venue1_ID`, `banned_venue2_ID`, `forced_venue_ID` |

Normalization requirements:

- Team IDs and stadium IDs are stripped and uppercased.
- Stadium aliases may be normalized only through deterministic in-code mappings.
- `Cont_Flag` values identify CAF participants. Expected CAF values are `CL` and `CC`; blanks mean the team is not currently CAF-participating.
- `forced_venue_ID` overrides the home stadium for the listed home/away fixture when provided.

### 2.2 `data/expanded_calendar.xlsx`

Required sheets:

| Sheet | Required use |
|---|---|
| `expanded_calendar` | Primary slot universe. This sheet contains actual playable slot rows and must provide `Day_ID`, `Date`, `Date time`, `Week_Num`, `Day_name`, `Is_FIFA`, `Is_CAF`, `Is_Ramadan`, and CAF/FIFA label columns when present. |
| `expanded _calendar_table` | Secondary expanded calendar table. It may be used for validation or fallback only if it can be normalized to the same slot schema. |
| `FIFA_DAYS1` | Authoritative FIFA-date expansion. |
| `cont_blockers_updated1` | Authoritative team-specific CAF blocker expansion. |
| `unique_CAF_dates` | CAF date list used to cross-check or supplement team-specific CAF blockers. |

The exact sheet name `expanded _calendar_table` includes a space before `_calendar_table`; implementations must handle that actual workbook name.

### 2.3 FIFA Day Definition

FIFA days are the union of:

- dates where slot rows have `Is_FIFA == 1`,
- dates listed in `FIFA_DAYS1.Date`,
- dates with non-empty FIFA labels such as `FIFA_DAY` or `FIFA_DAYS` in calendar sheets.

No league match may be scheduled on a FIFA day in any phase, including baseline scheduling, CAF repair, diagnostics, or fallback output.

### 2.4 CAF Blocker Definition

CAF blockers are derived only from `expanded_calendar.xlsx`:

- team-specific CAF rows in `cont_blockers_updated1`,
- team/date rows in `unique_CAF_dates`,
- CAF labels and `Is_CAF` flags in the slot universe when useful for diagnostics.

CAF blockers are deliberately ignored in the baseline scheduling phase. They are applied only in the CAF audit and repair phase.

---

## 3. Required Outputs

All outputs are generated artifacts and must never be read back as model inputs.

| File | Required contents |
|---|---|
| `output/optimized_schedule_pre_caf.csv` | Full baseline league schedule created while ignoring CAF blockers. Must contain every league fixture exactly once and zero FIFA-day matches. |
| `output/caf_postponement_queue.csv` | Matches removed from the baseline schedule because they violate CAF-aware rules or become invalid under the CAF-aware hard-constraint audit. |
| `output/caf_rescheduled_matches.csv` | Queue matches successfully placed into free CAF-safe slots. Empty file is acceptable if no queued match can be repaired. |
| `output/unresolved_caf_postponements.csv` | Queue matches that could not be placed in any free CAF-safe slot. |
| `output/optimized_schedule.csv` | Final accepted schedule: baseline schedule minus queued violations plus successfully repaired matches. |
| `output/week_round_map.csv` | Mapping from abstract round number to selected calendar week. |
| `output/data_load_log.txt` | Workbook/sheet row counts, validation messages, and run outcome. |

### 3.1 Final Schedule Columns

`output/optimized_schedule.csv` must include at minimum:

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

`Postponed` is `True` for matches that were removed during CAF audit and later repaired. It remains `True` even after successful rescheduling, because the match moved from its baseline slot.

### 3.2 Queue File Columns

`output/caf_postponement_queue.csv` must include:

- fixture identifiers: `Round`, `Home_Team_ID`, `Away_Team_ID`,
- original/baseline slot fields: `Date`, `Date_time`, `Day_ID`, `Calendar_Week_Num`,
- `Venue_Stadium_ID`,
- `Violation_Reason`: human-readable description of why the match was postponed,
- `Affected_Team_ID`: the team whose CAF conflict caused the postponement,
- `Conflicting_CAF_Match`: identifier or description of the specific CAF fixture that caused the conflict (e.g. opponent name and competition),
- `Conflicting_CAF_Date`: the exact date of the CAF match that triggered the buffer violation,
- `Conflict_Direction`: `PRE` if the league match was too close before the CAF match, `POST` if too close after, `SAME_DAY` if on the CAF blocker date itself,
- `Repair_Feasible_Slot_Count`: number of free CAF-safe slots available for this match at audit time,
- `Repair_Status`: one of `REPAIRED`, `UNRESOLVED`, or `PENDING`.

---

## 4. Scheduling Method

### 4.1 Fixture Generation

The league format is a double round-robin:

- 18 teams.
- 34 rounds.
- Each unordered pair plays twice.
- Each ordered pair, home vs away, appears exactly once.
- In the abstract fixture framework, each team is assigned to exactly one match per round. This is the nominal ordering only.

**The DRR fixture draw is random.** In real-life Egyptian Premier League operations the fixture pairs and home/away assignments are determined by a random draw. The model must replicate this: fixture pairing and home/away assignment within the DRR framework are produced by a seeded random process, not by an optimizer. Any valid DRR arrangement that satisfies the completeness rules above is acceptable as a fixture framework; the system must not prefer one arrangement over another based on soft objectives at this stage.

**A team is not required to have a league match played in every calendar round.** If a match is postponed to the CAF repair queue, the team's calendar slot for that round remains empty until the match is rescheduled. The abstract round number on a repaired match records its original round position; the calendar date it is eventually played may fall inside a different week or round window.

The governing scheduling constraint is always the rest-day rule, not strict round-by-round attendance. A team that misses a calendar round due to a CAF conflict must still satisfy all rest-day rules relative to its previous and next scheduled league matches.

### 4.2 Baseline Slot Assignment - CAF Ignored

The baseline assignment creates `output/optimized_schedule_pre_caf.csv`.

CAF rules must not be applied in this phase:

- do not exclude `Is_CAF` slot rows,
- do not exclude `cont_blockers_updated1` rows,
- do not exclude `unique_CAF_dates`,
- do not apply CAF-specific team buffers.

FIFA rules must always be applied:

- no slot on a FIFA day may be used,
- no fallback may insert a league match on a FIFA day,
- any schedule containing a FIFA-day match is invalid.

### 4.3 Baseline Hard Constraints

The baseline schedule must satisfy these hard constraints:

| ID | Constraint |
|---|---|
| H1 | Every league fixture is scheduled exactly once. |
| H2 | No league match is scheduled on a FIFA day. |
| H4 | A team cannot play more than one league match in the same slot or on the same calendar date. |
| H5 | A venue cannot host more than one league match in the same slot. |
| H6 | A slot must not exceed the configured league capacity. For the CAF repair phase, "free slot" means zero accepted league matches already assigned to that slot. |
| H7 | Each team must have at least three full calendar days of rest between any two consecutively played league matches. Equivalently, two consecutive played league match dates for the same team must be at least four calendar days apart. This gap is measured across actual played dates only; a team that skips a calendar round due to a CAF postponement is still bound by this rule between its previous and next played league match. |
| H7-CAF | For a CAF-participating team (`Cont_Flag` of `CL` or `CC`), a league match must be separated from any CAF match by at least four full calendar days in **either direction** — before the CAF match and after the CAF match. Equivalently, the league match date and the CAF match date must be at least five calendar days apart. The preferred buffer is five full rest days (six calendar days apart) where slots allow. |
| H8 | In played chronological order, a team cannot have more than two consecutive home matches or more than two consecutive away matches. |
| H9 | A fixture must use the forced venue from `Sec_Matrix` when provided; otherwise it uses the home team's `Home_Stadium_ID`. |

**Round attendance is not a hard constraint.** A team is not required to have a match played in every calendar round. If a match is moved to the CAF postponement queue, that team's calendar slot for that round is empty. The abstract round number is retained as metadata on the postponed fixture and used to measure week-movement penalty during repair.

If a full baseline schedule cannot be produced while ignoring CAF blockers, the run is infeasible and must report the reason. The system must not invent teams, slots, dates, venues, distances, or fixtures.

### 4.4 Baseline Soft Objectives

The baseline optimization should minimize a scalar objective after hard feasibility:

1. Home/away streak pressure and imbalance.
2. Travel distance.
3. Tier mismatch between match quality and slot quality.
4. Top-tier matches away from strong weekend/night slots.
5. Overuse of high-demand slots, if capacity greater than one is allowed.
6. Round/week movement penalties, if postponement domains are used before CAF repair.

Hard feasibility always outranks soft preferences.

---

## 5. CAF Audit

After the baseline schedule is complete, the system must run a CAF-aware audit.

A baseline match must be moved to `output/caf_postponement_queue.csv` if any of the following is true:

1. The match is on a team-specific CAF blocker date for either participant.
2. Either participant has `Cont_Flag` of `CL` or `CC` and the league match is too close before that team's CAF match.
3. The match would break the final hard constraints after CAF blockers are treated as protected team activity.

### 5.1 CAF Buffer Rule

For a team participating in CAF (`Cont_Flag` in `CL`, `CC`), the buffer applies **in both directions** around each CAF match:

- No league match may be scheduled on the same date as that team's CAF match.
- No league match may be scheduled within four full calendar days **before** the CAF match. The league match date and the CAF match date must be at least five calendar days apart. The preferred gap is five full rest days (six days apart) where slots allow.
- No league match may be scheduled within four full calendar days **after** the CAF match. The same five-day minimum (six-day preferred) applies going forward.

**Pre-CAF example:** if a CAF match is on Saturday, the latest acceptable prior league match is Monday. Tuesday, Wednesday, Thursday, Friday, and Saturday are not acceptable (five-day minimum gap; Monday → Saturday = 5 days apart, 4 full rest days).

**Post-CAF example:** if a CAF match is on Saturday, the earliest acceptable next league match is Thursday of the following week (Saturday → Thursday = 5 days apart, 4 full rest days). Friday or later of the following week is preferred (6 days apart, 5 full rest days).

The rationale is that CAF travel and match intensity require more recovery than a domestic league match. The local-to-local rest rule is three full rest days (four days apart); the CAF buffer is four full rest days minimum (five days apart), with five full rest days (six days apart) as the target.

### 5.2 Queue Semantics

Queued matches are removed from the accepted schedule before repair begins. The remaining schedule must still satisfy all baseline hard constraints and must contain no FIFA-day matches.

The queue is not a failure by itself. It is the set of matches requiring CAF-safe reinsertion.

---

## 6. CAF Repair

The repair phase tries to place each queued match into a free slot.

### 6.1 Free Slot Definition

A free slot is a row from the slot universe where:

- no accepted league match is already assigned to that exact slot row,
- the date is not a FIFA day,
- the slot date is inside the accepted season calendar,
- the slot has a valid `Date`, `Date time`, `Day_ID`, and `Week_Num`.

CAF repair must not use a slot that is merely under capacity if another match already occupies it. For repaired matches, "free" means no accepted league match in that slot.

### 6.2 Repair Feasibility Rules

A queued match may be inserted into a free slot only if all of these hold:

| Rule | Requirement |
|---|---|
| R1 | The slot is not on a FIFA day. |
| R2 | Neither team has another accepted league match on the same date. |
| R3 | Both teams have at least three full calendar days of relaxation from every other accepted league match. Date gaps must be at least four calendar days. |
| R4 | The venue has no accepted league match in the same slot. |
| R5 | Inserting the match does not create more than two consecutive home or away matches for either team in chronological played order. |
| R6 | For CAF-participating teams, the inserted date is not a CAF blocker date and is at least five calendar days away from any relevant CAF match in either direction — before an upcoming CAF match and after a preceding CAF match. Six calendar days apart is preferred where available. |
| R7 | The match uses the same venue rule as the baseline schedule: forced venue first, otherwise home stadium. |

### 6.3 Repair Objective

The repair objective should:

1. maximize the number of queued matches successfully repaired,
2. minimize movement away from the original round/week,
3. preserve home/away streak quality,
4. prefer better slot tiers for better matches,
5. avoid unnecessary travel or venue disruption.

If no CAF-safe free slot exists for a queued match, the match remains in `output/unresolved_caf_postponements.csv`.

---

## 7. Slot and Match Tiers

### 7.1 Slot Tier

Slot tier is derived from day and kickoff time:

- weekend/night slots are best,
- weekday or early slots are lower priority,
- the exact tiering function must be deterministic and documented in code.

### 7.2 Match Tier

`Match_Tier` is derived from the two teams' `Tier` values:

| Teams | Match_Tier |
|---|---|
| 1 vs 1 | 1 |
| 1 vs 2 | 1 |
| 1 vs 3 | 2 |
| 2 vs 2 | 2 |
| 2 vs 3 | 3 |
| 3 vs 3 | 3 |

Tier 1 is the highest-priority match tier.

---

## 8. Diagnostics and Audit Artifacts

The pipeline should write machine-readable diagnostics under `output/phases/` when enabled:

| File | Description |
|---|---|
| `01_load_summary.json` | Workbook names, sheet names, row counts, team count, slot count. |
| `02_fifa_summary.csv` | FIFA dates derived from all in-workbook FIFA sources. |
| `03_caf_blocker_summary.csv` | CAF blocker dates by team from in-workbook CAF sheets. |
| `04_fixture_framework.csv` | Generated DRR fixture list before slot assignment. |
| `05_baseline_feasible_slot_counts.csv` | Feasible slot count per match while CAF is ignored. |
| `06_baseline_solver_status.json` | Baseline feasibility/optimization status. |
| `07_caf_audit.csv` | Per-match CAF audit outcome and violation reasons. |
| `08_repair_feasible_slot_counts.csv` | Free CAF-safe slot counts for queued matches. |
| `09_repair_solver_status.json` | CAF repair status and unresolved count. |

---

## 9. Acceptance Criteria

1. The requirements and implementation use `data/Data_Model.xlsx` and `data/expanded_calendar.xlsx` only as model inputs.
2. The baseline schedule contains every double round-robin fixture exactly once.
3. No baseline, repaired, final, or unresolved output contains a scheduled league match on a FIFA day.
4. CAF blockers do not restrict baseline scheduling.
5. CAF violations are identified only after the baseline table exists.
6. Every CAF-violating match is written to `output/caf_postponement_queue.csv`.
7. Repaired matches are placed only in free slots and satisfy the three-full-day (four calendar days apart) league-to-league rest rule.
8. Repaired matches involving CAF teams are at least five calendar days away from any relevant CAF match in either direction (before and after).
9. `output/optimized_schedule.csv` contains the final accepted schedule and preserves `Postponed`/reason fields for repaired matches.
10. If a queued match cannot be repaired, it is written to `output/unresolved_caf_postponements.csv` instead of being silently dropped.
11. A team's absence from one or more calendar rounds due to CAF postponement is not treated as a schedule error. Round attendance is validated only at the fixture-completeness level (all 34 rounds worth of fixtures must eventually be played or remain in the unresolved queue), not at the per-round per-team level.

---

## 10. Non-Goals

- Using external files or scraped sources outside the two authoritative workbooks.
- Scheduling league matches on FIFA days under any circumstance.
- Generating or modifying CAF fixtures.
- Generating or modifying FIFA dates.
- Inventing missing teams, dates, stadiums, security rules, or distances.
- Treating previous output files as input data.

