"""Draw the traffic trends, calendar distributions and date combinations."""

from math import ceil

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, MultipleLocator
from pandas import Timedelta

INK = "#243547"
BLUE = "#0072B2"
GRID = "#E5EBF1"
DPI = 300
STYLE = {
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "text.color": INK,
    "axes.labelcolor": INK,
    "axes.edgecolor": "#A2B1BE",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.axisbelow": True,
    "xtick.color": "#485A6A",
    "ytick.color": "#485A6A",
}
PLOT_GROUPS = {
    "ordinary_weekday": "Ordinary\nweekday",
    "ordinary_weekend": "Ordinary\nweekend",
    "hk_holiday": "Hong Kong\npublic holiday",
    "mainland_holiday": "Mainland\nholiday",
    "mainland_makeup_workday": "Mainland\nmakeup day",
}


def heading(fig, title, subtitle, left=.093):
    fig.text(left, .967, title, va="top", fontsize=18, weight="semibold")
    fig.text(left, .918, subtitle, va="top", fontsize=10, color="#485A6A")


def group_grid(traffic, title, note, *, bottom, top):
    fig, axes = plt.subplots(3, 2, figsize=(10.4, 8.0), sharex=True, sharey=True)
    fig.subplots_adjust(left=.098, right=.977, bottom=bottom, top=top, wspace=.095, hspace=.42)
    first, last = traffic["date"].min(), traffic["date"].max()
    heading(fig, title, f"{first:%Y-%m-%d} to {last:%Y-%m-%d}  |  {note}")
    fig.supylabel("Daily crossings (thousand trips)", x=.029, fontsize=11)
    increment = 50_000
    upper = increment * ceil(1.06 * traffic["passengers"].max() / increment)
    axes[0, 0].set_ylim(0, upper)
    axes[0, 0].yaxis.set_major_locator(MultipleLocator(increment))
    axes[0, 0].yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value / 1_000:.0f}"))
    for ax in axes.flat:
        ax.grid(axis="y", color=GRID, linewidth=.8)
        ax.tick_params(axis="both", labelsize=9, length=3)
    return fig, axes


def daily_trends(traffic, window):
    fig, axes = group_grid(
        traffic, "Daily passenger traffic", f"{traffic['date'].nunique():,} dates per panel",
        bottom=.096, top=.822,
    )
    first, last = traffic["date"].min(), traffic["date"].max()
    axes[0, 0].set_xlim(first - Timedelta(days=8), last + Timedelta(days=8))
    axes[0, 0].xaxis.set_major_locator(mdates.MonthLocator(bymonth=(1, 7)))
    axes[0, 0].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    for ax, ((port, direction), observations) in zip(
        axes.flat, traffic.groupby(["control_point", "direction"])
    ):
        ax.set_title(f"{port}  |  {direction.title()}", loc="left", pad=7, weight="semibold")
        dates, passengers = observations["date"], observations["passengers"]
        ax.plot(dates, passengers, color="#879BAB", linewidth=.55, label="Daily observation")
        ax.plot(dates, passengers.rolling(window).mean(), color=BLUE, linewidth=1.7,
                label=f"{window}-day trailing mean")
        for value, marker, color, label in (
            (passengers.min(), "v", "#654A83", "Group minimum"),
            (passengers.max(), "^", "#D55E00", "Group maximum"),
        ):
            ax.scatter(dates[passengers.eq(value)], passengers[passengers.eq(value)],
                       marker=marker, s=39, color=color, edgecolors="white", linewidth=.6,
                       zorder=4, clip_on=False, label=label)

    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper left", bbox_to_anchor=(.086, .893), ncols=4,
               frameon=False, fontsize=9, handlelength=2.5, columnspacing=2)
    fig.supxlabel("Observation date (Hong Kong time)", x=.537, y=.027, fontsize=10)
    return fig


def calendar_comparison(traffic, views):
    fig, axes = group_grid(
        traffic, "Passenger traffic by calendar group", "Holiday groups can share dates",
        bottom=.14, top=.854,
    )
    dates = {name: views[name].index[views[name]] for name in PLOT_GROUPS}
    labels = [f"{label}\n(n={len(dates[name])})" for name, label in PLOT_GROUPS.items()]
    for ax, ((port, direction), observations) in zip(
        axes.flat, traffic.groupby(["control_point", "direction"])
    ):
        ax.set_title(f"{port}  |  {direction.title()}", loc="left", pad=7, weight="semibold")
        by_date = observations.set_index("date")["passengers"]
        ax.boxplot(
            [by_date.loc[group_dates] for group_dates in dates.values()],
            manage_ticks=False, patch_artist=True, widths=.53, whis=1.5,
            boxprops={"facecolor": "#DFEDF5", "edgecolor": "#507894"},
            whiskerprops={"color": "#507894"}, capprops={"color": "#507894"},
            medianprops={"color": BLUE, "linewidth": 1.65},
            flierprops={"marker": "o", "markersize": 2.5, "markerfacecolor": "#3A556B",
                        "markeredgecolor": "none", "alpha": .52, "clip_on": False},
        )
    axes[-1, 0].set_xticks(range(1, len(labels) + 1), labels)
    axes[-1, 0].set_xlim(.5, len(labels) + .5)
    fig.supxlabel("Calendar group (dates per panel)", x=.537, y=.026, fontsize=10)
    return fig


def calendar_overlap(overlap):
    fig, (matrix, counts) = plt.subplots(
        1, 2, figsize=(10.4, 4.85), sharey=True, width_ratios=(1, 1.2)
    )
    fig.subplots_adjust(left=.06, right=.966, bottom=.135, top=.772, wspace=.055)
    heading(fig, "Calendar flags on the same date",
            f"{overlap['days'].sum():,} dates  |  Dark dots show which flags apply", left=.06)
    flags = {
        "is_weekend": "Weekend",
        "hk_holiday": "Hong Kong\npublic holiday",
        "mainland_holiday": "Mainland\nholiday",
        "mainland_makeup_workday": "Mainland\nmakeup day",
    }
    positions = list(range(len(overlap)))
    for column, flag in enumerate(flags):
        active = overlap[flag].eq(1)
        matrix.scatter([column] * len(overlap), positions, s=20, color="#D2DCE4")
        matrix.scatter([column] * active.sum(), overlap.index[active], s=61, color=BLUE)
    matrix.set_xticks(range(len(flags)), list(flags.values()))
    matrix.xaxis.tick_top()
    matrix.tick_params(axis="x", length=0, pad=10)
    matrix.set_xlim(-.5, len(flags) - .5)
    matrix.set_ylim(len(overlap) - .5, -.5)
    matrix.set_yticks([])
    matrix.spines[["left", "bottom"]].set_visible(False)

    bars = counts.barh(positions, overlap["days"], height=.58, color="#517A95")
    counts.bar_label(bars, labels=[f"{days:,}" for days in overlap["days"]], padding=6)
    counts.set_xlim(0, 1.14 * overlap["days"].max())
    counts.set_xlabel("Number of dates")
    counts.grid(axis="x", color=GRID, linewidth=.8)
    counts.spines["left"].set_visible(False)
    return fig


def figures(traffic, views, overlap, window):
    with plt.style.context("default"), plt.rc_context(STYLE):
        yield "daily_trends", daily_trends(traffic, window)
        yield "calendar_comparison", calendar_comparison(traffic, views)
        yield "calendar_overlap", calendar_overlap(overlap)


def write_figures(output, traffic, views, overlap, window):
    for name, figure in figures(traffic, views, overlap, window):
        try:
            figure.savefig(output / f"{name}.png", dpi=DPI)
        finally:
            plt.close(figure)
