import unittest

import numpy as np
import pandas as pd

from src.generate_macro_signals import generate_macro_signals


def aligned(differentials):
    dates = pd.date_range("2020-01-01", periods=len(differentials))
    data = pd.DataFrame({
        "date": dates, "eurusd": 1.1,
        "ecb_deposit_pct": np.asarray(differentials) + .125,
        "fed_lower_pct": 0.0, "fed_upper_pct": .25,
        "fed_midpoint_pct": .125, "rate_differential_pp": differentials,
    })
    for sid in ("ECBDFR", "DFEDTARL", "DFEDTARU"):
        data[f"{sid}_source_date"] = dates - pd.Timedelta(days=1)
        data[f"{sid}_assumed_available_date"] = dates
        data[f"{sid}_source_age_days"] = 1
    return data


class MacroSignalTests(unittest.TestCase):
    def test_positive_negative_flat_and_less_negative(self):
        data = aligned([-2.0] * 63 + [-1.0, -3.0, -2.0])
        original = data.copy(deep=True)
        result = generate_macro_signals(data)
        np.testing.assert_allclose(result.macro_change_pp.iloc[63:], [1, -1, 0])
        self.assertEqual(result.macro_signal.iloc[63:].tolist(), [1, -1, 0])
        pd.testing.assert_frame_equal(data, original)
        pd.testing.assert_frame_equal(result[data.columns], original)
        self.assertEqual(list(result.columns[-2:]), ["macro_change_pp", "macro_signal"])

    def test_exact_observation_warmup_boundary_without_execution_shift(self):
        data = aligned([0.0] * 63 + [1.0])
        # A weekend-like gap proves the lag counts rows, not calendar days.
        data["date"] += pd.to_timedelta(np.arange(64) // 5 * 2, unit="D")
        for sid in ("ECBDFR", "DFEDTARL", "DFEDTARU"):
            data[f"{sid}_source_date"] = data.date - pd.Timedelta(days=1)
            data[f"{sid}_assumed_available_date"] = data.date
        result = generate_macro_signals(data)
        self.assertTrue(result.macro_change_pp.iloc[:63].isna().all())
        self.assertTrue(result.macro_signal.iloc[:63].eq(0).all())
        self.assertEqual(result.macro_change_pp.first_valid_index(), 63)
        self.assertEqual(result.macro_change_pp.iloc[63], 1)
        self.assertEqual(result.macro_signal.iloc[63], 1)
        short = generate_macro_signals(data.iloc[:63])
        self.assertTrue(short.macro_change_pp.isna().all())
        self.assertTrue(short.macro_signal.eq(0).all())

    def test_absolute_zero_tolerance_inclusive_and_no_relative_tolerance(self):
        changes = [0, 1e-12, -1e-12, 1e-10, -1e-10, 1.01e-10, -1.01e-10]
        result = generate_macro_signals(aligned([0.0] * 63 + changes))
        self.assertEqual(result.macro_signal.iloc[63:].tolist(), [0, 0, 0, 0, 0, 1, -1])
        np.testing.assert_allclose(result.macro_change_pp.iloc[63:], changes, rtol=0, atol=0)
        # A relative tolerance would incorrectly flatten this small change at a large level.
        result = generate_macro_signals(aligned([1000000.0] * 63 + [1000000.0 + 1e-8]))
        self.assertEqual(result.macro_signal.iloc[63], 1)

    def test_future_changes_leave_earlier_signals_unchanged(self):
        data = aligned([-2.0] * 63 + [-1.0] * 70)
        original = generate_macro_signals(data)
        data.loc[90:, "ecb_deposit_pct"] += 1
        data.loc[90:, "rate_differential_pp"] += 1
        changed = generate_macro_signals(data)
        pd.testing.assert_frame_equal(original.iloc[:90], changed.iloc[:90])
        self.assertNotEqual(original.macro_change_pp.iloc[90], changed.macro_change_pp.iloc[90])

    def test_invalid_values_dates_arithmetic_and_availability(self):
        base = aligned([-2.0] * 65)
        cases = [base.iloc[:0], base.drop(columns="ecb_deposit_pct"), base.iloc[::-1],
                 pd.concat([base, base[["date"]]], axis=1)]
        for column, value in [
            ("date", base.date.iloc[1]), ("date", "invalid-date"), ("date", None),
            ("ecb_deposit_pct", np.inf), ("ecb_deposit_pct", np.nan),
            ("fed_lower_pct", 1), ("fed_upper_pct", "bad"),
            ("fed_midpoint_pct", .5), ("rate_differential_pp", 10),
            ("eurusd", 0), ("eurusd", np.inf),
            ("ECBDFR_source_date", None),
            ("DFEDTARL_assumed_available_date", base.date.iloc[0] + pd.Timedelta(days=1)),
            ("DFEDTARU_assumed_available_date", base.date.iloc[0] - pd.Timedelta(days=1)),
            ("ECBDFR_source_age_days", 2),
        ]:
            data = base.astype({column: object}).copy()
            data.loc[0, column] = value
            cases.append(data)
        stale = base.copy()
        stale.loc[0, "ECBDFR_source_date"] -= pd.Timedelta(days=7)
        stale.loc[0, "ECBDFR_assumed_available_date"] -= pd.Timedelta(days=7)
        stale.loc[0, "ECBDFR_source_age_days"] = 8
        cases.append(stale)
        for index, data in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(ValueError):
                generate_macro_signals(data)
        future = base.copy()
        future.loc[0, "ECBDFR_assumed_available_date"] += pd.Timedelta(days=1)
        with self.assertRaisesRegex(ValueError, "future-dated"):
            generate_macro_signals(future)


if __name__ == "__main__":
    unittest.main()
