"""Trace the H8 repair's first swap attempt to find the bug."""
import sys
sys.path.insert(0, '.')
from src.data_loader import load_data
from src.h8_repair import find_h8_violations, _team_seq, _dates_for_team, _ok_h4_h7_caf, _venue_free
from src.baseline_solver import ScheduledMatch
from src.constants import MIN_REST_DAYS_LOCAL, MIN_REST_DAYS_CAF
import pandas as pd
from datetime import date

data = load_data()
caf_by_team = data.caf_dates_by_team

# Load schedule from pre-CAF output (what the repair actually sees)
df = pd.read_csv('output/optimized_schedule_pre_caf.csv')
df['Date'] = pd.to_datetime(df['Date']).dt.date

# Map day_id -> slot_idx by looking it up in usable_slots
slots = data.usable_slots
slots['_date'] = pd.to_datetime(slots['Date']).dt.date

# Build a mapping: (date, venue) -> slot_idx
date_venue_to_slot = {}
for si, row in slots.iterrows():
    d = row['_date']
    v = row.get('Stadium_ID', row.get('Venue', ''))
    date_venue_to_slot[(d, v)] = si

# Build schedule
schedule = []
for i, row in df.iterrows():
    d = row['Date']
    venue = row['Venue_Stadium_ID']
    si = date_venue_to_slot.get((d, venue), i)
    sm = ScheduledMatch(
        match_idx=i,
        round_num=int(row['Round']),
        home_team=row['Home_Team_ID'],
        away_team=row['Away_Team_ID'],
        venue=venue,
        match_tier=int(row['Match_Tier']) if pd.notna(row['Match_Tier']) else 0,
        slot_idx=si,
        day_id=row['Day_ID'],
        date=d,
        date_time=None,
        week_num=int(row['Calendar_Week_Num']),
        day_name='',
        slot_tier=int(row['Slot_tier']) if pd.notna(row['Slot_tier']) else 0,
        travel_km=float(row['Travel_km']) if pd.notna(row['Travel_km']) else 0.0,
    )
    schedule.append(sm)

violations = find_h8_violations(schedule)
print(f'Total violations: {len(violations)}')

# Focus on first violation
team_id, ia, ib, ic = violations[0]
sa, sb, sc = schedule[ia], schedule[ib], schedule[ic]
print(f'\nViolation 0: {team_id}')
print(f'  ia={ia} date={sa.date} r={sa.round_num} home={sa.home_team}')
print(f'  ib={ib} date={sb.date} r={sb.round_num} home={sb.home_team}')
print(f'  ic={ic} date={sc.date} r={sc.round_num} home={sc.home_team}')

sm_mid = schedule[ib]
d_first = sa.date
d_last = sc.date
d_mid = sm_mid.date
is_home_streak = (sm_mid.home_team == team_id)
print(f'\n  Middle match: {sm_mid.home_team} vs {sm_mid.away_team} at slot_idx={sm_mid.slot_idx}')
print(f'  is_home_streak={is_home_streak}')
print(f'  d_first={d_first}, d_last={d_last}')

# Get candidates (same logic as repair)
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
    distance = abs((d - d_mid).days)
    candidates.append((inside, distance, idx))
candidates.sort()

print(f'\n  Candidates sorted: {[(dist, schedule[idx].date, schedule[idx].round_num) for inside, dist, idx in candidates[:6]]}')

# Test first few swaps
for inside, dist, idx_cand in candidates[:6]:
    sm_cand = schedule[idx_cand]
    new_date_mid = sm_cand.date
    new_date_cand = sm_mid.date
    exclude = {ib, idx_cand}
    
    print(f'\n  --- Trying swap with idx={idx_cand} r={sm_cand.round_num} date={sm_cand.date} ---')
    print(f'    new_date_mid={new_date_mid}, new_date_cand={new_date_cand}')
    
    # Check streak window
    window_fail = d_first < new_date_mid < d_last
    print(f'    streak window fail: {window_fail}  ({d_first} < {new_date_mid} < {d_last})')
    if window_fail:
        print('    -> SKIP (inside window)')
        continue
    
    # Check 4 teams
    all_ok = True
    for t, nd in [
        (sm_mid.home_team, new_date_mid),
        (sm_mid.away_team, new_date_mid),
        (sm_cand.home_team, new_date_cand),
        (sm_cand.away_team, new_date_cand),
    ]:
        existing = _dates_for_team(schedule, t, exclude)
        caf = caf_by_team.get(t, [])
        ok = _ok_h4_h7_caf(nd, existing, caf)
        if not ok:
            conflicts_h7 = [d for d in existing if abs((nd - d).days) <= MIN_REST_DAYS_LOCAL]
            conflicts_caf = [d for d in caf if abs((nd - d).days) <= MIN_REST_DAYS_CAF]
            print(f'    FAIL: {t}@{nd}: h7_conflicts={conflicts_h7[:3]}, caf_conflicts={conflicts_caf[:3]}')
            all_ok = False
        else:
            print(f'    OK:   {t}@{nd}')
    
    if all_ok:
        # Check venue
        v1_ok = _venue_free(schedule, sm_mid.venue, sm_cand.slot_idx, exclude)
        v2_ok = _venue_free(schedule, sm_cand.venue, sm_mid.slot_idx, exclude)
        print(f'    venue_free(sm_mid.venue={sm_mid.venue} at slot={sm_cand.slot_idx}): {v1_ok}')
        print(f'    venue_free(sm_cand.venue={sm_cand.venue} at slot={sm_mid.slot_idx}): {v2_ok}')
        if v1_ok and v2_ok:
            print('    *** SWAP IS VALID ***')
        else:
            print('    -> FAIL (venue conflict)')
