# Fixed-snapshot reproduction

The supported setup was exercised with Python **3.14.3** on macOS Apple
silicon. Create a fresh virtual environment, install the pinned
`requirements.txt`, and run `python -m unittest discover -s tests -v` through
that environment's interpreter. Unit tests use synthetic fixtures and temporary
directories; they require no ignored data from an existing working directory.
See the README for exact clone, installation and execution commands.

## One-command execution

```sh
.venv/bin/python run_pipeline.py --download
.venv/bin/python run_pipeline.py --offline
```

Choose one mode explicitly. Download mode fetches real source observations;
offline mode requires the existing `data/raw/eurusd_ecb.csv` and a complete
timestamped FRED archive under `data/raw/policy_rates/`, including its
`metadata.json`. Copy the entire raw snapshot tree before an offline run.
`--policy-manifest` can pin a particular FRED archive. Failed or incomplete
manifests and raw hash mismatches are rejected.

The runner uses `sys.executable`, resolves scripts from its own repository,
creates output directories and stops immediately on a failed stage. Its order
is FX inspection, cleaning, returns, SMA signals, baseline backtest, full-period
evaluation, full-period benchmarks, policy alignment, macro signals,
common-window comparison, robustness, and Excel dashboard.

`--download --refresh` is required when raw CSV snapshots already exist. ECB
responses are archived under `data/raw/eurusd_snapshots/<UTC timestamp>/`;
refresh also retains the preceding active ECB bytes and provenance there.
The active ECB snapshot has a companion `eurusd_ecb_metadata.json`. FRED
responses and provenance remain in separate timestamped archives. Failed HTTP
or data-validation attempts retain response/provenance information without
replacing the established active ECB file. A legacy ECB snapshot with no
retrieval metadata can still be used offline: the run manifest records its
content hash without inventing its original retrieval timestamp.

## What should reproduce

With the same raw bytes, pinned dependencies and fixed assumptions, analytical
dates, observations, signals, positions, costs, equity, metrics and annual
returns should reconcile at full precision. Compare numeric CSV values with
relative and absolute tolerance **1e-12**, retaining genuine missing warm-up
values. Do not round to displayed percentages before comparing.

Processing/retrieval timestamps, absolute filesystem paths, archive identifiers,
hashes of timestamped provenance, and the metadata's preserved-file inventory
are provenance rather than strategy results. A workbook may differ because it
embeds input metadata hashes or because ZIP/creation metadata or print settings
differ. Compare its typed values, formulas/caches and complete series instead
of assuming any byte difference changes performance. The builder separately
tests identical bytes for identical verified inputs.

Current-vintage live downloads can reflect source revisions. Use a new isolated
directory to check them, report raw and analytical differences, and keep the
established snapshot intact. Reproducibility with a fixed snapshot is distinct
from obtaining identical data from a later live request. No strategy, window,
cost rule or execution convention is adjusted to improve agreement or returns.

## Verification performed

A fresh isolated repository copy and new virtual environment installed all
pinned requirements. **64 unit tests passed before copying any ignored data**.
The complete offline pipeline then ran with socket connections and DNS calls
blocked, using a copy of the established raw snapshots. All **14 analytical
CSV outputs were byte-identical**, and their parsed values reconciled at
relative/absolute tolerance 1e-12. Analytical JSON definitions, metrics and
diagnostics matched; expected differences were processing timestamps,
absolute paths and provenance references. Copied raw snapshots and established
workspace data hashes remained unchanged. The final workbook was generated.

A separate fresh isolated location also completed the real `--download`
pipeline using the new environment. The ECB response and all three FRED CSVs
were byte-identical to the established snapshots at verification time, and all
14 analytical CSV tables reconciled at tolerance 1e-12. No source revisions or
analytical differences were found in this run. New retrieval timestamps,
archive paths and provenance hashes are expected differences; this observation
does not promise unchanged future source vintages. Neither verification run
replaced the working repository's raw snapshots or analytical results.

The dashboard now saves two A3 landscape pages at 85% scale, with a manual
break before row 36 and no competing fit-to-page setting. Workbook tests check
chart anchors against that break and scaled page heights. These are structural
checks, not native rendering. The user reports the earlier uploaded workbook
was independently checked and rendered in LibreOffice; native Excel was not
tested. That earlier inspection does not verify this changed print layout.

## Expected outputs

Generated files stay ignored. `data/processed/` contains:

- `eurusd_clean.csv`, `eurusd_returns.csv`, `baseline_signals.csv`,
  `baseline_backtest.csv`, `baseline_drawdown.csv`, `baseline_metrics.json`.
- `benchmark_comparison.csv`, `benchmark_curves.csv`, `benchmark_metadata.json`.
- `policy_rates_aligned.csv`, `policy_rates_metadata.json`, `macro_signals.csv`.
- `common_window_comparison.csv`, `common_window_curves.csv`,
  `common_window_metadata.json`.
- `robustness_cost_sensitivity.csv`, `robustness_delay_sensitivity.csv`,
  `robustness_annual_returns.csv`, `robustness_metadata.json`.
- `pipeline_run_metadata.json`: mode, tested interpreter version, completion
  timestamp, selected policy manifest, raw hashes, stage order and output paths.

The final self-contained reporting snapshot is
`reports/macro_fx_dashboard.xlsx`. To rebuild only that workbook:

```sh
.venv/bin/python src/build_dashboard.py
```

Changing assumptions requires rerunning the relevant Python stages. All model
limitations remain: retrospective evaluation, current-vintage policy data,
assumed publication lag and revision risk, reference-rate execution proxies,
and excluded financing/carry, cash interest and daily resizing costs. Long EUR
is daily equity-relative exposure; flat is a zero-interest reference. These
results are not fully tradable FX performance or an untouched holdout.
