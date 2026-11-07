"""Retrospective full-period diagnostics of the baseline's net returns."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INITIAL_EQUITY = 10_000.0
ANNUALIZATION = 252


def validate_backtest(data: pd.DataFrame, initial_equity: float) -> pd.DataFrame:
    """Validate valuation dates, net returns, and independently reconciled equity.

    Row zero is the initial valuation, with no elapsed return interval. No
    missing net return is allowed, including on that row. SMA warmup fields
    and the initial missing FX return are outside this evaluator's inputs.
    """
    if not np.isfinite(initial_equity) or initial_equity <= 0:
        raise ValueError("Initial equity must be finite and positive.")
    required = {"date", "net_return", "equity"}
    if not required.issubset(data.columns):
        raise ValueError(f"Missing required columns: {sorted(required - set(data.columns))}")
    if not data.columns.is_unique or len(data) < 2:
        raise ValueError("Require unique columns and at least two valuation rows.")
    result = data[["date", "net_return", "equity"]].copy().reset_index(drop=True)
    try:
        result["date"] = pd.to_datetime(result["date"], errors="raise")
    except (ValueError, TypeError) as exc:
        raise ValueError("Dates must be valid.") from exc
    dates = result["date"]
    if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise ValueError("Dates must be nonmissing, unique, and ascending.")
    if (dates.iloc[-1].date() - dates.iloc[0].date()).days <= 0:
        raise ValueError("Evaluation requires positive elapsed calendar days.")
    for column in ("net_return", "equity"):
        try:
            result[column] = pd.to_numeric(result[column], errors="raise")
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{column} must be numeric.") from exc
        if not np.isfinite(result[column]).all():
            raise ValueError(f"{column} must be finite with no missing values.")
    if not result["equity"].gt(0).all() or not result["net_return"].gt(-1).all():
        raise ValueError("Equity and all net return growth factors must be positive.")
    if result["net_return"].iloc[0] != 0:
        raise ValueError("Initial valuation row must have zero net return and no elapsed interval.")
    expected = initial_equity * (1 + result["net_return"]).cumprod()
    if not np.isfinite(expected).all() or not np.allclose(
        result["equity"], expected, rtol=1e-10, atol=1e-8
    ):
        raise ValueError("Stored equity is inconsistent with compounded net returns and initial equity.")
    return result


def return_statistics(net_returns: pd.Series) -> dict:
    """Sample volatility and zero-reference-rate Sharpe using sqrt(252).

    Input contains elapsed return intervals only, retaining genuine flat returns.
    Fewer than two returns leaves both statistics undefined; zero dispersion
    leaves Sharpe undefined. Undefined values are Python None for strict JSON.
    """
    values = np.asarray(net_returns, dtype=float)
    if values.ndim != 1 or not np.isfinite(values).all():
        raise ValueError("Return statistics require finite one-dimensional returns.")
    if len(values) < 2:
        return {"annualized_volatility": None, "zero_reference_rate_sharpe": None}
    # Exact constant samples have zero dispersion, even if mean rounding would
    # otherwise leave a tiny nonzero floating-point residual in np.std.
    std = 0.0 if (values == values[0]).all() else float(np.std(values, ddof=1))
    volatility = std * np.sqrt(ANNUALIZATION)
    sharpe = None if std == 0 else float(np.mean(values) / std * np.sqrt(ANNUALIZATION))
    if not np.isfinite(volatility) or (sharpe is not None and not np.isfinite(sharpe)):
        raise ValueError("Return statistics are nonfinite.")
    return {"annualized_volatility": float(volatility), "zero_reference_rate_sharpe": sharpe}


def calculate_drawdown(equity: pd.Series, initial_equity: float) -> pd.DataFrame:
    """Include initial capital in every running peak, even before a new high."""
    values = np.asarray(equity, dtype=float)
    if (not np.isfinite(initial_equity) or initial_equity <= 0 or values.ndim != 1
            or len(values) == 0 or not np.isfinite(values).all() or (values <= 0).any()):
        raise ValueError("Drawdown requires finite positive equity and initial capital.")
    peak = np.maximum.accumulate(np.maximum(values, initial_equity))
    return pd.DataFrame({"equity": values, "running_peak": peak, "drawdown": values / peak - 1})


def evaluate_performance(
    data: pd.DataFrame, initial_equity: float = INITIAL_EQUITY
) -> tuple[dict, pd.DataFrame]:
    """Return a JSON-compatible metrics report and dated drawdown series."""
    validated = validate_backtest(data, initial_equity)
    dates = validated["date"]
    elapsed_days = (dates.iloc[-1].date() - dates.iloc[0].date()).days
    elapsed_years = elapsed_days / 365.25
    ratio = float(validated["equity"].iloc[-1] / initial_equity)
    try:
        cagr = ratio ** (1 / elapsed_years) - 1
    except OverflowError as exc:
        raise ValueError("CAGR is nonfinite.") from exc
    if not np.isfinite(cagr):
        raise ValueError("CAGR is nonfinite.")
    drawdown = calculate_drawdown(validated["equity"], initial_equity)
    drawdown.insert(0, "date", dates)
    report = {
        "scope": "Retrospective full-period baseline diagnostics; not out-of-sample results.",
        "evaluation": {
            "initial_valuation_date": dates.iloc[0].date().isoformat(),
            "first_return_end_date": dates.iloc[1].date().isoformat(),
            "final_observation_date": dates.iloc[-1].date().isoformat(),
            "valuation_count": len(validated),
            "return_observation_count": len(validated) - 1,
            "elapsed_calendar_days": elapsed_days,
            "elapsed_years": elapsed_years,
            "year_convention": "Actual calendar days from initial valuation to final observation / 365.25",
        },
        "initial_capital_usd": float(initial_equity),
        "final_equity_usd": float(validated["equity"].iloc[-1]),
        "metrics": {
            "total_return": ratio - 1,
            "cagr": cagr,
            **return_statistics(validated["net_return"].iloc[1:]),
            "maximum_drawdown": float(max(0.0, -drawdown["drawdown"].min())),
        },
        "metric_definitions": {
            "total_return": "final_equity / initial_capital - 1; fractional return",
            "cagr": "(final_equity / initial_capital) ** (1 / elapsed_years) - 1; annual fractional return",
            "annualized_volatility": "sample_std(net_returns, ddof=1) * sqrt(252); annual fractional volatility",
            "zero_reference_rate_sharpe": "mean(net_returns) / sample_std(net_returns, ddof=1) * sqrt(252); dimensionless, zero reference rate",
            "drawdown": "equity / running_peak - 1; fraction, with initial capital included in running_peak",
            "maximum_drawdown": "positive loss magnitude of the most negative drawdown; fraction",
        },
        "assumptions": {
            "return_basis": "Net returns, including turnover and terminal liquidation costs; genuine warmup flat returns retained.",
            "initial_row": "Initial valuation excluded from return statistics; no elapsed return interval.",
            "annualization_observations": ANNUALIZATION,
            "annualization_convention": "252 is a daily-observation annualization convention, not an exact annual observation count.",
            "reference_rate": "Zero assumed; Sharpe is not adjusted for historical cash rates.",
            "undefined_metrics": "JSON null for sample statistics with fewer than two returns, or Sharpe with zero standard deviation.",
            "baseline_model": "Unchanged 20/60-observation SMA signals; signal.shift(2); illustrative one-way cost 0.0001 per turnover unit plus final liquidation.",
            "limitations": "ECB reference rates are execution proxies, not guaranteed fills. Excludes financing/carry, cash interest, and daily exposure resizing costs; not fully tradable FX performance.",
            "equity_reconciliation": "initial_capital * cumprod(1 + net_return), checked at every row (rtol=1e-10, atol=1e-8).",
        },
    }
    return report, drawdown


def main() -> None:
    directory = PROJECT_ROOT / "data/processed"
    report, drawdown = evaluate_performance(pd.read_csv(directory / "baseline_backtest.csv"))
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "baseline_metrics.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    drawdown.to_csv(directory / "baseline_drawdown.csv", index=False, date_format="%Y-%m-%d")
    print(json.dumps(report["metrics"], indent=2, allow_nan=False))
    print(f"Saved baseline_metrics.json and baseline_drawdown.csv to: {directory}")


if __name__ == "__main__":
    main()
