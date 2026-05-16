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
