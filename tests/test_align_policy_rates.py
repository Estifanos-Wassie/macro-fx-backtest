import unittest

import numpy as np
import pandas as pd

from src.align_policy_rates import align_policy_rates


def sources():
    dates = pd.date_range('2020-01-01', periods=5)
    return {
        'ECBDFR': pd.DataFrame({'source_date': dates, 'rate_pct': [-.5, -.5, -.25, -.25, -.25]}),
        'DFEDTARL': pd.DataFrame({'source_date': dates, 'rate_pct': [1.5] * 5}),
        'DFEDTARU': pd.DataFrame({'source_date': dates, 'rate_pct': [1.75] * 5}),
    }


class PolicyAlignmentTests(unittest.TestCase):
    def test_arithmetic_negative_rates_and_modeled_availability_lag(self):
        fx = pd.DataFrame({'date': ['2020-01-02', '2020-01-03', '2020-01-04'], 'eurusd': [1.1] * 3})
        original = fx.copy(deep=True)
        data = sources()
        original_ecb = data['ECBDFR'].copy(deep=True)
        result, summary = align_policy_rates(fx, data)
        np.testing.assert_allclose(result.ecb_deposit_pct, [-.5, -.5, -.25])
        np.testing.assert_allclose(result.fed_midpoint_pct, [1.625] * 3)
        np.testing.assert_allclose(result.rate_differential_pp, [-2.125, -2.125, -1.875])
        self.assertEqual(result.ECBDFR_source_date.dt.strftime('%Y-%m-%d').tolist(), ['2020-01-01', '2020-01-02', '2020-01-03'])
        self.assertTrue(result.ECBDFR_assumed_available_date.le(result.date).all())
        self.assertEqual(summary['ECBDFR']['maximum_matched_source_age_days'], 1)
        pd.testing.assert_frame_equal(fx, original)
        pd.testing.assert_frame_equal(data['ECBDFR'], original_ecb)

    def test_series_are_aligned_separately_and_missing_rates_reported(self):
        data = sources()
        data['ECBDFR'].loc[1, 'rate_pct'] = np.nan
        data['DFEDTARU'] = data['DFEDTARU'].drop(index=1)
        result, summary = align_policy_rates(pd.DataFrame({'date': ['2020-01-03']}), data)
        self.assertEqual(result.ECBDFR_source_date.iloc[0], pd.Timestamp('2020-01-01'))
        self.assertEqual(result.DFEDTARL_source_date.iloc[0], pd.Timestamp('2020-01-02'))
        self.assertEqual(result.DFEDTARU_source_date.iloc[0], pd.Timestamp('2020-01-01'))
        self.assertEqual(summary['ECBDFR']['missing_value_count'], 1)
        self.assertEqual(summary['DFEDTARU']['absent_calendar_date_count'], 1)

    def test_seven_days_allowed_eight_days_stale(self):
        data = {key: value.iloc[:1] for key, value in sources().items()}
        result, summary = align_policy_rates(pd.DataFrame({'date': ['2020-01-08']}), data)
        self.assertEqual(summary['ECBDFR']['maximum_matched_source_age_days'], 7)
        with self.assertRaisesRegex(ValueError, 'stale'):
            align_policy_rates(pd.DataFrame({'date': ['2020-01-09']}), data)

    def test_future_data_excluded_and_unmatched_fails(self):
        data = sources()
        with self.assertRaisesRegex(ValueError, 'unmatched'):
            align_policy_rates(pd.DataFrame({'date': ['2020-01-01']}), data)
        first, _ = align_policy_rates(pd.DataFrame({'date': ['2020-01-03']}), data)
        data['ECBDFR'].loc[2:, 'rate_pct'] = 99
        changed, _ = align_policy_rates(pd.DataFrame({'date': ['2020-01-03']}), data)
        pd.testing.assert_frame_equal(first, changed)

    def test_invalid_source_and_fx_inputs(self):
        fx = pd.DataFrame({'date': ['2020-01-03']})
        for value in (np.inf, 'bad-number'):
            data = sources()
            data['ECBDFR']['rate_pct'] = data['ECBDFR']['rate_pct'].astype(object)
            data['ECBDFR'].loc[0, 'rate_pct'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                align_policy_rates(fx, data)
        for value in ('bad-date', None, '2020-01-02'):
            data = sources()
            data['ECBDFR']['source_date'] = data['ECBDFR']['source_date'].astype(object)
            data['ECBDFR'].loc[0, 'source_date'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                align_policy_rates(fx, data)
        data = sources()
        data['ECBDFR']['rate_pct'] = np.nan
        with self.assertRaisesRegex(ValueError, 'no usable'):
            align_policy_rates(fx, data)
        for dates in (['bad'], [None], ['2020-01-03'] * 2, ['2020-01-04', '2020-01-03']):
            with self.subTest(dates=dates), self.assertRaises(ValueError):
                align_policy_rates(pd.DataFrame({'date': dates}), sources())

    def test_inverted_fed_bounds_rejected_even_outside_fx_dates(self):
        data = sources()
        data['DFEDTARL'].loc[0, 'rate_pct'] = 2
        with self.assertRaisesRegex(ValueError, 'lower bound exceeds'):
            align_policy_rates(pd.DataFrame({'date': ['2020-01-05']}), data)


if __name__ == '__main__':
    unittest.main()
