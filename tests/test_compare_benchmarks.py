import json
import math
import unittest

import numpy as np
import pandas as pd

from src.backtest import run_backtest
from src.compare_benchmarks import build_benchmarks, compare_benchmarks
from src.evaluate_performance import evaluate_performance


def example():
    return run_backtest(pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=5),
        "eurusd": [100, 110, 121, 108.9, 119.79],
        "fx_return": [np.nan, .1, .1, -.1, .1],
        "signal": [-1, 1, 0, -1, 1],
    }))


class BenchmarkTests(unittest.TestCase):
    def test_hand_calculated_long_timing_costs_and_compounding(self):
        baseline = example()
        portfolios = build_benchmarks(baseline)
        long = portfolios["long_eur"]
        self.assertEqual(long.position.tolist(), [0, 0, 1, 1, 1])
        self.assertEqual(baseline.position.tolist(), [0, 0, -1, 1, 0])
        self.assertEqual(long.turnover.tolist(), [0, 0, 1, 0, 0])
        np.testing.assert_allclose(long.turnover_cost, [0, 0, .0001, 0, 0])
        np.testing.assert_allclose(long.terminal_closing_cost, [0, 0, 0, 0, .0001])
        np.testing.assert_allclose(long.net_return, [0, 0, .0999, -.1, .0999])
        np.testing.assert_allclose(long.equity, [10000, 10000, 10999, 9899.1, 10888.02009])
        summary, curves, metadata = compare_benchmarks(baseline)
        metrics = summary.set_index("portfolio").loc["long_eur"]
        self.assertAlmostEqual(metrics.total_return, .088802009)
        self.assertAlmostEqual(metrics.cagr, 1.088802009 ** (365.25 / 4) - 1)
        mean = (.0999 - .1 + .0999) / 4
        std = math.sqrt(((0 - mean)**2 + 2 * (.0999 - mean)**2 + (-.1 - mean)**2) / 3)
        self.assertAlmostEqual(metrics.annualized_volatility, std * math.sqrt(252))
        self.assertAlmostEqual(metrics.zero_reference_rate_sharpe, mean / std * math.sqrt(252))
        self.assertAlmostEqual(metrics.maximum_drawdown, .1)
        execution = metadata["long_eur_execution"]
        self.assertEqual(execution["entry_observation_date"], "2025-01-02")
        self.assertEqual(execution["first_active_return_date"], "2025-01-03")
        self.assertEqual(execution["total_turnover_units_including_liquidation"], 2)
        self.assertEqual(execution["entry_cost_return_fraction"], .0001)
        self.assertEqual(execution["terminal_cost_return_fraction"], .0001)
        np.testing.assert_allclose(curves.long_eur_drawdown, [0, 0, 0, -.1, -.01009])

    def test_flat_reference_and_undefined_sharpe(self):
        summary, curves, metadata = compare_benchmarks(example())
        flat = summary.set_index("portfolio").loc["flat_reference"]
        self.assertTrue(pd.isna(flat.zero_reference_rate_sharpe))
        for column in ("total_return", "cagr", "annualized_volatility", "maximum_drawdown"):
            self.assertEqual(flat[column], 0)
        for column in ("position", "net_return", "turnover", "turnover_cost", "terminal_closing_cost", "drawdown"):
            self.assertTrue(curves[f"flat_reference_{column}"].eq(0).all())
        self.assertTrue(curves.flat_reference_equity.eq(10000).all())
        self.assertIsNone(metadata["portfolios"]["flat_reference"]["metrics"]["zero_reference_rate_sharpe"])
        json.dumps(metadata, allow_nan=False)

    def test_baseline_unchanged_alignment_and_metric_reconciliation(self):
        data = example()
        original = data.copy(deep=True)
        summary, curves, metadata = compare_benchmarks(data)
        pd.testing.assert_frame_equal(data, original)
        np.testing.assert_array_equal(curves.baseline_net_return, original.net_return)
        np.testing.assert_array_equal(curves.baseline_equity, original.equity)
        for name, portfolio in build_benchmarks(data).items():
            pd.testing.assert_series_equal(portfolio.date, curves.date)
            report, drawdown = evaluate_performance(portfolio)
            self.assertEqual(report["evaluation"]["return_observation_count"], 4)
            for metric, expected in report["metrics"].items():
                actual = summary.set_index("portfolio").loc[name, metric]
                if expected is None:
                    self.assertTrue(pd.isna(actual))
                else:
                    self.assertAlmostEqual(actual, expected)
            np.testing.assert_allclose(curves[f"{name}_drawdown"], drawdown.drawdown)
        self.assertEqual(metadata["evaluation"]["return_observation_count"], 4)

    def test_later_start_and_final_interval_only(self):
        for signal in ([0, -1, 0, 1, 1], [0, 0, -1, 1, 1]):
            data = example()[["date", "eurusd", "fx_return"]].copy()
            data["signal"] = signal
            baseline = run_backtest(data)
            long = build_benchmarks(baseline)["long_eur"]
            start = baseline.index[baseline.position.ne(0)][0]
            self.assertEqual(long.index[long.position.ne(0)][0], start)
            self.assertTrue(long.position.iloc[:start].eq(0).all())
            self.assertEqual(long.turnover.sum(), 1)
            self.assertEqual(long.terminal_closing_cost.sum(), .0001)
            if start == len(data) - 1:
                self.assertAlmostEqual(long.net_return.iloc[-1], .1 - .0002)

    def test_invalid_and_inconsistent_baselines(self):
        with self.assertRaisesRegex(ValueError, "Missing baseline"):
            compare_benchmarks(example().drop(columns="position"))
        with self.assertRaisesRegex(ValueError, "ascending"):
            compare_benchmarks(example().iloc[::-1])
        for column in ("position", "turnover_cost", "terminal_closing_cost", "net_return", "equity"):
            invalid = example()
            invalid.loc[2, column] += 1
            with self.subTest(column=column), self.assertRaisesRegex(ValueError, "disagrees"):
                compare_benchmarks(invalid)
        data = example()[["date", "eurusd", "fx_return"]].copy()
        data["signal"] = 0
        with self.assertRaisesRegex(ValueError, "no active held position"):
            compare_benchmarks(run_backtest(data))


if __name__ == "__main__":
    unittest.main()
