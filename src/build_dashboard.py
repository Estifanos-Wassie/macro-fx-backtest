"""Build a verified, self-contained Excel reporting snapshot with native charts."""

from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd
import xlsxwriter
from xlsxwriter.utility import xl_col_to_name

if __package__:
    from .analyze_robustness import analyze_robustness
    from .compare_common_window import compare_common_window
else:
    from analyze_robustness import analyze_robustness
    from compare_common_window import compare_common_window

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PORTFOLIOS = ("baseline", "macro", "long_eur", "flat_reference")
LABELS = dict(zip(PORTFOLIOS, ("Moving-average baseline", "Policy differential change",
                              "Constant long EUR exposure", "Flat zero-interest reference")))
COLORS = dict(zip(PORTFOLIOS, ("#183153", "#008C95", "#6B70A0", "#A1ABB4")))
CSV_FILES = ("common_window_comparison", "common_window_curves", "baseline_signals", "macro_signals",
             "robustness_cost_sensitivity", "robustness_delay_sensitivity", "robustness_annual_returns")
JSON_FILES = ("common_window_metadata", "robustness_metadata", "policy_rates_metadata")
PERFORMANCE_START = 6  # Zero-based: Excel row 7 is initial valuation; row 8 first return.
SIGNALS_START = 18


def _match_frame(actual, expected, label):
    try:
        pd.testing.assert_frame_equal(actual.reset_index(drop=True), expected.reset_index(drop=True),
                                      check_dtype=False, check_exact=False, rtol=1e-10, atol=1e-12)
    except AssertionError as exc:
        raise ValueError(f"Inconsistent {label}: {exc}") from exc


def load_snapshot(directory=PROJECT_ROOT / "data/processed"):
    """Recompute and reconcile saved reporting inputs; never rewrite an artifact."""
    directory = Path(directory)
    frames, metadata, hashes = {}, {}, {}
    for stem in CSV_FILES + JSON_FILES:
        suffix = ".csv" if stem in CSV_FILES else ".json"
        path = directory / (stem + suffix)
        if not path.is_file():
            raise FileNotFoundError(f"Dashboard requires {path}; rerun the documented Python pipeline.")
        hashes[path.name] = sha256(path.read_bytes()).hexdigest()
        if suffix == ".csv":
            frames[stem] = pd.read_csv(path)
        else:
            metadata[stem] = json.loads(path.read_text())
    summary, curves, common = compare_common_window(frames["baseline_signals"], frames["macro_signals"])
    _match_frame(frames["common_window_comparison"], summary, "common-window metrics")
    saved_curves = frames["common_window_curves"].copy()
    for column in curves.select_dtypes(include=["datetime"]).columns:
        saved_curves[column] = pd.to_datetime(saved_curves[column], errors="raise")
    _match_frame(saved_curves, curves, "common-window curves")
    for key in ("evaluation", "boundaries", "initial_capital_usd", "execution_lag_observations",
                "one_way_cost_rate", "diagnostics", "signal_definitions", "metric_definitions"):
        if metadata["common_window_metadata"][key] != common[key]:
            raise ValueError(f"Inconsistent common-window metadata: {key}")
    tables, robustness, _ = analyze_robustness(frames["baseline_signals"], frames["macro_signals"],
                                             summary, curves)
    for name, table in tables.items():
        _match_frame(frames["robustness_" + name], table, name)
    for key in ("cost_sensitivity", "delay_sensitivity", "annual_returns", "total_return_sign_checks"):
        if metadata["robustness_metadata"][key] != robustness[key]:
            raise ValueError(f"Inconsistent robustness metadata: {key}")
    series = metadata["policy_rates_metadata"]["download_provenance"]["series"]
    if set(series) != {"ECBDFR", "DFEDTARL", "DFEDTARU"}:
        raise ValueError("Policy provenance must identify the three required FRED series.")
    for sid, entry in series.items():
        if entry["series_id"] != sid or entry["units"] != "Percent":
            raise ValueError(f"Inconsistent policy provenance: {sid}")
    # Verify snapshot files did not change while they were being reconciled.
    if any(sha256((directory / name).read_bytes()).hexdigest() != digest for name, digest in hashes.items()):
        raise ValueError("Dashboard input changed during verification.")
    return {"frames": frames, "metadata": metadata, "curves": curves,
            "common": common, "hashes": hashes}


