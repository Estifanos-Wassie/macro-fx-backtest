from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
input_path = PROJECT_ROOT / "data" / "raw" / "eurusd_ecb.csv"
output_path = PROJECT_ROOT / "data" / "processed" / "eurusd_clean.csv"

# Keep the fields needed for our analysis.
df = pd.read_csv(input_path, usecols=["TIME_PERIOD", "OBS_VALUE"])
df = df.rename(columns={
    "TIME_PERIOD": "date",
    "OBS_VALUE": "eurusd",
})

# Convert types; stop if an entry cannot be converted.
df["date"] = pd.to_datetime(df["date"], errors="raise")
df["eurusd"] = pd.to_numeric(df["eurusd"], errors="raise")

# Stop rather than silently discard problematic observations.
if df.empty or df.isna().any().any():
    raise ValueError("The dataset is empty or contains missing values.")

if df["date"].duplicated().any() or (df["eurusd"] <= 0).any():
    raise ValueError("Duplicate dates or nonpositive rates found.")

df = df.sort_values("date").reset_index(drop=True)

output_path.parent.mkdir(parents=True, exist_ok=True)
df.to_csv(output_path, index=False, date_format="%Y-%m-%d")

print(f"Saved {len(df)} rows to: {output_path}")
print(df.head())
