"""Align percent policy levels with an assumed one-calendar-day availability lag."""

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd

if __package__:
    from .download_policy_rates import SERIES, describe_source, parse_policy_csv
else:
    from download_policy_rates import SERIES, describe_source, parse_policy_csv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAX_SOURCE_AGE_DAYS = 7


def validate_fed_bounds(lower: pd.DataFrame, upper: pd.DataFrame) -> None:
    """Check every common observed source date, not just FX-matched dates."""
    paired = lower.merge(upper, on="source_date", suffixes=("_lower", "_upper"))
    if paired.rate_pct_lower.gt(paired.rate_pct_upper).any():
        raise ValueError("Fed lower bound exceeds upper bound on a source observation date.")


def align_policy_rates(fx: pd.DataFrame, sources: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict]:
    """Backward-as-of each series independently, skipping reported missing rates.

    Availability = source date + one calendar day is a modeling assumption,
    not an established historical publication timestamp. Never interpolate or
    backfill from the future; age is measured from the matched source date.
    """
    if "date" not in fx.columns or fx.empty or not fx.columns.is_unique:
        raise ValueError("FX data require nonempty rows and a unique date column.")
    result = fx.copy().reset_index(drop=True)
    try:
        result["date"] = pd.to_datetime(result["date"], format="%Y-%m-%d", errors="raise")
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid FX dates.") from exc
    dates = result["date"]
    if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise ValueError("FX dates must be nonmissing, unique, and ascending in original order.")
    if set(sources) != set(SERIES):
        raise ValueError("Require exactly ECBDFR, DFEDTARL, and DFEDTARU sources.")
    # Validate reusable-function inputs, including callers not using the CSV parser.
    checked = {}
    summaries = {}
    for series_id, data in sources.items():
        if set(data.columns) != {"source_date", "rate_pct"} or data.empty:
            raise ValueError(f"{series_id}: require source_date and rate_pct observations.")
        canonical = data.rename(columns={"source_date": "observation_date", "rate_pct": series_id})
        checked[series_id] = parse_policy_csv(canonical.to_csv(index=False).encode(), series_id)
        current = checked[series_id]
        summaries[series_id] = describe_source(
            current, current.source_date.min().date().isoformat(), current.source_date.max().date().isoformat()
        )
    validate_fed_bounds(checked["DFEDTARL"], checked["DFEDTARU"])
    for series_id, data in checked.items():
        column = SERIES[series_id]["column"]
        source_col = f"{series_id}_source_date"
        availability_col = f"{series_id}_assumed_available_date"
        age_col = f"{series_id}_source_age_days"
        if {column, source_col, availability_col, age_col} & set(result.columns):
            raise ValueError("FX columns conflict with policy-rate output columns.")
        available = data.dropna(subset=["rate_pct"]).rename(
            columns={"source_date": source_col, "rate_pct": column}
        )
        available[availability_col] = available[source_col] + pd.Timedelta(days=1)
        result = pd.merge_asof(result, available, left_on="date", right_on=availability_col, direction="backward")
        if result[source_col].isna().any():
            bad = result.loc[result[source_col].isna(), "date"].dt.strftime("%Y-%m-%d").tolist()
            raise ValueError(f"{series_id}: unmatched FX dates: {bad[:5]}")
        ages = (result["date"] - result[source_col]).dt.days
        if ages.gt(MAX_SOURCE_AGE_DAYS).any():
            raise ValueError(f"{series_id}: stale source observation exceeds {MAX_SOURCE_AGE_DAYS} calendar days.")
        if not result[availability_col].le(result["date"]).all() or not ages.ge(1).all():
            raise ValueError(f"{series_id}: future data used before assumed availability.")
        result[age_col] = ages
        summaries[series_id]["maximum_matched_source_age_days"] = int(ages.max())
    if result.fed_lower_pct.gt(result.fed_upper_pct).any():
        raise ValueError("Fed lower bound exceeds upper bound after separate alignment.")
    result["fed_midpoint_pct"] = (result.fed_lower_pct + result.fed_upper_pct) / 2
    result["rate_differential_pp"] = result.ecb_deposit_pct - result.fed_midpoint_pct
    if not np.isfinite(result[["fed_midpoint_pct", "rate_differential_pp"]]).all().all():
        raise ValueError("Nonfinite policy arithmetic.")
    if len(result) != len(fx) or not result["date"].equals(dates):
        raise ValueError("FX dates or order changed during alignment.")
    return result, summaries


