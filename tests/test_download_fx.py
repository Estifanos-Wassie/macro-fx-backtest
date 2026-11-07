from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import pandas as pd
import requests

from src.download_data import download_fx


def response(content, status=200):
    result = requests.Response()
    result.status_code = status
    result.url = "https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A"
    result._content = content
    return result


class FXDownloadTests(unittest.TestCase):
    def test_refresh_consent_archiving_and_provenance(self):
        dates = list(pd.date_range("2015-01-02", periods=2815)) + [pd.Timestamp("2025-12-31")]
        content = pd.DataFrame({"TIME_PERIOD": dates, "OBS_VALUE": 1.1}).to_csv(index=False).encode()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active = root / "eurusd_ecb.csv"
            active.write_bytes(b"original")
            get = Mock(return_value=response(content))
            with self.assertRaises(FileExistsError):
                download_fx(root, get=get)
            get.assert_not_called()
            download_fx(root, refresh=True, get=get)
            metadata = json.loads((root / "eurusd_ecb_metadata.json").read_text())
            archive = Path(metadata["archive_directory"])
            self.assertEqual((archive / "previous_eurusd_ecb.csv").read_bytes(), b"original")
            self.assertEqual(active.read_bytes(), content)
            self.assertEqual(metadata["sha256"], sha256(content).hexdigest())
            self.assertEqual(metadata["status"], "complete")

    def test_http_and_schema_failures_preserve_established_snapshot(self):
        for reply in (response(b"unavailable", 503), response(b"date,wrong\n2015-01-02,0\n")):
            with self.subTest(status=reply.status_code), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "eurusd_ecb.csv").write_bytes(b"original")
                with self.assertRaises(RuntimeError):
                    download_fx(root, refresh=True, get=Mock(return_value=reply))
                self.assertEqual((root / "eurusd_ecb.csv").read_bytes(), b"original")
                manifest = next(root.glob("eurusd_snapshots/*/metadata.json"))
                self.assertEqual(json.loads(manifest.read_text())["status"], "failed")


if __name__ == "__main__":
    unittest.main()
