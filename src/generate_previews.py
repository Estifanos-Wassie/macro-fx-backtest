"""Render Python/Matplotlib previews of verified saved common-window results."""

import os
from pathlib import Path
import tempfile
import json

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "macro-fx-matplotlib"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter, StrMethodFormatter
import numpy as np
import pandas as pd

if __package__:
    from .build_dashboard import COLORS, LABELS, PORTFOLIOS
    from .evaluate_performance import evaluate_performance
else:
    from build_dashboard import COLORS, LABELS, PORTFOLIOS
    from evaluate_performance import evaluate_performance

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_preview_data(directory):
    """Reconcile plotted paths, dates and metrics without rerunning simulations."""
    directory = Path(directory)
    curves = pd.read_csv(directory / "common_window_curves.csv")
    summary = pd.read_csv(directory / "common_window_comparison.csv")
    metadata = json.loads((directory / "common_window_metadata.json").read_text())
    if summary.portfolio.duplicated().any() or set(summary.portfolio) != set(PORTFOLIOS):
        raise ValueError("Preview requires the four common-window portfolios.")
    summary = summary.set_index("portfolio")
    for name in PORTFOLIOS:
        data = curves[["date", f"{name}_net_return", f"{name}_equity"]].rename(
            columns={f"{name}_net_return": "net_return", f"{name}_equity": "equity"}
        )
        report, drawdown = evaluate_performance(data, metadata["initial_capital_usd"])
        if report["evaluation"] != metadata["evaluation"]:
            raise ValueError("Preview dates or observation counts disagree with metadata.")
        if not np.allclose(curves[f"{name}_drawdown"], drawdown.drawdown, rtol=0, atol=1e-12):
            raise ValueError(f"Inconsistent saved {name} drawdown.")
        for metric, expected in report["metrics"].items():
            actual = summary.loc[name, metric]
            if (expected is None and not pd.isna(actual)) or (
                expected is not None and not np.isclose(actual, expected, rtol=1e-10, atol=1e-12)
            ):
                raise ValueError(f"Inconsistent saved {name} {metric}.")
    curves["date"] = pd.to_datetime(curves["date"], errors="raise")
    return curves, metadata


def generate_previews(directory=PROJECT_ROOT / "data/processed", output_directory=PROJECT_ROOT / "docs/assets"):
    curves, metadata = load_preview_data(directory)
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    evaluation = metadata["evaluation"]
    paths = []
    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 11, "path.simplify": False}):
        for field, heading, ylabel in (("equity", "Common-window equity", "Portfolio equity (USD)"),
                                       ("drawdown", "Common-window drawdown", "Drawdown from running peak")):
            fig = plt.figure(figsize=(12, 6.5), facecolor="white")
            ax = fig.add_axes((.11, .29, .865, .54))
            fig.suptitle(f"EUR/USD research | {heading}", x=.11, y=.96, ha="left",
                         fontsize=18, fontweight="bold", color="#183153")
            fig.text(.11, .89, f"Valuation {evaluation['initial_valuation_date']}  |  Returns {evaluation['first_return_end_date']} to "
                     f"{evaluation['final_observation_date']}  |  {evaluation['return_observation_count']:,} intervals", color="#526574")
            for name in PORTFOLIOS:
                ax.plot(curves.date, curves[f"{name}_{field}"], label=LABELS[name], color=COLORS[name],
                        linewidth=1.7, linestyle="--" if name == "flat_reference" else "-")
            ax.set_xlim(curves.date.iloc[0], curves.date.iloc[-1])
            ax.xaxis.set_major_locator(mdates.YearLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
            ax.yaxis.set_major_formatter(StrMethodFormatter("${x:,.0f}") if field == "equity" else PercentFormatter(1))
            ax.set_ylabel(ylabel, labelpad=12)
            ax.grid(True, color="#E6EAEE", linewidth=.7)
            ax.set_axisbelow(True)
            ax.spines[["top", "right"]].set_visible(False)
            for side in ("left", "bottom"):
                ax.spines[side].set_color("#AAB4BE")
            handles, labels = ax.get_legend_handles_labels()
            fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(.52, .165), ncol=2,
                       frameon=False, columnspacing=2, handlelength=3)
            fig.text(.11, .115, "Python-generated performance preview — not an Excel screenshot", color="#183153", fontweight="bold", fontsize=10)
            fig.text(.11, .077, f"ECB reference execution proxies | ${metadata['initial_capital_usd']:,.0f} start | "
                     f"{metadata['one_way_cost_rate']*10000:g} bp one-way | {metadata['execution_lag_observations']}-observation execution lag", color="#526574", fontsize=10)
            fig.text(.11, .04, "Retrospective sample | Excludes carry/financing, cash interest and exposure-resizing costs", color="#526574", fontsize=10)
            path = output_directory / f"common_window_{field}.png"
            fig.savefig(path, dpi=160, metadata={"Software": "Macro FX Research | Python / Matplotlib"})
            plt.close(fig)
            paths.append(path)
            print(f"Saved {len(curves):,} observations per portfolio: {path}")
    return paths


if __name__ == "__main__":
    generate_previews()
