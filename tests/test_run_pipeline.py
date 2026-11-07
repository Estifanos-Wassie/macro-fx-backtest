from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

from run_pipeline import STAGES, run_pipeline


def snapshots(root):
    raw = root / "data/raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "eurusd_ecb.csv").write_bytes(b"synthetic FX snapshot")
    policy = raw / "policy_rates/20200101T000000Z"
    policy.mkdir(parents=True, exist_ok=True)
    entries = {}
    for sid in ("ECBDFR", "DFEDTARL", "DFEDTARU"):
        content = f"observation_date,{sid}\n2014-01-01,0\n".encode()
        (policy / f"{sid}.csv").write_bytes(content)
        entries[sid] = {"raw_file": f"{sid}.csv", "sha256": sha256(content).hexdigest()}
    (policy / "metadata.json").write_text(json.dumps({"status": "complete", "series": entries}))


class PipelineTests(unittest.TestCase):
    def test_offline_dependency_order_interpreter_and_no_download_stage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshots(root)
            run = Mock()
            report = run_pipeline("offline", root=root, run=run)
            scripts = [Path(call.args[0][1]).name for call in run.call_args_list]
            self.assertEqual(scripts, [script for _, script in STAGES])
            self.assertFalse(any(name.startswith("download") for name in scripts))
            for call in run.call_args_list:
                self.assertEqual(call.args[0][0], sys.executable)
                self.assertTrue(call.kwargs["check"])
                self.assertEqual(call.kwargs["cwd"], root.resolve())
            self.assertTrue((root / "reports").is_dir())
            self.assertEqual(report["mode"], "offline")
            align = next(call for call in run.call_args_list if Path(call.args[0][1]).name == "align_policy_rates.py")
            self.assertEqual(align.args[0][2], "--manifest")

    def test_failure_stops_immediately_and_missing_snapshots_fail_before_stages(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = Mock()
            with self.assertRaisesRegex(FileNotFoundError, "Offline mode requires"):
                run_pipeline("offline", root=root, run=run)
            run.assert_not_called()
            snapshots(root)
            run.side_effect = subprocess.CalledProcessError(1, "synthetic failed stage")
            with self.assertRaises(subprocess.CalledProcessError):
                run_pipeline("offline", root=root, run=run)
            self.assertEqual(run.call_count, 1)
            self.assertFalse((root / "data/processed/pipeline_run_metadata.json").exists())

    def test_download_requires_refresh_when_snapshots_exist(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshots(root)
            run = Mock()
            with self.assertRaisesRegex(FileExistsError, "--refresh"):
                run_pipeline("download", root=root, run=run)
            run.assert_not_called()
            run_pipeline("download", refresh=True, root=root, run=run)
            self.assertEqual(Path(run.call_args_list[0].args[0][1]).name, "download_data.py")
            self.assertIn("--refresh", run.call_args_list[0].args[0])
            self.assertEqual(Path(run.call_args_list[1].args[0][1]).name, "download_policy_rates.py")
            self.assertEqual(run.call_count, len(STAGES) + 2)

    def test_bad_options_failed_manifest_and_hash_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshots(root)
            for mode, refresh in (("offline", True), ("invalid", False)):
                with self.assertRaises(ValueError):
                    run_pipeline(mode, refresh, root=root, run=Mock())
            manifest = next((root / "data/raw/policy_rates").glob("*/metadata.json"))
            metadata = json.loads(manifest.read_text())
            metadata["status"] = "failed"
            manifest.write_text(json.dumps(metadata))
            with self.assertRaisesRegex(ValueError, "incomplete/failed"):
                run_pipeline("offline", root=root, run=Mock())
            snapshots(root)
            (manifest.parent / "ECBDFR.csv").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "inconsistent policy snapshot"):
                run_pipeline("offline", root=root, run=Mock())


if __name__ == "__main__":
    unittest.main()
