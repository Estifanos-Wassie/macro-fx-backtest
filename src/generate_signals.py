from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
input_path = PROJECT_ROOT / "data" / "processed" / "eurusd_returns.csv"
output_path = PROJECT_ROOT / "data" / "processed" / "baseline_signals.csv"

df = pd.read_csv(input_path)
df["date"] = pd.to_datetime(df["date"], errors="raise")
df = df.sort_values("date").reset_index(drop=True)

# Windows count reference observations, not calendar days.
df["sma_20"] = df["eurusd"].rolling(window=20, min_periods=20).mean()
df["sma_60"] = df["eurusd"].rolling(window=60, min_periods=60).mean()

# Equal or unavailable averages leave the signal neutral.
df["signal"] = 0
df.loc[df["sma_20"] > df["sma_60"], "signal"] = 1
df.loc[df["sma_20"] < df["sma_60"], "signal"] = -1

# This signal is available only after its observation; it cannot earn
# the fx_return on the same row, which precedes that observation.
output_path.parent.mkdir(parents=True, exist_ok=True)
df.to_csv(output_path, index=False, date_format="%Y-%m-%d")

print(f"Saved {len(df)} rows to: {output_path}")
print("Signal counts:")
print(df["signal"].value_counts().sort_index())
