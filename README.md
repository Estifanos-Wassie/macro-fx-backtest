# Macro FX Trading Signal Backtest

A Python research project exploring trading signals using historical
daily foreign exchange data, with an Excel performance dashboard.

## Status
Completed data download, inspection, cleaning, return calculation, and baseline
signal generation. The dataset contains 2,816 ECB daily EUR/USD reference
observations (USD per EUR), from 2015-01-02 through 2025-12-31, with 2,815
nonmissing observation-to-observation returns. These reference rates are not
guaranteed executable trading prices.

The baseline uses simple moving averages over 20 and 60 observations, each
requiring its full window. The signal is +1 when the 20-observation average
exceeds the 60-observation average, -1 when below, and 0 when equal or either
average is unavailable. The first 59 signals are therefore zero.

A signal using an observation becomes available only after that observation;
it cannot earn the return that preceded it (the same row's `fx_return`).
Positions, execution timing, costs, performance metrics, and the macroeconomic
signal remain future work.

## Run the pipeline

From the project root, using the existing virtual environment:

```sh
.venv/bin/python src/download_data.py
.venv/bin/python src/inspect_data.py
.venv/bin/python src/clean_data.py
.venv/bin/python src/calculate_returns.py
.venv/bin/python src/generate_signals.py
```

The download step writes `data/raw/eurusd_ecb.csv`; skip it to preserve the
existing raw download. Signal generation reads `data/processed/eurusd_returns.csv`
and writes `data/processed/baseline_signals.csv`, preserving the input columns
and adding `sma_20`, `sma_60`, and `signal`. Scripts resolve data paths relative
to their location in the project.

## Planned Features
- Collect and clean historical daily FX data.
- Build a baseline trading signal and extend it with a macroeconomic input.
- Backtest with transaction costs and carefully timed signals.
- Evaluate Sharpe ratio and maximum drawdown.
- Create an Excel dashboard showing equity, drawdown, and signal performance.

## Tools
Python, pandas, NumPy, Matplotlib, Requests, and XlsxWriter.
