"""Join passenger counts, calendar and as-of weather by date with Python 3.10+.

Run without arguments to rebuild; --check compares both outputs without writing.
All input checks finish before existing deliverables can be overwritten.
"""

import argparse
import csv
import io
import json
import re
import sys
from collections import Counter
from datetime import date, datetime, time, timedelta

from clean_passenger import DATA, DIRECTIONS, END, FIELDS as PASSENGER_FIELDS
from clean_passenger import HKT, POINTS, START, json_bytes, sha256

CALENDAR_FIELDS = [
    "date", "hk_holiday", "mainland_holiday", "mainland_makeup_workday",
    "is_weekend", "hk_holiday_name", "mainland_holiday_name",
    "mainland_makeup_workday_for", "hk_source_url", "mainland_source_url",
]
FLAGS = CALENDAR_FIELDS[1:5]
KEY = PASSENGER_FIELDS[:3]
BASE_FIELDS = PASSENGER_FIELDS + CALENDAR_FIELDS[1:]
WEATHER_FEATURES = ["forecast_psr", "tc_signal_at_cutoff"]
WEATHER_FIELDS = [
    "date", "rain_mm", "rain_trace", "mean_temp_c", "tc_signal_on_date",
    "rainstorm_on_date", "tc_signal_at_cutoff", "rainstorm_at_cutoff",
    "forecast_min_c", "forecast_max_c", "forecast_psr", "forecast_published_at_hkt",
    "forecast_archived_at_hkt",
]
PSR_LEVELS = ("Low", "Medium Low", "Medium", "Medium High", "High")
TC_SIGNAL_LEVELS = (0, 1, 3, 8, 9, 10)
OUTPUT_FIELDS = BASE_FIELDS + WEATHER_FEATURES
PASSENGER = DATA / "passenger_daily.csv"
CALENDAR = DATA / "holidays.csv"
WEATHER = DATA / "weather_daily.csv"
OUTPUT = DATA / "traffic_calendar.csv"
AUDIT = DATA / "traffic_calendar_audit.json"


def read_csv(payload, fields, label, *, legacy_fields=()):
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig"), newline=""))
    if reader.fieldnames not in (fields, legacy_fields):
        raise ValueError(f"{label}: unexpected columns {reader.fieldnames}")
    rows = list(reader)
    for line, row in enumerate(rows, 2):
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"{label}: invalid column count at line {line}")
        try:
            day = date.fromisoformat(row["date"])
            if day.isoformat() != row["date"]:
                raise ValueError("not YYYY-MM-DD")
        except ValueError as error:
            raise ValueError(f"{label}: invalid date at line {line}: {row['date']}") from error
    return rows


def csv_bytes(rows, fields):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def weather_by_date(weather, expected_dates):
    counts = Counter(row["date"] for row in weather)
    duplicates = sorted(day for day, count in counts.items() if count > 1)
    if duplicates:
        raise ValueError(f"Duplicate weather dates: {duplicates}")
    if counts.keys() != expected_dates:
        raise ValueError(f"Weather coverage: missing={sorted(expected_dates - counts.keys())}; "
                         f"unexpected={sorted(counts.keys() - expected_dates)}")

    signal_codes = set(map(str, TC_SIGNAL_LEVELS))
    for row in weather:
        day = row["date"]
        if row["tc_signal_at_cutoff"] not in signal_codes:
            raise ValueError(f"Invalid typhoon signal for {day}: {row['tc_signal_at_cutoff']!r}")
        probability = row["forecast_psr"]
        published_text = row["forecast_published_at_hkt"]
        archived_text = row["forecast_archived_at_hkt"]
        if not probability and not published_text and not archived_text:
            continue
        if probability not in PSR_LEVELS:
            raise ValueError(f"Invalid forecast rain probability for {day}: {probability!r}")
        try:
            published = datetime.fromisoformat(published_text)
            archived = datetime.fromisoformat(archived_text)
        except ValueError as error:
            raise ValueError(f"Invalid forecast timestamps for {day}") from error
        previous_day = date.fromisoformat(day) - timedelta(days=1)
        cutoff = datetime.combine(previous_day, time(18), tzinfo=HKT)
        if (published.utcoffset() != cutoff.utcoffset() or archived.utcoffset() != cutoff.utcoffset()
                or archived.date() != previous_day or published > cutoff or archived > cutoff
                or published.replace(second=0, microsecond=0) > archived):
            raise ValueError(f"Forecast timestamps violate the D-1 18:00 HKT cutoff for {day}")
    return {row["date"]: row for row in weather}


