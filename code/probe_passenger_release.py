"""Capture a small official archive sample for the 18:00 availability review.

Network required. Archive collection times are evidence of availability for
these snapshots, not a promise of the publisher's daily release time.
"""

import csv
import io
import json
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import urlopen

from clean_passenger import DATA, DIRECTIONS, HKT, POINTS, URL, json_bytes, sha256

BASE = "https://app.data.gov.hk/v1/historical-archive/"


def main():
    query = {"url": URL, "start": "20261001", "end": "20261004"}
    list_url = BASE + "list-file-versions?" + urlencode(query)
    with urlopen(list_url, timeout=120) as response:
        listing = json.load(response)
    timestamps = listing["timestamps"]
    if len(timestamps) != 4 or {t[:8] for t in timestamps} != {
            "20261001", "20261002", "20261003", "20261004"}:
        raise ValueError("Archive sample changed; review the requested dates")
    evidence = {
        "retrieved_at_hkt": datetime.now(HKT).isoformat(timespec="seconds"),
        "api_documentation_url": "https://data.gov.hk/en/help/api-spec",
        "archive_timezone": "GMT+8 (as stated in API documentation)",
        "list_url": list_url,
        "archive_timestamps": timestamps,
        "interpretation": "Archive collection time is not guaranteed first publication time.",
        "samples": [],
    }
    for timestamp in timestamps:
        url = BASE + "get-file?" + urlencode({"url": URL, "time": timestamp})
        with urlopen(url, timeout=120) as response:
            payload = response.read()
        rows = list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))))
        latest = max(datetime.strptime(r["Date"], "%d-%m-%Y").date() for r in rows)
        sample = [r for r in rows if r["Control Point"] in POINTS
                  and datetime.strptime(r["Date"], "%d-%m-%Y").date() == latest]
        keys = {(r["Control Point"], r["Arrival / Departure"]) for r in sample}
        if len(sample) != 6 or keys != {(p, d) for p in POINTS for d in DIRECTIONS}:
            raise ValueError(f"{timestamp}: latest date does not contain all six series")
        evidence["samples"].append({
            "archive_timestamp_hkt": timestamp, "archive_url": url,
            "raw_bytes": len(payload), "raw_sha256": sha256(payload),
            "latest_observation_date": latest.isoformat(),
            "latest_target_rows": [{k: v for k, v in row.items() if k} for row in sample],
        })
        print(f"Archive {timestamp}: latest observation {latest}, all six series present")
    output = DATA / "passenger_release_evidence.json"
    output.write_bytes(json_bytes(evidence))
    print(f"Saved {output.name}")


if __name__ == "__main__":
    main()
