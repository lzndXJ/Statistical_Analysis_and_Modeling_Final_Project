"""Check join cardinality, date alignment and non-destructive failure behavior."""

import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from pathlib import Path
from unittest.mock import patch

import merge_traffic_calendar as merger

FIRST, LAST = date(2024, 9, 28), date(2024, 9, 29)


def fixture():
    passengers, calendar = [], []
    for day in (FIRST, LAST):
        for point in merger.POINTS:
            for direction in merger.DIRECTIONS.values():
                passengers.append(dict(zip(merger.PASSENGER_FIELDS,
                                           [day.isoformat(), point, direction, "3", "2", "1", "6"])))
        # Saturday is ordinary; Sunday is a makeup workday. Weekends remain independent.
        makeup = day == LAST
        calendar.append(dict(zip(merger.CALENDAR_FIELDS,
                                 [day.isoformat(), "0", "0", str(int(makeup)), "1", "", "",
                                  "国庆节" if makeup else "", "",
                                  "https://example.test/official-notice" if makeup else ""])))
    return passengers, calendar


def weather_fixture():
    return [
        {"date": FIRST.isoformat(), "tc_signal_at_cutoff": "3", "tc_signal_on_date": "10",
         "forecast_psr": "High", "forecast_published_at_hkt": "2024-09-27T16:30:00+08:00",
         "forecast_archived_at_hkt": "2024-09-27T18:00:00+08:00"},
        {"date": LAST.isoformat(), "tc_signal_at_cutoff": "0"},
    ]


def build(passengers, calendar, weather=None):
    if weather is None:
        weather = weather_fixture()
    return merger.merge(merger.csv_bytes(passengers, merger.PASSENGER_FIELDS),
                        merger.csv_bytes(calendar, merger.CALENDAR_FIELDS),
                        merger.csv_bytes(weather, merger.WEATHER_FIELDS), FIRST, LAST)


