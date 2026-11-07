"""Mocked downloader tests; these do not verify live FRED access."""

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import requests

from src.download_policy_rates import (
    CSV_URL, SERIES, describe_source, download_policy_rates, parse_policy_csv,
)


def response(content, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = content
    result.url = CSV_URL
    return result


class PolicyDownloadTests(unittest.TestCase):
    def test_mock_download_archives_bytes_hashes_and_provenance(self):
        def get(url, params, timeout):
            self.assertEqual(url, CSV_URL)
            self.assertEqual(params['cosd'], '2014-01-01')
            self.assertEqual(params['coed'], '2014-01-03')
            self.assertEqual(timeout, 60)
            return response(f"observation_date,{params['id']}\n2014-01-01,-0.1\n2014-01-02,.\n2014-01-03,0.25\n".encode())
        mocked = Mock(side_effect=get)
        with tempfile.TemporaryDirectory() as temporary:
            manifest = download_policy_rates(Path(temporary), end='2014-01-03', get=mocked)
            metadata = json.loads(manifest.read_text())
            self.assertEqual(metadata['status'], 'complete')
            self.assertEqual(mocked.call_count, 3)
            for series_id in SERIES:
                entry = metadata['series'][series_id]
                raw = (manifest.parent / entry['raw_file']).read_bytes()
                self.assertEqual(entry['sha256'], sha256(raw).hexdigest())
                self.assertEqual(entry['units'], 'Percent')
                self.assertEqual(entry['missing_value_count'], 1)
                self.assertEqual(entry['missing_value_dates'], ['2014-01-02'])
                self.assertEqual(entry['absent_calendar_date_count'], 0)
                self.assertTrue(entry['retrieved_at_utc'].endswith('+00:00'))
            # A later download must not replace an earlier archive.
            second = download_policy_rates(Path(temporary), end='2014-01-03', get=mocked)
            self.assertNotEqual(manifest, second)
            self.assertTrue(manifest.is_file())

    def test_http_failure_preserves_original_response_and_failed_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(RuntimeError, '503'):
                download_policy_rates(Path(temporary), get=Mock(return_value=response(b'Unavailable', 503)))
            manifest = next(Path(temporary).glob('*/metadata.json'))
            metadata = json.loads(manifest.read_text())
            self.assertEqual(metadata['status'], 'failed')
            self.assertEqual((manifest.parent / 'ECBDFR.csv').read_bytes(), b'Unavailable')

    def test_network_failure_is_not_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(RuntimeError, 'network unavailable'):
                download_policy_rates(Path(temporary), get=Mock(side_effect=requests.ConnectionError('network unavailable')))
            manifest = next(Path(temporary).glob('*/metadata.json'))
            self.assertEqual(json.loads(manifest.read_text())['status'], 'failed')

    def test_bad_csv_and_coverage_fail(self):
        cases = [
            b'date,wrong\n2014-01-01,0\n',
            b'observation_date,ECBDFR\ninvalid,0\n',
            b'observation_date,ECBDFR\n,0\n',
            b'observation_date,ECBDFR\n2014-01-01,0\n2014-01-01,1\n',
            b'observation_date,ECBDFR\n2014-01-01,inf\n',
            b'observation_date,ECBDFR\n2014-01-01,unexpected\n',
        ]
        for content in cases:
            with self.subTest(content=content), self.assertRaises(ValueError):
                parse_policy_csv(content, 'ECBDFR')
        data = parse_policy_csv(b'observation_date,ECBDFR\n2014-01-01,0\n2014-01-03,1\n', 'ECBDFR')
        self.assertEqual(describe_source(data, '2014-01-01', '2014-01-03')['absent_calendar_dates'], ['2014-01-02'])
        with self.assertRaisesRegex(ValueError, 'coverage'):
            describe_source(data, '2014-01-01', '2014-01-04')
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(RuntimeError):
                download_policy_rates(Path(temporary), get=Mock(return_value=response(cases[0])))
            manifest = next(Path(temporary).glob('*/metadata.json'))
            self.assertEqual(json.loads(manifest.read_text())['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
