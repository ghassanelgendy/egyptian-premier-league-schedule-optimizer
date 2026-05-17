import pandas as pd
import os

def expand(start_str, end_str):
    return pd.date_range(start_str, end_str).date.tolist()

def save_fifa(tag, dates):
    df = pd.DataFrame({'Date': sorted(list(set(dates)))})
    path = f'past seasons data/fifa_dates_{tag}.csv'
    df.to_csv(path, index=False)
    print(f"Saved {tag}: {len(df)} days")

# 18/19 (45 Days)
f1819 = []
for start, end in [("2018-09-03", "2018-09-11"), ("2018-10-08", "2018-10-16"), ("2018-11-12", "2018-11-20"), ("2019-03-18", "2019-03-26"), ("2019-06-03", "2019-06-11")]:
    f1819.extend(expand(start, end))
save_fifa("18_19", f1819)

# 19/20 (45 Days)
f1920 = []
for start, end in [("2019-09-02", "2019-09-10"), ("2019-10-07", "2019-10-15"), ("2019-11-11", "2019-11-19"), ("2020-03-23", "2020-03-31"), ("2020-06-01", "2020-06-09")]:
    f1920.extend(expand(start, end))
save_fifa("19_20", f1920)

# 20/21 (43 Days)
f2021 = []
for start, end in [("2020-10-05", "2020-10-13"), ("2020-11-09", "2020-11-17"), ("2021-03-22", "2021-03-30"), ("2021-05-31", "2021-06-15")]:
    f2021.extend(expand(start, end))
save_fifa("20_21", f2021)

# 21/22 (61 Days)
f2122 = []
for start, end in [("2021-08-30", "2021-09-07"), ("2021-10-04", "2021-10-12"), ("2021-11-08", "2021-11-16"), ("2022-01-24", "2022-02-01"), ("2022-03-21", "2022-03-29"), ("2022-05-30", "2022-06-14")]:
    f2122.extend(expand(start, end))
save_fifa("21_22", f2122)

# 22/23 (62 Days)
f2223 = []
for start, end in [("2022-09-19", "2022-09-27"), ("2022-11-14", "2022-12-18"), ("2023-03-20", "2023-03-28"), ("2023-06-12", "2023-06-20")]:
    f2223.extend(expand(start, end))
save_fifa("22_23", f2223)

# 23/24 (45 Days)
f2324 = []
for start, end in [("2023-09-04", "2023-09-12"), ("2023-10-09", "2023-10-17"), ("2023-11-13", "2023-11-21"), ("2024-03-18", "2024-03-26"), ("2024-06-03", "2024-06-11")]:
    f2324.extend(expand(start, end))
save_fifa("23_24", f2324)
