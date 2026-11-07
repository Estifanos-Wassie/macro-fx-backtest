"""Fixed 63-FX-observation policy-differential change signal; no performance."""

from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOOKBACK = 63
ZERO_TOLERANCE_PP = 1e-10  # Absolute floating-point handling, not an economic threshold.
SERIES_IDS = ("ECBDFR", "DFEDTARL", "DFEDTARU")
RATE_COLUMNS = (
    "ecb_deposit_pct", "fed_lower_pct", "fed_upper_pct",
    "fed_midpoint_pct", "rate_differential_pp",
)


def validate_aligned_data(data: pd.DataFrame) -> pd.DataFrame:
    """Validate prepared values and their original one-day availability audit.

    No sorting, interpolation, realignment, or replacement of rates is done.
    Arithmetic checks use absolute tolerance 1e-10 and zero relative tolerance.
    """
    audit_columns = [f"{sid}_{suffix}" for sid in SERIES_IDS for suffix in (
        "source_date", "assumed_available_date", "source_age_days"
    )]
    required = {"date", "eurusd", *RATE_COLUMNS, *audit_columns}
    if not data.columns.is_unique or data.empty:
        raise ValueError("Aligned data must be nonempty with unique columns.")
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"Missing aligned columns: {sorted(missing)}")
    if {"macro_change_pp", "macro_signal"} & set(data.columns):
        raise ValueError("Input already contains macro signal output columns.")
    result = data.copy().reset_index(drop=True)
    date_columns = ["date"] + [f"{sid}_{suffix}" for sid in SERIES_IDS
                               for suffix in ("source_date", "assumed_available_date")]
    for column in date_columns:
        try:
            result[column] = pd.to_datetime(result[column], format="%Y-%m-%d", errors="raise")
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid dates in {column}.") from exc
        if result[column].isna().any():
            raise ValueError(f"Missing dates in {column}.")
    dates = result["date"]
    if dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise ValueError("FX dates must be unique and chronological in original order.")
    numeric_columns = ["eurusd", *RATE_COLUMNS] + [f"{sid}_source_age_days" for sid in SERIES_IDS]
    for column in numeric_columns:
        try:
            result[column] = pd.to_numeric(result[column], errors="raise")
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{column} must be numeric.") from exc
        if not np.isfinite(result[column]).all():
            raise ValueError(f"{column} must be finite with no missing values.")
    if not result.eurusd.gt(0).all():
        raise ValueError("EUR/USD rates must be positive.")
    if result.fed_lower_pct.gt(result.fed_upper_pct).any():
        raise ValueError("Fed lower bound exceeds upper bound.")
    midpoint = (result.fed_lower_pct + result.fed_upper_pct) / 2
    differential = result.ecb_deposit_pct - midpoint
    for column, expected in (("fed_midpoint_pct", midpoint), ("rate_differential_pp", differential)):
        if not np.isfinite(expected).all() or not np.allclose(
            result[column], expected, rtol=0, atol=ZERO_TOLERANCE_PP
        ):
            raise ValueError(f"Inconsistent {column} arithmetic.")
    for sid in SERIES_IDS:
        source = result[f"{sid}_source_date"]
        available = result[f"{sid}_assumed_available_date"]
        if available.gt(dates).any():
            raise ValueError(f"{sid}: future-dated assumed availability.")
        if not available.eq(source + pd.Timedelta(days=1)).all():
            raise ValueError(f"{sid}: assumed availability must preserve the one-calendar-day lag.")
        ages = (dates - source).dt.days
        if (not ages.between(1, 7).all()
                or not result[f"{sid}_source_age_days"].eq(ages).all()):
            raise ValueError(f"{sid}: inconsistent or stale source ages.")
    return result


def generate_macro_signals(data: pd.DataFrame) -> pd.DataFrame:
    """Add the fixed absolute change and its sign; retain all input observations.

    Row 63 compares to row 0. Changes within +/-1e-10 percentage points are
    numerical zero with no relative tolerance. Changes themselves stay unrounded.
    This is a signal, not a held position. A later backtest applies the existing
    two-observation execution delay once; this function applies no execution lag.
    """
    result = validate_aligned_data(data)
    result["macro_change_pp"] = result["rate_differential_pp"].diff(LOOKBACK)
    if not np.isfinite(result["macro_change_pp"].iloc[LOOKBACK:]).all():
        raise ValueError("Macro changes must be finite after warmup.")
    result["macro_signal"] = 0
    result.loc[result.macro_change_pp.gt(ZERO_TOLERANCE_PP), "macro_signal"] = 1
    result.loc[result.macro_change_pp.lt(-ZERO_TOLERANCE_PP), "macro_signal"] = -1
    return result


def main() -> None:
    directory = PROJECT_ROOT / "data/processed"
    data = pd.read_csv(directory / "policy_rates_aligned.csv")
    if len(data) != 2816:
        raise ValueError("Expected the original 2,816 aligned FX observations.")
    result = generate_macro_signals(data)
    output = directory / "macro_signals.csv"
    result.to_csv(output, index=False, date_format="%Y-%m-%d")
    print(f"Saved {len(result)} rows to: {output}")
    print("Signal counts:")
    print(result.macro_signal.value_counts().reindex([-1, 0, 1], fill_value=0))
    print(f"Warmup zeros: {LOOKBACK}; eligible zeros: {result.macro_signal.iloc[LOOKBACK:].eq(0).sum()}")


if __name__ == "__main__":
    main()
