"""Regression tests for failures that could silently corrupt the handoff."""

import csv
import io
import unittest
from datetime import date

from clean_passenger import DataQualityError, DIRECTIONS, POINTS, RAW_FIELDS, clean


DAY = date(2024, 2, 29)


def fixture():
    return [["29-02-2024", p, d, "3", "2", "1", "6", ""]
            for p in POINTS for d in DIRECTIONS]


def encode(rows, header=None):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(RAW_FIELDS + [""] if header is None else header)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8-sig")


class PassengerTests(unittest.TestCase):
    def rejected(self, rows, error):
        with self.assertRaises(DataQualityError) as caught:
            clean(encode(rows), DAY, DAY)
        self.assertIn(error, {item["error"] for item in caught.exception.issues})

    def test_day_first_bom_empty_column_sort_and_zero_preserved(self):
        rows = fixture()[::-1]
        rows[0][3:7] = ["0"] * 4
        result, audit = clean(encode(rows), DAY, DAY)
        self.assertEqual(len(result), 6)
        self.assertTrue(all(r["date"] == "2024-02-29" for r in result))
        self.assertEqual(result[0]["control_point"], "Lo Wu")
        self.assertEqual(result[0]["direction"], "arrival")
        self.assertEqual(audit["zero_counts"]["passengers"], 1)
        self.assertEqual(len(audit["zero_total_keys"]), 1)

    def test_inclusive_boundaries_and_exact_control_point(self):
        rows = fixture()
        rows += [[d, p, a, "3", "2", "1", "6", ""] for d in
                 ["28-02-2024", "01-03-2024", "02-03-2024"]
                 for p in POINTS for a in DIRECTIONS]
        rows.append(["29-02-2024", "Lok Ma Chau", "Arrival", "1", "0", "0", "1", ""])
        result, audit = clean(encode(rows), DAY, date(2024, 3, 1))
        self.assertEqual(len(result), 12)
        self.assertEqual(audit["excluded_outside_date_range"], 12)
        self.assertEqual(audit["excluded_other_control_points_in_range"], 1)

    def test_duplicate_even_when_identical(self):
        rows = fixture()
        self.rejected(rows + [rows[0]], "duplicate_key")

    def test_missing_series_is_not_zero_filled(self):
        self.rejected(fixture()[:-1], "missing_keys")

    def test_invalid_counts(self):
        for value in ["", "NA", "-1", "1.5", "1,000", "NaN"]:
            with self.subTest(value=value):
                rows = fixture()
                rows[0][3] = value
                self.rejected(rows, "invalid_count")

    def test_mismatched_total(self):
        rows = fixture()
        rows[0][6] = "7"
        self.rejected(rows, "total_mismatch")

    def test_unknown_direction(self):
        rows = fixture()
        rows[0][2] = "Inbound"
        self.rejected(rows, "unknown_direction")

    def test_nonempty_extra_column(self):
        rows = fixture()
        rows[0][-1] = "unexpected"
        self.rejected(rows, "invalid_row_width_or_extra_value")

    def test_invalid_date(self):
        rows = fixture()
        rows[0][0] = "02-29-2024"
        self.rejected(rows, "invalid_date")

    def test_wrong_header_rejected(self):
        with self.assertRaises(DataQualityError):
            clean(encode(fixture(), ["wrong"]), DAY, DAY)


if __name__ == "__main__":
    unittest.main()
