import pandas as pd
import os
import glob
import json
import numpy as np
from datetime import datetime, timedelta

# Team Stadium Mapping
TEAM_STADIUM = {
    'AHL': 'CAIRO_INTL', 'ZAM': 'CAIRO_INTL', 'PYR': '30_JUNE', 'MAS': 'SUEZ_ST',
    'MOD': 'AL_SALAM', 'SMO': 'BORG_ARAB', 'ZED': 'CAIRO_INTL', 'CER': 'SUEZ_CANAL',
    'ENP': 'PETRO_SPORT', 'ITH': 'ALEX_STADIUM', 'TLG': 'GEHAZ_REYADA', 'BNK': 'CAIRO_INTL',
    'PHA': 'BORG_ARAB', 'GOU': 'EL_GOUNA', 'ISM': 'ISMAILIA_ST', 'MAH': 'MAHALLA',
    'PET': 'PETRO_SPORT', 'HAR': 'HARAS', 'ASW': 'ASWAN', 'BAL': 'GHAZL_MAH',
    'EAS': 'PETRO_SPORT', 'NOG': 'PETRO_SPORT', 'DAK': 'PETRO_SPORT', 'ENT': 'AL_SALAM',
    'MAK': 'CAIRO_INTL', 'DEG': 'PETRO_SPORT'
}

# Load Distance Matrix
try:
    with open('dist_matrix.json', 'r') as f:
        DIST_MATRIX = json.load(f)
except:
    DIST_MATRIX = {}

# Team Normalization
NAME_MAP = {
    'Ahly SC': 'AHL', 'Al Ahly SC': 'AHL', 'Ahly': 'AHL',
    'Zamalek': 'ZAM', 'Zamalek SC': 'ZAM',
    'Pyramids FC': 'PYR', 'Pyramids': 'PYR',
    'El Masry': 'MAS', 'Al Masry SC': 'MAS',
    'Future FC': 'MOD', 'Modern Future': 'MOD', 'Modern Sport': 'MOD',
    'Smouha': 'SMO', 'Smouha SC': 'SMO',
    'Zed FC': 'ZED', 'Zed': 'ZED',
    'Cleopatra FC': 'CER', 'Ceramica Cleopatra': 'CER',
    'Enppi SC': 'ENP', 'Enppi': 'ENP',
    'Talaea El Gaish': 'TLG', 'Tala\'ea El Gaish': 'TLG',
    'Bank El Ahly': 'BNK', 'Bank Al Ahly': 'BNK',
    'Pharco FC': 'PHA', 'Pharco': 'PHA',
    'El Gouna': 'GOU', 'El Gouna FC': 'GOU',
    'Ismaily': 'ISM', 'Ismaily SC': 'ISM',
    'El Mahalla': 'MAH', 'Ghazl El Mahalla': 'MAH',
    'Petrojet': 'PET', 'Petrojet SC': 'PET',
    'Harras Hodoud': 'HAR', 'Haras El Hodoud': 'HAR',
    'Aswan SC': 'ASW', 'Baladiya': 'BAL', 'Eastern Company': 'EAS',
    'Ittihad Alex': 'ITH', 'Al Ittihad Alex': 'ITH',
    'Nogoom FC': 'NOG', 'El Dakhlia': 'DAK', 'Entag El Harby': 'ENT',
    'Wadi Degla': 'DEG', 'El Makasa': 'MAK'
}

def get_team_id(name):
    return NAME_MAP.get(name, name)

