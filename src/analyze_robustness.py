"""Bounded retrospective sensitivities; no parameter search or holdout claims."""

from datetime import date
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd

if __package__:
    from .backtest import INITIAL_EQUITY, ONE_WAY_COST, run_position_backtest
    from .compare_benchmarks import CALCULATED
    from .compare_common_window import build_common_portfolios, derive_common_boundaries, validate_signals
    from .evaluate_performance import evaluate_performance
else:
    from backtest import INITIAL_EQUITY, ONE_WAY_COST, run_position_backtest
    from compare_benchmarks import CALCULATED
    from compare_common_window import build_common_portfolios, derive_common_boundaries, validate_signals
    from evaluate_performance import evaluate_performance

PROJECT_ROOT = Path(__file__).resolve().parents[1]
COST_BPS = (0, 1, 5, 10)
EXECUTION_SHIFTS = (2, 3, 5)
PORTFOLIOS = ("baseline", "macro", "long_eur", "flat_reference")


def simulate_execution_scenario(baseline, macro, shift, initial_index):
    """Lag full-history signals once, slice the shared window, simulate from cash.

    Inputs are reconciled by validate_signals before scenario construction.
    The existing policy availability lag is untouched.
    """
    if shift not in EXECUTION_SHIFTS or initial_index + 1 >= len(baseline):
        raise ValueError("Unsupported execution shift or insufficient shared-window history.")
    window = baseline[["date", "eurusd", "fx_return"]].iloc[initial_index:].reset_index(drop=True).copy()
    window.loc[0, "fx_return"] = np.nan
    window["signal"] = 0
    result = {}
    for name in PORTFOLIOS:
        if name in ("baseline", "macro"):
            signal = baseline.signal if name == "baseline" else macro.macro_signal
            held = signal.shift(shift, fill_value=0).iloc[initial_index:].reset_index(drop=True).copy()
        else:
            held = pd.Series(int(name == "long_eur"), index=window.index)
        held.iloc[0] = 0
        result[name] = run_position_backtest(window, held, one_way_cost=ONE_WAY_COST)
    return result


def reconcile_original(portfolios, saved_summary, saved_curves):
    """Require the original scenario to reproduce saved curves and every metric."""
    if ("portfolio" not in saved_summary or saved_summary.portfolio.duplicated().any()
            or set(saved_summary.portfolio) != set(PORTFOLIOS)):
        raise ValueError("Saved comparison must contain exactly four unique portfolios.")
    summary = saved_summary.set_index("portfolio")
    saved_dates = pd.to_datetime(saved_curves["date"], errors="raise").reset_index(drop=True)
    for name, portfolio in portfolios.items():
        if not portfolio.date.equals(saved_dates):
            raise ValueError("Original scenario dates differ from saved common-window curves.")
        report, drawdown = evaluate_performance(portfolio)
        for column in CALCULATED + ["drawdown"]:
            expected = drawdown.drawdown if column == "drawdown" else portfolio[column]
            if not np.allclose(saved_curves[f"{name}_{column}"], expected, rtol=1e-10, atol=1e-12):
                raise ValueError(f"Original scenario {name} {column} differs from saved results.")
        for metric, expected in report["metrics"].items():
            saved = summary.loc[name, metric]
            if (expected is None and not pd.isna(saved)) or (
                expected is not None and not np.isclose(saved, expected, rtol=1e-10, atol=1e-12)
            ):
                raise ValueError(f"Original scenario {name} {metric} differs from saved results.")


