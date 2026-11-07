"""Run the fixed FX research pipeline in explicit offline or download mode."""

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
STAGES = (
    ("Inspect FX data", "inspect_data.py"), ("Clean FX data", "clean_data.py"),
    ("Calculate FX returns", "calculate_returns.py"), ("Generate SMA signals", "generate_signals.py"),
    ("Backtest SMA baseline", "backtest.py"), ("Evaluate full-period baseline", "evaluate_performance.py"),
    ("Compare full-period benchmarks", "compare_benchmarks.py"), ("Align policy rates", "align_policy_rates.py"),
    ("Generate macro signals", "generate_macro_signals.py"), ("Compare common window", "compare_common_window.py"),
    ("Analyze bounded robustness", "analyze_robustness.py"), ("Build Excel snapshot", "build_dashboard.py"),
)


def select_manifest(root, explicit=None):
    candidates = sorted((root / "data/raw/policy_rates").glob("*/metadata.json"))
    manifest = Path(explicit) if explicit else candidates[-1] if candidates else None
    if manifest is None or not manifest.is_file():
        raise FileNotFoundError("Offline mode requires an archived FRED metadata.json and its raw CSVs; obtain or copy snapshots first.")
    metadata = json.loads(manifest.read_text())
    if metadata.get("status") != "complete" or set(metadata.get("series", {})) != {"ECBDFR", "DFEDTARL", "DFEDTARU"}:
        raise ValueError(f"Policy snapshot is incomplete/failed: {manifest}; select a complete archive explicitly.")
    for entry in metadata["series"].values():
        source = manifest.parent / entry["raw_file"]
        if not source.is_file() or sha256(source.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"Missing or inconsistent policy snapshot: {source}")
    return manifest.resolve()


def run_pipeline(mode, refresh=False, policy_manifest=None, root=ROOT, run=None):
    root = Path(root).resolve()
    run = subprocess.run if run is None else run
    if mode not in ("offline", "download") or (refresh and mode != "download"):
        raise ValueError("Choose offline or download; --refresh is valid only with --download.")
    if policy_manifest and mode != "offline":
        raise ValueError("--policy-manifest selects an offline snapshot only.")
    for name in ("data/raw", "data/processed", "reports"):
        (root / name).mkdir(parents=True, exist_ok=True)
    def stage(label, script, *arguments):
        print(f"\n>>> {label}", flush=True)
        run([sys.executable, str(root / "src" / script), *map(str, arguments)], cwd=root, check=True)
    if mode == "download":
        existing = list((root / "data/raw").rglob("*.csv"))
        if existing and not refresh:
            raise FileExistsError("Existing raw snapshots detected; use --download --refresh to request a new vintage. Previous snapshots are archived, not discarded.")
        stage("Download ECB FX snapshot", "download_data.py", *(["--refresh"] if refresh else []))
        stage("Download FRED policy snapshots", "download_policy_rates.py")
    elif not (root / "data/raw/eurusd_ecb.csv").is_file():
        raise FileNotFoundError("Offline mode requires data/raw/eurusd_ecb.csv; obtain or copy snapshots first.")
    manifest = select_manifest(root, policy_manifest)
    raw_hashes = {str(p.relative_to(root)): sha256(p.read_bytes()).hexdigest()
                  for p in (root / "data/raw").rglob("*") if p.is_file()}
    for label, script in STAGES:
        stage(label, script, *(["--manifest", manifest] if script == "align_policy_rates.py" else []))
    if any(sha256((root / name).read_bytes()).hexdigest() != digest for name, digest in raw_hashes.items()):
        raise ValueError("Raw snapshots changed during processing.")
    report = {"mode": mode, "python_version": platform.python_version(),
              "completed_at_utc": datetime.now(timezone.utc).isoformat(),
              "policy_manifest": str(manifest), "raw_snapshot_sha256": raw_hashes,
              "stages": [script for _, script in STAGES],
              "processed_outputs": sorted(p.name for p in (root / "data/processed").glob("*") if p.is_file()),
              "dashboard": "reports/macro_fx_dashboard.xlsx"}
    (root / "data/processed/pipeline_run_metadata.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"\nPipeline complete ({mode}). Analytical outputs: {root / 'data/processed'}\n"
          f"Workbook: {root / 'reports/macro_fx_dashboard.xlsx'}", flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline", action="store_true", help="Use existing raw snapshots; no download stage or network requests.")
    mode.add_argument("--download", action="store_true", help="Retrieve real ECB and FRED source data with provenance.")
    parser.add_argument("--refresh", action="store_true", help="Explicitly retrieve a new vintage; retain older raw snapshots.")
    parser.add_argument("--policy-manifest", type=Path, help="Select an archived FRED metadata.json for offline mode.")
    args = parser.parse_args()
    try:
        run_pipeline("offline" if args.offline else "download", args.refresh, args.policy_manifest)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Pipeline failed: {exc}\n")


if __name__ == "__main__":
    main()
