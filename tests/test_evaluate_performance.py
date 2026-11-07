import json
import math
import unittest

import numpy as np
import pandas as pd

from src.evaluate_performance import (
    calculate_drawdown,
    evaluate_performance,
    return_statistics,
)


def example():
    return pd.DataFrame({
        "date": ["2020-01-01", "2020-07-01", "2021-01-01"],
        "net_return": [0, .1, -.2],
        "equity": [10000, 11000, 8800],
    })


class PerformanceTests(unittest.TestCase):
    def test_total_return_and_actual_calendar_cagr(self):
        report, _ = evaluate_performance(example())
        self.assertAlmostEqual(report["metrics"]["total_return"], -.12)
        self.assertAlmostEqual(report["metrics"]["cagr"], .88 ** (365.25 / 366) - 1)
        evaluation = report["evaluation"]
        self.assertEqual(evaluation["elapsed_calendar_days"], 366)
        self.assertEqual(evaluation["initial_valuation_date"], "2020-01-01")
        self.assertEqual(evaluation["first_return_end_date"], "2020-07-01")
        self.assertEqual(evaluation["final_observation_date"], "2021-01-01")
        self.assertEqual(evaluation["return_observation_count"], 2)

    def test_sample_std_and_zero_reference_sharpe_exclude_initial_row(self):
        report, _ = evaluate_performance(example())
        # Mean of +10%, -20% is -5%; sample variance = .045.
        std = math.sqrt(.045)
        self.assertAlmostEqual(report["metrics"]["annualized_volatility"], std * math.sqrt(252))
        self.assertAlmostEqual(report["metrics"]["zero_reference_rate_sharpe"], -.05 / std * math.sqrt(252))

    def test_flat_returns_and_strict_json_null(self):
        data = example()
        data["net_return"] = 0.0
        data["equity"] = 10000.0
        report, drawdown = evaluate_performance(data)
        for name in ("total_return", "cagr", "annualized_volatility", "maximum_drawdown"):
            self.assertEqual(report["metrics"][name], 0)
        self.assertIsNone(report["metrics"]["zero_reference_rate_sharpe"])
        self.assertTrue(drawdown.drawdown.eq(0).all())
        encoded = json.dumps(report, allow_nan=False)
        self.assertIn('"zero_reference_rate_sharpe": null', encoded)

    def test_loss_before_any_new_peak(self):
        data = example()
        data["net_return"] = [0, -.1, -.1]
        data["equity"] = [10000, 9000, 8100]
        report, drawdown = evaluate_performance(data)
        np.testing.assert_allclose(drawdown.running_peak, [10000, 10000, 10000])
        np.testing.assert_allclose(drawdown.drawdown, [0, -.1, -.19])
        self.assertAlmostEqual(report["metrics"]["maximum_drawdown"], .19)
        # The reusable helper must also seed the peak if the first supplied value is a loss.
        direct = calculate_drawdown(pd.Series([9000, 8100]), 10000)
        np.testing.assert_allclose(direct.drawdown, [-.1, -.19])

    def test_recovery_then_deeper_drawdown(self):
        data = pd.DataFrame({
            "date": pd.date_range("2020-01-01", periods=6),
            "net_return": [0, -.1, 1 / 3, -.25, 1 / 3, -.5],
            "equity": [10000, 9000, 12000, 9000, 12000, 6000],
        })
        report, drawdown = evaluate_performance(data)
        np.testing.assert_allclose(drawdown.running_peak, [10000, 10000, 12000, 12000, 12000, 12000])
        np.testing.assert_allclose(drawdown.drawdown, [0, -.1, 0, -.25, 0, -.5])
        self.assertEqual(report["metrics"]["maximum_drawdown"], .5)

    def test_one_return_has_undefined_sample_statistics(self):
        report, _ = evaluate_performance(example().iloc[:2])
        self.assertIsNone(report["metrics"]["annualized_volatility"])
        self.assertIsNone(report["metrics"]["zero_reference_rate_sharpe"])
        self.assertIsNone(return_statistics(pd.Series(dtype=float))["zero_reference_rate_sharpe"])
        self.assertIsNone(return_statistics(pd.Series([.125, .125]))["zero_reference_rate_sharpe"])
        self.assertIsNone(return_statistics(pd.Series([.1, .1, .1]))["zero_reference_rate_sharpe"])
        json.dumps(report, allow_nan=False)

    def test_warmup_flat_returns_and_terminal_cost_retained(self):
        data = pd.DataFrame({
            "date": pd.date_range("2020-01-01", periods=4),
            "net_return": [0, 0, 0, -.0001],
            "equity": [10000, 10000, 10000, 9999],
        })
        report, _ = evaluate_performance(data)
        self.assertEqual(report["evaluation"]["return_observation_count"], 3)
        self.assertAlmostEqual(report["metrics"]["total_return"], -.0001)
        # Sample variance of 0, 0, -.0001 is (1e-8 / 3).
        std = math.sqrt(1e-8 / 3)
        self.assertAlmostEqual(report["metrics"]["annualized_volatility"], std * math.sqrt(252))
        self.assertAlmostEqual(report["metrics"]["zero_reference_rate_sharpe"], (-.0001 / 3) / std * math.sqrt(252))

    def test_invalid_inputs(self):
        cases = [
            (example().drop(columns="equity"), "required columns"),
            (example().iloc[:1], "at least two"),
            (example().iloc[::-1], "ascending"),
            (pd.concat([example(), example()[["equity"]]], axis=1), "unique columns"),
        ]
        for column, row, value, message in [
            ("date", 1, "2020-01-01", "unique"),
            ("date", 1, None, "nonmissing"),
            ("date", 1, "invalid-date", "Dates"),
            ("net_return", 1, np.nan, "finite"),
            ("net_return", 1, np.inf, "finite"),
            ("net_return", 1, "invalid", "numeric"),
            ("net_return", 0, .01, "Initial valuation"),
            ("net_return", 1, -1, "positive"),
            ("equity", 1, np.nan, "finite"),
            ("equity", 1, np.inf, "finite"),
            ("equity", 1, 0, "positive"),
            ("equity", 1, -100, "positive"),
            ("equity", 1, 10000, "inconsistent"),
            ("equity", 0, 9999, "inconsistent"),
        ]:
            data = example().astype({column: object})
            data.loc[row, column] = value
            cases.append((data, message))
        same_day = example().iloc[:2].copy()
        same_day["date"] = ["2020-01-01 00:00:00", "2020-01-01 12:00:00"]
        cases.append((same_day, "elapsed calendar days"))
        for number, (data, message) in enumerate(cases):
            with self.subTest(case=number, message=message):
                with self.assertRaisesRegex(ValueError, message):
                    evaluate_performance(data)
        for initial in (0, -100, np.inf, np.nan):
            with self.subTest(initial=initial), self.assertRaisesRegex(ValueError, "Initial equity"):
                evaluate_performance(example(), initial_equity=initial)
        with self.assertRaisesRegex(ValueError, "finite"):
            return_statistics(pd.Series([0, np.nan]))
        with self.assertRaisesRegex(ValueError, "positive equity"):
            calculate_drawdown(pd.Series([0]), 10000)


if __name__ == "__main__":
    unittest.main()