def calendar_year_returns(saved_curves):
    """Compound the original net rows by interval-ending year; never reset trades."""
    rows = []
    for name in PORTFOLIOS:
        data = saved_curves[["date", f"{name}_net_return", f"{name}_equity"]].rename(
            columns={f"{name}_net_return": "net_return", f"{name}_equity": "equity"}
        ).copy()
        report, _ = evaluate_performance(data)
        data["date"] = pd.to_datetime(data["date"])
        initial, final = data.date.iloc[0].date(), data.date.iloc[-1].date()
        evaluated = data.iloc[1:]  # Only the no-interval initial valuation is excluded.
        annual_factors = []
        for year, group in evaluated.groupby(evaluated.date.dt.year):
            factor = float((1 + group.net_return).prod())
            annual_factors.append(factor)
            partial = initial > date(int(year), 1, 1) or final < date(int(year), 12, 31)
            rows.append({
                "portfolio": name, "year": int(year), "partial_year": partial,
                "return_observation_count": len(group),
                "first_return_date": group.date.iloc[0].date().isoformat(),
                "last_return_date": group.date.iloc[-1].date().isoformat(),
                "annual_return": factor - 1,
            })
        if not np.isclose(np.prod(annual_factors) - 1, report["metrics"]["total_return"], rtol=0, atol=1e-10):
            raise ValueError(f"{name}: annual compounding does not reconcile to common-window return.")
    return pd.DataFrame(rows)


