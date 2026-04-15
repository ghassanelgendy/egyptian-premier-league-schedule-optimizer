"""Debug script to analyze H8 violations and swap feasibility."""
import sys
sys.path.insert(0, '.')
from src.data_loader import load_data
from src.h8_repair import find_h8_violations, _team_seq, _dates_for_team, _ok_h4_h7_caf
from src.baseline_solver import ScheduledMatch
from src.constants import MIN_REST_DAYS_LOCAL, MIN_REST_DAYS_CAF
import pandas as pd
from datetime import date

data = load_data()
caf_by_team = data.caf_dates_by_team

df = pd.read_csv('output/optimized_schedule.csv')
df['Date'] = pd.to_datetime(df['Date']).dt.date

schedule = []
for i, row in df.iterrows():
    d = row['Date']
    sm = ScheduledMatch(
        match_idx=i,
        round_num=int(row['Round']),
        home_team=row['Home_Team_ID'],
        away_team=row['Away_Team_ID'],
        venue=row['Venue_Stadium_ID'],
        match_tier=int(row['Match_Tier']) if pd.notna(row['Match_Tier']) else 0,
        slot_idx=i,
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
print()

for team_id, ia, ib, ic in violations[:8]:
    sa, sb, sc = schedule[ia], schedule[ib], schedule[ic]
    ha = 'H' if sa.home_team == team_id else 'A'
    hb = 'H' if sb.home_team == team_id else 'A'
    hc = 'H' if sc.home_team == team_id else 'A'
    print(f'{team_id}: {ha}@r{sa.round_num}({sa.date}) | {hb}@r{sb.round_num}({sb.date}) | {hc}@r{sc.round_num}({sc.date})')

    sm_mid = schedule[ib]
    is_home_streak = (sm_mid.home_team == team_id)
    d_first = sa.date
    d_last = sc.date

    seq = _team_seq(schedule, team_id)
    candidates = []
    for idx in seq:
        if idx in (ia, ib, ic):
            continue
        sm = schedule[idx]
        if (sm.home_team == team_id) == is_home_streak:
            continue
        dist = abs((sm.date - sm_mid.date).days)
        candidates.append((dist, idx))
    candidates.sort()

    print(f'  Middle: {sm_mid.home_team} vs {sm_mid.away_team} at {sm_mid.date}')
    print(f'  Opposite-dir candidates to swap with:')
    found_any = False
    for dist, idx in candidates[:5]:
        sm_cand = schedule[idx]
        hc2 = 'H' if sm_cand.home_team == team_id else 'A'
        new_date_mid = sm_cand.date
        new_date_cand = sm_mid.date
        exc = {ib, idx}

        # Check streak window
        if d_first < new_date_mid < d_last:
            reason = 'inside streak window'
        else:
            reasons = []
            for t, nd in [
                (sm_mid.home_team, new_date_mid),
                (sm_mid.away_team, new_date_mid),
                (sm_cand.home_team, new_date_cand),
                (sm_cand.away_team, new_date_cand),
            ]:
                existing = _dates_for_team(schedule, t, exc)
                caf = caf_by_team.get(t, [])
                if nd in existing:
                    reasons.append(f'{t}@{nd}: H4 same-date conflict')
                else:
                    conflicts = [d for d in existing if abs((nd - d).days) <= MIN_REST_DAYS_LOCAL]
                    caf_c = [d for d in caf if abs((nd - d).days) <= MIN_REST_DAYS_CAF]
                    if conflicts:
                        reasons.append(f'{t}@{nd}: H7 rest conflict {conflicts[:2]}')
                    elif caf_c:
                        reasons.append(f'{t}@{nd}: CAF rest conflict {caf_c[:2]}')
            reason = '; '.join(reasons) if reasons else 'OK - swap valid!'
            if not reasons:
                found_any = True

        print(f'    [{dist}d] {hc2}@r{sm_cand.round_num}({sm_cand.date}): {reason}')

    if not found_any:
        print('  ** NO VALID SWAP FOUND for this violation **')
    print()
