# 🧠 Gemini Agent Skills Reference Guide
This document aggregates all development skills, custom instructions, and reference manuals used by the AI coding assistant for this project.

## Table of Contents
* [cp-sat-optimizer](#skill-cp-sat-optimizer)
* [pandas-data-wrangler](#skill-pandas-data-wrangler)
* [sports-scheduling-domain](#skill-sports-scheduling-domain)
* [streamlit-dashboard-builder](#skill-streamlit-dashboard-builder)

---

# Skill: cp-sat-optimizer
# cp-sat-optimizer

Specialized guidance for debugging and optimizing OR-Tools CP-SAT models in the EPL scheduling context.

## Instructions

- Use this skill when working with `src/baseline_solver.py` or any CP-SAT related code.
- Refer to `references/debugging.md` for infeasibility analysis.
- Ensure all hard constraints (H1-H12) are correctly modeled.
- Optimize for `W_ROUND_ORDER`, `W_WEEK_UNDERLOAD`, `W_WEEK_OVERLOAD`, `W_TRAVEL`, `W_TIER_MISMATCH`, and `W_CAF_PREFERRED`.

## Reference Files

- `references/debugging.md`: Common debugging steps for CP-SAT infeasibility.


## References for cp-sat-optimizer
### Reference: debugging.md
# CP-SAT Debugging Guide (EPL Context)

## Common Infeasibility Causes

Check if any of these hard constraints are overly restrictive:

- **H1**: Every fixture assigned exactly once.
- **H2**: No matches on FIFA dates (ensure `expanded_calendar.xlsx` has enough non-FIFA slots).
- **H3**: Round windows (check `output/phases/03_round_windows.csv` for overlap or gaps).
- **H4**: Team same-day play (max 1 match per team per day).
- **H5**: Venue-slot conflict (one match per slot per venue).
- **H6**: Slot capacity (`MAX_MATCHES_PER_SLOT`).
- **H7**: Day capacity (`MAX_MATCHES_PER_DAY`).
- **H8**: Local rest days (`MIN_REST_DAYS_LOCAL` = 3).
- **H9**: Global round order.
- **H10**: Forced venues (check `Sec_Matrix`).
- **H11**: CAF buffers (only in repair/audit, but baseline must avoid known blockers).
- **H12**: Stadium service gap (`MIN_STADIUM_SERVICE_GAP_DAYS`).

## Conflict Analysis

1.  **Find Conflict Annotation**: Use `solver.ResponseStats()` and `solver.SufficientAssumptionsForInfeasibility()`.
2.  **Feasible Slot Counts**: Check `output/phases/05_baseline_feasible_slot_counts.csv`. If a match has 0 feasible slots, check its domain builder logic.
3.  **Relaxation**: Temporarily comment out constraints one by one to isolate the conflict.


### Reference: example_reference.md
# Reference Documentation for Cp Sat Optimizer

This is a placeholder for detailed reference documentation.
Replace with actual reference content or delete if not needed.

## Structure Suggestions

### API Reference Example
- Overview
- Authentication
- Endpoints with examples
- Error codes

### Workflow Guide Example
- Prerequisites
- Step-by-step instructions
- Best practices



---

# Skill: pandas-data-wrangler
# pandas-data-wrangler

Schema definitions and data transformation patterns for the project's authoritative Excel and CSV files.

## Instructions

- Use this skill when modifying `src/data_loader.py` or performing data transformations.
- Refer to `references/schemas.md` for required columns and sheets in authoritative workbooks.
- Ensure all IDs are stripped and uppercased during normalization.
- Handle `Cont_Flag` values (`CL`, `CC`) correctly for CAF teams.

## Reference Files

- `references/schemas.md`: Detailed schema for `Data_Model.xlsx` and `expanded_calendar.xlsx`.


## References for pandas-data-wrangler
### Reference: example_reference.md
# Reference Documentation for Pandas Data Wrangler

This is a placeholder for detailed reference documentation.
Replace with actual reference content or delete if not needed.

## Structure Suggestions

### API Reference Example
- Overview
- Authentication
- Endpoints with examples
- Error codes

### Workflow Guide Example
- Prerequisites
- Step-by-step instructions
- Best practices


### Reference: schemas.md
# Authoritative Data Schemas

## `data/Data_Model.xlsx`

### Sheet: `team_data`
- `Team_ID`: Unique team identifier (e.g., AHL, ZAM).
- `Team_Name`: Full name.
- `Gov_ID`, `Gov_Name`: Governorate info.
- `Home_Stadium_ID`, `Alt_Stadium_ID`: Primary and backup venues.
- `Tier`: Team competitive tier (1-4).
- `Cont_Flag`: `CL` (Champions League) or `CC` (Confederation Cup).

### Sheet: `Stadiums`
- `Stadium_ID`, `Stadium_Name`, `Gov_ID`, `City`.
- `Is_Floodlit`: 1 if stadium has lights.

### Sheet: `dist_Matrix`
- `Origin`: Stadium ID.
- Additional columns: Destination Stadium IDs with distance in km.

### Sheet: `Sec_Matrix`
- `home_team_ID`, `away_team_ID`.
- `banned_venue1_ID`, `banned_venue2_ID`.
- `forced_venue_ID`: Overrides home stadium for this pair.

## `data/expanded_calendar.xlsx`

### Sheet: `expanded_calendar` (Primary)
- `Day_ID`, `Date`, `Date time`, `Week_Num`, `Day_name`.
- `Is_FIFA`: 1 if global blackout.
- `Is_CAF`: 1 if potential CAF conflict.

### Sheet: `FIFA_DAYS1`
- List of authoritative FIFA dates.

### Sheet: `cont_blockers_updated1`
- Team-specific CAF blocker dates.

### Sheet: `unique_CAF_dates`
- Global CAF date list.



---

# Skill: sports-scheduling-domain
# sports-scheduling-domain

Domain-specific knowledge of EPL scheduling constraints, FIFA dates, and CAF buffer rules.

## Instructions

- Use this skill to understand the logic behind scheduling decisions and constraints.
- Refer to `references/rules.md` for a summary of hard constraints and repair rules.
- Maintain the bidirectional CAF buffer (4 full rest days minimum).
- Ensure no matches are scheduled on FIFA dates.

## Reference Files

- `references/rules.md`: Summary of hard constraints (H1-H12) and repair rules (R1-R10).


## References for sports-scheduling-domain
### Reference: example_reference.md
# Reference Documentation for Sports Scheduling Domain

This is a placeholder for detailed reference documentation.
Replace with actual reference content or delete if not needed.

## Structure Suggestions

### API Reference Example
- Overview
- Authentication
- Endpoints with examples
- Error codes

### Workflow Guide Example
- Prerequisites
- Step-by-step instructions
- Best practices


### Reference: rules.md
# EPL Scheduling Rules

## Baseline Hard Constraints (H1-H12)

- **H1**: Every fixture assigned exactly once.
- **H2**: No matches on FIFA dates.
- **H3**: Restricted to round windows.
- **H4**: Max 1 match per team per day.
- **H5**: Max 1 match per venue per slot.
- **H6**: `MAX_MATCHES_PER_SLOT` (Default: 2).
- **H7**: `MAX_MATCHES_PER_DAY` (Default: 3).
- **H8**: `MIN_REST_DAYS_LOCAL` = 3 (4 days apart).
- **H9**: Global round order must be chronological.
- **H10**: Honor forced venues from `Sec_Matrix`.
- **H11**: Avoid known CAF blockers (team-specific).
- **H12**: Stadium maintenance gap (`MIN_STADIUM_SERVICE_GAP_DAYS`).

## Repair Feasibility Rules (R1-R10)

- **R1**: Not a FIFA date.
- **R2**: Not before original match date.
- **R3**: Daily load <= `MAX_MATCHES_PER_DAY`.
- **R4**: No other match for either team on that date.
- **R5**: Satisfy local rest rules (3 days).
- **R6**: Venue is free.
- **R7**: No home/away streak violation (>2).
- **R8**: Bidirectional CAF buffer (4 rest days / 5 days apart).
- **R9**: Weekly load <= `HARD_MAX_MATCHES_PER_WEEK`.
- **R10**: Respect stadium maintenance gap.

## Rest Rule Summary

| Context | Full Rest Days | Days Apart |
| :--- | :--- | :--- |
| League -> League | 3 | 4 |
| League <-> CAF | 3 (hard), 5 (preferred) | 4 (hard), 6 (preferred) |
| **Note** | CAF buffer is bidirectional | - |



---

# Skill: streamlit-dashboard-builder
# streamlit-dashboard-builder

Guidelines for building Streamlit UI components adhering to the Nile League dark theme and state management patterns.

## Instructions

- Follow the Nile League dark theme for all UI components.
- Use `st.session_state` for managing application state between runs.
- Refer to `references/theme.md` for color palettes and brand assets.
- Map `Team_ID` to assets in the `icons/` folder.

## Reference Files

- `references/theme.md`: Hex codes and visual assets for the Nile League theme.


## References for streamlit-dashboard-builder
### Reference: example_reference.md
# Reference Documentation for Streamlit Dashboard Builder

This is a placeholder for detailed reference documentation.
Replace with actual reference content or delete if not needed.

## Structure Suggestions

### API Reference Example
- Overview
- Authentication
- Endpoints with examples
- Error codes

### Workflow Guide Example
- Prerequisites
- Step-by-step instructions
- Best practices


### Reference: theme.md
# Nile League Theme & Brand Assets

## Color Palette (Dark Theme)

- **Surface**: `#232126`
- **Text**: `#f8f9f7`
- **Purple Accents**:
  - `#68239e`
  - `#75409f`
  - `#8f67ad`
  - `#ab97ba`
  - `#d2cad9`

## Visual Assets

- **Brand Logo**: `Nile_League.png`
- **Club Icons**: Located in `icons/` folder.
  - Format: 512x512 or 700x700 PNG.
  - Naming: `egypt_<team-name>_...png`
- **Page Icon**: Use `Nile_League.png`.

## UI Patterns

- Active tab indicator: Thin underline only.
- Layout: Use `st.columns` for side-by-side stats and icons.
- Charts: Use colors from the purple accent palette.



---