def build_workbook(snapshot, output):
    """Write native Excel values/formulas/charts with independently verified caches."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    frames, curves, common = snapshot["frames"], snapshot["curves"], snapshot["common"]
    evaluation = common["evaluation"]
    summary = frames["common_window_comparison"].set_index("portfolio")
    with xlsxwriter.Workbook(output, {"strings_to_formulas": False, "strings_to_urls": False}) as book:
        # Fixed creation property makes repeated builds of the same inputs reproducible.
        book.set_properties({"title": "Macro FX research dashboard", "author": "FX Research",
                             "comments": "Self-contained retrospective reporting snapshot",
                             "created": datetime(2000, 1, 1)})
        sheets = {name: book.add_worksheet(name) for name in (
            "Dashboard", "Performance", "Signals", "Robustness", "Methodology")}
        base = {"font_name": "Calibri", "font_size": 11, "font_color": "#344454", "valign": "vcenter"}
        def fmt(**values):
            return book.add_format({**base, **values})
        formats = {
            "title": fmt(font_size=24, bold=True, font_color="white", bg_color="#183153"),
            "section": fmt(font_size=14, bold=True, font_color="#183153"),
            "header": fmt(bold=True, font_color="white", bg_color="#183153", text_wrap=True),
            "text": fmt(text_wrap=True), "note": fmt(font_size=10, text_wrap=True, font_color="#596B7D"),
            "percent": fmt(num_format='0.00%;[Red](0.00%);0.00%'),
            "number": fmt(num_format='0.000;[Red](0.000);0.000'),
            "currency": fmt(num_format='$#,##0.00;[Red]($#,##0.00)'),
            "date": fmt(num_format="yyyy-mm-dd"), "integer": fmt(num_format="0"),
            "na": fmt(font_color="#596B7D", text_wrap=True),
            "finding": fmt(bg_color="#E0F1EF", font_color="#175D63", bold=True, text_wrap=True),
            "hash": fmt(font_name="Consolas", font_size=10, text_wrap=True),
        }
        for sheet in sheets.values():
            sheet.hide_gridlines(2)
            sheet.set_default_row(21)
            sheet.set_column("A:L", 16)
            sheet.set_zoom(90)
            sheet.set_landscape()
            sheet.fit_to_pages(1, 0)
        def title(sheet, text, last=11):
            sheet.merge_range(0, 0, 1, last, text, formats["title"])
            sheet.set_row(0, 25)
            sheet.set_row(1, 20)
        def note(sheet, row, text, last=11, height=38):
            sheet.merge_range(row, 0, row, last, text, formats["note"])
            sheet.set_row(row, height)
        def value(sheet, row, col, item, style="text"):
            if pd.isna(item):
                sheet.write_blank(row, col, None, formats[style])
            elif isinstance(item, (pd.Timestamp, datetime)):
                sheet.write_datetime(row, col, item.to_pydatetime() if isinstance(item, pd.Timestamp) else item, formats["date"])
            elif isinstance(item, (int, float, np.integer, np.floating)):
                sheet.write_number(row, col, float(item), formats[style])
            else:
                sheet.write_string(row, col, str(item), formats[style])
        def table(sheet, row, headers, count, name):
            sheet.add_table(row, 0, row + count, len(headers) - 1, {
                "name": name, "style": "Table Style Medium 2",
                "columns": [{"header": h, "header_format": formats["header"]} for h in headers],
            })
            sheet.set_row(row, 44)

        method = sheets["Methodology"]
        title(method, "Methodology & snapshot provenance", 9)
        method.set_column("A:A", 39)
        method.set_column("B:B", 28)
        method.set_column("C:J", 15)
        settings = [("Starting capital (USD)", common["initial_capital_usd"], "currency"),
                    ("One-way turnover cost (fraction)", common["one_way_cost_rate"], "percent"),
                    ("Signal-to-position shift (observations)", common["execution_lag_observations"], "integer"),
                    ("Annualization convention", 252, "integer"),
                    ("Elapsed calendar years (days / 365.25)", evaluation["elapsed_years"], "number"),
                    ("Initial valuation / execution boundary", pd.Timestamp(evaluation["initial_valuation_date"]), "date"),
                    ("First evaluated return date", pd.Timestamp(evaluation["first_return_end_date"]), "date"),
                    ("Final observation", pd.Timestamp(evaluation["final_observation_date"]), "date"),
                    ("Evaluated return observations", evaluation["return_observation_count"], "integer")]
        for row, (label, item, style) in enumerate(settings, start=5):
            method.write(row, 0, label, formats["text"])
            value(method, row, 1, item, style)
            method.set_row(row, 32)
        method.freeze_panes(5, 1)

        performance = sheets["Performance"]
        title(performance, "Performance | complete common-window series", 24)
        note(performance, 3, "Return fractions include original turnover and terminal costs. Equity, peaks and drawdowns use Excel formulas with verified cached values. Initial valuation has no elapsed return interval.", 24)
        performance.set_column(0, 0, 14)
        performance.set_column(1, 24, 19)
        performance.freeze_panes(PERFORMANCE_START, 1)
        performance.repeat_rows(PERFORMANCE_START - 1)
        headers = ["Date"]
        for name in PORTFOLIOS:
            headers += [f"{LABELS[name]} | {field}" for field in (
                "net return", "equity USD", "running peak USD", "drawdown", "turnover cost", "closing cost")]
        table(performance, PERFORMANCE_START - 1, headers, len(curves), "PerformanceData")
        performance.set_row(PERFORMANCE_START - 1, 78)
        for i, when in enumerate(curves.date):
            value(performance, PERFORMANCE_START + i, 0, when)
        locations = {}
        for j, name in enumerate(PORTFOLIOS):
            net, equity, peak, dd, turnover_cost, closing_cost = range(1 + j * 6, 7 + j * 6)
            locations[name] = {"net": net, "equity": equity, "drawdown": dd}
            running_peak = np.maximum.accumulate(np.maximum(curves[f"{name}_equity"], common["initial_capital_usd"]))
            for i, source in curves.iterrows():
                row, excel = PERFORMANCE_START + i, PERFORMANCE_START + i + 1
                value(performance, row, net, source[f"{name}_net_return"], "percent")
                previous = "Methodology!$B$6" if i == 0 else f"{xl_col_to_name(equity)}{excel-1}"
                performance.write_formula(row, equity, f"={previous}*(1+{xl_col_to_name(net)}{excel})", formats["currency"], source[f"{name}_equity"])
                prev_peak = "Methodology!$B$6" if i == 0 else f"{xl_col_to_name(peak)}{excel-1}"
                performance.write_formula(row, peak, f"=MAX({prev_peak},{xl_col_to_name(equity)}{excel})", formats["currency"], running_peak[i])
                performance.write_formula(row, dd, f"={xl_col_to_name(equity)}{excel}/{xl_col_to_name(peak)}{excel}-1", formats["percent"], source[f"{name}_drawdown"])
                value(performance, row, turnover_cost, source[f"{name}_turnover_cost"], "percent")
                value(performance, row, closing_cost, source[f"{name}_terminal_closing_cost"], "percent")

        dashboard = sheets["Dashboard"]
        title(dashboard, "MACRO FX | Research dashboard")
        dashboard.set_column("A:A", 34)
        dashboard.set_column("B:C", 15)
        dashboard.set_column("D:D", 20)
        dashboard.set_column("E:E", 29)
        dashboard.set_column("F:G", 21)
        dashboard.freeze_panes(8, 1)
        note(dashboard, 3, f"COMMON WINDOW  •  Initial valuation {evaluation['initial_valuation_date']}  •  First return {evaluation['first_return_end_date']}  •  Final {evaluation['final_observation_date']}  •  {evaluation['return_observation_count']:,} return intervals")
        note(dashboard, 5, f"Starting capital ${common['initial_capital_usd']:,.0f} per portfolio  |  One-way cost {common['one_way_cost_rate']*10000:g} bp per turnover unit  |  Execution shift {common['execution_lag_observations']} FX observations  |  Retrospective sample", height=30)
        metric_headers = ["Portfolio", "Total return", "CAGR", "Annualized volatility", "Zero-reference Sharpe", "Max drawdown loss", "Final equity USD"]
        for col, label in enumerate(metric_headers):
            dashboard.write(7, col, label, formats["header"])
        dashboard.set_row(7, 42)
        last_excel = PERFORMANCE_START + len(curves)
        for j, name in enumerate(PORTFOLIOS):
            row = 8 + j
            dashboard.write(row, 0, LABELS[name], fmt(bold=True, font_color=COLORS[name], text_wrap=True))
            dashboard.set_row(row, 33)
            net_col = xl_col_to_name(locations[name]["net"])
            eq_col = xl_col_to_name(locations[name]["equity"])
            dd_col = xl_col_to_name(locations[name]["drawdown"])
            returns = f"Performance!{net_col}{PERFORMANCE_START+2}:{net_col}{last_excel}"
            final_eq = f"Performance!{eq_col}{last_excel}"
            formulas = [f"={final_eq}/Methodology!$B$6-1",
                        f"=({final_eq}/Methodology!$B$6)^(1/Methodology!$B$10)-1",
                        f"=STDEV({returns})*SQRT(Methodology!$B$9)",
                        f'=IF(STDEV({returns})=0,"N/A — zero volatility",AVERAGE({returns})/STDEV({returns})*SQRT(Methodology!$B$9))',
                        f"=-MIN(Performance!{dd_col}{PERFORMANCE_START+1}:{dd_col}{last_excel})", f"={final_eq}"]
            metrics = summary.loc[name]
            caches = [metrics.total_return, metrics.cagr, metrics.annualized_volatility,
                      metrics.zero_reference_rate_sharpe, metrics.maximum_drawdown,
                      curves[f"{name}_equity"].iloc[-1]]
            for col, (formula, cache) in enumerate(zip(formulas, caches), start=1):
                style = "currency" if col == 6 else "number" if col == 4 else "percent"
                if pd.isna(cache):
                    cache, style = "N/A — zero volatility", "na"
                dashboard.write_formula(row, col, formula, formats[style], cache)
        underperformed = all(summary.loc[name, "total_return"] < summary.loc["long_eur", "total_return"] for name in ("baseline", "macro"))
        finding = ("Both tested strategies underperformed constant long EUR exposure in this retrospective sample."
                   if underperformed else "Retrospective comparison shown below; no preferred strategy is selected.")
        dashboard.merge_range(13, 0, 14, 11, finding, formats["finding"])
        for field, anchor, chart_title, percent in (("equity", "A17", "Common-window equity | USD", False),
                                                    ("drawdown", "A36", "Common-window drawdown | from running peak", True)):
            chart = book.add_chart({"type": "line"})
            for name in PORTFOLIOS:
                chart.add_series({"name": LABELS[name], "categories": ["Performance", PERFORMANCE_START, 0, PERFORMANCE_START + len(curves)-1, 0],
                                  "values": ["Performance", PERFORMANCE_START, locations[name][field], PERFORMANCE_START + len(curves)-1, locations[name][field]],
                                  "line": {"color": COLORS[name], "width": 1.6}})
            chart.set_title({"name": chart_title, "name_font": {"size": 14, "color": "#183153"}})
            chart.set_x_axis({"date_axis": True, "num_format": "yyyy", "major_unit": 2, "major_unit_type": "years"})
            chart.set_y_axis({"num_format": "0%" if percent else "$#,##0", "major_gridlines": {"visible": True, "line": {"color": "#E7EBEF"}}})
            chart.set_legend({"position": "bottom", "font": {"size": 10}})
            chart.set_chartarea({"border": {"none": True}})
            chart.set_size({"width": 1080, "height": 350})
            dashboard.insert_chart(anchor, chart)
        note(dashboard, 54, "Reporting snapshot, not an interactive strategy simulator. To change assumptions, rerun the Python pipeline and rebuild. See Methodology for limitations and input hashes.")
        dashboard.print_area("A1:L56")
        dashboard.fit_to_pages(1, 2)

        signals = sheets["Signals"]
        title(signals, "Signals | held-position audit & conditional summaries", 20)
        signals.set_column("A:A", 29)
        signals.set_column("B:U", 21)
        signals.freeze_panes(SIGNALS_START, 1)
        note(signals, 3, "Counts are evaluated return observations, not trades. Mean net returns are conditional interval averages, not contributions to total compounded return.", 20)
        for col, label in enumerate(["Strategy", "Held position", "Interval count", "Mean interval net return"]):
            signals.write(5, col, label, formats["header"])
        signals.set_row(5, 44)
        signal_headers = ["Return / valuation date", "Baseline origin signal date", "Baseline origin signal", "Baseline held position", "Baseline net return", "Baseline turnover", "Baseline closing cost",
                          "Macro origin signal date", "Macro origin signal", "Macro held position", "Macro net return", "Macro turnover", "Macro closing cost",
                          "Origin differential pp", "Origin macro change pp", "Origin ECB source date", "Origin ECB assumed availability", "Origin Fed lower source date", "Origin Fed lower assumed availability", "Origin Fed upper source date", "Origin Fed upper assumed availability"]
        table(signals, SIGNALS_START - 1, signal_headers, len(curves), "SignalsData")
        signals.set_row(SIGNALS_START - 1, 65)
        baseline, macro = frames["baseline_signals"], frames["macro_signals"]
        lag = common["execution_lag_observations"]
        for i, source in curves.iterrows():
            origin = int(source.full_history_row_index) - lag
            row = SIGNALS_START + i
            origin_macro = macro.iloc[origin]
            values = [source.date, source.baseline_originating_signal_date,
                      baseline.signal.iloc[origin] if i else None, source.baseline_position, source.baseline_net_return,
                      source.baseline_turnover, source.baseline_terminal_closing_cost,
                      source.macro_originating_signal_date, origin_macro.macro_signal if i else None,
                      source.macro_position, source.macro_net_return, source.macro_turnover, source.macro_terminal_closing_cost,
                      origin_macro.rate_differential_pp if i else None, origin_macro.macro_change_pp if i else None]
            for sid in ("ECBDFR", "DFEDTARL", "DFEDTARU"):
                values += [pd.Timestamp(origin_macro[f"{sid}_source_date"]) if i else None,
                           pd.Timestamp(origin_macro[f"{sid}_assumed_available_date"]) if i else None]
            for col, item in enumerate(values):
                style = "percent" if col in (4, 6, 10, 12) else "number" if col in (13, 14) else "integer" if col in (2, 3, 5, 8, 9, 11) else "text"
                value(signals, row, col, item, style)
        end_signal = SIGNALS_START + len(curves)
        for j, name in enumerate(("baseline", "macro")):
            pos_col, net_col, turnover_col = ("D", "E", "F") if name == "baseline" else ("J", "K", "L")
            pos_range = f"{pos_col}{SIGNALS_START+2}:{pos_col}{end_signal}"
            net_range = f"{net_col}{SIGNALS_START+2}:{net_col}{end_signal}"
            for k, position in enumerate((-1, 0, 1)):
                row = 6 + j * 3 + k
                mask = curves[f"{name}_position"].iloc[1:].eq(position)
                count = int(mask.sum())
                mean = curves[f"{name}_net_return"].iloc[1:][mask].mean()
                signals.write(row, 0, LABELS[name], formats["text"])
                value(signals, row, 1, position, "integer")
                signals.write_formula(row, 2, f"=COUNTIF({pos_range},B{row+1})", formats["integer"], count)
                signals.write_formula(row, 3, f'=IF(C{row+1}=0,"N/A — no intervals",AVERAGEIF({pos_range},B{row+1},{net_range}))',
                                      formats["percent"], "N/A — no intervals" if not count else mean)
                signals.set_row(row, 33)
            diagnostic = common["diagnostics"][name]
            for col, label in enumerate(("Strategy", "Exposure fraction", "Position changes", "Turnover incl. close"), start=7):
                signals.write(5, col, label, formats["header"])
            row = 6 + j
            signals.write(row, 7, LABELS[name], formats["text"])
            signals.write_formula(row, 8, f'=COUNTIF({pos_range},"<>0")/COUNT({pos_range})', formats["percent"], diagnostic["exposure_fraction"])
            signals.write_formula(row, 9, f'=COUNTIF({turnover_col}{SIGNALS_START+2}:{turnover_col}{end_signal},">0")', formats["integer"], diagnostic["normal_position_change_count"])
            signals.write_formula(row, 10, f'=SUM({turnover_col}{SIGNALS_START+2}:{turnover_col}{end_signal})+ABS({pos_col}{end_signal})', formats["integer"], diagnostic["total_turnover_units_including_liquidation"])
        note(signals, 13, "Exposure fraction: nonzero positions / all evaluated intervals. Position changes: interval rows with turnover > 0, from cash, excluding final close. Turnover: sum absolute position changes plus final liquidation; reversals count twice.", 20)
        note(signals, 15, "Origin signal information is from two FX observations earlier; held positions are already delayed once. Initial valuation is excluded from summaries. Conditional flat-row net returns may include exit costs.", 20)

        robust = sheets["Robustness"]
        title(robust, "Robustness | bounded retrospective checks", 9)
        robust.set_column("A:B", 20)
        robust.set_column("C:C", 35)
        robust.set_column("D:H", 22)
        robust.freeze_panes(6, 3)
        note(robust, 3, f"COST WINDOW: {evaluation['initial_valuation_date']} initial valuation; {evaluation['first_return_end_date']}–{evaluation['final_observation_date']} return dates; {evaluation['return_observation_count']:,} intervals. Positions fixed across costs.", 9)
        for stem, header_row, name in (("cost_sensitivity", 5, "CostSensitivity"), ("delay_sensitivity", 26, "DelaySensitivity")):
            source = frames["robustness_" + stem]
            headers = ["One-way cost bp", "Execution shift", "Portfolio", "Total return", "CAGR", "Annualized volatility", "Zero-reference Sharpe", "Max drawdown loss"]
            table(robust, header_row, headers, len(source), name)
            for i, item in source.iterrows():
                values = [item.one_way_cost_bps, item.execution_shift, LABELS[item.portfolio], item.total_return, item.cagr,
                          item.annualized_volatility, item.zero_reference_rate_sharpe, item.maximum_drawdown]
                for col, entry in enumerate(values):
                    if col == 6 and pd.isna(entry):
                        entry = "N/A — zero volatility"
                    value(robust, header_row + i + 1, col, entry, "integer" if col < 2 else "text" if col == 2 else "number" if col == 6 else "percent")
        delay = snapshot["metadata"]["robustness_metadata"]["delay_sensitivity"]["evaluation"]
        note(robust, 24, f"SHORTER DELAY WINDOW: {delay['initial_valuation_date']} cash valuation; {delay['first_return_end_date']}–{delay['final_observation_date']} return dates; {delay['return_observation_count']:,} intervals. Costs 1 bp. Total shifts 2/3/5 applied once; policy availability lag unchanged.", 9, 46)
        note(robust, 42, "ANNUAL RETURNS: original 1-bp/two-observation common-window net returns. No annual trade resets or extra costs. 2015 is partial; annual compounding reconciles to original totals.", 9)
        annual = frames["robustness_annual_returns"]
        years = sorted(annual.year.unique())
        table(robust, 44, ["Year", "Period", "Return intervals"] + [LABELS[n] for n in PORTFOLIOS], len(years), "AnnualReturns")
        for i, year in enumerate(years):
            group = annual.loc[annual.year.eq(year)].set_index("portfolio")
            values = [year, "Partial year" if group.partial_year.any() else "Full year", group.return_observation_count.iloc[0]] + [group.loc[n, "annual_return"] for n in PORTFOLIOS]
            for col, item in enumerate(values):
                value(robust, 45 + i, col, item, "percent" if col >= 3 else "integer" if col in (0, 2) else "text")
        robust.conditional_format(45, 3, 44 + len(years), 6, {"type": "3_color_scale", "min_color": "#F4CCCC", "mid_type": "num", "mid_value": 0, "mid_color": "#FFFFFF", "max_color": "#CBE8E2"})

        sections = [
            ("Snapshot & refresh", "Self-contained workbook: no external file links, macros or running Python are required. Values describe a reporting snapshot, not an interactive strategy simulator. Change assumptions only by rerunning the Python pipeline, then .venv/bin/python src/build_dashboard.py. Earlier outputs are preserved."),
            ("Sources", "ECB daily USD per EUR reference rates: https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A ; FX history 2015-01-02–2025-12-31. Policy history requested 2014-01-01–2025-12-31 from FRED, percent levels, not seasonally adjusted, daily seven-day series."),
            ("Series IDs & URLs", "ECBDFR: https://fred.stlouisfed.org/series/ECBDFR ; DFEDTARL: https://fred.stlouisfed.org/series/DFEDTARL ; DFEDTARU: https://fred.stlouisfed.org/series/DFEDTARU . Original sources: European Central Bank and Board of Governors of the Federal Reserve System."),
            ("Signal definitions", common["signal_definitions"]["baseline"] + " " + common["signal_definitions"]["macro"] + " Macro differential changes are percentage points, not percentage changes or carry income."),
            ("Availability & execution", "Policy source observation date + one calendar day is ASSUMED availability. Series are backward-aligned separately, never from future values; source age is at most seven days. Current-vintage history and a one-day lag do not establish historical publication timing or eliminate revision risk. Signal after t executes at t+1 and first earns row t+2 return. Full-history shift(2) is applied once, then the common window resets to cash."),
            ("Return & cost model", "FX return[t] = P[t]/P[t-1]-1, USD per EUR. Gross = position × FX return. Turnover = absolute position change from initial cash zero; reversals have two units. Net = gross - turnover × cost - separate final liquidation cost. Equity = initial capital × cumulative product(1 + net return). Entry costs are booked on the first earned interval; final liquidation remains on the last row."),
            ("Metric definitions", "Total return = final/initial equity - 1. CAGR = (final/initial)^(1/elapsed calendar years)-1, with actual days/365.25. Annual volatility = sample standard deviation (ddof=1) × sqrt(252). Zero-reference-rate Sharpe = mean/sample standard deviation × sqrt(252), not adjusted for historical cash rates. 252 is a convention, not an exact annual count. Undefined zero-volatility Sharpe displays N/A. Statistics exclude initial valuation and include eligible flats."),
            ("Drawdown & signal summaries", "Running peak = maximum of initial capital and equity to date; drawdown = equity/peak - 1. Maximum drawdown is a positive loss magnitude. Counts are observations, not trades. Conditional mean interval net returns are not contributions to compounded total return. Performance formulas use verified cached values for previews."),
            ("Interpretation & limitations", "All results are retrospective, not holdout or out-of-sample validation. No rules are optimized or reversed. Long EUR means constant daily equity-relative exposure, not fixed-quantity currency holdings. Flat means zero-interest reference, not historical cash performance. ECB reference rates are assumed execution proxies, not guaranteed fills. Excludes financing/carry, interest on cash and daily exposure-resizing costs; not fully tradable FX performance."),
        ]
        row = 16
        for heading, text in sections:
            method.merge_range(row, 0, row, 9, heading, formats["section"])
            method.merge_range(row + 1, 0, row + 1, 9, text, formats["text"])
            method.set_row(row + 1, 70 if len(text) > 450 else 55)
            row += 3
        method.merge_range(row, 0, row, 9, "Input artifact SHA-256 | immutable build provenance", formats["section"])
        row += 1
        for filename, digest in snapshot["hashes"].items():
            method.write(row, 0, filename, formats["text"])
            method.merge_range(row, 1, row, 9, digest, formats["hash"])
            method.set_row(row, 33)
            row += 1
        method.merge_range(row + 1, 0, row + 1, 9, "Policy raw response hashes, source URLs and UTC retrieval times are recorded in policy_rates_metadata.json; its hash above pins that provenance. Common-window and robustness metadata record preserved-artifact hashes and exact scenario windows.", formats["note"])
        method.set_row(row + 1, 40)
        dashboard.activate()
        dashboard.set_first_sheet()
    return output


def main():
    snapshot = load_snapshot()
    output = build_workbook(snapshot, PROJECT_ROOT / "reports/macro_fx_dashboard.xlsx")
    print(f"Built verified reporting snapshot: {output}")


if __name__ == "__main__":
    main()
