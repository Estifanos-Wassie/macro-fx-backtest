"""Four-portfolio retrospective comparison with common eligibility and cash reset."""

from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd

if __package__:
    from .backtest import (EXECUTION_LAG, INITIAL_EQUITY, ONE_WAY_COST,
                           calculate_positions, run_position_backtest, validate_input)
    from .compare_benchmarks import CALCULATED
    from .evaluate_performance import evaluate_performance
    from .generate_macro_signals import LOOKBACK, ZERO_TOLERANCE_PP, generate_macro_signals
else:
    from backtest import (EXECUTION_LAG, INITIAL_EQUITY, ONE_WAY_COST,
                          calculate_positions, run_position_backtest, validate_input)
    from compare_benchmarks import CALCULATED
    from evaluate_performance import evaluate_performance
    from generate_macro_signals import LOOKBACK, ZERO_TOLERANCE_PP, generate_macro_signals

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def validate_signals(baseline: pd.DataFrame, macro: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Reconcile saved indicators/signals against their fixed definitions."""
    if not {"sma_20", "sma_60"}.issubset(baseline.columns):
        raise ValueError("Baseline requires full-history sma_20 and sma_60 columns.")
    baseline = validate_input(baseline)
    for window in (20, 60):
        expected = baseline.eurusd.rolling(window, min_periods=window).mean()
        if not np.allclose(baseline[f"sma_{window}"], expected, equal_nan=True, rtol=0, atol=1e-12):
            raise ValueError(f"Saved SMA {window} differs from the fixed baseline rule.")
    expected_signals = (baseline.sma_20.gt(baseline.sma_60).astype(int)
                        - baseline.sma_20.lt(baseline.sma_60).astype(int))
    if not baseline.signal.equals(expected_signals):
        # Accept numeric signals even if their CSV dtype is float.
        if not np.array_equal(baseline.signal, expected_signals):
            raise ValueError("Baseline signals differ from the fixed SMA rule.")
    if not {"macro_change_pp", "macro_signal"}.issubset(macro.columns) or not macro.columns.is_unique:
        raise ValueError("Require unique macro columns including macro_change_pp and macro_signal.")
    expected_macro = generate_macro_signals(macro.drop(columns=["macro_change_pp", "macro_signal"]))
    try:
        changes = pd.to_numeric(macro["macro_change_pp"], errors="raise").reset_index(drop=True)
        signals = pd.to_numeric(macro["macro_signal"], errors="raise").reset_index(drop=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("Saved macro changes and signals must be numeric.") from exc
    if (not np.array_equal(changes.isna(), expected_macro.macro_change_pp.isna())
            or not np.allclose(changes, expected_macro.macro_change_pp, equal_nan=True,
                               rtol=0, atol=ZERO_TOLERANCE_PP)
            or not np.array_equal(signals, expected_macro.macro_signal)):
        raise ValueError("Saved macro changes or signals differ from the fixed 63-observation rule.")
    macro = expected_macro.copy()
    # Keep supplied values after reconciliation; do not replace saved signals.
    macro["macro_change_pp"], macro["macro_signal"] = changes, signals
    if (not baseline.date.equals(macro.date)
            or not np.array_equal(baseline.eurusd, macro.eurusd)):
        raise ValueError("Full-history baseline and macro dates/rates must match exactly.")
    return baseline, macro


def derive_common_boundaries(baseline: pd.DataFrame, macro: pd.DataFrame) -> dict:
    """Derive history eligibility; neutral eligible signals still count."""
    baseline_ready = baseline.sma_20.notna() & baseline.sma_60.notna()
    macro_ready = macro.macro_change_pp.notna()
    expected = np.arange(len(baseline))
    if (not np.array_equal(baseline_ready, expected >= 59)
            or not np.array_equal(macro_ready, expected >= LOOKBACK)):
        raise ValueError("Expected contiguous baseline eligibility at index 59 and macro at index 63.")
    shared = np.flatnonzero(baseline_ready & macro_ready)
    if len(shared) == 0 or EXECUTION_LAG != 2 or LOOKBACK != 63:
        raise ValueError("Insufficient shared history or changed fixed execution/lookback assumptions.")
    signal_index = int(shared[0])
    first_return = signal_index + EXECUTION_LAG
    initial = first_return - 1
    if initial != 64 or first_return != 65 or first_return >= len(baseline):
        raise ValueError("Common window requires valuation index 64, first return index 65, and observed returns.")
    return {
        "baseline_signal_eligibility_index": int(np.flatnonzero(baseline_ready)[0]),
        "macro_signal_eligibility_index": int(np.flatnonzero(macro_ready)[0]),
        "common_signal_eligibility_index": signal_index,
        "initial_valuation_index": initial,
        "first_return_index": first_return,
    }


def build_common_portfolios(baseline: pd.DataFrame, macro: pd.DataFrame) -> tuple[dict, dict]:
    """Lag full-history signals once, then slice holdings and reset to cash."""
    baseline, macro = validate_signals(baseline, macro)
    boundaries = derive_common_boundaries(baseline, macro)
    initial = boundaries["initial_valuation_index"]
    full_positions = {
        "baseline": calculate_positions(baseline.signal),
        "macro": calculate_positions(macro.macro_signal),
    }
    window = baseline[["date", "eurusd", "fx_return"]].iloc[initial:].reset_index(drop=True).copy()
    # The boundary's preceding interval is outside this new simulation.
    window.loc[0, "fx_return"] = np.nan
    window["signal"] = 0  # The held-position engine never delays these placeholders.
    portfolios = {}
    for name in ("baseline", "macro", "long_eur", "flat_reference"):
        if name in full_positions:
            held = full_positions[name].iloc[initial:].reset_index(drop=True).copy()
        else:
            held = pd.Series(1 if name == "long_eur" else 0, index=window.index)
        held.iloc[0] = 0  # No pre-window position, equity, or cost is carried in.
        portfolio = run_position_backtest(window, held)
        if (portfolio.loc[0, ["position", "net_return", "turnover_cost", "terminal_closing_cost"]].ne(0).any()
                or portfolio.equity.iloc[0] != INITIAL_EQUITY):
            raise ValueError("Common initial valuation must be cash with no returns or costs.")
        portfolios[name] = portfolio
    return portfolios, boundaries


def compare_common_window(baseline: pd.DataFrame, macro: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    portfolios, boundaries = build_common_portfolios(baseline, macro)
    initial = boundaries["initial_valuation_index"]
    curves = portfolios["baseline"][["date", "fx_return"]].copy()
    curves["full_history_row_index"] = np.arange(initial, len(baseline))
    full_dates = pd.to_datetime(baseline.date).reset_index(drop=True)
    origin_dates = full_dates.shift(EXECUTION_LAG).iloc[initial:].reset_index(drop=True)
    origin_dates.iloc[0] = pd.NaT  # No earning position on the boundary row.
    summaries, reports, diagnostics = [], {}, {}
    common_evaluation = None
    for name, portfolio in portfolios.items():
        report, drawdown = evaluate_performance(portfolio)
        if not portfolio.date.equals(curves.date):
            raise ValueError("Common portfolio dates do not match.")
        if common_evaluation is not None and common_evaluation != report["evaluation"]:
            raise ValueError("Common portfolio evaluation periods/counts differ.")
        common_evaluation = report["evaluation"]
        summaries.append({"portfolio": name, **report["metrics"]})
        reports[name] = {"metrics": report["metrics"], "final_equity_usd": report["final_equity_usd"]}
        for column in CALCULATED:
            curves[f"{name}_{column}"] = portfolio[column]
        curves[f"{name}_drawdown"] = drawdown.drawdown
        if name in ("baseline", "macro"):
            curves[f"{name}_originating_signal_date"] = origin_dates
        diagnostics[name] = {
            "exposure_fraction": float(portfolio.position.iloc[1:].ne(0).mean()),
            "normal_position_change_count": int(portfolio.turnover.iloc[1:].gt(0).sum()),
            "normal_turnover_units": int(portfolio.turnover.sum()),
            "terminal_liquidation_units": int(abs(portfolio.position.iloc[-1])),
            "total_turnover_units_including_liquidation": int(portfolio.turnover.sum() + abs(portfolio.position.iloc[-1])),
        }
    metadata = {
        "scope": "Retrospective common-window diagnostics; not a holdout or out-of-sample evaluation. No parameter tuning or winning-rule selection.",
        "boundaries": boundaries,
        "evaluation": common_evaluation,
        "initial_capital_usd": INITIAL_EQUITY,
        "execution_lag_observations": EXECUTION_LAG,
        "one_way_cost_rate": ONE_WAY_COST,
        "signal_definitions": {
            "baseline": "Sign of 20-observation SMA minus 60-observation SMA; full windows; eligibility starts at 59 regardless of signal sign.",
            "macro": "d = ECB deposit minus Fed target midpoint in percentage points; sign of d[t]-d[t-63], with absolute <=1e-10 treated as zero, no relative tolerance; eligibility starts at 63.",
            "long_eur": "Constant +1 equity-relative daily EUR exposure from the common execution boundary; not fixed-quantity currency holdings.",
            "flat_reference": "Flat zero-interest reference; not historical cash investment performance; undefined Sharpe.",
        },
        "metric_definitions": report["metric_definitions"],
        "diagnostic_definitions": {
            "exposure_fraction": "Nonzero held-position return rows / all evaluated return rows; excludes initial valuation, includes eligible macro flats in denominator.",
            "normal_position_change_count": "Return rows where held position differs from preceding row, with initial cash zero; excludes separate terminal liquidation.",
            "total_turnover_units_including_liquidation": "Sum abs(position[t]-position[t-1]) from cash plus abs(final held position); reversal contributes two units.",
        },
        "assumptions": [
            "Derive eligibility from history, compute signal.shift(2) on full history once, then slice and reset to cash at the common valuation.",
            "Initial valuation row has zero portfolio return and cost; first evaluated return row pays entry turnover from cash. Final liquidation cost is separate on final row.",
            "Macro policy-data availability lag is already embedded and remains intact. Eligible zero signals remain flat periods.",
            "All portfolios start at $10,000; net-return statistics exclude only initial valuation; sample ddof=1, sqrt(252) annualization convention, zero-reference Sharpe, actual calendar days/365.25 CAGR, initial-capital-aware drawdown.",
            "Illustrative 1-bp one-way cost per turnover unit. Excludes financing/carry, cash interest, daily resizing costs. ECB reference rates are execution proxies, not guaranteed fills; not fully tradable FX performance.",
            "Policy data are current vintage with assumed one-day availability; historical publication timing and revision risk remain unresolved.",
            "Fractional metric units; undefined values are blank in CSV and null in JSON. Earlier full-period artifacts are preserved.",
        ],
        "portfolios": reports,
        "diagnostics": diagnostics,
    }
    return pd.DataFrame(summaries), curves, metadata


def main() -> None:
    directory = PROJECT_ROOT / "data/processed"
    protected = {p: sha256(p.read_bytes()).hexdigest() for p in (PROJECT_ROOT / "data").rglob("*")
                 if p.is_file() and not p.name.startswith("common_window_")}
    baseline = pd.read_csv(directory / "baseline_signals.csv")
    macro = pd.read_csv(directory / "macro_signals.csv")
    if len(baseline) != 2816 or len(macro) != 2816:
        raise ValueError("Expected the original 2,816 full-history FX observations.")
    summary, curves, metadata = compare_common_window(baseline, macro)
    summary.to_csv(directory / "common_window_comparison.csv", index=False)
    curves.to_csv(directory / "common_window_curves.csv", index=False, date_format="%Y-%m-%d")
    if any(sha256(p.read_bytes()).hexdigest() != value for p, value in protected.items()):
        raise ValueError("A pre-existing data artifact changed during comparison.")
    metadata["preserved_artifact_sha256"] = {str(p.relative_to(PROJECT_ROOT)): value for p, value in protected.items()}
    (directory / "common_window_metadata.json").write_text(
        json.dumps(metadata, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(summary.to_string(index=False))
    print(json.dumps(metadata["evaluation"], indent=2))
    print(json.dumps(metadata["diagnostics"]["macro"], indent=2))


if __name__ == "__main__":
    main()
