import unittest

import numpy as np
import pandas as pd

from src.backtest import run_backtest


def example():
    # Returns: unavailable, +10%, +10%, -10%, +10%, +10%, -10%, +10%.
    return pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=8),
        "eurusd": [100, 110, 121, 108.9, 119.79, 131.769, 118.5921, 130.45131],
        "fx_return": [np.nan, .1, .1, -.1, .1, .1, -.1, .1],
        "signal": [1, 1, -1, 0, -1, 1, 1, -1],
    })


class BacktestTests(unittest.TestCase):
    def test_hand_calculated_lag_and_long_short_flat_returns(self):
        data = example()
        original = data.copy(deep=True)
        result = run_backtest(data)
        self.assertEqual(result.position.tolist(), [0, 0, 1, 1, -1, 0, -1, 1])
        np.testing.assert_allclose(result.gross_return, [0, 0, .1, -.1, -.1, 0, .1, .1])
        pd.testing.assert_frame_equal(data, original)
        pd.testing.assert_frame_equal(result[data.columns], original)
        self.assertTrue(pd.isna(result.fx_return.iloc[0]))

    def test_entry_reversal_unchanged_exit_and_terminal_costs(self):
        result = run_backtest(example())
        self.assertEqual(result.turnover.tolist(), [0, 0, 1, 0, 2, 1, 1, 2])
        np.testing.assert_allclose(result.turnover_cost, [0, 0, .0001, 0, .0002, .0001, .0001, .0002])
        np.testing.assert_allclose(result.terminal_closing_cost, [0, 0, 0, 0, 0, 0, 0, .0001])
        np.testing.assert_allclose(result.net_return, [0, 0, .0999, -.1, -.1002, -.0001, .0999, .0997])

    def test_compounding(self):
        result = run_backtest(example())
        expected = 10_000 * 1.0999 * .9 * .8998 * .9999 * 1.0999 * 1.0997
        self.assertAlmostEqual(result.equity.iloc[-1], expected, places=8)
        self.assertEqual(result.equity.iloc[0], 10_000)
        self.assertAlmostEqual(result.equity.iloc[3], 10_000 * 1.0999 * .9)

    def test_future_signal_does_not_change_earlier_results(self):
        data = example()
        original = run_backtest(data)
        data.loc[4, "signal"] = 1
        changed = run_backtest(data)
        calculated = ["position", "gross_return", "turnover", "turnover_cost",
                      "terminal_closing_cost", "net_return", "equity"]
        pd.testing.assert_frame_equal(original.loc[:5, calculated], changed.loc[:5, calculated])
        self.assertNotEqual(original.position.iloc[6], changed.position.iloc[6])

    def test_final_two_signals_are_unused(self):
        data = example()
        original = run_backtest(data)
        data.loc[6:, "signal"] = [0, 1]
        changed = run_backtest(data)
        pd.testing.assert_frame_equal(original.drop(columns="signal"), changed.drop(columns="signal"))

    def test_flat_final_position_and_short_inputs(self):
        data = example()
        data.loc[5, "signal"] = 0
        self.assertEqual(run_backtest(data).terminal_closing_cost.sum(), 0)
        for length in (1, 2):
            with self.subTest(length=length):
                result = run_backtest(example().iloc[:length])
                self.assertTrue(result.position.eq(0).all())
                self.assertTrue(result.equity.eq(10_000).all())

    def test_zero_cost_and_custom_equity(self):
        result = run_backtest(example(), one_way_cost=0, initial_equity=500)
        self.assertEqual(result.turnover_cost.sum() + result.terminal_closing_cost.sum(), 0)
        self.assertAlmostEqual(result.equity.iloc[-1], 500 * 1.1 * .9 * .9 * 1.1 * 1.1)

    def test_invalid_inputs_fail_clearly(self):
        cases = []
        cases.append((example().drop(columns="signal"), "required columns"))
        cases.append((example().iloc[:0], "nonempty"))
        cases.append((example().iloc[::-1], "ascending"))
        for column, row, value, message in [
            ("date", 1, pd.Timestamp("2025-01-01"), "unique"),
            ("date", 1, pd.NaT, "nonmissing"),
            ("eurusd", 2, 0, "positive"),
            ("eurusd", 2, -1, "positive"),
            ("eurusd", 2, np.nan, "finite"),
            ("eurusd", 2, np.inf, "finite"),
            ("signal", 2, 2, "Signals"),
            ("signal", 2, np.nan, "Signals"),
            ("signal", 2, np.inf, "Signals"),
            ("fx_return", 0, 0, "sole missing"),
            ("fx_return", 2, np.nan, "sole missing"),
            ("fx_return", 2, np.inf, "finite"),
            ("fx_return", 2, .2, "percentage changes"),
        ]:
            data = example()
            # Permit deliberately invalid values without pandas dtype warnings.
            data[column] = data[column].astype(object)
            data.loc[row, column] = value
            cases.append((data, message))
        for column, value, message in [("date", "bad-date", "Dates"),
                                       ("eurusd", "bad-rate", "numeric")]:
            data = example().astype({column: object})
            data.loc[2, column] = value
            cases.append((data, message))
        for data, message in cases:
            with self.subTest(message=message, data=data.to_dict()):
                with self.assertRaisesRegex(ValueError, message):
                    run_backtest(data)

    def test_optional_columns_allow_only_expected_warmup(self):
        data = example()
        data["sma_20"] = np.nan
        data["sma_60"] = np.nan
        run_backtest(data)
        data.loc[0, "sma_20"] = np.inf
        with self.assertRaisesRegex(ValueError, "sma_20"):
            run_backtest(data)
        data = example()
        data["extra"] = np.inf
        with self.assertRaisesRegex(ValueError, "extra"):
            run_backtest(data)

    def test_invalid_parameters(self):
        for cost in (-.001, np.inf, np.nan):
            with self.subTest(cost=cost), self.assertRaisesRegex(ValueError, "cost"):
                run_backtest(example(), one_way_cost=cost)
        for equity in (0, -1, np.inf, np.nan):
            with self.subTest(equity=equity), self.assertRaisesRegex(ValueError, "equity"):
                run_backtest(example(), initial_equity=equity)

    def test_sma_values_after_warmup_must_be_present_and_finite(self):
        data = pd.DataFrame({
            "date": pd.date_range("2025-01-01", periods=65),
            "eurusd": 1.0,
            "fx_return": [np.nan] + [0.0] * 64,
            "signal": 0,
        })
        for window in (20, 60):
            data[f"sma_{window}"] = data.eurusd.rolling(window).mean()
        run_backtest(data)
        for column in ("sma_20", "sma_60"):
            for value in (np.nan, np.inf):
                invalid = data.copy()
                invalid.loc[60, column] = value
                with self.subTest(column=column, value=value):
                    with self.assertRaisesRegex(ValueError, column):
                        run_backtest(invalid)


if __name__ == "__main__":
    unittest.main()
