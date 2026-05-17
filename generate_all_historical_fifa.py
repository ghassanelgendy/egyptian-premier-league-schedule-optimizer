import pandas as pd
import os

def expand(start_str, end_str):
    start = pd.to_datetime(start_str)
    end = pd.to_datetime(end_str)
    return pd.date_range(start, end).date.tolist()

def save_fifa(tag, dates):
    os.makedirs('past seasons data', exist_ok=True)
    df = pd.DataFrame({'Date': sorted(list(set(dates)))})
    path = f'past seasons data/fifa_dates_{tag}.csv'
    df.to_csv(path, index=False)
    print(f"Saved {tag}: {len(df)} days to {path}")

# 2018/19
f1819 = []
f1819.extend(expand("2018-09-03", "2018-09-11"))
f1819.extend(expand("2018-10-08", "2018-10-16"))
f1819.extend(expand("2018-11-12", "2018-11-20"))
f1819.extend(expand("2019-03-18", "2019-03-26"))
f1819.extend(expand("2019-06-03", "2019-06-11"))
f1819.extend(expand("2019-06-14", "2019-07-07"))
save_fifa("18_19", f1819)

# 2019/20
f1920 = []
f1920.extend(expand("2019-09-02", "2019-09-10"))
f1920.extend(expand("2019-10-07", "2019-10-15"))
f1920.extend(expand("2019-11-11", "2019-11-19"))
save_fifa("19_20", f1920)

# 2020/21
f2021 = []
f2021.extend(expand("2020-08-31", "2020-09-08"))
f2021.extend(expand("2020-10-05", "2020-10-13"))
f2021.extend(expand("2020-11-09", "2020-11-17"))
f2021.extend(expand("2021-03-22", "2021-03-30"))
f2021.extend(expand("2021-05-31", "2021-06-15"))
f2021.extend(expand("2021-06-11", "2021-07-11"))
save_fifa("20_21", f2021)

# 2021/22
f2122 = []
f2122.extend(expand("2021-08-30", "2021-09-08"))
f2122.extend(expand("2021-10-04", "2021-10-12"))
f2122.extend(expand("2021-11-08", "2021-11-16"))
f2122.extend(expand("2022-01-09", "2022-02-06"))
f2122.extend(expand("2022-01-24", "2022-02-01"))
f2122.extend(expand("2022-03-21", "2022-03-29"))
f2122.extend(expand("2022-05-30", "2022-06-14"))
save_fifa("21_22", f2122)

# 2022/23
f2223 = []
f2223.extend(expand("2022-09-19", "2022-09-27"))
f2223.extend(expand("2022-11-14", "2022-12-18"))
f2223.extend(expand("2023-03-20", "2023-03-28"))
f2223.extend(expand("2023-06-12", "2023-06-20"))
save_fifa("22_23", f2223)

# 2023/24
f2324 = []
f2324.extend(expand("2023-09-04", "2023-09-12"))
f2324.extend(expand("2023-10-09", "2023-10-17"))
f2324.extend(expand("2023-11-13", "2023-11-21"))
f2324.extend(expand("2024-01-12", "2024-02-11"))
f2324.extend(expand("2024-03-18", "2024-03-26"))
f2324.extend(expand("2024-06-03", "2024-06-11"))
f2324.extend(expand("2024-06-14", "2024-07-14"))
save_fifa("23_24", f2324)
