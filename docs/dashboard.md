# Excel reporting dashboard

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

The user reports that the previously uploaded dashboard was independently
checked and rendered in LibreOffice; native Excel was not tested. That claim
applies to the uploaded version, not the newly revised print layout. The current
layout specifies two A3 landscape pages at 85% scale, with a manual break
before the second chart. Saved settings and chart anchors are checked so each
chart stays on its own page; **the revised printed appearance still needs
renderer verification**. On-screen layout, formulas and series are preserved.

Presentation refinements based on the user's initial Numbers screenshot review
use annual, year-only chart ticks, concise legends, four-decimal percentage
formats for conditional mean interval returns, and narrower wrapped Methodology
text. Flat-position intervals can include exit costs. Detailed tables retain
their readable text and horizontal scrolling. The revised Numbers appearance
and native Excel rendering remain unverified until inspected in those apps.


See the [README](../README.md) for project setup and the
[reproduction guide](reproducibility.md) for expected pipeline outputs.
