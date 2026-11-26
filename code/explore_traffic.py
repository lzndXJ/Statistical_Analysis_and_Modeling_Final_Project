"""Rebuild the Issue #10 exploratory tables and figures from the reviewed CSV."""

import argparse
import csv
import gzip
import io
import json
import platform
from importlib.metadata import version
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

import pandas as pd

from clean_passenger import DIRECTIONS, END, POINTS, RAW, RAW_FIELDS, ROOT, SOURCE, START
from clean_passenger import FIELDS as PASSENGER_FIELDS
from clean_passenger import json_bytes, sha256
from merge_traffic_calendar import BASE_FIELDS, KEY, OUTPUT_FIELDS, read_csv
from merge_traffic_calendar import OUTPUT as TRAFFIC_CSV

GROUP = KEY[1:]
COUNTS = PASSENGER_FIELDS[3:]
CALENDAR_FLAGS = ["is_weekend", "hk_holiday", "mainland_holiday", "mainland_makeup_workday"]
CALENDAR_NAMES = ["hk_holiday_name", "mainland_holiday_name", "mainland_makeup_workday_for"]
DEFAULT_OUTPUT = ROOT / "docs" / "探索分析" / "图表"
TREND_WINDOW = 28
COMPARABLE_LAST_MONTH = 10


def read_traffic(payload):
    """Check one record per date, port and direction and one calendar per date."""
    rows = read_csv(payload, OUTPUT_FIELDS, TRAFFIC_CSV.name, legacy_fields=BASE_FIELDS)
    traffic = pd.DataFrame(rows, columns=BASE_FIELDS)
    traffic["date"] = pd.to_datetime(traffic["date"], format="%Y-%m-%d")
    numeric_columns = COUNTS + CALENDAR_FLAGS
    traffic[numeric_columns] = traffic[numeric_columns].astype("int64")
    traffic = traffic.sort_values(KEY, ignore_index=True)

    dates = pd.date_range(START, END, freq="D")
    expected = pd.MultiIndex.from_product([dates, POINTS, DIRECTIONS.values()], names=KEY)
    if not pd.MultiIndex.from_frame(traffic[KEY]).equals(expected):
        raise ValueError("Expected one record for each project date, port and direction.")
    counts = traffic[COUNTS]
    if (counts < 0).any().any() or not counts[COUNTS[:-1]].sum(axis=1).eq(counts["passengers"]).all():
        raise ValueError("Passenger counts must be nonnegative and add up to the reported total.")

    daily = traffic[["date", *CALENDAR_FLAGS]].drop_duplicates().set_index("date")
    if not daily.index.is_unique or not daily.isin([0, 1]).all().all():
        raise ValueError("Each date must have one set of binary calendar flags.")
    if not daily["is_weekend"].eq(daily.index.dayofweek >= 5).all():
        raise ValueError("Weekend flags must follow the Saturday/Sunday calendar.")
    if (daily["mainland_holiday"] & daily["mainland_makeup_workday"]).any():
        raise ValueError("Mainland holiday and makeup workday cannot share a date.")
    return traffic, daily


def describe(traffic):
    return traffic.groupby(GROUP).agg(
        days=("date", "size"),
        first_date=("date", "min"),
        last_date=("date", "max"),
        mean_passengers=("passengers", "mean"),
        sd_passengers=("passengers", "std"),
        min_passengers=("passengers", "min"),
        q1_passengers=("passengers", lambda values: values.quantile(.25)),
        median_passengers=("passengers", "median"),
        q3_passengers=("passengers", lambda values: values.quantile(.75)),
        max_passengers=("passengers", "max"),
    )


def calendar_views(daily):
    weekend, hk, mainland, makeup = (daily[column].eq(1) for column in CALENDAR_FLAGS)
    ordinary = ~(hk | mainland | makeup)
    return {
        "weekday": ~weekend,
        "weekend": weekend,
        "ordinary_weekday": ~weekend & ordinary,
        "ordinary_weekend": weekend & ordinary,
        "hk_holiday": hk,
        "mainland_holiday": mainland,
        "mainland_makeup_workday": makeup,
        "hk_holiday_only": hk & ~(mainland | makeup),
        "mainland_holiday_only": mainland & ~hk,
        "both_holidays": hk & mainland,
    }


def compare_calendar(traffic, views):
    summaries = pd.concat(
        {name: describe(traffic[traffic["date"].isin(mask.index[mask])]) for name, mask in views.items()},
        names=["calendar_group"],
    )
    baseline = summaries.loc["ordinary_weekday", "median_passengers"]
    change = (summaries["median_passengers"].div(baseline) - 1) * 100
    return summaries.assign(median_change_vs_ordinary_weekday_pct=change).reset_index()


def count_overlaps(daily):
    return (
        daily.reset_index().groupby(CALENDAR_FLAGS, as_index=False)
        .agg(days=("date", "size"), example_date=("date", "min"))
        .sort_values("days", ascending=False, kind="stable", ignore_index=True)
    )


def compare_years(traffic):
    comparable = traffic[traffic["date"].dt.month <= COMPARABLE_LAST_MONTH]
    return (
        comparable.assign(year=comparable["date"].dt.year)
        .groupby([*GROUP, "year"], as_index=False)
        .agg(days=("date", "size"), first_date=("date", "min"), last_date=("date", "max"),
             mean_passengers=("passengers", "mean"))
    )


def read_official_snapshot():
    payload = gzip.decompress(RAW.read_bytes())
    provenance = json.loads(SOURCE.read_bytes())
    if sha256(payload) != provenance["raw_sha256"] or len(payload) != provenance["raw_bytes"]:
        raise ValueError("The official CSV snapshot does not match its recorded provenance.")
    return payload


