# Macro FX Trading Signal Backtest

A Python research project exploring trading signals using historical
daily foreign exchange data, with an Excel performance dashboard.

## Status
Completed data download, inspection, cleaning, return calculation, baseline
signal generation, a transparent baseline backtest, performance evaluation,
aligned benchmark comparisons, policy-rate data preparation, and a standalone
macro signal, a four-portfolio common-window comparison, bounded robustness
checks, and a reproducible Excel reporting dashboard.
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
.venv/bin/python src/compare_benchmarks.py
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

## Benchmark comparison

`src/compare_benchmarks.py` exposes `validate_baseline`, `build_benchmarks`, and
`compare_benchmarks`, plus the runnable pipeline command above. It reads the
saved baseline backtest and writes three ignored outputs in `data/processed/`:

- `benchmark_comparison.csv`: one metric row per portfolio; fractional units,
  with a blank field for undefined Sharpe.
- `benchmark_curves.csv`: aligned dates and each portfolio's net returns,
  equity, drawdown, held positions, gross returns, turnover, and separate costs.
- `benchmark_metadata.json`: dates, capital, cost rate, metric definitions,
  benchmark definitions, entry timing, turnover, costs, and metrics; undefined
  metrics use JSON `null`.

The baseline uses its saved net returns and equity unchanged, after reconciling
them to the existing model. The long-EUR benchmark stays flat until the same
first held-position return row, then holds +1 through the final interval.
This is **constant long EUR exposure under the daily equity-relative exposure
model**, not a literal fixed-quantity currency holding. It reuses the backtest
engine with synthetic instructions placed two rows before the desired holdings;
the engine applies the execution lag once. Resulting positions and costs are
checked explicitly. If the baseline never takes exposure, the comparison fails
clearly because no shared active start exists.

The long benchmark enters at the **2015-03-27** observation and first earns the
return ending **2015-03-30**, matching the baseline's first nonzero position.
Entry costs 0.0001 of equity (1 bp), recorded on that first return row. It has
no intermediate turnover and liquidates on **2025-12-31**, with a separate
0.0001 closing cost on the final row: **2 turnover units including liquidation**.
The flat portfolio has zero positions, returns, costs, and drawdown; equity
remains $10,000. It is a **zero-interest reference**, not historical cash
investment performance. Its Sharpe is undefined, rather than zero.

All three portfolios share the 2015-01-02 initial valuation, $10,000 capital,
2025-12-31 final observation, and 2,815 evaluated return intervals. Genuine flat
warmup returns remain included and the initial valuation is excluded from return
statistics. Metrics reuse the evaluator's sample standard deviation, sqrt(252)
annualization, zero reference rate, actual-calendar-day CAGR, and running peaks
that include initial capital.

| Portfolio | Total return | CAGR | Annualized volatility | Zero-reference-rate Sharpe | Maximum drawdown (loss magnitude) |
|---|---:|---:|---:|---:|---:|
| Moving-average baseline | -5.72% | -0.53% | 7.72% | -0.030 | 21.62% |
| Constant long EUR exposure | 8.21% | 0.72% | 7.72% | 0.130 | 23.44% |
| Flat zero-interest reference | 0.00% | 0.00% | 0.00% | Undefined | 0.00% |

These remain retrospective full-period diagnostics, not out-of-sample results.
The shared active start is chosen retrospectively from the baseline. No strategy
parameters are tuned. All portfolios use the same reference observations and
daily exposure conventions; financing/carry, cash interest, and daily resizing
costs remain excluded. ECB reference rates are assumed execution proxies,
not guaranteed fills, so this is not fully tradable FX performance.

## Policy-rate data preparation

This stage collects and aligns policy-rate inputs only. It does not create
macroeconomic trading signals or calculate their performance.

Official FRED metadata identifies all three series as **Percent**, **Not
Seasonally Adjusted**, with **Daily, 7-Day** frequency:

