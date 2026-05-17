import pandas as pd
import os
import glob
import json
import numpy as np
from datetime import datetime, timedelta

# --- MAPPINGS ---
TEAM_STADIUM = {
    'AHL': 'CAIRO_INTL', 'ZAM': 'CAIRO_INTL', 'PYR': '30_JUNE', 'MAS': 'SUEZ_ST',
    'MOD': 'AL_SALAM', 'SMO': 'BORG_ARAB', 'ZED': 'CAIRO_INTL', 'CER': 'SUEZ_CANAL',
    'ENP': 'PETRO_SPORT', 'ITH': 'ALEX_STADIUM', 'TLG': 'GEHAZ_REYADA', 'BNK': 'CAIRO_INTL',
    'PHA': 'BORG_ARAB', 'GOU': 'EL_GOUNA', 'ISM': 'ISMAILIA_ST', 'MAH': 'MAHALLA',
    'PET': 'PETRO_SPORT', 'HAR': 'HARAS', 'ASW': 'ASWAN', 'BAL': 'GHAZL_MAH',
    'EAS': 'PETRO_SPORT', 'NOG': 'PETRO_SPORT', 'DAK': 'PETRO_SPORT', 'ENT': 'AL_SALAM',
    'MAK': 'CAIRO_INTL', 'DEG': 'PETRO_SPORT'
}

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

class HistoricalEngine:
    def __init__(self, dist_matrix):
        self.dist_matrix = dist_matrix
        self.data_dir = "past seasons data"

    def analyze_all(self):
        files = sorted(glob.glob(f'{self.data_dir}/egyptian_league_*.csv'))
        results = []
        for f in files:
            results.append(self.analyze_season(f))
        return results

    def analyze_season(self, csv_path):
        tag = os.path.basename(csv_path).replace('egyptian_league_', '').replace('.csv', '')
        
        # Load Context
        fifa_dates = set()
        f_path = f'{self.data_dir}/fifa_dates_{tag}.csv'
        if os.path.exists(f_path):
            fifa_dates = set(pd.to_datetime(pd.read_csv(f_path)['Date']).dt.date)

        caf_by_team = {}
        c_path = f'{self.data_dir}/caf_dates_{tag}.csv'
        if os.path.exists(c_path):
            cdf = pd.read_csv(c_path)
            for _, r in cdf.iterrows():
                caf_by_team.setdefault(r['Team_ID'], set()).add(pd.to_datetime(r['Date']).date())

        # Load Matches
        df = pd.read_csv(csv_path)
        df_clean = df[~df['Date'].isin(['Pending', 'pending', 'nan'])].copy()
        df_clean['Date'] = pd.to_datetime(df_clean['Date'], dayfirst=True, errors='coerce')
        df_clean = df_clean.dropna(subset=['Date'])
        df_sorted = df_clean.sort_values('Date')

        metrics = {
            'Season': tag.replace('_', '/'),
            'Matches': len(df_clean),
            'FIFA Days': sum(1 for d in fifa_dates if df_sorted['Date'].min().date() <= d <= df_sorted['Date'].max().date()),
            'Total Travel': 0,
            'Max Raw Gap': 0,
            'Max Waste Gap': 0,
            'HA Streak': 0
        }

        team_data = {}
        team_loc = {}

        for _, row in df_sorted.iterrows():
            h_id, a_id, d = get_team_id(row['Home Team']), get_team_id(row['Away Team']), row['Date'].date()
            for tid in [h_id, a_id]:
                if tid not in team_data: team_data[tid] = {'dates': [], 'ha': []}
                team_data[tid]['dates'].append(d)
            
            team_data[h_id]['ha'].append('H')
            team_data[a_id]['ha'].append('A')

            # Travel
            h_stadium = TEAM_STADIUM.get(h_id, 'CAIRO_INTL')
            a_base = TEAM_STADIUM.get(a_id, 'CAIRO_INTL')
            curr = team_loc.get(a_id, a_base)
            if curr in self.dist_matrix and h_stadium in self.dist_matrix[curr]:
                metrics['Total Travel'] += self.dist_matrix[curr][h_stadium]
            team_loc[a_id] = h_stadium

        all_raw, all_waste = [], []
        max_streak = 0
        for tid, data in team_data.items():
            dates = sorted(data['dates'])
            team_caf = caf_by_team.get(tid, set())
            
            # Gaps
            for i in range(1, len(dates)):
                d1, d2 = dates[i-1], dates[i]
                raw = (d2 - d1).days
                all_raw.append(raw)
                
                gap_range = pd.date_range(d1 + timedelta(days=1), d2 - timedelta(days=1))
                f_count = sum(1 for day in gap_range if day.date() in fifa_dates)
                c_count = sum(1 for day in gap_range if day.date() in team_caf and day.date() not in fifa_dates)
                
                waste = max(0, raw - f_count - (c_count * 4))
                all_waste.append(waste)

            # Streaks
            streak = 1
            for i in range(1, len(data['ha'])):
                if data['ha'][i] == data['ha'][i-1]:
                    streak += 1
                    max_streak = max(max_streak, streak)
                else: streak = 1

        metrics['Max Raw Gap'] = max(all_raw) if all_raw else 0
        metrics['Max Waste Gap'] = max(all_waste) if all_waste else 0
        metrics['HA Streak'] = max_streak
        metrics['Total Travel'] = int(metrics['Total Travel'])

        return metrics
