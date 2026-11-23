"""Build and verify the passenger handoff using Python 3.10+ standard library.

Default: rebuild from the committed official snapshot, without network access.
--check: verify provenance and compare the CSV/audit without writing files.
--download: explicitly refresh the snapshot from Immigration Department.
"""

import argparse
import csv
import gzip
import hashlib
import io
import json
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw" / "statistics_on_daily_passenger_traffic.csv.gz"
SOURCE = DATA / "raw" / "passenger_source.json"
OUTPUT = DATA / "passenger_daily.csv"
AUDIT = DATA / "passenger_audit.json"
URL = ("https://www.immd.gov.hk/opendata/eng/transport/immigration_clearance/"
       "statistics_on_daily_passenger_traffic.csv")
START, END = date(2024, 1, 1), date(2026, 10, 31)
POINTS = ("Lo Wu", "Lok Ma Chau Spur Line", "Shenzhen Bay")
DIRECTIONS = {"Arrival": "arrival", "Departure": "departure"}
RAW_FIELDS = ["Date", "Control Point", "Arrival / Departure", "Hong Kong Residents",
              "Mainland Visitors", "Other Visitors", "Total"]
FIELDS = ["date", "control_point", "direction", "hong_kong_residents",
          "mainland_visitors", "other_visitors", "passengers"]
HKT = timezone(timedelta(hours=8))


def sha256(payload):
    return hashlib.sha256(payload).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


class DataQualityError(ValueError):
    """Contains all detected violations, including exact missing keys."""

    def __init__(self, issues):
        self.issues = issues
        super().__init__(json.dumps(issues, ensure_ascii=False, indent=2))


def clean(payload, start=START, end=END):
    """Validate before returning any output; never impute, deduplicate or clip."""
    if start > end:
        raise ValueError("start must not exceed end")
    reader = csv.reader(io.StringIO(payload.decode("utf-8-sig"), newline=""))
    header = next(reader, [])
    # The official CSV has a trailing comma, hence an eighth empty column.
    if header not in (RAW_FIELDS, RAW_FIELDS + [""]):
        raise DataQualityError([{"error": "unexpected_header", "value": header}])
    rows, issues, source_dates = [], [], []
    counts = Counter()
    seen = {}
    for line, cells in enumerate(reader, 2):
        counts["raw_rows"] += 1
        if len(cells) != len(header) or (len(header) == 8 and cells[-1].strip()):
            issues.append({"error": "invalid_row_width_or_extra_value", "line": line})
            continue
        cells = [value.strip() for value in cells[:7]]
        try:
            if not re.fullmatch(r"[0-9]{2}-[0-9]{2}-[0-9]{4}", cells[0]):
                raise ValueError("expected DD-MM-YYYY")
            day = datetime.strptime(cells[0], "%d-%m-%Y").date()
        except ValueError:
            issues.append({"error": "invalid_date", "line": line, "value": cells[0]})
            continue
        source_dates.append(day)
        if not start <= day <= end:
            counts["excluded_outside_date_range"] += 1
            continue
        if cells[1] not in POINTS:
            counts["excluded_other_control_points_in_range"] += 1
            continue
        counts["selected_raw_rows"] += 1
        if cells[2] not in DIRECTIONS:
            issues.append({"error": "unknown_direction", "line": line, "value": cells[2]})
            continue
        key = (day.isoformat(), cells[1], DIRECTIONS[cells[2]])
        if key in seen:
            issues.append({"error": "duplicate_key", "key": key,
                           "lines": [seen[key], line]})
        seen[key] = line
        if any(not re.fullmatch(r"[0-9]+", value) for value in cells[3:]):
            issues.append({"error": "invalid_count", "line": line, "key": key,
                           "values": cells[3:]})
            continue
        values = [int(value) for value in cells[3:]]
        if sum(values[:3]) != values[3]:
            issues.append({"error": "total_mismatch", "line": line, "key": key,
                           "values": values})
        rows.append(dict(zip(FIELDS, [*key, *values])))

    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    expected = {(day.isoformat(), point, direction) for day in days
                for point in POINTS for direction in DIRECTIONS.values()}
    missing = sorted(expected - seen.keys())
    if missing:
        issues.append({"error": "missing_keys", "count": len(missing), "keys": missing})
    if issues:
        raise DataQualityError(issues)

    rows.sort(key=lambda row: tuple(row[field] for field in FIELDS[:3]))
    groups = []
    for point in POINTS:
        for direction in DIRECTIONS.values():
            group = [r for r in rows if r["control_point"] == point
                     and r["direction"] == direction]
            groups.append({"control_point": point, "direction": direction,
                           "rows": len(group), "first_date": group[0]["date"],
                           "last_date": group[-1]["date"],
                           "passengers_sum": sum(r["passengers"] for r in group),
                           "passengers_min": min(r["passengers"] for r in group),
                           "passengers_max": max(r["passengers"] for r in group)})
    audit = {
        "source_sha256": sha256(payload),
        "raw_rows": counts["raw_rows"],
        "raw_first_date": min(source_dates).isoformat(),
        "raw_last_date": max(source_dates).isoformat(),
        "excluded_outside_date_range": counts["excluded_outside_date_range"],
        "excluded_other_control_points_in_range": counts["excluded_other_control_points_in_range"],
        "selected_raw_rows": counts["selected_raw_rows"],
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "expected_days": len(days), "actual_days": len({r["date"] for r in rows}),
        "expected_rows": len(expected), "actual_rows": len(rows),
        "duplicate_keys": 0, "missing_keys": [], "invalid_count_rows": 0,
        "total_mismatch_rows": 0,
        "zero_counts": {field: sum(r[field] == 0 for r in rows) for field in FIELDS[3:]},
        "zero_total_keys": [{field: r[field] for field in FIELDS[:3]}
                            for r in rows if r["passengers"] == 0],
        "rows_by_year": dict(sorted(Counter(r["date"][:4] for r in rows).items())),
        "groups": groups,
    }
    return rows, audit