def process_policy_rates(manifest_path: Path, fx_path: Path, output_directory: Path) -> tuple[Path, Path]:
    """Verify archived hashes and coverage, align, and write auditable outputs."""
    manifest_path, fx_path, output_directory = map(Path, (manifest_path, fx_path, output_directory))
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest["status"] != "complete" or set(manifest["series"]) != set(SERIES):
        raise ValueError("Download manifest is incomplete or failed; cannot align it.")
    sources = {}
    for series_id, entry in manifest["series"].items():
        content = (manifest_path.parent / entry["raw_file"]).read_bytes()
        if sha256(content).hexdigest() != entry["sha256"]:
            raise ValueError(f"{series_id}: raw file hash differs from download manifest.")
        sources[series_id] = parse_policy_csv(content, series_id)
        describe_source(sources[series_id], manifest["requested_start_date"], manifest["requested_end_date"])
    fx_bytes = fx_path.read_bytes()
    fx = pd.read_csv(fx_path)
    if len(fx) != 2816:
        raise ValueError("Expected exactly the original 2,816 FX observation dates.")
    aligned, summaries = align_policy_rates(fx, sources)
    output_directory.mkdir(parents=True, exist_ok=True)
    csv_path = output_directory / "policy_rates_aligned.csv"
    metadata_path = output_directory / "policy_rates_metadata.json"
    csv_bytes = aligned.to_csv(index=False, date_format="%Y-%m-%d").encode()
    metadata = {
        "processed_at_utc": datetime.now(timezone.utc).isoformat(),
        "raw_manifest_path": str(manifest_path.resolve()),
        "raw_manifest_sha256": sha256(manifest_bytes).hexdigest(),
        "download_provenance": manifest,
        "fx_input": str(fx_path.resolve()), "fx_sha256": sha256(fx_bytes).hexdigest(),
        "aligned_sha256": sha256(csv_bytes).hexdigest(),
        "row_count": len(aligned),
        "fx_start_date": aligned.date.min().date().isoformat(),
        "fx_end_date": aligned.date.max().date().isoformat(),
        "source_summaries": summaries,
        "units": {"*_pct": "Percent levels", "rate_differential_pp": "Percentage points: ECB deposit minus Fed midpoint"},
        "assumptions": [
            "Source observation date + one calendar day is ASSUMED availability, not verified publication timing.",
            "Each series aligned separately using a backward as-of join; no future backfill or interpolation.",
            "Missing source rates are reported and skipped; prior valid observations permitted only within seven calendar days of their source dates.",
            "Current-vintage historical series; the lag neither establishes historical publication availability nor eliminates revision risk. Retrospective research only.",
            "Data preparation only; no macro trading signals or macro performance calculated.",
        ],
    }
    csv_path.write_bytes(csv_bytes)
    metadata_path.write_text(json.dumps(metadata, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    for series_id, summary in summaries.items():
        print(f"{series_id}: missing={summary['missing_value_count']}, "
              f"absent dates={summary['absent_calendar_date_count']}, "
              f"maximum source age={summary['maximum_matched_source_age_days']} days")
    print(f"Saved {len(aligned)} aligned rows to {csv_path}")
    return csv_path, metadata_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, help="Explicit raw download metadata.json; default is latest attempt.")
    args = parser.parse_args()
    manifest = args.manifest
    if manifest is None:
        candidates = sorted((PROJECT_ROOT / "data/raw/policy_rates").glob("*/metadata.json"))
        if not candidates:
            raise FileNotFoundError("No policy-rate download manifest; run download_policy_rates.py first.")
        manifest = candidates[-1]  # Fail on a failed latest attempt rather than silently reuse old data.
    process_policy_rates(manifest, PROJECT_ROOT / "data/processed/eurusd_clean.csv", PROJECT_ROOT / "data/processed")


if __name__ == "__main__":
    main()
