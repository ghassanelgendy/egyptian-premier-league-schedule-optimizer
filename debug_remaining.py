"""Analyze the 10 remaining H8 violations to understand what blocks repair."""
import sys
sys.path.insert(0, '.')
from src.data_loader import load_data
from src.h8_repair import (find_h8_violations, count_h8_violations, repair_h8,
                            _team_seq, _dates_for_team, _ok_h4_h7_caf, _venue_free, _try_swap)
from src.baseline_solver import ScheduledMatch
from src.constants import MIN_REST_DAYS_LOCAL, MIN_REST_DAYS_CAF
import pandas as pd

data = load_data()
caf_by_team = data.caf_dates_by_team

slots = data.usable_slots.copy()
slots['dt_str'] = slots['Date time'].apply(lambda x: str(x) if pd.notna(x) else '')
dt_to_si = {}
for si, row in slots.iterrows():
    key = row['dt_str']
    if key and key not in dt_to_si:
        dt_to_si[key] = int(si)

df = pd.read_csv('output/optimized_schedule_pre_caf.csv')
df['Date'] = pd.to_datetime(df['Date']).dt.date
df['Date_time_str'] = pd.to_datetime(df['Date_time']).apply(lambda x: str(x) if pd.notna(x) else '')

schedule = []
for i, row in df.iterrows():
    si = dt_to_si.get(row['Date_time_str'], i)
    sm = ScheduledMatch(
        match_idx=i, round_num=int(row['Round']),
        home_team=row['Home_Team_ID'], away_team=row['Away_Team_ID'],
        venue=row['Venue_Stadium_ID'],
        match_tier=int(row['Match_Tier']) if pd.notna(row['Match_Tier']) else 0,
        slot_idx=si, day_id=row['Day_ID'], date=row['Date'],
        date_time=row['Date_time'], week_num=int(row['Calendar_Week_Num']),
        day_name='', slot_tier=int(row['Slot_tier']) if pd.notna(row['Slot_tier']) else 0,
        travel_km=float(row['Travel_km']) if pd.notna(row['Travel_km']) else 0.0,
    )
    schedule.append(sm)

# First run the repair
schedule = repair_h8(schedule, data, max_iters=2000)

violations = find_h8_violations(schedule)
print(f"Remaining violations: {len(violations)}")

for team_id, ia, ib, ic in violations:
    sa, sb, sc = schedule[ia], schedule[ib], schedule[ic]
    print(f"\n{team_id}: {sa.date}(r{sa.round_num}) | {sb.date}(r{sb.round_num}) | {sc.date}(r{sc.round_num})")
    
    sm_mid = schedule[ib]
    d_first, d_last = sa.date, sc.date
    is_home_streak = (sm_mid.home_team == team_id)
    
    seq = _team_seq(schedule, team_id)
    candidates = [(abs((schedule[idx].date - sm_mid.date).days), idx)
                  for idx in seq
                  if idx not in (ia, ib, ic)
                  and (schedule[idx].home_team == team_id) != is_home_streak]
    candidates.sort()
    
    print(f"  Opposite-dir candidates (first 5 of {len(candidates)}):")
    for dist, idx_cand in candidates[:5]:
        sm_cand = schedule[idx_cand]
        new_date_mid = sm_cand.date
        new_date_cand = sm_mid.date
        exc = {ib, idx_cand}
        
        reasons = []
        if d_first < new_date_mid < d_last:
            reasons.append('inside streak window')
        else:
            for t, nd in [(sm_mid.home_team, new_date_mid), (sm_mid.away_team, new_date_mid),
                          (sm_cand.home_team, new_date_cand), (sm_cand.away_team, new_date_cand)]:
                existing = _dates_for_team(schedule, t, exc)
                caf = caf_by_team.get(t, [])
                if not _ok_h4_h7_caf(nd, existing, caf):
                    conflicts = [d for d in existing if abs((nd - d).days) <= MIN_REST_DAYS_LOCAL]
                    caf_c = [d for d in caf if abs((nd - d).days) <= MIN_REST_DAYS_CAF]
                    reasons.append(f'{t}@{nd}: rest={[str(x) for x in conflicts[:2]]} caf={[str(x) for x in caf_c[:2]]}')
        
        print(f"  [{dist}d] r{sm_cand.round_num}({sm_cand.date}): {'; '.join(reasons) if reasons else 'OK (but creates new violation?)'}")