def analyze_robustness(baseline, macro, saved_summary, saved_curves):
    """Return scenario tables, JSON-compatible metadata, and reusable simulations."""
    baseline, macro = validate_signals(baseline, macro)
    original, boundaries = build_common_portfolios(baseline, macro)
    reconcile_original(original, saved_summary, saved_curves)
    cost_scenarios, delay_scenarios = {}, {}
    rows = {"cost_sensitivity": [], "delay_sensitivity": []}
    original_evaluation = None
    definitions = None
    for bps in COST_BPS:
        cost_scenarios[bps] = {}
        for name, portfolio in original.items():
            # Reprice the identical held positions; no new signal lag is applied.
            data = portfolio[["date", "eurusd", "fx_return", "signal"]]
            simulated = run_position_backtest(data, portfolio.position, one_way_cost=bps / 10000)
            if not simulated.position.equals(portfolio.position):
                raise ValueError("Cost scenarios changed positions.")
            report, _ = evaluate_performance(simulated)  # Requires positive equity/growth factors.
            original_evaluation = report["evaluation"]
            definitions = report["metric_definitions"]
            rows["cost_sensitivity"].append({"one_way_cost_bps": bps, "execution_shift": 2,
                                              "portfolio": name, **report["metrics"]})
            cost_scenarios[bps][name] = simulated
            if bps == 0 and not np.array_equal(simulated.net_return, simulated.gross_return):
                raise ValueError("Zero-cost net and gross returns disagree.")
            if bps > 0:
                prior = COST_BPS[COST_BPS.index(bps) - 1]
                if simulated.equity.iloc[-1] > cost_scenarios[prior][name].equity.iloc[-1]:
                    raise ValueError("Higher costs improved final equity with unchanged positions.")
    reconcile_original(cost_scenarios[1], saved_summary, saved_curves)
    first_return_index = boundaries["common_signal_eligibility_index"] + max(EXECUTION_SHIFTS)
    initial_index = first_return_index - 1
    if first_return_index != 68 or initial_index != 67 or first_return_index >= len(baseline):
        raise ValueError("Delay sensitivity requires first return index 68 and initial valuation index 67.")
    delay_evaluation = None
    for shift in EXECUTION_SHIFTS:
        delay_scenarios[shift] = simulate_execution_scenario(baseline, macro, shift, initial_index)
        for name, portfolio in delay_scenarios[shift].items():
            report, _ = evaluate_performance(portfolio)
            if delay_evaluation is not None and report["evaluation"] != delay_evaluation:
                raise ValueError("Delay sensitivity dates/counts differ across scenarios.")
            delay_evaluation = report["evaluation"]
            rows["delay_sensitivity"].append({"execution_shift": shift, "one_way_cost_bps": 1,
                                               "portfolio": name, **report["metrics"]})
    tables = {key: pd.DataFrame(value) for key, value in rows.items()}
    tables["annual_returns"] = calendar_year_returns(saved_curves)
    signs = {}
    for name in ("baseline", "macro"):
        family_signs = {key: np.sign(table.loc[table.portfolio.eq(name), "total_return"]).tolist()
                        for key, table in tables.items() if key != "annual_returns"}
        signs[name] = {
            "cost_scenarios_sign_change": len(set(family_signs["cost_sensitivity"])) > 1,
            "delay_scenarios_sign_change": len(set(family_signs["delay_sensitivity"])) > 1,
            "any_specified_scenario_sign_change": len(set(sum(family_signs.values(), []))) > 1,
        }
    metadata = {
        "scope": "Bounded retrospective sensitivity checks; not optimization, a preferred-rule selection, or out-of-sample/holdout validation.",
        "initial_capital_usd": INITIAL_EQUITY,
        "cost_sensitivity": {"one_way_cost_bps": list(COST_BPS), "execution_shift_observations": 2,
                             "boundaries": boundaries, "evaluation": original_evaluation},
        "delay_sensitivity": {"execution_shift_observations": list(EXECUTION_SHIFTS), "one_way_cost_bps": 1,
                              "first_return_index": first_return_index, "initial_valuation_index": initial_index,
                              "evaluation": delay_evaluation},
        "annual_returns": {"evaluation": original_evaluation,
                           "definition": "Product(1 + original net return) - 1 by interval-ending calendar year; no annual trade reset, entry, or liquidation. 2015 is partial.",
                           "compounding_reconciliation": "Passed for all four portfolios, absolute tolerance 1e-10."},
        "metric_definitions": definitions,
        "total_return_sign_checks": signs,
        "assumptions": [
            "Fixed 20/60 SMA and 63-observation differential change signals; no reversal of rules or additional lookback search.",
            "Policy-data assumed availability lag remains embedded. Execution shifts are signal-to-position lags applied exactly once on full history, not added to the existing two-row shift.",
            "Cost scenarios use identical original-window positions. Delay scenarios all reset to cash at the shared shorter window; long EUR starts at that same boundary in every scenario.",
            "All costs include initial entry, reversals (two turnover units), and separate final liquidation. Initial valuation rows have zero portfolio return/cost.",
            "Net-return statistics retain eligible flats and exclude initial valuation only. Zero-reference-rate Sharpe is undefined for flat portfolios; JSON null/CSV blank.",
            "CAGR uses actual calendar days/365.25; sample standard deviation ddof=1 and sqrt(252) annualization; initial-capital-aware drawdown is a positive loss magnitude.",
            "ECB reference execution proxies, not guaranteed fills; excludes financing/carry, cash interest and daily resizing costs. Current-vintage policy data and assumed publication availability retain revision/timing risk.",
            "Returns and drawdowns are fractions; Sharpe is dimensionless. No scenario is selected as preferred.",
        ],
        "checks": {"one_bp_reproduces_saved_results": True, "cost_positions_identical": True,
                   "positive_equity_factors": True, "cost_final_equity_monotonic": True,
                   "annual_compounding_reconciles": True},
    }
    return tables, metadata, {"cost": cost_scenarios, "delay": delay_scenarios}


def main():
    directory = PROJECT_ROOT / "data/processed"
    protected = {p: sha256(p.read_bytes()).hexdigest() for p in (PROJECT_ROOT / "data").rglob("*")
                 if p.is_file() and not p.name.startswith("robustness_")}
    baseline = pd.read_csv(directory / "baseline_signals.csv")
    macro = pd.read_csv(directory / "macro_signals.csv")
    if len(baseline) != 2816 or len(macro) != 2816:
        raise ValueError("Require the original 2,816 full-history observations.")
    tables, metadata, _ = analyze_robustness(
        baseline, macro, pd.read_csv(directory / "common_window_comparison.csv"),
        pd.read_csv(directory / "common_window_curves.csv"),
    )
    for name, table in tables.items():
        table.to_csv(directory / f"robustness_{name}.csv", index=False)
        print(f"\n{name}\n{table.to_string(index=False)}")
    if any(sha256(p.read_bytes()).hexdigest() != digest for p, digest in protected.items()):
        raise ValueError("A prior artifact changed during robustness analysis.")
    metadata["preserved_artifact_sha256"] = {str(p.relative_to(PROJECT_ROOT)): digest for p, digest in protected.items()}
    (directory / "robustness_metadata.json").write_text(
        json.dumps(metadata, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