def verify_extremes(traffic, raw_payload):
    """Keep all tied group minima and maxima and locate their official CSV records."""
    grouped = traffic.groupby(GROUP)["passengers"]
    extremes = pd.concat([
        traffic[traffic["passengers"].eq(grouped.transform(kind))].assign(extreme=kind)
        for kind in ("min", "max")
    ]).sort_values([*GROUP, "passengers", "date"], ignore_index=True)

    official_direction = {clean: official for official, clean in DIRECTIONS.items()}
    official_keys = [
        (day.strftime("%d-%m-%Y"), port, official_direction[direction])
        for day, port, direction in extremes[KEY].itertuples(index=False, name=None)
    ]
    wanted = set(official_keys)
    reader = csv.reader(io.StringIO(raw_payload.decode("utf-8-sig"), newline=""))
    header = next(reader, [])
    if header not in (RAW_FIELDS, [*RAW_FIELDS, ""]):
        raise ValueError("Unexpected official snapshot header.")
    matches = {}
    for cells in reader:
        official_key = tuple(cell.strip() for cell in cells[:3])
        if official_key not in wanted:
            continue
        if official_key in matches:
            raise ValueError(f"Duplicate official record: {official_key}")
        if len(cells) != len(header) or any(cell.strip() for cell in cells[7:]):
            raise ValueError(f"Invalid official record width at line {reader.line_num}.")
        matches[official_key] = (reader.line_num, tuple(int(value) for value in cells[3:7]))

    for key, counts in zip(official_keys, extremes[COUNTS].itertuples(index=False, name=None)):
        if key not in matches or counts != matches[key][1]:
            raise ValueError(f"Extreme value differs from the official CSV: {key}")

    extremes["raw_line"] = [matches[key][0] for key in official_keys]
    extremes["raw_date"] = [key[0] for key in official_keys]
    extremes["raw_direction"] = [key[2] for key in official_keys]
    columns = ["extreme", *PASSENGER_FIELDS, *CALENDAR_FLAGS, *CALENDAR_NAMES,
               "raw_line", "raw_date", "raw_direction"]
    return extremes[columns]


def publish_artifact(staged, output):
    # Create the replacement in the output directory so it inherits its permissions.
    temporary = NamedTemporaryFile(dir=output, prefix=".eda-", suffix=".tmp", delete=False)
    replacement = Path(temporary.name)
    try:
        with temporary:
            temporary.write(staged.read_bytes())
        replacement.replace(output / staged.name)
    finally:
        replacement.unlink(missing_ok=True)


def rebuild(output):
    from traffic_eda_plots import DPI, write_figures

    traffic_payload = TRAFFIC_CSV.read_bytes()
    traffic, daily = read_traffic(traffic_payload)
    raw_payload = read_official_snapshot()
    views = calendar_views(daily)
    overlap = count_overlaps(daily)
    extremes = verify_extremes(traffic, raw_payload)
    tables = {
        "group_summary.csv": describe(traffic).reset_index(),
        "calendar_summary.csv": compare_calendar(traffic, views),
        "calendar_overlap.csv": overlap,
        "matched_year_summary.csv": compare_years(traffic),
        "verified_extremes.csv": extremes,
    }

    # Build the complete set before replacing any of the previous results.
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".eda-", dir=output.parent) as temporary:
        staged = Path(temporary)
        for name, table in tables.items():
            table.to_csv(staged / name, index=False, encoding="utf-8", lineterminator="\n",
                         date_format="%Y-%m-%d", float_format="%.2f")
        write_figures(staged, traffic, views, overlap, TREND_WINDOW)
        artifacts = sorted(staged.iterdir())
        manifest = {
            "reproduce_command": "python code/explore_traffic.py",
            "input_files": {
                TRAFFIC_CSV.relative_to(ROOT).as_posix(): {"sha256": sha256(traffic_payload)},
                RAW.relative_to(ROOT).as_posix(): {"uncompressed_sha256": sha256(raw_payload)},
            },
            "runtime": {
                "python": platform.python_version(),
                **{package: version(package) for package in ("pandas", "numpy", "matplotlib", "pillow")},
            },
            "parameters": {
                "first_date": START.isoformat(),
                "last_date": END.isoformat(),
                "days": len(daily),
                "observations": len(traffic),
                "unit": "passenger trips",
                "trailing_mean_days": TREND_WINDOW,
                "matched_year_months": [1, COMPARABLE_LAST_MONTH],
                "calendar_baseline": "ordinary_weekday",
                "png_dpi": DPI,
                "random_seed": None,
            },
            "output_sha256": {path.name: sha256(path.read_bytes()) for path in artifacts},
        }
        manifest_file = staged / "reproduction.json"
        manifest_file.write_bytes(json_bytes(manifest))
        output.mkdir(exist_ok=True)
        for path in [*artifacts, manifest_file]:
            publish_artifact(path, output)

    displayed_output = output.relative_to(ROOT) if output.is_relative_to(ROOT) else output
    print(f"Explored {len(traffic):,} rows / {len(daily):,} days across {len(tables['group_summary.csv'])} series.")
    print(f"Matched {len(extremes)} extreme records to the original CSV. Outputs: {displayed_output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT,
                        help=f"Output directory (default: {DEFAULT_OUTPUT.relative_to(ROOT).as_posix()})")
    args = parser.parse_args()
    rebuild(args.output_dir.resolve())


if __name__ == "__main__":
    main()
