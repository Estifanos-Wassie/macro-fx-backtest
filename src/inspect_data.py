from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
file_path = PROJECT_ROOT / "data" / "raw" / "eurusd_ecb.csv"

df = pd.read_csv(file_path)

# Convert the two fields we need into dates and numbers.
dates = pd.to_datetime(df["TIME_PERIOD"], errors="coerce")
rates = pd.to_numeric(df["OBS_VALUE"], errors="coerce")

print("First five observations:")
print(df[["TIME_PERIOD", "OBS_VALUE"]].head())

print("\nData quality checks:")
print("Missing or invalid dates:", dates.isna().sum())
print("Missing or invalid rates:", rates.isna().sum())
print("Duplicate dates:", dates.duplicated().sum())
print("Zero or negative rates:", (rates <= 0).sum())
print("Dates in ascending order:", dates.is_monotonic_increasing)