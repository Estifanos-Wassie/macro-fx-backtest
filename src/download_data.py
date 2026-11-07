from pathlib import Path

import requests

# Find the project folder.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Request daily USD-per-EUR observations for a fixed research period.
url = "https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A"
params = {
    "startPeriod": "2015-01-01",
    "endPeriod": "2025-12-31",
    "format": "csvdata",
}

print("Downloading EUR/USD data from the ECB...")

response = requests.get(url, params=params, timeout=60)
response.raise_for_status()

# Preserve the original download before cleaning it.
output_path = PROJECT_ROOT / "data" / "raw" / "eurusd_ecb.csv"
output_path.parent.mkdir(parents=True, exist_ok=True)
output_path.write_bytes(response.content)

print(f"Download saved to: {output_path}")