| FRED series | Definition | Original source | Aligned value column |
|---|---|---|---|
| [ECBDFR](https://fred.stlouisfed.org/series/ECBDFR) | ECB Deposit Facility Rate for Euro Area | European Central Bank; Key ECB Interest Rates | `ecb_deposit_pct` |
| [DFEDTARL](https://fred.stlouisfed.org/series/DFEDTARL) | Federal Funds Target Range, Lower Limit | Board of Governors; FOMC Press Release | `fed_lower_pct` |
| [DFEDTARU](https://fred.stlouisfed.org/series/DFEDTARU) | Federal Funds Target Range, Upper Limit | Board of Governors; FOMC Press Release | `fed_upper_pct` |

Run from the project root using the existing environment:

```sh
.venv/bin/python src/download_policy_rates.py
.venv/bin/python src/align_policy_rates.py
.venv/bin/python -m unittest discover -s tests -v
```

The downloader requests **2014-01-01 through 2025-12-31**, providing pre-FX
history, via FRED's `https://fred.stlouisfed.org/graph/fredgraph.csv` facility
with `id`, `cosd`, and `coed` parameters. Each run archives original response
bytes in a new timestamped `data/raw/policy_rates/<UTC timestamp>/` directory.
Its `metadata.json` records series IDs, official metadata URLs, request and
response URLs, units, frequency, requested and actual periods, HTTP status,
UTC retrieval times, SHA-256 hashes, and missing-value/absent-date reports.
No previous raw download is replaced. HTTP or validation failures preserve any
received body and a failed manifest; they do not become successful datasets.

The alignment command uses the latest download attempt and rejects it if failed
or incomplete, rather than silently using an older download. To select an
existing successful archive explicitly, supply
`--manifest data/raw/policy_rates/<UTC timestamp>/metadata.json`. Raw hashes and
requested endpoint coverage are rechecked before processing. Dates and numbers
are parsed strictly; duplicate or invalid dates and infinite rates are rejected.
Negative policy rates are valid. Missing source values and absent calendar rows
are reported explicitly in metadata; missing rates are skipped during matching.

Each series is aligned **separately**, using a backward as-of join from the FX
date to **source observation date + one calendar day** as its **ASSUMED
availability date**. This is a modeling lag, not a verified historical
publication timestamp. No future backfill or interpolation is used. Matched
availability must be on or before the FX date. Source age is measured from
the source observation date, and values older than **seven calendar days** or
unmatched FX dates cause failure. A prior valid value may bridge a missing
source value only within this age limit.

Fed lower bounds are checked against upper bounds on common source dates and
again after separate alignment. Derived quantities are:

- `fed_midpoint_pct = (fed_lower_pct + fed_upper_pct) / 2`, a percent level.
- `rate_differential_pp = ecb_deposit_pct - fed_midpoint_pct`, a difference in
  percentage points. Neither quantity is a decimal investment return.

Outputs are ignored `data/processed/policy_rates_aligned.csv` and
`policy_rates_metadata.json`. The CSV preserves the FX input columns and all
2,816 original dates in order, adding rate values, the derived quantities,
and each series' matched source date, assumed availability date, and age.
Processed metadata includes original provenance, input/output hashes, missing
reports, maximum source ages, and timing assumptions. Existing FX, baseline,
and benchmark artifacts are preserved.

The verified download contains **4,383 observations per series**, from
2014-01-01 through 2025-12-31, with **zero missing values** and **zero absent
calendar dates**. The aligned output has **2,816 rows**, and maximum source
age is **one day for each series**. For example, the downloaded Fed range on
source date 2015-12-16 is 0.25–0.50%; under the assumed lag it first appears
on FX date 2015-12-17. FX date 2015-12-16 still uses the previous source day's
0.00–0.25% range.

Downloaded history reflects the **current vintage at retrieval**, not a
historical real-time vintage. A one-day lag does not establish historically
correct publication availability or eliminate revision risk. This remains
retrospective research. Downloader unit tests mock HTTP responses and are
separate from actual FRED download and full-dataset alignment verification.

## Standalone macro signal

`src/generate_macro_signals.py` exposes `validate_aligned_data` and
`generate_macro_signals` plus a runnable entry point:

```sh
.venv/bin/python src/generate_macro_signals.py
.venv/bin/python -m unittest discover -s tests -v
```

It reads the existing `data/processed/policy_rates_aligned.csv` and writes
ignored `data/processed/macro_signals.csv`, preserving all 2,816 dates, input
values, and per-series source-date, assumed-availability, and source-age audit
columns. No policy data are downloaded again or realigned. Validation checks
unique chronological FX dates, finite rates, Fed bound ordering, midpoint and
differential arithmetic, and the original one-calendar-day assumed availability
lag with source ages of at most seven days. Availability must not exceed the
corresponding FX date.

The fixed rule was chosen before evaluating the signal:

- `d_t = ecb_deposit_pct_t - fed_midpoint_pct_t`, in percentage points.
- `macro_change_pp_t = d_t - d_(t-63)`, an absolute difference in percentage
  points over **63 FX observations**, not 63 calendar days.
- `macro_signal = +1` for changes greater than `1e-10`, `-1` for changes below
  `-1e-10`, and `0` otherwise or when history is insufficient.

Absolute changes **at or below 1e-10 percentage points** are numerical zero,
with **no relative tolerance**. This is floating-point handling, not an
economic threshold. The change column retains its unrounded difference.
There is no percentage-change calculation on policy rates or differentials.
The lookback of 63 observations is a fixed, roughly quarterly research horizon;
neither it nor the tolerance is optimized.

The hypothesis is that a rise in the ECB-minus-Fed policy differential may
support EUR appreciation, while a fall may support depreciation. A negative
differential becoming less negative therefore gives a positive signal. This
is an untested directional hypothesis, **not carry income**: no interest
accrual, financing, currency returns, or macro performance is calculated here.

The first 63 changes (indices 0–62) remain missing with zero signals. Index 63
is the first eligible change because it compares index 63 with index 0. In the
current dataset this is **2015-04-01**: `-0.325 - (-0.325) = 0` percentage
points, so the first eligible signal is neutral. Counts are **999 negative,
552 positive, and 1,265 zero**; zeros comprise **63 warm-up observations** and
**1,202 eligible flat observations**.

This output is a **signal, not a held position**. It uses only the already
backward-aligned values with their modeled availability lag intact. The signal
on FX row t is formed after observation t. This script applies no execution
delay; a later backtest will apply the existing two-observation delay once,
executing at t+1 and first earning the return ending at t+2. The separate
common-window comparison below now evaluates that fixed signal. Current-vintage policy history, assumed publication
availability, and revision risk remain limitations. This is retrospective
research, not out-of-sample research or evidence of tradable profitability.

## Common-window comparison

Run the comparison and its tests using the existing generated signal files:

```sh
.venv/bin/python src/compare_common_window.py
.venv/bin/python -m unittest discover -s tests -v
```

`compare_common_window.py` validates the saved SMA and macro signal definitions,
derives eligibility, builds the four portfolios, and reuses the existing
evaluator for every metric. The backtest now exposes `run_position_backtest`
for already-lagged held positions; `run_backtest` delegates to it after applying
the existing lag. Full-history baseline behavior remains unchanged.

Eligibility depends on required history, **not the first nonzero signal**:
the 20/60-observation SMA baseline is eligible at index 59, and the fixed
63-observation macro difference at index 63. Both must have contiguous valid
indicators thereafter. The common eligible signal index is therefore 63.
Applying the two-observation execution delay gives the first evaluated return
at **index 65 (2015-04-07)**, with its initial valuation/execution boundary at
**index 64 (2015-04-02)**. These boundaries are derived and checked against the
fixed history and timing assumptions; inconsistent inputs cause failure.

Strategy positions are calculated as `signal.shift(2)` on full history before
selecting the window. The macro policy-data availability lag is already
embedded and is preserved. No second execution delay is applied. Each
portfolio starts from cash with **$10,000** at the initial valuation, which has
zero portfolio return, position, and cost. Its preceding FX interval is outside
this simulation. On the first evaluated return row, turnover is measured from
cash, even if the full-history strategy previously held the same position.
Eligible macro zero signals remain genuine flat periods in the comparison;
the start is not moved forward until the macro strategy trades.

Constant long EUR exposure begins at the same execution boundary and earns the
first evaluated return. It follows the daily equity-relative exposure model,
not a fixed-quantity currency holding. The flat reference remains at $10,000,
with zero returns and undefined Sharpe. All four portfolios pay the same
illustrative 1-bp one-way turnover cost and separate final-liquidation cost
when applicable. Initial equity, dates, metric definitions, and statistical
observation counts are identical.

The window ends **2025-12-31**, with **2,751 evaluated returns** and 2,752
valuation rows. Annualization and units follow the evaluator above: net returns,
sample standard deviation, sqrt(252) convention, zero-reference-rate Sharpe,
actual-calendar-day CAGR, and initial-capital-aware drawdown.

| Portfolio | Total return | CAGR | Annualized volatility | Zero-reference-rate Sharpe | Maximum drawdown (loss magnitude) |
|---|---:|---:|---:|---:|---:|
| Moving-average baseline | -5.94% | -0.57% | 7.80% | -0.033 | 21.62% |
| Policy differential change | -24.14% | -2.54% | 5.75% | -0.411 | 27.17% |
| Constant long EUR exposure | 8.47% | 0.76% | 7.80% | 0.134 | 23.44% |
| Flat zero-interest reference | 0.00% | 0.00% | 0.00% | Undefined | 0.00% |

Common-window baseline metrics can differ from the earlier full-period
metrics because earlier returns are excluded, the capital and running peak
reset to $10,000, a new entry from cash is charged, and the elapsed-time and
return-statistics samples change. These are new simulations rather than slices
of previously accumulated equity. Earlier results remain preserved.

The macro strategy has nonzero exposure on **1,549 / 2,751 = 56.31%** of
evaluated return intervals. Exposure fraction counts nonzero held-position rows
over all evaluated return rows, including eligible flats in the denominator.
Its **49 position changes** count return rows where exposure differs from the
preceding row, starting from cash; the separate terminal close is excluded.
Normal turnover sums absolute position changes: **53 units**, with a reversal
counting as two. Final liquidation adds one unit for **54 total units**.

New ignored outputs under `data/processed/` are:

- `common_window_comparison.csv`: one metric row per portfolio.
- `common_window_curves.csv`: aligned dates, FX returns, full-history row
  indices, portfolio net returns, equity, drawdowns, positions, turnover, costs,
  and originating strategy-signal dates.
- `common_window_metadata.json`: eligibility and boundary indices, dates,
  return count, initial capital, execution lag, costs, signal/metric definitions,
  exposure diagnostics, limitations, and before/after-verified hashes of the
  pre-existing data artifacts. Undefined metrics are JSON null and CSV blanks.

These are **retrospective common-window diagnostics**, not a holdout or
out-of-sample evaluation. No parameters were tuned and no winning rule is
selected. The macro signal is not carry income. Financing/carry, cash interest,
and daily resizing costs remain excluded; ECB reference rates are assumed
execution proxies rather than guaranteed fills. Current-vintage policy data,
modeled availability, and revision risk remain limitations. These results do
not establish fully tradable FX performance.

## Bounded robustness checks

Run `.venv/bin/python src/analyze_robustness.py` after the common-window
comparison. Run all tests with `.venv/bin/python -m unittest discover -s tests -v`.
The analysis reuses the existing held-position simulation and evaluation
functions without changing signal rules or earlier outputs.

The fixed cost scenarios are **0, 1, 5, and 10 bp one-way**, with identical
positions and the original two-observation delay/window. The **1-bp case
reproduces the saved common-window results**. Increasing costs reduces or leaves
unchanged final equity. Moving-average total returns range from -4.88% to
-14.96%; macro returns range from -23.73% to -27.74% across these costs.

The fixed execution shifts are **2, 3, and 5 FX observations**, at 1 bp one-way.
Each shift is applied once to full-history signals, keeping the modeled
policy-data availability lag intact. All delays use a shared shorter window:
initial cash valuation **2015-04-09 (index 67)**, first evaluated return
**2015-04-10 (index 68)**, final observation **2025-12-31**, and **2,748 returns**.
This differs from the cost/annual analysis window of 2015-04-02 initial
valuation, 2015-04-07 first return, and 2,751 returns. Each portfolio resets to
$10,000 cash, including fresh entry and final-liquidation costs where applicable.

Calendar-year returns compound the original saved 1-bp/two-observation net
returns, preserving actual costs and flat periods without annual trade resets.
**2015 is partial**. Compounding annual returns reconciles with each original
common-window total return.

See [the complete cost, delay, and annual-return tables](docs/robustness.md)
for every scenario, definitions, windows, counts, and limitations. Generated
`robustness_*.csv` tables and `robustness_metadata.json` are ignored under
`data/processed/`; metadata records scenario assumptions, reconciliation checks,
and verified hashes of preserved artifacts.

Neither strategy's total return changes sign across the specified cost or
delay scenarios: both remain negative. These are retrospective sensitivity
checks, not parameter optimization, a preferred-rule selection, or a holdout
evaluation. No signal was reversed and no additional lookbacks were searched.
Existing financing, execution-proxy, daily-resizing-cost, policy-vintage and
publication-timing limitations remain in force.

## Excel reporting dashboard

Build the self-contained workbook from the verified saved outputs:

```sh
.venv/bin/python src/build_dashboard.py
```

Output: **`reports/macro_fx_dashboard.xlsx`**, ignored by Git. Requires the
common-window comparison, original signal files, robustness tables, and their
metadata. If those reports need refreshing from the existing prepared inputs:

```sh
.venv/bin/python src/compare_common_window.py
.venv/bin/python src/analyze_robustness.py
.venv/bin/python src/build_dashboard.py
.venv/bin/python -m unittest discover -s tests -v
```

The builder reconciles saved common-window curves and metrics against the
shared simulation/evaluation functions, and all sensitivity and annual tables
against the robustness analysis. Missing or inconsistent inputs cause failure.
It preserves existing strategy settings and data outputs. Input artifact
SHA-256 hashes are recorded inside the workbook; identical verified inputs
produce identical workbook bytes.

The five sheets are:

- **Dashboard:** common-window dates, capital, illustrative costs and execution
  delay; four-portfolio metrics; native Excel equity and drawdown line charts
  covering every valuation row. Undefined Sharpe displays “N/A — zero volatility.”
- **Performance:** all common-window dates, net returns, turnover/closing
  costs, and traceable equity, running-peak and drawdown formulas. Every formula
  includes a verified cached result for previews, including initial capital
  and terminal liquidation treatment.
- **Signals:** held positions, originating signal dates/values, macro change
  inputs and policy availability audits. Position summaries show observation
  counts and conditional mean interval net returns; these are not trade counts
  or contributions to compounded portfolio return. Exposure, changes and
  turnover have explicit definitions.
- **Robustness:** complete cost and execution-delay scenarios, distinct window
  labels, and calendar-year returns with conditional formatting. 2015 is
  labeled partial year.
- **Methodology:** sources, series IDs, signal and metric definitions, timing,
  units, omitted financing/resizing costs, policy vintage/revision limitations,
  refresh instructions, and input hashes.

The workbook is a **reporting snapshot**, with no external file links, macros,
or need for Python while viewing. It is not an interactive strategy simulator:
changing strategy assumptions requires rerunning the relevant Python pipeline
stages and rebuilding the workbook. Its primary comparison is the common
window, rather than earlier full-period baseline metrics. Both tested
strategies underperformed constant long EUR exposure in this retrospective
sample; this does not select a preferred rule or establish tradable performance.

Workbook tests inspect the XLSX XML for sheet structure, formula ranges and
caches, chart references and complete cached series, headline metrics, signal
summaries, scenario tables, annual returns, provenance, and absence of macros
or external links. Excel and LibreOffice are not installed in the build
environment, so **native visual rendering remains unverified**; structural and
numerical checks do not substitute for that inspection.

## Tools
Python, pandas, NumPy, Matplotlib, Requests, and XlsxWriter.