def csv_bytes(rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def download():
    with urlopen(Request(URL, headers={"User-Agent": "PassengerCourseProject/1.0"}),
                 timeout=120) as response:
        payload = response.read()
        metadata = {"source_url": URL, "resolved_url": response.url,
                    "downloaded_at_hkt": datetime.now(HKT).isoformat(timespec="seconds"),
                    "http_date": response.headers.get("Date"),
                    "http_last_modified": response.headers.get("Last-Modified"),
                    "http_etag": response.headers.get("ETag"),
                    "content_type": response.headers.get("Content-Type"),
                    "raw_bytes": len(payload), "raw_sha256": sha256(payload)}
    clean(payload)  # Do not replace a usable snapshot with an invalid download.
    compressed = gzip.compress(payload, mtime=0)
    metadata["snapshot_bytes"] = len(compressed)
    RAW.parent.mkdir(parents=True, exist_ok=True)
    RAW.write_bytes(compressed)
    SOURCE.write_bytes(json_bytes(metadata))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--download", action="store_true")
    args = parser.parse_args()
    try:
        if args.download:
            download()
        payload = gzip.decompress(RAW.read_bytes())
        metadata = json.loads(SOURCE.read_text(encoding="utf-8"))
        if (metadata["raw_sha256"] != sha256(payload)
                or metadata["raw_bytes"] != len(payload)
                or metadata["snapshot_bytes"] != RAW.stat().st_size
                or metadata["source_url"] != URL):
            raise ValueError("Raw snapshot does not match its source manifest")
        rows, audit = clean(payload)
        output = csv_bytes(rows)
        audit["output_bytes"] = len(output)
        audit["output_sha256"] = sha256(output)
        artifacts = {OUTPUT: output, AUDIT: json_bytes(audit)}
        if args.check:
            for path, expected in artifacts.items():
                if not path.exists() or path.read_bytes() != expected:
                    raise ValueError(f"{path.relative_to(ROOT)} differs from the source build")
        else:
            for path, content in artifacts.items():
                path.write_bytes(content)
        print(f"{'Verified' if args.check else 'Built'} {len(rows):,} rows / "
              f"{audit['actual_days']:,} days; CSV {len(output):,} bytes")
    except (OSError, ValueError, KeyError, EOFError) as error:
        print(f"Passenger validation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
