# Authoritative Data Schemas

## `data/Data_Model.xlsx`

### Sheet: `team_data`
- `Team_ID`: Unique team identifier (e.g., AHL, ZAM).
- `Team_Name`: Full name.
- `Gov_ID`, `Gov_Name`: Governorate info.
- `Home_Stadium_ID`, `Alt_Stadium_ID`: Primary and backup venues.
- `Tier`: Team competitive tier (1-4).
- `Cont_Flag`: `CL` (Champions League) or `CC` (Confederation Cup).

### Sheet: `Stadiums`
- `Stadium_ID`, `Stadium_Name`, `Gov_ID`, `City`.
- `Is_Floodlit`: 1 if stadium has lights.

### Sheet: `dist_Matrix`
- `Origin`: Stadium ID.
- Additional columns: Destination Stadium IDs with distance in km.

### Sheet: `Sec_Matrix`
- `home_team_ID`, `away_team_ID`.
- `banned_venue1_ID`, `banned_venue2_ID`.
- `forced_venue_ID`: Overrides home stadium for this pair.

## `data/expanded_calendar.xlsx`

### Sheet: `expanded_calendar` (Primary)
- `Day_ID`, `Date`, `Date time`, `Week_Num`, `Day_name`.
- `Is_FIFA`: 1 if global blackout.
- `Is_CAF`: 1 if potential CAF conflict.

### Sheet: `FIFA_DAYS1`
- List of authoritative FIFA dates.

### Sheet: `cont_blockers_updated1`
- Team-specific CAF blocker dates.

### Sheet: `unique_CAF_dates`
- Global CAF date list.
