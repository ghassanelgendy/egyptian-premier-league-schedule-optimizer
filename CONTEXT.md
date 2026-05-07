# Egyptian Premier League Schedule Optimizer - Repository Context

## Purpose

This repository builds a full Egyptian Premier League schedule from two Excel workbooks:

- `data/Data_Model.xlsx`
- `data/expanded_calendar.xlsx`

The scheduling flow is:

1. Load and validate workbook data.
2. Generate a seeded double round-robin fixture list.
3. Build feasible slot domains per match.
4. Solve a baseline schedule with OR-Tools CP-SAT.
5. Audit baseline matches against CAF conflicts.
6. Repair CAF-violating matches into later free slots where possible.
7. Write CSV outputs and validation artifacts.

The repo also includes a Streamlit app for running the pipeline, tuning model constants, and inspecting outputs.

## How To Run

- CLI pipeline: `python main.py`
- CLI with a fixed seed: `python main.py --seed 42`
- Streamlit UI: `streamlit run streamlit_app.py`

Dependencies are listed in `requirements.txt`:

- `ortools`
- `pandas`
- `openpyxl`
- `streamlit`

## Top-Level Index

### Runtime entrypoints

- `main.py`
  Runs the 6-phase scheduling pipeline end to end and writes output artifacts.
- `streamlit_app.py`
  Streamlit UI for running the model, patching tunable constants in-session, and browsing results.

### Core engine

- `src/constants.py`
  Central model configuration: league shape, rest rules, capacities, objective weights, solver limits, paths.
- `src/data_loader.py`
  Loads and validates the two authoritative workbooks into the `LeagueData` dataclass.
- `src/fixture_generator.py`
  Builds the double round-robin fixture framework and solves home/away orientation.
- `src/tiers.py`
  Computes slot tiers and match tiers.
- `src/slot_domain.py`
  Builds per-match feasible slot sets and round windows.
- `src/baseline_solver.py`
  Main CP-SAT baseline assignment model. Produces scheduled league matches.
- `src/caf_audit.py`
  Detects CAF conflicts in the baseline schedule and prepares the postponement queue.
- `src/caf_repair_solver.py`
  Attempts to reinsert postponed matches into free CAF-safe slots.
- `src/output_writer.py`
  Writes final and intermediate CSV outputs.
- `src/validation.py`
  Writes final validation reports for completeness, FIFA, venue, daily load, round order, and CAF buffers.

### Inputs

- `data/`
  Authoritative model inputs only.
  - `Data_Model.xlsx`
  - `expanded_calendar.xlsx`

### Documentation

- `Documentations/PRD.md`
  Product and model requirements for the current app and pipeline.
- `Documentations/MODEL_EXPLANATION.md`
  Solver semantics and baseline-vs-repair design notes.
- `walkthrough.md`
  Long-form project walkthrough with architecture and pipeline narrative.
- `Documentations/presentation.pdf`
- `Documentations/Documentation Phase I .pdf`

### Reference assets and research

- `icons/`
  Team logo PNGs used by the Streamlit UI.
- `past seasons data/`
  Historical league and CAF files for reference, not authoritative model input.
- `Research papers/`
  Academic references related to sports scheduling and tournament optimization.

### Generated outputs

- `output/`
  Expected runtime output folder. Not committed.
- `output/phases/`
  Expected diagnostic artifact folder. Not committed.

Git ignores:

- `/output`
- `/old_output`

## Actual Pipeline In Code

`main.py` currently executes these phases:

1. `src.data_loader.load_data()`
2. `src.fixture_generator.generate_drr(data, seed)`
3. `src.slot_domain.build_domains(data, matches)`
4. `src.baseline_solver.solve_baseline(data, matches, domains)`
5. `src.output_writer.write_pre_caf_schedule(...)`
6. `src.caf_audit.caf_audit(baseline, data)`
7. `src.caf_repair_solver.caf_repair(...)` or skip repair if there are no CAF violations
8. `src.output_writer.*` final artifact writers
9. `src.validation.write_validation_reports(...)`

## Important Project Rules

- Only `data/Data_Model.xlsx` and `data/expanded_calendar.xlsx` are valid model inputs.
- Previous CSV outputs must not be fed back into the solver.
- FIFA dates are hard blackouts.
- CAF handling is split into audit and repair after baseline scheduling.
- The repo name and UI refer to the Egyptian Premier League, but some code strings still use the shorthand `EPL`.

## Main Data Structures

- `LeagueData` in `src/data_loader.py`
  Holds teams, stadiums, distance matrix, security rules, slots, usable slots, FIFA dates, CAF blockers, team CAF dates, and unique CAF dates.
- `Match` in `src/fixture_generator.py`
  Represents one abstract fixture in the double round-robin.
- `ScheduledMatch` in `src/baseline_solver.py`
  Represents a fixture assigned to a real calendar slot.
- `CAFViolation` in `src/caf_audit.py`
  Represents a baseline match that conflicts with CAF rules.

## Current Repository Notes

- There was no root `README.md`, `AGENTS.md`, or dedicated context file before this one.
- `walkthrough.md` is useful but long; use this file first when you need a quick repo map.
- `src/__pycache__/` is present in the repo and can be ignored during code reading.
