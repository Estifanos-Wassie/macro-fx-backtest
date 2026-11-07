from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
input_path = PROJECT_ROOT / "data" / "processed" / "eurusd_clean.csv"
output_path = PROJECT_ROOT / "data" / "processed" / "eurusd_returns.csv"

df = pd.read_csv(input_path, parse_dates=["date"])
df = df.sort_values("date").reset_index(drop=True)

# Fractional change from the previous available observation.
df["fx_return"] = df["eurusd"].pct_change(fill_method=None)

df.to_csv(output_path, index=False, date_format="%Y-%m-%d")

print(df.head())
print("Available returns:", df["fx_return"].notna().sum())
print(f"Saved to: {output_path}")