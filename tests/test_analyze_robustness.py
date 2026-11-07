import unittest

import numpy as np
import pandas as pd

from src.analyze_robustness import COST_BPS, PORTFOLIOS, analyze_robustness, calendar_year_returns
from src.compare_common_window import compare_common_window
from src.generate_macro_signals import generate_macro_signals


def fixture():
    dates = pd.date_range("2020-10-15", periods=90)
    rates = pd.Series(1 + np.arange(90) * .002)
    baseline = pd.DataFrame({"date": dates, "eurusd": rates})
    baseline["fx_return"] = rates.pct_change(fill_method=None)
    baseline["sma_20"] = rates.rolling(20).mean()
    baseline["sma_60"] = rates.rolling(60).mean()
    baseline["signal"] = (baseline.sma_20.gt(baseline.sma_60).astype(int)
                          - baseline.sma_20.lt(baseline.sma_60).astype(int))
    differential = np.array([-2.] * 63 + ([-1., -1., -3., -3., -2., -2.] * 5)[:27])
    macro = pd.DataFrame({"date": dates, "eurusd": rates, "ecb_deposit_pct": differential + .125,
                          "fed_lower_pct": 0., "fed_upper_pct": .25,
                          "fed_midpoint_pct": .125, "rate_differential_pp": differential})
    for sid in ("ECBDFR", "DFEDTARL", "DFEDTARU"):
        macro[f"{sid}_source_date"] = dates - pd.Timedelta(days=1)
        macro[f"{sid}_assumed_available_date"] = dates
        macro[f"{sid}_source_age_days"] = 1
    return baseline, generate_macro_signals(macro)


class RobustnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline, cls.macro = fixture()
        cls.summary, cls.curves, _ = compare_common_window(cls.baseline, cls.macro)
        cls.tables, cls.metadata, cls.scenarios = analyze_robustness(
            cls.baseline, cls.macro, cls.summary, cls.curves
        )

    def test_zero_cost_net_equals_gross_and_positions_fixed(self):
        for name in PORTFOLIOS:
            zero = self.scenarios["cost"][0][name]
            np.testing.assert_array_equal(zero.net_return, zero.gross_return)
            self.assertEqual(zero.turnover_cost.sum() + zero.terminal_closing_cost.sum(), 0)
            for bps in COST_BPS:
                pd.testing.assert_series_equal(self.scenarios["cost"][bps][name].position, zero.position)

    def test_increasing_cost_cannot_improve_equity_with_positive_factors(self):
        for name in PORTFOLIOS:
            final = []
            for bps in COST_BPS:
                portfolio = self.scenarios["cost"][bps][name]
                self.assertTrue((1 + portfolio.net_return).gt(0).all())
                final.append(portfolio.equity.iloc[-1])
            self.assertEqual(final, sorted(final, reverse=True))

    def test_reversal_entry_and_terminal_costs_in_every_cost_scenario(self):
        for bps in COST_BPS:
            rate = bps / 10000
            macro = self.scenarios["cost"][bps]["macro"]
            reversals = macro.turnover.eq(2)
            self.assertTrue(reversals.any())
            np.testing.assert_allclose(macro.loc[reversals, "turnover_cost"], 2 * rate)
            self.assertEqual(macro.turnover_cost.iloc[1], rate)
            self.assertEqual(macro.terminal_closing_cost.iloc[-1], rate)
            self.assertEqual(macro.terminal_closing_cost.iloc[:-1].sum(), 0)
            long = self.scenarios["cost"][bps]["long_eur"]
            self.assertEqual(long.turnover_cost.sum(), rate)
            self.assertEqual(long.terminal_closing_cost.sum(), rate)

    def test_delay_shared_dates_lag_once_and_cash_reset(self):
        dates = self.baseline.date.iloc[67:].reset_index(drop=True)
        for shift, portfolios in self.scenarios["delay"].items():
            for name, portfolio in portfolios.items():
                pd.testing.assert_series_equal(portfolio.date, dates)
                self.assertEqual(portfolio.position.iloc[0], 0)
                self.assertEqual(portfolio.equity.iloc[0], 10000)
                self.assertEqual(portfolio.net_return.iloc[0], 0)
                self.assertEqual(portfolio.turnover_cost.iloc[0], 0)
                if name in ("baseline", "macro"):
                    source = self.baseline.signal if name == "baseline" else self.macro.macro_signal
                    np.testing.assert_array_equal(portfolio.position.iloc[1:], source.iloc[68-shift:-shift])
                    self.assertEqual(portfolio.turnover_cost.iloc[1], abs(source.iloc[68-shift]) * .0001)
            np.testing.assert_array_equal(portfolios["long_eur"].position, [0] + [1] * (len(dates)-1))
        self.assertEqual(self.metadata["delay_sensitivity"]["first_return_index"], 68)
        self.assertEqual(self.metadata["delay_sensitivity"]["evaluation"]["return_observation_count"], 22)

    def test_original_one_bp_reproduces_saved_results(self):
        for name in PORTFOLIOS:
            portfolio = self.scenarios["cost"][1][name]
            np.testing.assert_allclose(portfolio.net_return, self.curves[f"{name}_net_return"], rtol=0, atol=0)
            np.testing.assert_allclose(portfolio.equity, self.curves[f"{name}_equity"], rtol=0, atol=0)
        cost = self.tables["cost_sensitivity"].query("one_way_cost_bps == 1").set_index("portfolio")
        for metric in ("total_return", "cagr", "zero_reference_rate_sharpe", "maximum_drawdown"):
            np.testing.assert_allclose(cost[metric], self.summary.set_index("portfolio")[metric], equal_nan=True)

    def test_annual_hand_calculation_no_new_year_trade_reset(self):
        curves = pd.DataFrame({"date": ["2020-12-30", "2020-12-31", "2021-01-04"]})
        for name in PORTFOLIOS:
            curves[f"{name}_net_return"] = [0, .0999, -.1001] if name != "flat_reference" else [0, 0, 0]
            curves[f"{name}_equity"] = [10000, 10999, 9898.0001] if name != "flat_reference" else [10000] * 3
        annual = calendar_year_returns(curves)
        baseline = annual.loc[annual.portfolio.eq("baseline")]
        np.testing.assert_allclose(baseline.annual_return, [.0999, -.1001])
        self.assertEqual(baseline.return_observation_count.tolist(), [1, 1])
        for name in PORTFOLIOS:
            group = self.tables["annual_returns"].loc[lambda t: t.portfolio.eq(name)]
            self.assertAlmostEqual((1 + group.annual_return).prod() - 1,
                                   self.summary.set_index("portfolio").loc[name, "total_return"], places=12)
            self.assertEqual(group.return_observation_count.sum(), 25)

    def test_inconsistent_saved_results_rejected(self):
        bad = self.curves.copy()
        bad.loc[1, "baseline_net_return"] += .001
        with self.assertRaisesRegex(ValueError, "differs from saved"):
            analyze_robustness(self.baseline, self.macro, self.summary, bad)
        bad = self.summary.copy()
        bad.loc[0, "total_return"] += .1
        with self.assertRaisesRegex(ValueError, "differs from saved"):
            analyze_robustness(self.baseline, self.macro, bad, self.curves)
        bad = self.curves.copy()
        bad.loc[2, "macro_net_return"] = np.nan
        with self.assertRaises(ValueError):
            calendar_year_returns(bad)


if __name__ == "__main__":
    unittest.main()
