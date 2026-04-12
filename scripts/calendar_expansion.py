import pandas as pd
from datetime import datetime

# ---------------- CONFIGURATION ----------------
# Exact name of your Excel file (make sure the typo .xlxs vs .xlsx is correct on your computer)
INPUT_FILE = "data/calendar.xlsx" 
SHEET_NAME = "MAINCALENDAR"  # The specific tab/sheet name
OUTPUT_FILE = "expanded_calendar.csv"

# Define the Date Ranges
WINTER_START = datetime(2026, 12, 21).date()
SPRING_START = datetime(2027, 3, 30).date()

# Define Time Slots
SLOTS_SUMMER_AUTUMN = ["17:00", "20:00", "22:00"]       # Aug 1 - Dec 20
SLOTS_WINTER        = ["14:30", "17:00", "19:00", "21:00"] # Dec 21 - Mar 29
SLOTS_SPRING        = ["17:00", "20:00", "22:00"]       # Mar 30 - End
# -----------------------------------------------

def get_time_slots(date_obj):
    """Returns the list of time slots based on the season."""
    date_val = date_obj.date()
    
    if date_val < WINTER_START:
        return SLOTS_SUMMER_AUTUMN
    elif WINTER_START <= date_val < SPRING_START:
        return SLOTS_WINTER
    else:
        return SLOTS_SPRING

try:
    print(f"Reading file '{INPUT_FILE}' (Sheet: {SHEET_NAME})...")
    
    # READ EXCEL INSTEAD OF CSV
    df = pd.read_excel(INPUT_FILE, sheet_name=SHEET_NAME)
    
    # Ensure Date column is datetime
    df['Date_Obj'] = pd.to_datetime(df['Date'])

    new_rows = []
    print("Expanding rows...")

    for _, row in df.iterrows():
        # Get slots for this date
        time_slots = get_time_slots(row['Date_Obj'])
        
        for time_str in time_slots:
            new_row = row.copy()
            
            # Create "Date time" column
            # This makes a string like: "2026-08-01 17:00"
            # We assume the excel date is already clean.
            # If your excel date has time attached (00:00:00), .dt.date removes it.
            date_part = row['Date_Obj'].date() 
            dt_str = f"{date_part} {time_str}"
            
            new_row['Date time'] = dt_str
            new_rows.append(new_row)

    # Create new DataFrame
    expanded_df = pd.DataFrame(new_rows)

    # Drop helper column
    if 'Date_Obj' in expanded_df.columns:
        expanded_df.drop(columns=['Date_Obj'], inplace=True)

    # Reorder columns preference
    desired_order = [
        'Day_ID', 'Week_Num', 'Date time', 'day', 'month', 'year', 'Day_name', 
        'Is_FIFA', 'Is_CAF', 'Is_Ramadan', 'FIFA_DAY', 'CAF_CL_ROUND', 
        'CAF_CC_ROUND', 'Is_SuperCup'
    ]
    
    # Organize columns safely
    final_cols = [col for col in desired_order if col in expanded_df.columns]
    remaining_cols = [col for col in expanded_df.columns if col not in final_cols]
    final_df = expanded_df[final_cols + remaining_cols]

    # Save result
    final_df.to_csv(OUTPUT_FILE, index=False)
    print(f"Success! File saved as: {OUTPUT_FILE}")

except FileNotFoundError:
    print(f"Error: Could not find '{INPUT_FILE}'. Check the name and folder.")
except ValueError as e:
    print(f"Error: Could not find sheet '{SHEET_NAME}'. Check your Excel tabs.")
except Exception as e:
    print(f"An error occurred: {e}")