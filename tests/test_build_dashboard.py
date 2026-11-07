from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import numpy as np
import pandas as pd
from xlsxwriter.utility import xl_col_to_name

from src.analyze_robustness import analyze_robustness
from src.build_dashboard import (CSV_FILES, JSON_FILES, PERFORMANCE_START, SIGNALS_START,
                                  PORTFOLIOS, build_workbook, load_snapshot)
from src.compare_common_window import compare_common_window
from src.generate_macro_signals import generate_macro_signals

NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "c": "http://schemas.openxmlformats.org/drawingml/2006/chart"}


def write_synthetic_snapshot(directory):
    """Generate self-contained test inputs, independent of ignored real-data files."""
    dates = pd.date_range("2020-10-15", periods=90)
    rates = pd.Series(1 + np.arange(90) * .002)
    baseline = pd.DataFrame({"date": dates, "eurusd": rates})
    baseline["fx_return"] = rates.pct_change(fill_method=None)
    baseline["sma_20"] = rates.rolling(20).mean()
    baseline["sma_60"] = rates.rolling(60).mean()
    baseline["signal"] = (baseline.sma_20.gt(baseline.sma_60).astype(int)
                          - baseline.sma_20.lt(baseline.sma_60).astype(int))
    d = np.array([-2.] * 63 + ([-1., -1., -3., -3., -2., -2.] * 5)[:27])
    macro = pd.DataFrame({"date": dates, "eurusd": rates, "ecb_deposit_pct": d + .125,
                          "fed_lower_pct": 0., "fed_upper_pct": .25,
                          "fed_midpoint_pct": .125, "rate_differential_pp": d})
    for sid in ("ECBDFR", "DFEDTARL", "DFEDTARU"):
        macro[f"{sid}_source_date"] = dates - pd.Timedelta(days=1)
        macro[f"{sid}_assumed_available_date"] = dates
        macro[f"{sid}_source_age_days"] = 1
    macro = generate_macro_signals(macro)
    summary, curves, common = compare_common_window(baseline, macro)
    tables, robust, _ = analyze_robustness(baseline, macro, summary, curves)
    frames = {"baseline_signals": baseline, "macro_signals": macro,
              "common_window_comparison": summary, "common_window_curves": curves,
              **{"robustness_" + k: v for k, v in tables.items()}}
    for name, frame in frames.items():
        frame.to_csv(directory / (name + ".csv"), index=False, date_format="%Y-%m-%d")
    policy = {"download_provenance": {"series": {
        sid: {"series_id": sid, "units": "Percent"} for sid in ("ECBDFR", "DFEDTARL", "DFEDTARU")}}}
    for name, metadata in (("common_window_metadata", common), ("robustness_metadata", robust),
                           ("policy_rates_metadata", policy)):
        (directory / (name + ".json")).write_text(json.dumps(metadata, allow_nan=False))


class WorkbookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temporary.name)
        write_synthetic_snapshot(cls.directory)
        cls.snapshot = load_snapshot(cls.directory)
        cls.output = build_workbook(cls.snapshot, cls.directory / "dashboard.xlsx")
        cls.zip = ZipFile(cls.output)
        shared = ET.fromstring(cls.zip.read("xl/sharedStrings.xml"))
        cls.strings = ["".join(node.itertext()) for node in shared]
        cls.sheets = [ET.fromstring(cls.zip.read(f"xl/worksheets/sheet{i}.xml")) for i in range(1, 6)]

    @classmethod
    def tearDownClass(cls):
        cls.zip.close()
        cls.temporary.cleanup()

    def cell(self, sheet, address):
        if not hasattr(self, "cell_index"):
            self.cell_index = [{c.get("r"): c for c in root.findall(".//s:c", NS)} for root in self.sheets]
        cell = self.cell_index[sheet].get(address)
        self.assertIsNotNone(cell, address)
        raw = cell.find("s:v", NS)
        if raw is None:
            return cell, None
        if cell.get("t") == "s":
            return cell, self.strings[int(raw.text)]
        if cell.get("t") == "str":
            return cell, raw.text
        return cell, float(raw.text)

    def test_structure_self_containment_and_reproducibility(self):
        workbook = ET.fromstring(self.zip.read("xl/workbook.xml"))
        names = [node.get("name") for node in workbook.findall("s:sheets/s:sheet", NS)]
        self.assertEqual(names, ["Dashboard", "Performance", "Signals", "Robustness", "Methodology"])
        self.assertFalse(any("externalLink" in p or "vbaProject" in p or "connections.xml" in p for p in self.zip.namelist()))
        self.assertEqual(len([p for p in self.zip.namelist() if p.startswith("xl/tables/table")]), 5)
        for sheet in self.sheets:
            self.assertIsNotNone(sheet.find("s:sheetViews/s:sheetView/s:pane", NS))
            for cell in sheet.findall(".//s:c[s:f]", NS):
                self.assertIsNotNone(cell.find("s:v", NS), cell.get("r"))
                self.assertNotIn("[", cell.find("s:f", NS).text)
                self.assertNotEqual(cell.get("t"), "e")
        before = {name: sha256((self.directory / name).read_bytes()).hexdigest()
                  for name in self.snapshot["hashes"]}
        second = build_workbook(self.snapshot, self.directory / "second.xlsx")
        self.assertEqual(self.output.read_bytes(), second.read_bytes())
        self.assertEqual(before, {name: sha256((self.directory / name).read_bytes()).hexdigest() for name in before})

    def test_all_performance_formulas_and_headline_caches(self):
        curves = self.snapshot["curves"]
        summary = self.snapshot["frames"]["common_window_comparison"].set_index("portfolio")
        for j, name in enumerate(PORTFOLIOS):
            peak = 10000.
            for i, source in curves.iterrows():
                row = PERFORMANCE_START + i + 1
                net, equity, high, dd = [xl_col_to_name(c) for c in range(1+j*6, 5+j*6)]
                peak = max(peak, source[f"{name}_equity"])
                cell, cache = self.cell(1, f"{equity}{row}")
                previous = "Methodology!$B$6" if i == 0 else f"{equity}{row-1}"
                self.assertEqual(cell.find("s:f", NS).text, f"{previous}*(1+{net}{row})")
                self.assertAlmostEqual(cache, source[f"{name}_equity"])
                self.assertAlmostEqual(self.cell(1, f"{high}{row}")[1], peak)
                self.assertAlmostEqual(self.cell(1, f"{dd}{row}")[1], source[f"{name}_drawdown"])
                self.assertAlmostEqual(self.cell(1, f"{xl_col_to_name(6+j*6)}{row}")[1], source[f"{name}_terminal_closing_cost"])
            metric_names = ["total_return", "cagr", "annualized_volatility", "zero_reference_rate_sharpe", "maximum_drawdown"]
            for col, metric in enumerate(metric_names, start=1):
                _, cache = self.cell(0, f"{xl_col_to_name(col)}{9+j}")
                expected = summary.loc[name, metric]
                if pd.isna(expected):
                    self.assertEqual(cache, "N/A — zero volatility")
                else:
                    self.assertAlmostEqual(cache, expected)
            self.assertAlmostEqual(self.cell(0, f"G{9+j}")[1], curves[f"{name}_equity"].iloc[-1])
        self.assertIsInstance(self.cell(1, "A7")[1], float)  # Typed Excel date serial.
        self.assertEqual(self.cell(1, "C7")[1], 10000)
        sharpe_formula = self.cell(0, "E9")[0].find("s:f", NS).text
        self.assertIn(f"B8:B{PERFORMANCE_START+len(curves)}", sharpe_formula)

    def test_complete_native_chart_ranges_and_caches(self):
        curves = self.snapshot["curves"]
        last = PERFORMANCE_START + len(curves)
        for number, field in ((1, "equity"), (2, "drawdown")):
            chart = ET.fromstring(self.zip.read(f"xl/charts/chart{number}.xml"))
            axis = chart.find(".//c:dateAx", NS)
            self.assertIsNotNone(axis)  # Dates must not become dense text categories.
            self.assertEqual(axis.find("c:numFmt", NS).get("formatCode"), "yyyy")
            self.assertEqual(axis.find("c:numFmt", NS).get("sourceLinked"), "0")
            self.assertEqual(axis.find("c:majorUnit", NS).get("val"), "1")
            self.assertEqual(axis.find("c:majorTimeUnit", NS).get("val"), "years")
            series = chart.findall(".//c:ser", NS)
            self.assertEqual(len(series), 4)
            for j, (item, name) in enumerate(zip(series, PORTFOLIOS)):
                categories = item.find("c:cat/c:numRef/c:f", NS).text
                self.assertEqual(categories, f"Performance!$A$7:$A${last}")
                col = xl_col_to_name((2 if field == "equity" else 4) + j*6)
                self.assertEqual(item.find("c:val/c:numRef/c:f", NS).text, f"Performance!${col}$7:${col}${last}")
                cache = item.find("c:val/c:numRef/c:numCache", NS)
                self.assertEqual(int(cache.find("c:ptCount", NS).get("val")), len(curves))
                values = [float(point.find("c:v", NS).text) for point in cache.findall("c:pt", NS)]
                np.testing.assert_allclose(values, curves[f"{name}_{field}"], rtol=0, atol=1e-10)

    def test_signal_summaries_provenance_and_scenario_tables(self):
        curves = self.snapshot["curves"]
        styles = ET.fromstring(self.zip.read("xl/styles.xml"))
        number_formats = {node.get("numFmtId"): node.get("formatCode")
                          for node in styles.findall("s:numFmts/s:numFmt", NS)}
        cell_formats = styles.findall("s:cellXfs/s:xf", NS)
        for j, name in enumerate(("baseline", "macro")):
            for k, held in enumerate((-1, 0, 1)):
                mask = curves[f"{name}_position"].iloc[1:].eq(held)
                row = 7+j*3+k
                self.assertEqual(self.cell(2, f"C{row}")[1], mask.sum())
                mean_cell, mean = self.cell(2, f"D{row}")
                number_format = number_formats[cell_formats[int(mean_cell.get("s"))].get("numFmtId")]
                # Precision is part of interpreting small cost-bearing conditional means.
                self.assertEqual(number_format, '0.0000%;[Red](0.0000%);0.0000%')
                if mask.any():
                    self.assertAlmostEqual(mean, curves[f"{name}_net_return"].iloc[1:][mask].mean())
                else:
                    self.assertEqual(mean, "N/A — no intervals")
            diagnostic = self.snapshot["common"]["diagnostics"][name]
            self.assertAlmostEqual(self.cell(2, f"I{7+j}")[1], diagnostic["exposure_fraction"])
            self.assertEqual(self.cell(2, f"J{7+j}")[1], diagnostic["normal_position_change_count"])
            self.assertEqual(self.cell(2, f"K{7+j}")[1], diagnostic["total_turnover_units_including_liquidation"])
        for stem, first_row in (("cost_sensitivity", 7), ("delay_sensitivity", 28)):
            source = self.snapshot["frames"]["robustness_" + stem]
            for i, item in source.iterrows():
                for col, key in (("D", "total_return"), ("E", "cagr"), ("F", "annualized_volatility"),
                                 ("G", "zero_reference_rate_sharpe"), ("H", "maximum_drawdown")):
                    actual = self.cell(3, f"{col}{first_row+i}")[1]
                    if pd.isna(item[key]):
                        self.assertEqual(actual, "N/A — zero volatility")
                    else:
                        self.assertAlmostEqual(actual, item[key])
        self.assertIsNotNone(self.sheets[3].find("s:conditionalFormatting", NS))
        annual = self.snapshot["frames"]["robustness_annual_returns"]
        for i, year in enumerate(sorted(annual.year.unique())):
            group = annual.loc[annual.year.eq(year)].set_index("portfolio")
            self.assertEqual(self.cell(3, f"A{46+i}")[1], year)
            self.assertEqual(self.cell(3, f"C{46+i}")[1], group.return_observation_count.iloc[0])
            for j, name in enumerate(PORTFOLIOS):
                self.assertAlmostEqual(self.cell(3, f"{xl_col_to_name(3+j)}{46+i}")[1],
                                       group.loc[name, "annual_return"])
        for digest in self.snapshot["hashes"].values():
            self.assertIn(digest, self.strings)

    def test_missing_or_inconsistent_artifacts_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with self.assertRaisesRegex(FileNotFoundError, "Dashboard requires"):
                load_snapshot(directory)
            for name in self.snapshot["hashes"]:
                (directory / name).write_bytes((self.directory / name).read_bytes())
            bad = pd.read_csv(directory / "common_window_comparison.csv")
            bad.loc[0, "total_return"] += .1
            bad.to_csv(directory / "common_window_comparison.csv", index=False)
            with self.assertRaisesRegex(ValueError, "Inconsistent common-window metrics"):
                load_snapshot(directory)


if __name__ == "__main__":
    unittest.main()
