# Macro FX Trading Signal Backtest

A Python research project exploring trading signals using historical
daily foreign exchange data, with an Excel performance dashboard.

## Status
Completed data download, inspection, cleaning, return calculation, baseline
signal generation, a transparent baseline backtest, and performance evaluation.
The dataset contains
2,816 ECB daily EUR/USD reference
observations (USD per EUR), from 2015-01-02 through 2025-12-31, with 2,815
nonmissing observation-to-observation returns. These reference rates are not
guaranteed executable trading prices.

The baseline uses simple moving averages over 20 and 60 observations, each
requiring its full window. The signal is +1 when the 20-observation average
exceeds the 60-observation average, -1 when below, and 0 when equal or either
average is unavailable. The first 59 signals are therefore zero.

A signal using an observation becomes available only after that observation;
it cannot earn the return that preceded it (the same row's `fx_return`).
The baseline backtest now models delayed positions and illustrative transaction
costs. Full-period performance diagnostics are implemented; the macroeconomic
signal and the dashboard remain future work.

## Run the pipeline

From the project root, using the existing virtual environment:

```sh
.venv/bin/python src/download_data.py
.venv/bin/python src/inspect_data.py
.venv/bin/python src/clean_data.py
.venv/bin/python src/calculate_returns.py
.venv/bin/python src/generate_signals.py
.venv/bin/python src/backtest.py
.venv/bin/python src/evaluate_performance.py
```

The download step writes `data/raw/eurusd_ecb.csv`; skip it to preserve the
existing raw download. Signal generation reads `data/processed/eurusd_returns.csv`
and writes `data/processed/baseline_signals.csv`, preserving the input columns
and adding `sma_20`, `sma_60`, and `signal`. Scripts resolve data paths relative
to their location in the project.

## Baseline backtest

`src/backtest.py` exposes reusable `validate_input`, `calculate_positions`, and
`run_backtest` functions and a runnable entry point. It reads
`data/processed/baseline_signals.csv` and writes
`data/processed/baseline_backtest.csv`, preserving input columns. Generated data
remains ignored by Git. Run the automated checks with:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

For row t, the USD-per-EUR rate is P_t and `fx_return` is
`r_t = P_t / P_(t-1) - 1`. Signal s_t becomes available only after observation t.
We assume execution at observation t+1 and then earn the return from t+1 to t+2.
Thus the position earning row t's return is `p_t = s_(t-2)`:
`signal.shift(2)`, with initial positions zero. For example, a signal on row 0
executes at observation 1 and first earns row 2's return. The last two signals
cannot earn a subsequent observed return and are unused.

Positions -1, 0, and +1 represent stylized FX exposure relative to portfolio
equity. With initial preceding position zero and one-way cost c = 0.0001:

- `gross_return_t = p_t * r_t`
- `turnover_t = abs(p_t - p_(t-1))`
- `turnover_cost_t = c * turnover_t`
- `terminal_closing_cost_t = c * abs(p_t)` on the final row only; zero otherwise
- `net_return_t = gross_return_t - turnover_cost_t - terminal_closing_cost_t`
- `equity_t = 10000 * product(1 + net_return_i)` through row t

The assumed one-way cost is **1 basis point per unit of turnover**, an illustrative
assumption rather than an observed broker quote. Entry or exit has turnover 1;
a direct -1 to +1 reversal has turnover 2. Normal costs are recorded on the row
whose return interval starts with that position change. The final row also
charges liquidation at the final observation, separately from normal turnover.
Its `position` column retains the exposure that earned the final interval's
return; exposure after terminal liquidation is zero. Total `turnover` excludes
that separate terminal close.

Inputs must have required columns, nonmissing unique ascending dates, finite
positive rates, signals in {-1, 0, 1}, and returns matching rate percentage
changes (floating-point tolerance: relative 1e-10, absolute 1e-12). Unexpected
missing or infinite values are rejected. Expected optional SMA warmup gaps are
allowed. The initial FX return must be the sole missing return; it is treated
as zero for calculation only after validation and confirming the initial
position is zero. The saved input `fx_return` retains its initial missing value.

This simplified model excludes financing/carry, interest on cash, and costs
from daily exposure resizing. ECB reference observations are assumed execution
proxies, not guaranteed fills. These are simulated research results and should
not be described as fully tradable FX performance. No parameters are optimized.

## Performance evaluation

`src/evaluate_performance.py` provides reusable `validate_backtest`,
`return_statistics`, `calculate_drawdown`, and `evaluate_performance` functions.
Its entry point reads `data/processed/baseline_backtest.csv` and writes ignored
outputs `baseline_metrics.json` and `baseline_drawdown.csv` in the same folder.
The JSON includes definitions, units, dates, observation counts, capital, and
assumptions. The drawdown CSV contains `date`, `equity`, `running_peak`, and
`drawdown`. Undefined metrics are JSON `null`, never NaN or Infinity.

These are **retrospective full-period baseline diagnostics**, not out-of-sample
results. Evaluation uses net returns, retaining the genuine flat warmup returns
and final liquidation cost. The initial valuation row has no elapsed return
interval and is excluded from return statistics, even though its stored net
return is zero. Missing or infinite net returns are rejected, never filled.
Dates must be unique and ascending, elapsed calendar days must be positive,
and equity must be finite and positive. Every stored equity value is checked
against `initial_capital * cumprod(1 + net_return)` with relative tolerance
1e-10 and absolute tolerance 1e-8.

The initial valuation date is **2015-01-02**, the first return interval ends
**2015-01-05**, and the final observation is **2025-12-31**. This gives 2,815
return observations from 2,816 valuation rows. Initial capital is $10,000.
Elapsed years are actual calendar days between initial valuation and final
observation divided by **365.25**, including weekends and holidays.

- Total return: `final_equity / initial_capital - 1`.
- CAGR: `(final_equity / initial_capital) ** (1 / elapsed_years) - 1`.
- Annualized volatility: `sample_std(net_returns, ddof=1) * sqrt(252)`.
- Zero-reference-rate Sharpe: `mean(net_returns) / sample_std(net_returns, ddof=1)
  * sqrt(252)`. It assumes a zero reference rate and is not adjusted for
  historical cash rates. It is undefined with fewer than two returns or zero
  standard deviation; sample volatility is undefined with fewer than two returns.
- Running peak: the maximum of initial capital and equity observed so far.
- Drawdown: `equity / running_peak - 1`, zero or negative. Including initial
  capital captures losses before any new equity high.
- Maximum drawdown: `max(0, -min(drawdown))`, reported as a positive loss magnitude.

Returns, CAGR, volatility, and drawdowns are stored as fractions (multiply by
100 for percentages). Equity is in USD; Sharpe is dimensionless. The factor
**252** is an annualization convention for this daily-observation dataset,
not a claim of exactly 252 observations in each calendar year. CAGR instead
uses actual elapsed calendar time. The execution, illustrative costs, and
limitations of the baseline model above remain unchanged; no strategy
parameters were tuned during evaluation.

## Planned Features
- Extend the baseline trading signal with a macroeconomic input.
- Create an Excel dashboard showing equity, drawdown, and signal performance.

## Tools
Python, pandas, NumPy, Matplotlib, Requests, and XlsxWriter.