class MergeTests(unittest.TestCase):
    def test_join_is_by_date_preserves_fields_and_weekend_makeup(self):
        passengers, calendar = fixture()
        output, audit_bytes = build(passengers[::-1], calendar[::-1], weather_fixture()[::-1])
        reader = csv.DictReader(io.StringIO(output.decode("utf-8")))
        self.assertEqual(reader.fieldnames, merger.BASE_FIELDS + ["forecast_psr", "tc_signal_at_cutoff"])
        rows = list(reader)
        self.assertEqual(len(rows), 12)
        source = {tuple(r[f] for f in merger.KEY): r for r in passengers}
        for row in rows:
            self.assertEqual({f: row[f] for f in merger.PASSENGER_FIELDS},
                             source[tuple(row[f] for f in merger.KEY)])
            self.assertEqual(row["mainland_makeup_workday"], str(int(row["date"] == LAST.isoformat())))
            self.assertEqual(row["is_weekend"], "1")
            self.assertEqual(row["hk_holiday_name"], "")
            expected_weather = ("High", "3") if row["date"] == FIRST.isoformat() else ("", "0")
            self.assertEqual(tuple(row[f] for f in merger.WEATHER_FEATURES), expected_weather)
        audit = json.loads(audit_bytes)
        self.assertEqual(audit["flags"]["mainland_makeup_workday"],
                         {"calendar_days": 1, "joined_rows": 6})
        self.assertEqual(audit["weather"]["forecast_psr"]["missing_dates"], [LAST.isoformat()])
        self.assertEqual(audit["weather"]["forecast_psr"]["missing_rows"], 6)

    def test_duplicate_calendar_date_cannot_multiply_rows(self):
        p, c = fixture()
        with self.assertRaisesRegex(ValueError, "Duplicate calendar dates"):
            build(p, c + [c[0]])

    def test_missing_calendar_date_cannot_be_filled_with_zero(self):
        p, c = fixture()
        with self.assertRaisesRegex(ValueError, "Unmatched passenger dates.*2024-09-29"):
            build(p, c[:1])

    def test_weather_date_coverage(self):
        p, c = fixture()
        weather = weather_fixture()
        with self.assertRaisesRegex(ValueError, "Duplicate weather dates.*2024-09-28"):
            build(p, c, weather + [weather[0]])
        with self.assertRaisesRegex(ValueError, "Weather coverage.*2024-09-29"):
            build(p, c, weather[:1])

    def test_weather_values_and_as_of_timestamps(self):
        p, c = fixture()
        cases = [
            ({"tc_signal_at_cutoff": ""}, "Invalid typhoon signal"),
            ({"forecast_psr": ""}, "Invalid forecast rain probability"),
            ({"forecast_archived_at_hkt": ""}, "Invalid forecast timestamps"),
            ({"forecast_archived_at_hkt": "2024-09-27T18:01:00+08:00"}, "violate the D-1 18:00"),
            ({"forecast_published_at_hkt": "2024-09-28T10:00:00+08:00"}, "violate the D-1 18:00"),
            ({"forecast_archived_at_hkt": "2024-09-27T18:00:00"}, "violate the D-1 18:00"),
        ]
        for changes, message in cases:
            with self.subTest(changes=changes):
                weather = weather_fixture()
                weather[0].update(changes)
                with self.assertRaisesRegex(ValueError, message):
                    build(p, c, weather)

    def test_duplicate_passenger_key_is_not_deduplicated(self):
        p, c = fixture()
        with self.assertRaisesRegex(ValueError, "Duplicate passenger keys"):
            build(p + [p[0]], c)

    def test_missing_direction_and_unexpected_calendar_day(self):
        p, c = fixture()
        with self.assertRaisesRegex(ValueError, "Passenger coverage"):
            build(p[:-1], c)
        c.append(dict(c[0], date="2024-09-30"))
        with self.assertRaisesRegex(ValueError, "Calendar coverage"):
            build(p, c)

    def test_invalid_flags_and_conflicting_calendar(self):
        for changes, error in [({"hk_holiday": ""}, "Invalid calendar flag"),
                               ({"is_weekend": "0"}, "Weekend flag mismatch"),
                               ({"mainland_holiday": "1"}, "holiday/workday conflict"),
                               ({"mainland_makeup_workday_for": ""}, "Flag/name mismatch"),
                               ({"mainland_source_url": ""}, "Flag/source mismatch")]:
            with self.subTest(changes=changes):
                p, c = fixture()
                c[1].update(changes)
                with self.assertRaisesRegex(ValueError, error):
                    build(p, c)

    def test_bad_count_or_total_cannot_pass_through(self):
        for value, error in [("-1", "Invalid passenger count"), ("7", "total mismatch")]:
            p, c = fixture()
            p[0]["passengers"] = value
            with self.assertRaisesRegex(ValueError, error):
                build(p, c)

    def test_formatting_and_order_do_not_change_audit(self):
        p, c = fixture()
        expected = build(p, c)
        result = merger.merge(b"\xef\xbb\xbf" + merger.csv_bytes(p[::-1], merger.PASSENGER_FIELDS).replace(b"\n", b"\r\n"),
                              merger.csv_bytes(c[::-1], merger.CALENDAR_FIELDS).replace(b"\n", b"\r\n"),
                              merger.csv_bytes(weather_fixture()[::-1], merger.WEATHER_FIELDS).replace(b"\n", b"\r\n"),
                              FIRST, LAST)
        self.assertEqual(result, expected)

    def test_rejects_extra_column_and_malformed_date(self):
        p, c = fixture()
        with self.assertRaisesRegex(ValueError, "unexpected columns"):
            merger.merge(merger.csv_bytes(p, merger.PASSENGER_FIELDS + ["extra"]),
                         merger.csv_bytes(c, merger.CALENDAR_FIELDS),
                         merger.csv_bytes(weather_fixture(), merger.WEATHER_FIELDS), FIRST, LAST)
        c[0]["date"] = "20240928"
        with self.assertRaisesRegex(ValueError, "invalid date"):
            build(p, c)

    def test_bad_input_does_not_overwrite_existing_outputs(self):
        p, c = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {name: root / name for name in ("PASSENGER", "CALENDAR", "WEATHER", "OUTPUT", "AUDIT")}
            paths["PASSENGER"].write_bytes(merger.csv_bytes(p, merger.PASSENGER_FIELDS))
            paths["CALENDAR"].write_bytes(merger.csv_bytes(c + [c[0]], merger.CALENDAR_FIELDS))
            paths["WEATHER"].write_bytes(merger.csv_bytes(weather_fixture(), merger.WEATHER_FIELDS))
            for name in ("OUTPUT", "AUDIT"):
                paths[name].write_bytes(b"existing delivery")
            with patch.multiple(merger, **paths), patch("sys.argv", ["merge_traffic_calendar.py"]), redirect_stderr(io.StringIO()):
                self.assertEqual(merger.main(), 1)
            for name in ("OUTPUT", "AUDIT"):
                self.assertEqual(paths[name].read_bytes(), b"existing delivery")

    def test_check_detects_tampered_artifact_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = merger.merge(merger.PASSENGER.read_bytes(), merger.CALENDAR.read_bytes(),
                                    merger.WEATHER.read_bytes())
            paths = {"OUTPUT": root / "result.csv", "AUDIT": root / "audit.json"}
            paths["OUTPUT"].write_bytes(expected[0])
            paths["AUDIT"].write_bytes(expected[1])
            with patch.multiple(merger, **paths), patch("sys.argv", ["merge_traffic_calendar.py", "--check"]), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(merger.main(), 0)
                changed = list(csv.DictReader(io.StringIO(expected[0].decode("utf-8"))))
                changed[0]["passengers"] = str(int(changed[0]["passengers"]) + 1)
                paths["OUTPUT"].write_bytes(merger.csv_bytes(changed, merger.OUTPUT_FIELDS))
                before = paths["OUTPUT"].read_bytes()
                self.assertNotEqual(before, expected[0])
                self.assertEqual(merger.main(), 1)
                self.assertEqual(paths["OUTPUT"].read_bytes(), before)
                self.assertEqual(paths["AUDIT"].read_bytes(), expected[1])


if __name__ == "__main__":
    unittest.main()
