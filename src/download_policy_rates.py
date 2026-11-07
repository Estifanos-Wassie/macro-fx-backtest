"""Archive current-vintage FRED CSV responses without replacing earlier downloads."""

from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

import numpy as np
import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
START_DATE = "2014-01-01"
END_DATE = "2025-12-31"
CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SERIES = {
    "ECBDFR": {
        "name": "ECB Deposit Facility Rate for Euro Area",
        "column": "ecb_deposit_pct",
        "original_source": "European Central Bank",
        "release": "Key ECB Interest Rates",
    },
    "DFEDTARL": {
        "name": "Federal Funds Target Range - Lower Limit",
        "column": "fed_lower_pct",
        "original_source": "Board of Governors of the Federal Reserve System (US)",
        "release": "FOMC Press Release",
    },
    "DFEDTARU": {
        "name": "Federal Funds Target Range - Upper Limit",
        "column": "fed_upper_pct",
        "original_source": "Board of Governors of the Federal Reserve System (US)",
        "release": "FOMC Press Release",
    },
}


def parse_policy_csv(content: bytes, series_id: str) -> pd.DataFrame:
    """Parse percent levels; allow explicit missing markers and negative rates."""
    if series_id not in SERIES:
        raise ValueError(f"Unknown policy series: {series_id}")
    data = pd.read_csv(BytesIO(content), keep_default_na=False, na_values=["", "."])
    if list(data.columns) != ["observation_date", series_id] or data.empty:
        raise ValueError(f"{series_id}: expected nonempty observation_date,{series_id} CSV.")
    try:
        dates = pd.to_datetime(data["observation_date"], format="%Y-%m-%d", errors="raise")
        rates = pd.to_numeric(data[series_id], errors="raise")
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{series_id}: invalid source date or numeric rate.") from exc
    if dates.isna().any() or dates.duplicated().any():
        raise ValueError(f"{series_id}: missing or duplicate source dates.")
    if np.isinf(rates).any():
        raise ValueError(f"{series_id}: infinite source rates.")
    return pd.DataFrame({"source_date": dates, "rate_pct": rates}).sort_values(
        "source_date"
    ).reset_index(drop=True)


def describe_source(data: pd.DataFrame, start: str, end: str) -> dict:
    """Require endpoint coverage; report missing values and absent calendar rows."""
    first, last = pd.Timestamp(start), pd.Timestamp(end)
    if first > last or data.source_date.min() != first or data.source_date.max() != last:
        raise ValueError(f"Source date coverage must span exactly {start} through {end}.")
    absent = pd.date_range(first, last).difference(data.source_date)
    missing = data.loc[data.rate_pct.isna(), "source_date"]
    if data.rate_pct.notna().sum() == 0:
        raise ValueError("Source has no usable numeric observations.")
    return {
        "source_start_date": data.source_date.min().date().isoformat(),
        "source_end_date": data.source_date.max().date().isoformat(),
        "observation_count": len(data),
        "missing_value_count": int(data.rate_pct.isna().sum()),
        "missing_value_dates": [d.date().isoformat() for d in missing],
        "absent_calendar_date_count": len(absent),
        "absent_calendar_dates": [d.date().isoformat() for d in absent],
    }


def download_policy_rates(
    raw_directory: Path = PROJECT_ROOT / "data/raw/policy_rates",
    start: str = START_DATE,
    end: str = END_DATE,
    get=None,
) -> Path:
    """Download only the requested series, preserving bytes before validation.

    Failed HTTP/CSV responses and an explicit failure manifest are retained.
    Mocked tests inject `get`; actual verification uses requests.get.
    """
    get = requests.get if get is None else get
    now = datetime.now(timezone.utc)
    directory = Path(raw_directory) / now.strftime("%Y%m%dT%H%M%S%fZ")
    directory.mkdir(parents=True, exist_ok=False)
    manifest_path = directory / "metadata.json"
    metadata = {
        "status": "incomplete",
        "requested_start_date": start,
        "requested_end_date": end,
        "vintage": "Current-vintage historical series at retrieval; not real-time vintage data.",
        "series": {},
    }
    try:
        for series_id, details in SERIES.items():
            params = {"id": series_id, "cosd": start, "coed": end}
            request_url = requests.Request("GET", CSV_URL, params=params).prepare().url
            entry = {
                **details, "series_id": series_id,
                "series_url": f"https://fred.stlouisfed.org/series/{series_id}",
                "request_url": request_url,
                "units": "Percent", "seasonal_adjustment": "Not Seasonally Adjusted",
                "frequency": "Daily, 7-Day",
                "requested_start_date": start, "requested_end_date": end,
            }
            metadata["series"][series_id] = entry
            response = get(CSV_URL, params=params, timeout=60)
            entry["retrieved_at_utc"] = datetime.now(timezone.utc).isoformat()
            entry["http_status"] = response.status_code
            entry["response_url"] = response.url
            entry["raw_file"] = f"{series_id}.csv"
            (directory / entry["raw_file"]).write_bytes(response.content)
            entry["sha256"] = sha256(response.content).hexdigest()
            response.raise_for_status()
            entry.update(describe_source(parse_policy_csv(response.content, series_id), start, end))
            print(f"{series_id}: {entry['source_start_date']} through {entry['source_end_date']}; "
                  f"{entry['observation_count']} rows; {entry['missing_value_count']} missing values; "
                  f"{entry['absent_calendar_date_count']} absent calendar dates")
        metadata["status"] = "complete"
    except Exception as exc:
        metadata["status"] = "failed"
        metadata["error"] = f"{type(exc).__name__}: {exc}"
        raise RuntimeError(f"Policy download failed; details and any response bytes: {manifest_path}: {exc}") from exc
    finally:
        metadata["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        manifest_path.write_text(json.dumps(metadata, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return manifest_path


def main() -> None:
    print(f"Download metadata: {download_policy_rates()}")


if __name__ == "__main__":
    main()
