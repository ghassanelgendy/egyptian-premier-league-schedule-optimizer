"""Test the H8 repair on actual ScheduledMatch objects reconstructed from CSV output."""
import sys
sys.path.insert(0, '.')
from src.data_loader import load_data
from src.h8_repair import find_h8_violations, count_h8_violations, repair_h8, _try_swap, _team_seq
from src.baseline_solver import ScheduledMatch
from src.constants import MIN_REST_DAYS_LOCAL, MIN_REST_DAYS_CAF
import pandas as pd

data = load_data()

# Build a Date_time -> slot_idx mapping
slots = data.usable_slots.copy()
slots['dt_str'] = slots['Date time'].apply(lambda x: str(x) if pd.notna(x) else '')
dt_to_si = {}
for si, row in slots.iterrows():
    key = row['dt_str']
    if key and key not in dt_to_si:
        dt_to_si[key] = int(si)

# Load the pre-CAF schedule (closest to what main.py passes to repair_h8)
df = pd.read_csv('output/optimized_schedule_pre_caf.csv')
df['Date'] = pd.to_datetime(df['Date']).dt.date
df['Date_time_str'] = pd.to_datetime(df['Date_time']).apply(lambda x: str(x) if pd.notna(x) else '')

schedule = []
for i, row in df.iterrows():
    si = dt_to_si.get(row['Date_time_str'], i)
    sm = ScheduledMatch(
        match_idx=i,
        round_num=int(row['Round']),
        home_team=row['Home_Team_ID'],
        away_team=row['Away_Team_ID'],
        venue=row['Venue_Stadium_ID'],
        match_tier=int(row['Match_Tier']) if pd.notna(row['Match_Tier']) else 0,
        slot_idx=si,
        day_id=row['Day_ID'],
        date=row['Date'],
        date_time=row['Date_time'],
        week_num=int(row['Calendar_Week_Num']),
        day_name='',
        slot_tier=int(row['Slot_tier']) if pd.notna(row['Slot_tier']) else 0,
        travel_km=float(row['Travel_km']) if pd.notna(row['Travel_km']) else 0.0,
    )
    schedule.append(sm)

print(f"Loaded {len(schedule)} matches. Slot_idx range: {min(s.slot_idx for s in schedule)} - {max(s.slot_idx for s in schedule)}")

# Check for slot_idx collisions (same slot, same venue)
from collections import defaultdict
slot_venue_count = defaultdict(list)
for sm in schedule:
    slot_venue_count[(sm.slot_idx, sm.venue)].append(sm)
collisions = {k: v for k, v in slot_venue_count.items() if len(v) > 1}
print(f"Slot+venue collisions: {len(collisions)}")

violations = find_h8_violations(schedule)
print(f"H8 violations: {len(violations)}")

# Test first violation manually
if violations:
    team_id, ia, ib, ic = violations[0]
    sa, sb, sc = schedule[ia], schedule[ib], schedule[ic]
    print(f"\nViolation 0: {team_id}")
    print(f"  {sa.date} r{sa.round_num} {'H' if sa.home_team==team_id else 'A'}")
    print(f"  {sb.date} r{sb.round_num} {'H' if sb.home_team==team_id else 'A'} (middle, slot_idx={sb.slot_idx})")
    print(f"  {sc.date} r{sc.round_num} {'H' if sc.home_team==team_id else 'A'}")

    sm_mid = schedule[ib]
    d_first, d_last = sa.date, sc.date
    is_home_streak = (sm_mid.home_team == team_id)
    seq = _team_seq(schedule, team_id)
    candidates = []
    for idx in seq:
        if idx in (ia, ib, ic):
            continue
        sm = schedule[idx]
        if (sm.home_team == team_id) == is_home_streak:
            continue
        d = sm.date
        inside = 1 if (d_first < d < d_last) else 0
        dist = abs((d - sm_mid.date).days)
        candidates.append((inside, dist, idx))
    candidates.sort()

    print(f"\n  Testing {len(candidates)} candidates:")
    for inside, dist, idx_cand in candidates[:8]:
        sm_cand = schedule[idx_cand]
        result = _try_swap(schedule, ib, idx_cand, d_first, d_last, data.caf_dates_by_team)
        status = "APPLIED" if result else "failed"
        print(f"    [{dist}d] r{sm_cand.round_num}({sm_cand.date}) {'H' if sm_cand.home_team==team_id else 'A'}: {status}")
        if result:
            # Undo swap for testing (swap back)
            _try_swap(schedule, idx_cand, ib, d_last, d_first, data.caf_dates_by_team)
            break

    # Now run the actual repair
    print(f"\nRunning repair (5 iterations max):")
    result_schedule = repair_h8(list(schedule), data, max_iters=5)
    post = count_h8_violations(result_schedule)
    print(f"Violations after 5 iters: {post}")
