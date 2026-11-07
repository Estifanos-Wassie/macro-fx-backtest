# Bounded retrospective robustness analysis

These fixed sensitivity checks are not parameter optimization, holdout validation, or a choice of a winning rule. Signal definitions and their policy-data availability assumptions are unchanged.

Run `.venv/bin/python src/analyze_robustness.py`; tests: `.venv/bin/python -m unittest discover -s tests -v`.

Total return, CAGR, and maximum drawdown below are percentages. Maximum drawdown is a positive loss magnitude. Sharpe is dimensionless and assumes a zero reference rate; it is not adjusted for historical cash rates. All portfolios start from $10,000.

## Trading-cost sensitivity

One-way costs are 0, 1, 5, and 10 basis points (bps / 10,000 as return fractions). Positions stay identical, with the existing two-observation execution lag. The original common window has initial valuation 2015-04-02 (index 64), first evaluated return 2015-04-07 (index 65), final observation 2025-12-31, and 2,751 return observations. Each scenario recomputes entry, reversal and final-liquidation costs through the shared position engine. The 1-bp scenario reconciles with the saved original curves and metrics.

| Cost (bp) | Portfolio | Total return | CAGR | Zero-reference Sharpe | Max drawdown loss |
|---:|---|---:|---:|---:|---:|
| 0 | Moving average | -4.88% | -0.46% | -0.020 | 21.45% |
| 0 | Macro | -23.73% | -2.49% | -0.402 | 26.79% |
| 0 | Long EUR | 8.49% | 0.76% | 0.135 | 23.44% |
| 0 | Flat | 0.00% | 0.00% | Undefined | 0.00% |
| 1 | Moving average | -5.94% | -0.57% | -0.033 | 21.62% |
| 1 | Macro | -24.14% | -2.54% | -0.411 | 27.17% |
| 1 | Long EUR | 8.47% | 0.76% | 0.134 | 23.44% |
| 1 | Flat | 0.00% | 0.00% | Undefined | 0.00% |
| 5 | Moving average | -10.06% | -0.98% | -0.085 | 23.41% |
| 5 | Macro | -25.76% | -2.73% | -0.446 | 28.67% |
| 5 | Long EUR | 8.39% | 0.75% | 0.134 | 23.44% |
| 5 | Flat | 0.00% | 0.00% | Undefined | 0.00% |
| 10 | Moving average | -14.96% | -1.50% | -0.151 | 27.14% |
| 10 | Macro | -27.74% | -2.98% | -0.489 | 30.50% |
| 10 | Long EUR | 8.28% | 0.74% | 0.132 | 23.44% |
| 10 | Flat | 0.00% | 0.00% | Undefined | 0.00% |

## Execution-delay sensitivity

Total signal-to-position shifts of 2, 3, and 5 FX observations are applied once to full-history signals, with one-way costs fixed at 1 bp. They replace the two-row execution assumption for this check; they do not add a second shift to pre-lagged positions. The policy-data assumed availability lag stays embedded.

All delay scenarios share the shorter window: initial cash valuation **2015-04-09 (index 67)**, first evaluated return **2015-04-10 (index 68 = 63 + 5)**, final observation **2025-12-31**, and **2,748 evaluated returns**. Full-history positions are calculated before slicing. Every portfolio resets to cash, pays fresh entry turnover when applicable, and closes its final exposure. Long EUR begins at the shared boundary for all shifts. These results must not be compared as if they used the original cost-sensitivity window.

| Shift (FX observations) | Portfolio | Total return | CAGR | Zero-reference Sharpe | Max drawdown loss |
|---:|---|---:|---:|---:|---:|
| 2 | Moving average | -6.42% | -0.62% | -0.039 | 21.62% |
| 2 | Macro | -24.14% | -2.54% | -0.411 | 27.17% |
| 2 | Long EUR | 9.04% | 0.81% | 0.141 | 23.44% |
| 2 | Flat | 0.00% | 0.00% | Undefined | 0.00% |
| 3 | Moving average | -9.17% | -0.89% | -0.074 | 22.08% |
| 3 | Macro | -27.39% | -2.94% | -0.481 | 30.50% |
| 3 | Long EUR | 9.04% | 0.81% | 0.141 | 23.44% |
| 3 | Flat | 0.00% | 0.00% | Undefined | 0.00% |
| 5 | Moving average | -7.66% | -0.74% | -0.055 | 22.85% |
| 5 | Macro | -25.35% | -2.69% | -0.439 | 28.23% |
| 5 | Long EUR | 9.04% | 0.81% | 0.141 | 23.44% |
| 5 | Flat | 0.00% | 0.00% | Undefined | 0.00% |

## Calendar-year returns

Each annual return equals product(1 + net return) - 1, grouping the original saved 1-bp, two-observation common-window series by interval-ending calendar year. Initial valuation is excluded; eligible flat returns remain. Costs stay on their original rows, with no annual entry, liquidation or position reset. 2015 is partial, starting with the return ending 2015-04-07. Compounding the annual returns reproduces each original common-window total return.

| Year | Return observations | Moving average | Macro | Long EUR | Flat |
|---|---:|---:|---:|---:|---:|
| 2015 (partial) | 191 | -15.28% | 0.55% | 0.52% | 0.00% |
| 2016 | 257 | 2.66% | -4.65% | -3.18% | 0.00% |
| 2017 | 255 | 4.43% | -12.96% | 13.77% | 0.00% |
| 2018 | 255 | 7.01% | 5.19% | -4.53% | 0.00% |
| 2019 | 255 | -4.17% | 1.80% | -1.89% | 0.00% |
| 2020 | 257 | 2.27% | -2.67% | 9.23% | 0.00% |
| 2021 | 258 | 1.88% | 0.00% | -7.70% | 0.00% |
| 2022 | 257 | 1.48% | 4.11% | -5.83% | 0.00% |
| 2023 | 255 | -5.74% | 4.63% | 3.60% | 0.00% |
| 2024 | 256 | -7.63% | -7.55% | -5.98% | 0.00% |
| 2025 | 255 | 9.70% | -13.38% | 13.09% | 0.00% |

## Findings and limits

Neither moving-average nor macro total return changes sign in the specified cost or delay scenarios: both remain negative throughout. Higher costs reduce or leave unchanged final equity with fixed positions and positive return factors. These bounded results do not establish robustness outside the listed assumptions and do not identify a preferred delay or rule.

All simulations reuse the existing engine and evaluator. CAGR uses actual calendar days / 365.25; volatility and zero-reference Sharpe use sample standard deviation (ddof=1) and the sqrt(252) convention. Drawdown includes initial capital in the peak. The long benchmark is daily equity-relative EUR exposure, not fixed-quantity currency holdings. Flat is a zero-interest reference, not historical cash performance. Financing/carry, cash interest and daily resizing costs remain excluded; ECB reference rates are execution proxies, not guaranteed fills. Policy history is current vintage, with assumed availability and revision risk. This is retrospective research, not fully tradable FX performance.

Ignored generated outputs under `data/processed/`: `robustness_cost_sensitivity.csv`, `robustness_delay_sensitivity.csv`, `robustness_annual_returns.csv`, and `robustness_metadata.json`. Tables store returns as fractions; metadata records definitions, scenario parameters, exact windows/counts, reconciliation checks and preserved artifact hashes. JSON uses null for undefined metrics, CSV uses blank fields. Earlier outputs are preserved byte-for-byte.
