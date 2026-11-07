"""Download ECB reference observations, archiving bytes and provenance."""

import argparse
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
URL = "https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A"
PARAMS = {"startPeriod": "2015-01-01", "endPeriod": "2025-12-31", "format": "csvdata"}


def download_fx(raw_directory=PROJECT_ROOT / "data/raw", refresh=False, get=None):
    """Require explicit refresh before replacing a snapshot; retain old bytes."""
    raw_directory = Path(raw_directory)
    active = raw_directory / "eurusd_ecb.csv"
    if active.exists() and not refresh:
        raise FileExistsError(f"Raw snapshot exists: {active}; use --refresh to archive and replace it.")
    directory = raw_directory / "eurusd_snapshots" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory.mkdir(parents=True, exist_ok=False)
    metadata = {"status": "incomplete", "series_id": "EXR.D.USD.EUR.SP00.A", "source_url": URL,
                "requested_period": PARAMS.copy(), "units": "USD per EUR reference rate"}
    try:
        response = (requests.get if get is None else get)(URL, params=PARAMS, timeout=60)
        metadata.update({"retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                         "response_url": response.url, "http_status": response.status_code,
                         "sha256": sha256(response.content).hexdigest(), "raw_file": "response.csv"})
        (directory / "response.csv").write_bytes(response.content)
        response.raise_for_status()
        data = pd.read_csv(BytesIO(response.content))
        if not {"TIME_PERIOD", "OBS_VALUE"}.issubset(data.columns):
            raise ValueError("ECB response requires TIME_PERIOD and OBS_VALUE columns.")
        dates = pd.to_datetime(data.TIME_PERIOD, errors="raise")
        rates = pd.to_numeric(data.OBS_VALUE, errors="raise")
        if (len(data) != 2816 or dates.isna().any() or dates.duplicated().any()
                or not dates.is_monotonic_increasing or not np.isfinite(rates).all() or not rates.gt(0).all()
                or dates.min() != pd.Timestamp("2015-01-02") or dates.max() != pd.Timestamp("2025-12-31")):
            raise ValueError("ECB response violates the fixed research window or rate quality checks.")
        metadata.update({"observation_count": len(data), "source_start_date": dates.min().date().isoformat(),
                         "source_end_date": dates.max().date().isoformat()})
        if active.exists():
            shutil.copyfile(active, directory / "previous_eurusd_ecb.csv")
            metadata["previous_snapshot_sha256"] = sha256(active.read_bytes()).hexdigest()
            old_metadata = raw_directory / "eurusd_ecb_metadata.json"
            if old_metadata.exists():
                shutil.copyfile(old_metadata, directory / "previous_metadata.json")
        active.write_bytes(response.content)
        metadata["status"] = "complete"
    except Exception as exc:
        metadata.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
        raise RuntimeError(f"ECB download failed; preserved response/provenance in {directory}: {exc}") from exc
    finally:
        (directory / "metadata.json").write_text(json.dumps(metadata, indent=2, allow_nan=False) + "\n")
    metadata["archive_directory"] = str(directory.resolve())
    (raw_directory / "eurusd_ecb_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Downloaded {len(data)} ECB observations to {active}; archive: {directory}")
    return active


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="Archive and replace an existing active FX snapshot.")
    args = parser.parse_args()
    download_fx(refresh=args.refresh)


if __name__ == "__main__":
    main()
