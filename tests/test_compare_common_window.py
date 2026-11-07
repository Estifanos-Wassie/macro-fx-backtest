import unittest

import numpy as np
import pandas as pd

from src.backtest import calculate_positions, run_backtest, run_position_backtest
from src.compare_common_window import build_common_portfolios, compare_common_window
from src.evaluate_performance import evaluate_performance
from src.generate_macro_signals import generate_macro_signals


def inputs(length=80, differentials=None, rates=None):
    dates = pd.date_range("2020-01-01", periods=length)
    rates = np.arange(length) * .01 + 1 if rates is None else np.asarray(rates)
    baseline = pd.DataFrame({"date": dates, "eurusd": rates})
    baseline["fx_return"] = baseline.eurusd.pct_change(fill_method=None)
    baseline["sma_20"] = baseline.eurusd.rolling(20).mean()
    baseline["sma_60"] = baseline.eurusd.rolling(60).mean()
    baseline["signal"] = (baseline.sma_20.gt(baseline.sma_60).astype(int)
                          - baseline.sma_20.lt(baseline.sma_60).astype(int))
    d = np.full(length, -2.) if differentials is None else np.asarray(differentials)
    macro = pd.DataFrame({
        "date": dates, "eurusd": rates, "ecb_deposit_pct": d + .125,
        "fed_lower_pct": 0., "fed_upper_pct": .25,
        "fed_midpoint_pct": .125, "rate_differential_pp": d,
    })
    for sid in ("ECBDFR", "DFEDTARL", "DFEDTARU"):
        macro[f"{sid}_source_date"] = dates - pd.Timedelta(days=1)
        macro[f"{sid}_assumed_available_date"] = dates
        macro[f"{sid}_source_age_days"] = 1
    return baseline, generate_macro_signals(macro)


