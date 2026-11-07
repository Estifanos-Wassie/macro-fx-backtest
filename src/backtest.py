"""Stylized FX exposure backtest using ECB reference rates as execution proxies."""

from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ONE_WAY_COST = 0.0001  # Illustrative 1 bp per unit; not a broker quote.
INITIAL_EQUITY = 10_000.0


def validate_input(data: pd.DataFrame) -> pd.DataFrame:
    """Return a validated copy; reject bad ordering rather than silently fixing it.

    Only the initial FX return and optional SMA warmup values may be missing.
    Return consistency allows small CSV floating-point round-trip differences.
    """
    required = {"date", "eurusd", "fx_return", "signal"}
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")
    if data.empty or not data.columns.is_unique:
        raise ValueError("Input must be nonempty with unique column names.")
    result = data.copy().reset_index(drop=True)
    try:
        result["date"] = pd.to_datetime(result["date"], errors="raise")
    except (ValueError, TypeError) as exc:
        raise ValueError("Dates must be valid.") from exc
    dates = result["date"]
    if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise ValueError("Dates must be nonmissing, unique, and ascending.")
    for column in ("eurusd", "fx_return", "signal"):
        try:
            result[column] = pd.to_numeric(result[column], errors="raise")
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{column} must be numeric.") from exc
    rates = result["eurusd"]
    if not np.isfinite(rates).all() or not rates.gt(0).all():
        raise ValueError("Rates must be finite and positive.")
    if not result["signal"].isin([-1, 0, 1]).all():
        raise ValueError("Signals must belong to {-1, 0, 1} with no missing values.")
    returns = result["fx_return"]
    if not pd.isna(returns.iloc[0]) or returns.isna().sum() != 1:
        raise ValueError("The initial FX return must be the sole missing return.")
    if not np.isfinite(returns.iloc[1:]).all():
        raise ValueError("Returns after the initial row must be finite.")
    expected = rates.pct_change(fill_method=None).iloc[1:]
    if not np.isfinite(expected).all() or not np.allclose(
        returns.iloc[1:], expected, rtol=1e-10, atol=1e-12
    ):
        raise ValueError("Supplied FX returns do not match rate percentage changes.")
    for column in result.columns.difference(list(required)):
        values = result[column]
        if column in ("sma_20", "sma_60"):
            window = int(column.split("_")[1])
            try:
                values = pd.to_numeric(values, errors="raise")
            except (ValueError, TypeError) as exc:
                raise ValueError(f"{column} must be numeric.") from exc
            warmup = np.arange(len(result)) < window - 1
            if not np.array_equal(values.isna().to_numpy(), warmup):
                raise ValueError(f"Unexpected missing values in {column}.")
            if not np.isfinite(values.iloc[window - 1:]).all():
                raise ValueError(f"Nonfinite values in {column}.")
        elif values.isna().any() or (
            pd.api.types.is_numeric_dtype(values) and not np.isfinite(values).all()
        ):
            raise ValueError(f"Unexpected missing or nonfinite values in {column}.")
    return result


def calculate_positions(signals: pd.Series) -> pd.Series:
    """s[t] is known after t, executes at t+1, and earns row t+2's return.

    The last two signals cannot earn an observed return and are unused.
    The final row's position describes its earning interval, before liquidation.
    """
    return signals.shift(2, fill_value=0).astype(int)


def run_backtest(
    data: pd.DataFrame,
    one_way_cost: float = ONE_WAY_COST,
    initial_equity: float = INITIAL_EQUITY,
) -> pd.DataFrame:
    """Preserve input fields and add positions, costs, returns, and equity.

    Costs are return fractions. Normal turnover is booked on the row of the
    interval starting with the position change. Final liquidation is separate.
    Excludes financing/carry, cash interest, and daily exposure resizing costs.
    """
    if not np.isfinite(one_way_cost) or one_way_cost < 0:
        raise ValueError("One-way cost must be finite and nonnegative.")
    if not np.isfinite(initial_equity) or initial_equity <= 0:
        raise ValueError("Initial equity must be finite and positive.")
    result = validate_input(data)
    result["position"] = calculate_positions(result["signal"])
    if result["position"].iloc[0] != 0:
        raise ValueError("Initial position must be zero before filling the initial return.")
    # Validation has established that this is the only missing return.
    earning_returns = result["fx_return"].fillna(0)
    result["gross_return"] = result["position"] * earning_returns
    previous = result["position"].shift(1, fill_value=0)
    result["turnover"] = (result["position"] - previous).abs()
    result["turnover_cost"] = one_way_cost * result["turnover"]
    result["terminal_closing_cost"] = 0.0
    result.loc[result.index[-1], "terminal_closing_cost"] = (
        abs(result["position"].iloc[-1]) * one_way_cost
    )
    result["net_return"] = (
        result["gross_return"] - result["turnover_cost"] - result["terminal_closing_cost"]
    )
    result["equity"] = initial_equity * (1 + result["net_return"]).cumprod()
    if not np.isfinite(result["equity"]).all():
        raise ValueError("Compounded equity is nonfinite.")
    return result


def main() -> None:
    input_path = PROJECT_ROOT / "data/processed/baseline_signals.csv"
    output_path = PROJECT_ROOT / "data/processed/baseline_backtest.csv"
    result = run_backtest(pd.read_csv(input_path))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_path, index=False, date_format="%Y-%m-%d")
    print(f"Saved {len(result)} rows to: {output_path}")
    print(f"Final simulated equity: ${result['equity'].iloc[-1]:,.2f}")


if __name__ == "__main__":
    main()