def merge(passenger_payload, calendar_payload, weather_payload, start=START, end=END):
    if start > end:
        raise ValueError("start must not exceed end")
    passengers = read_csv(passenger_payload, PASSENGER_FIELDS, "passenger_daily.csv")
    calendar = read_csv(calendar_payload, CALENDAR_FIELDS, "holidays.csv")
    keys = [tuple(row[field] for field in KEY) for row in passengers]
    duplicate_keys = [key for key, count in Counter(keys).items() if count > 1]
    if duplicate_keys:
        raise ValueError(f"Duplicate passenger keys: {duplicate_keys}")
    dates = [row["date"] for row in calendar]
    duplicate_dates = [day for day, count in Counter(dates).items() if count > 1]
    if duplicate_dates:
        raise ValueError(f"Duplicate calendar dates: {duplicate_dates}")

    by_date = {row["date"]: row for row in calendar}
    passenger_dates = {row["date"] for row in passengers}
    unmatched = sorted(passenger_dates - by_date.keys())
    if unmatched:
        raise ValueError(f"Unmatched passenger dates: {unmatched}")
    expected_dates = {(start + timedelta(days=i)).isoformat()
                      for i in range((end - start).days + 1)}
    expected_keys = {(day, point, direction) for day in expected_dates
                     for point in POINTS for direction in DIRECTIONS.values()}
    if set(keys) != expected_keys:
        raise ValueError(f"Passenger coverage: missing={sorted(expected_keys - set(keys))}; "
                         f"unexpected={sorted(set(keys) - expected_keys)}")
    if set(dates) != expected_dates:
        raise ValueError(f"Calendar coverage: missing={sorted(expected_dates - set(dates))}; "
                         f"unexpected={sorted(set(dates) - expected_dates)}")
    weather = read_csv(weather_payload, WEATHER_FIELDS, WEATHER.name)
    weather_lookup = weather_by_date(weather, expected_dates)

    for row in passengers:
        values = [row[field] for field in PASSENGER_FIELDS[3:]]
        if any(not re.fullmatch(r"[0-9]+", value) for value in values):
            raise ValueError(f"Invalid passenger count: {row}")
        if sum(map(int, values[:3])) != int(values[3]):
            raise ValueError(f"Passenger total mismatch: {row}")
    for row in calendar:
        if any(row[field] not in ("0", "1") for field in FLAGS):
            raise ValueError(f"Invalid calendar flag: {row}")
        day = date.fromisoformat(row["date"])
        if int(row["is_weekend"]) != int(day.weekday() >= 5):
            raise ValueError(f"Weekend flag mismatch: {row['date']}")
        if row["mainland_holiday"] == row["mainland_makeup_workday"] == "1":
            raise ValueError(f"Mainland holiday/workday conflict: {row['date']}")
        for flag, name in zip(FLAGS[:3], CALENDAR_FIELDS[5:8]):
            if (row[flag] == "1") != bool(row[name].strip()):
                raise ValueError(f"Flag/name mismatch: {row['date']} {flag}")
        for flag, source in ((row["hk_holiday"] == "1", "hk_source_url"),
                             (row["mainland_holiday"] == "1" or
                              row["mainland_makeup_workday"] == "1", "mainland_source_url")):
            if flag != bool(row[source].strip()):
                raise ValueError(f"Flag/source mismatch: {row['date']} {source}")

    passengers.sort(key=lambda row: tuple(row[field] for field in KEY))
    calendar.sort(key=lambda row: row["date"])
    weather.sort(key=lambda row: row["date"])
    # Each passenger record gets the calendar and weather for its target date.
    joined = [dict(row, **{field: by_date[row["date"]][field] for field in CALENDAR_FIELDS[1:]},
                   **{field: weather_lookup[row["date"]][field] for field in WEATHER_FEATURES})
              for row in passengers]
    if len(joined) != len(passengers) or len({tuple(r[f] for f in KEY) for r in joined}) != len(keys):
        raise ValueError("Join changed row count or key uniqueness")
    if any({f: row[f] for f in PASSENGER_FIELDS} != original
           for row, original in zip(joined, passengers)):
        raise ValueError("Join changed passenger fields")
    if any({f: row[f] for f in CALENDAR_FIELDS} != by_date[row["date"]] for row in joined):
        raise ValueError("Join changed calendar fields")
    if any(row[f] != weather_lookup[row["date"]][f] for row in joined for f in WEATHER_FEATURES):
        raise ValueError("Join changed weather fields")

    output = csv_bytes(joined, OUTPUT_FIELDS)
    psr_days = Counter(row["forecast_psr"] for row in weather)
    missing_psr_dates = [row["date"] for row in weather if not row["forecast_psr"]]
    signal_days = Counter(int(row["tc_signal_at_cutoff"]) for row in weather)
    audit = {
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "input_versions": {
            "hash_convention": "SHA-256 of parsed CSV, sorted by key, UTF-8 without BOM, LF",
            "passenger_daily.csv": sha256(csv_bytes(passengers, PASSENGER_FIELDS)),
            "holidays.csv": sha256(csv_bytes(calendar, CALENDAR_FIELDS)),
            "weather_daily.csv": sha256(csv_bytes(weather, WEATHER_FIELDS)),
        },
        "passenger_rows_before": len(passengers), "calendar_rows": len(calendar),
        "expected_days": len(expected_dates), "expected_rows": len(expected_keys),
        "rows_after": len(joined), "unique_keys_after": len(keys),
        "duplicate_passenger_keys": [], "duplicate_calendar_dates": [],
        "unmatched_passenger_dates": unmatched, "unused_calendar_dates": [],
        "missing_passenger_keys": [], "passenger_fields_unchanged": True,
        "calendar_fields_match_source": True, "output_columns": OUTPUT_FIELDS,
        "weather": {
            "rows": len(weather), "features_match_source": True, "cutoff_hkt": "D-1 18:00",
            "forecast_psr": {
                "available_days": len(weather) - len(missing_psr_dates),
                "missing_dates": missing_psr_dates,
                "missing_rows": sum(not row["forecast_psr"] for row in joined),
                "days_by_level": {level: psr_days[level] for level in PSR_LEVELS},
            },
            "tc_signal_at_cutoff": {
                "available_days": len(weather),
                "days_by_signal": {str(level): signal_days[level] for level in TC_SIGNAL_LEVELS},
            },
        },
        "flags": {field: {"calendar_days": sum(int(r[field]) for r in calendar),
                          "joined_rows": sum(int(r[field]) for r in joined)} for field in FLAGS},
        "rows_by_year": dict(sorted(Counter(r["date"][:4] for r in joined).items())),
        "groups": [{"control_point": point, "direction": direction,
                    "rows": sum(r["control_point"] == point and r["direction"] == direction
                                for r in joined)}
                   for point in POINTS for direction in DIRECTIONS.values()],
        "output_bytes": len(output), "output_sha256": sha256(output),
    }
    return output, json_bytes(audit)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify without writing any file")
    args = parser.parse_args()
    try:
        output, audit = merge(PASSENGER.read_bytes(), CALENDAR.read_bytes(), WEATHER.read_bytes())
        artifacts = {OUTPUT: output, AUDIT: audit}
        if args.check:
            for path, expected in artifacts.items():
                if not path.is_file() or path.read_bytes() != expected:
                    raise ValueError(f"{path.name} differs from the input build")
        else:
            for path, content in artifacts.items():
                path.write_bytes(content)
        report = json.loads(audit)
        print(f"{'Verified' if args.check else 'Built'} {report['rows_after']:,} rows / "
              f"{report['expected_days']:,} days / {len(OUTPUT_FIELDS)} columns; "
              f"0 unmatched dates; CSV {len(output):,} bytes")
    except (OSError, ValueError, csv.Error) as error:
        print(f"Traffic calendar validation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
