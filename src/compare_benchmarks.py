"""Aligned retrospective comparisons under the baseline's daily FX model."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

if __package__:
    from .backtest import INITIAL_EQUITY, ONE_WAY_COST, run_backtest
    from .evaluate_performance import evaluate_performance
else:
    from backtest import INITIAL_EQUITY, ONE_WAY_COST, run_backtest
    from evaluate_performance import evaluate_performance

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CALCULATED = [
    "position", "gross_return", "turnover", "turnover_cost",
    "terminal_closing_cost", "net_return", "equity",
]


def validate_baseline(data: pd.DataFrame) -> pd.DataFrame:
    """Reconcile the saved baseline to the unchanged model; use saved results."""
    missing = set(["date", "eurusd", "fx_return", "signal"] + CALCULATED) - set(data.columns)
    if missing:
        raise ValueError(f"Missing baseline columns: {sorted(missing)}")
    # run_backtest validates dates, rates, returns, signals and numeric fields.
    expected = run_backtest(data)
    baseline = data.copy().reset_index(drop=True)
    baseline["date"] = expected["date"]
    for column in CALCULATED:
        try:
            baseline[column] = pd.to_numeric(baseline[column], errors="raise")
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Saved baseline {column} must be numeric.") from exc
        if not np.allclose(baseline[column], expected[column], rtol=1e-10, atol=1e-12):
            raise ValueError(f"Saved baseline {column} disagrees with the baseline model.")
    evaluate_performance(baseline)
    return baseline


def build_benchmarks(baseline: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Build a constant long and a flat reference without delaying holdings twice.

    The shared engine accepts signals, not held positions. Place synthetic long
    instructions exactly two rows before the desired held positions, then let
    run_backtest apply its normal lag once. Verify the resulting held positions.
    Fail clearly when there is no baseline exposure to define a shared start.
    """
    saved = validate_baseline(baseline)
    active = np.flatnonzero(saved["position"].to_numpy() != 0)
    if len(active) == 0:
        raise ValueError("Baseline has no active held position to anchor the long benchmark.")
    start = int(active[0])
    if start < 2:
        raise ValueError("First baseline position must respect the two-row signal lag.")
    source = saved[["date", "eurusd", "fx_return"]].copy()
    source["signal"] = 0
    source.loc[start - 2:len(source) - 3, "signal"] = 1
    long = run_backtest(source)
    desired = np.arange(len(source)) >= start
    if not np.array_equal(long["position"].to_numpy(), desired.astype(int)):
        raise ValueError("Long benchmark timing does not match the baseline's first active date.")
    expected_turnover = np.zeros(len(source), dtype=int)
    expected_turnover[start] = 1
    expected_close = np.zeros(len(source))
    expected_close[-1] = ONE_WAY_COST
    if (not np.array_equal(long["turnover"], expected_turnover)
            or not np.allclose(long["turnover_cost"], expected_turnover * ONE_WAY_COST)
            or not np.allclose(long["terminal_closing_cost"], expected_close)):
        raise ValueError("Long benchmark must have exactly one entry and one final liquidation.")
    if long.loc[long["position"].ne(0), "date"].iloc[0] != saved.loc[start, "date"]:
        raise ValueError("Long and baseline first active dates differ.")
    source["signal"] = 0
    flat = run_backtest(source)
    if (not flat[CALCULATED[:-1]].eq(0).all().all()
            or not flat["equity"].eq(INITIAL_EQUITY).all()):
        raise ValueError("Flat reference must have zero exposure, returns, and costs.")
    return {"baseline": saved, "long_eur": long, "flat_reference": flat}