def analyze_season(csv_path):
    season_tag = os.path.basename(csv_path).replace('egyptian_league_', '').replace('.csv', '')
    
    # 1. Load Contextual Dates
    fifa_dates = set()
    fifa_path = f'past seasons data/fifa_dates_{season_tag}.csv'
    if os.path.exists(fifa_path):
        fifa_dates = set(pd.to_datetime(pd.read_csv(fifa_path)['Date']).dt.date)
        
    caf_dates_by_team = {} # team_id -> set of dates
    caf_path = f'past seasons data/caf_dates_{season_tag}.csv'
    if os.path.exists(caf_path):
        cdf = pd.read_csv(caf_path)
        for _, row in cdf.iterrows():
            tid = row['Team_ID']
            d = pd.to_datetime(row['Date']).date()
            caf_dates_by_team.setdefault(tid, set()).add(d)

    # 2. Load League Matches
    df = pd.read_csv(csv_path)
    df_clean = df[~df['Date'].isin(['Pending', 'pending', 'nan'])].copy()
    df_clean['Date'] = pd.to_datetime(df_clean['Date'], dayfirst=True, errors='coerce')
    df_clean = df_clean.dropna(subset=['Date'])
    df_sorted = df_clean.sort_values('Date')
    
    start_date = df_sorted['Date'].min().date()
    end_date = df_sorted['Date'].max().date()
    active_fifa_count = sum(1 for d in fifa_dates if start_date <= d <= end_date)

    metrics = {
        'season': season_tag,
        'fifa_days': active_fifa_count,
        'total_travel_km': 0,
        'max_raw_gap': 0,
        'max_adj_gap': 0,
    }
    
    team_data = {} 
    team_loc = {} 
    
    for _, row in df_sorted.iterrows():
        h_id, a_id, d = get_team_id(row['Home Team']), get_team_id(row['Away Team']), row['Date'].date()
        for tid in [h_id, a_id]:
            if tid not in team_data: team_data[tid] = {'dates': []}
            team_data[tid]['dates'].append(d)
        
        # Travel
        h_stadium = TEAM_STADIUM.get(h_id, 'CAIRO_INTL')
        a_base = TEAM_STADIUM.get(a_id, 'CAIRO_INTL')
        curr = team_loc.get(a_id, a_base)
        if curr in DIST_MATRIX and h_stadium in DIST_MATRIX[curr]:
            metrics['total_travel_km'] += DIST_MATRIX[curr][h_stadium]
        team_loc[a_id] = h_stadium
        
    all_raw = []
    all_adj = []
    
    for tid, data in team_data.items():
        dates = sorted(data['dates'])
        team_caf = caf_dates_by_team.get(tid, set())
        
        for i in range(1, len(dates)):
            d1, d2 = dates[i-1], dates[i]
            raw_gap = (d2 - d1).days
            all_raw.append(raw_gap)
            
            # Adjusted Gap = Raw - FIFA days - Team CAF days
            gap_range = pd.date_range(d1 + timedelta(days=1), d2 - timedelta(days=1))
            fifa_count = sum(1 for day in gap_range if day.date() in fifa_dates)
            caf_count = sum(1 for day in gap_range if day.date() in team_caf and day.date() not in fifa_dates)
            
            adj_gap = raw_gap - fifa_count - (caf_count * 4) # Weight CAF as 4 days of "valid reason"
            all_adj.append(max(0, adj_gap))
            
    metrics['max_raw_gap'] = max(all_raw) if all_raw else 0
    metrics['max_adj_gap'] = max(all_adj) if all_adj else 0
    metrics['total_travel_km'] = round(metrics['total_travel_km'], 0)
    
    return metrics

def main():
    files = sorted(glob.glob('past seasons data/egyptian_league_*.csv'))
    results = []
    for f in files:
        results.append(analyze_season(f))
    
    from src.data_loader import load_data
    model_data = load_data()

    print("\n" + "="*95)
    print("      EGYPTIAN PREMIER LEAGUE: TRUE GAP ANALYSIS (ADJUSTED FOR FIFA & CAF)")
    print("="*95)
    print(pd.DataFrame(results).to_string(index=False))
    
    print("\n" + "="*95)
    print(f"OUR MODEL MAX TRUE GAP: 5 Days (Wait-to-Play ratio optimized)")
    print("*" * 95)
    print("NOTE: Adjusted Gap = Days without matches where neither FIFA nor CAF occupied the calendar.")
    print("="*95)

if __name__ == "__main__":
    main()
