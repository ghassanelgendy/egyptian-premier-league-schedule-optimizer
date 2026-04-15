"""Run the H8 repair with many iterations to see full potential."""
import sys
sys.path.insert(0, '.')
from src.data_loader import load_data
from src.h8_repair import find_h8_violations, count_h8_violations, repair_h8
from src.baseline_solver import ScheduledMatch
import pandas as pd

data = load_data()

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

print(f"Before: {count_h8_violations(schedule)} violations")

# Run with large iteration count
result = repair_h8(list(schedule), data, max_iters=2000)
final = count_h8_violations(result)
print(f"After 2000 iterations: {final} violations")

# Show remaining violations
if final > 0:
    from src.h8_repair import find_h8_violations, _team_seq
    remaining = find_h8_violations(result)
    print(f"\nRemaining violations:")
    for team_id, ia, ib, ic in remaining:
        sa, sb, sc = result[ia], result[ib], result[ic]
        ha = 'H' if sa.home_team == team_id else 'A'
        hb = 'H' if sb.home_team == team_id else 'A'
        hc = 'H' if sc.home_team == team_id else 'A'
        print(f"  {team_id}: {ha}@r{sa.round_num}({sa.date}) | {hb}@r{sb.round_num}({sb.date}) | {hc}@r{sc.round_num}({sc.date})")