class CommonWindowTests(unittest.TestCase):
    def test_eligibility_independent_of_nonzero_signals(self):
        baseline, macro = inputs()
        portfolios, boundaries = build_common_portfolios(baseline, macro)
        self.assertEqual(boundaries["baseline_signal_eligibility_index"], 59)
        self.assertEqual(boundaries["macro_signal_eligibility_index"], 63)
        self.assertEqual(boundaries["initial_valuation_index"], 64)
        self.assertEqual(boundaries["first_return_index"], 65)
        self.assertTrue(portfolios["macro"].position.eq(0).all())
        self.assertEqual(len(portfolios["macro"]), 16)
        summary, _, metadata = compare_common_window(baseline, macro)
        self.assertEqual(metadata["evaluation"]["return_observation_count"], 15)
        self.assertTrue(pd.isna(summary.set_index("portfolio").loc["macro", "zero_reference_rate_sharpe"]))
        d = [-2.] * 80
        d[72:] = [-1.] * 8
        _, later_macro = inputs(differentials=d)
        later, later_boundary = build_common_portfolios(baseline, later_macro)
        self.assertEqual(later_boundary, boundaries)
        self.assertEqual(later["macro"].index[later["macro"].position.ne(0)][0], 10)  # 74 - 64

    def test_full_history_lag_once_and_cash_reset_entry(self):
        d = [-2.] * 80
        d[63:] = [-1.] * 17
        baseline, macro = inputs(differentials=d)
        original_baseline, original_macro = baseline.copy(deep=True), macro.copy(deep=True)
        portfolios, _ = build_common_portfolios(baseline, macro)
        for name, signals in (("baseline", baseline.signal), ("macro", macro.macro_signal)):
            portfolio = portfolios[name]
            self.assertEqual(portfolio.position.iloc[0], 0)
            self.assertEqual(portfolio.equity.iloc[0], 10000)
            self.assertEqual(portfolio.net_return.iloc[0], 0)
            self.assertEqual(portfolio.turnover_cost.iloc[0], 0)
            # Signal 63 is used at row 65, despite being before the valuation slice.
            self.assertEqual(portfolio.position.iloc[1], signals.iloc[63])
            np.testing.assert_array_equal(portfolio.position.iloc[1:], signals.iloc[63:-2])
            self.assertEqual(portfolio.turnover.iloc[1], 1)
            self.assertEqual(portfolio.turnover_cost.iloc[1], .0001)
            self.assertAlmostEqual(portfolio.equity.iloc[1], 10000 * (1 + baseline.fx_return.iloc[65] - .0001))
        # Full-period baseline already held +1, but common window must pay a fresh entry.
        full = run_backtest(baseline)
        self.assertEqual(full.position.iloc[64], 1)
        self.assertEqual(full.turnover.iloc[65], 0)
        self.assertNotEqual(full.equity.iloc[64], 10000)
        pd.testing.assert_frame_equal(baseline, original_baseline)
        pd.testing.assert_frame_equal(macro, original_macro)

    def test_hand_calculated_macro_flats_reversals_and_terminal_cost(self):
        d = [-2.] * 63 + [-1., -1., -2., -3., -1., -1., -2., -3., -3., -2., -2.]
        rates = [1.] * 65 + [1.1, .99, .99, .891, .9801, .9801, .9801, 1.07811, 1.07811]
        baseline, macro = inputs(length=74, differentials=d, rates=rates)
        portfolios, _ = build_common_portfolios(baseline, macro)
        portfolio = portfolios["macro"]
        self.assertEqual(portfolio.position.tolist(), [0, 1, 1, 0, -1, 1, 1, 0, -1, -1])
        self.assertEqual(portfolio.turnover.tolist(), [0, 1, 0, 1, 1, 2, 0, 1, 1, 0])
        np.testing.assert_allclose(portfolio.net_return, [0, .0999, -.1, -.0001, .0999, .0998, 0, -.0001, -.1001, -.0001], atol=1e-14)
        np.testing.assert_allclose(portfolio.terminal_closing_cost, [0] * 9 + [.0001])
        expected = 10000 * 1.0999 * .9 * .9999 * 1.0999 * 1.0998 * .9999 * .8999 * .9999
        self.assertAlmostEqual(portfolio.equity.iloc[-1], expected, places=8)
        _, _, metadata = compare_common_window(baseline, macro)
        diagnostic = metadata["diagnostics"]["macro"]
        self.assertEqual(diagnostic["exposure_fraction"], 7 / 9)
        self.assertEqual(diagnostic["normal_position_change_count"], 6)
        self.assertEqual(diagnostic["total_turnover_units_including_liquidation"], 8)

    def test_aligned_metrics_and_long_flat_references(self):
        baseline, macro = inputs()
        summary, curves, metadata = compare_common_window(baseline, macro)
        portfolios, _ = build_common_portfolios(baseline, macro)
        for name, portfolio in portfolios.items():
            report, drawdown = evaluate_performance(portfolio)
            self.assertEqual(report["evaluation"], metadata["evaluation"])
            pd.testing.assert_series_equal(portfolio.date, curves.date)
            for metric, expected in report["metrics"].items():
                actual = summary.set_index("portfolio").loc[name, metric]
                if expected is None:
                    self.assertTrue(pd.isna(actual))
                else:
                    self.assertAlmostEqual(actual, expected)
            np.testing.assert_allclose(curves[f"{name}_drawdown"], drawdown.drawdown)
        long = portfolios["long_eur"]
        self.assertEqual(long.position.tolist(), [0] + [1] * 15)
        self.assertEqual(long.turnover.sum(), 1)
        self.assertEqual(long.terminal_closing_cost.sum(), .0001)
        self.assertTrue(portfolios["flat_reference"].equity.eq(10000).all())
        self.assertTrue(curves.flat_reference_drawdown.eq(0).all())
        self.assertEqual(curves.macro_originating_signal_date.iloc[1], macro.date.iloc[63])

    def test_bad_history_alignment_and_saved_signals_fail(self):
        baseline, macro = inputs()
        with self.assertRaisesRegex(ValueError, "valuation index"):
            build_common_portfolios(baseline.iloc[:65], macro.iloc[:65])
        bad = baseline.copy()
        bad.loc[59, "sma_60"] = np.nan
        with self.assertRaises(ValueError):
            build_common_portfolios(bad, macro)
        bad = macro.copy()
        bad.loc[63, "macro_signal"] = 1
        with self.assertRaisesRegex(ValueError, "fixed 63-observation"):
            build_common_portfolios(baseline, bad)
        bad = macro.copy()
        bad.loc[63, "macro_change_pp"] = np.nan
        with self.assertRaises(ValueError):
            build_common_portfolios(baseline, bad)
        bad = baseline.copy()
        bad["date"] += pd.Timedelta(days=1)
        with self.assertRaisesRegex(ValueError, "match exactly"):
            build_common_portfolios(bad, macro)

    def test_held_position_engine_rejects_invalid_positions(self):
        baseline, _ = inputs()
        for held in (pd.Series([0]), pd.Series([2] * len(baseline)),
                     pd.Series([np.nan] * len(baseline)), pd.Series([1] * len(baseline))):
            with self.subTest(first=held.iloc[0]), self.assertRaises(ValueError):
                run_position_backtest(baseline, held)
        np.testing.assert_array_equal(calculate_positions(baseline.signal).iloc[2:], baseline.signal.iloc[:-2])


if __name__ == "__main__":
    unittest.main()