def compare_benchmarks(baseline: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Return metric rows, aligned wide curves with audit fields, and metadata."""
    portfolios = build_benchmarks(baseline)
    curves = pd.DataFrame({"date": portfolios["baseline"]["date"]})
    summaries = []
    evaluations = {}
    definitions = None
    evaluation = None
    for name, portfolio in portfolios.items():
        report, drawdown = evaluate_performance(portfolio)
        if not portfolio["date"].equals(curves["date"]):
            raise ValueError("Portfolio dates are not identical.")
        if evaluation is not None and report["evaluation"] != evaluation:
            raise ValueError("Portfolio evaluation dates or observation counts differ.")
        evaluation = report["evaluation"]
        definitions = report["metric_definitions"]
        summaries.append({"portfolio": name, **report["metrics"]})
        for column in CALCULATED:
            curves[f"{name}_{column}"] = portfolio[column]
        curves[f"{name}_drawdown"] = drawdown["drawdown"]
        evaluations[name] = {
            "metrics": report["metrics"],
            "final_equity_usd": report["final_equity_usd"],
        }
    flat_metrics = evaluations["flat_reference"]["metrics"]
    if (flat_metrics["zero_reference_rate_sharpe"] is not None
            or any(flat_metrics[k] != 0 for k in (
                "total_return", "cagr", "maximum_drawdown", "annualized_volatility"
            ))):
        raise ValueError("Flat reference must have zero metrics and undefined Sharpe.")
    long = portfolios["long_eur"]
    start = int(np.flatnonzero(long["position"])[0])
    metadata = {
        "scope": "Retrospective full-period diagnostics; not out-of-sample results.",
        "evaluation": evaluation,
        "initial_capital_usd": INITIAL_EQUITY,
        "one_way_cost_rate": ONE_WAY_COST,
        "metric_definitions": definitions,
        "portfolio_definitions": {
            "baseline": "Saved moving-average baseline net returns and equity, without modification.",
            "long_eur": "Constant +1 long EUR exposure under the daily equity-relative exposure model, starting with the baseline's first held position; not a literal fixed-quantity currency holding.",
            "flat_reference": "Zero positions, returns, costs, and drawdown; constant initial equity. Zero-interest reference, not historical cash investment performance.",
        },
        "long_eur_execution": {
            "entry_observation_date": long.loc[start - 1, "date"].date().isoformat(),
            "first_active_return_date": long.loc[start, "date"].date().isoformat(),
            "liquidation_date": long["date"].iloc[-1].date().isoformat(),
            "normal_turnover_units": int(long["turnover"].sum()),
            "terminal_turnover_units": int(abs(long["position"].iloc[-1])),
            "total_turnover_units_including_liquidation": int(long["turnover"].sum() + abs(long["position"].iloc[-1])),
            "entry_cost_return_fraction": float(long["turnover_cost"].sum()),
            "terminal_cost_return_fraction": float(long["terminal_closing_cost"].sum()),
            "cost_booking": "Entry at the preceding observation is charged on the first active return row; terminal liquidation is charged separately on the final row.",
        },
        "assumptions": [
            "Initial valuation excluded from return statistics; genuine flat warmup returns and terminal liquidation costs retained.",
            "Sample standard deviation ddof=1; sqrt(252) annualization convention; zero-reference-rate Sharpe, not adjusted for historical cash rates.",
            "CAGR uses actual elapsed calendar days / 365.25; drawdown includes initial capital in the running peak.",
            "Metrics use fractional units; Sharpe is dimensionless. Undefined CSV metrics are blank; JSON uses null.",
            "ECB reference rates are execution proxies, not guaranteed fills; excludes financing/carry, cash interest, and daily exposure resizing costs. Not fully tradable FX performance.",
            "Baseline parameters, two-row signal delay, and illustrative one-way cost of 0.0001 are unchanged. Shared benchmark start is anchored retrospectively to the baseline.",
        ],
        "portfolios": evaluations,
    }
    return pd.DataFrame(summaries), curves, metadata


def main() -> None:
    directory = PROJECT_ROOT / "data/processed"
    summary, curves, metadata = compare_benchmarks(pd.read_csv(directory / "baseline_backtest.csv"))
    summary.to_csv(directory / "benchmark_comparison.csv", index=False)
    curves.to_csv(directory / "benchmark_curves.csv", index=False, date_format="%Y-%m-%d")
    (directory / "benchmark_metadata.json").write_text(
        json.dumps(metadata, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(summary.to_string(index=False))
    print(json.dumps(metadata["long_eur_execution"], indent=2))


if __name__ == "__main__":
    main()
