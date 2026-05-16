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
