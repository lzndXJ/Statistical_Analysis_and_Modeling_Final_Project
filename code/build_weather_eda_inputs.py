"""Build the daily weather source table from official HKO records."""

import argparse
import csv
import io
import re
from calendar import month_name
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from zipfile import ZipFile

from lxml import html

from clean_passenger import END, HKT, ROOT, START, json_bytes, sha256
from explore_traffic import publish_artifact
from merge_traffic_calendar import PSR_LEVELS, WEATHER, WEATHER_FIELDS

OUTPUT = WEATHER.parent
SOURCE_DIR = ROOT / "tmp" / "issue-10-weather-source"
RAIN_URL = "https://data.weather.gov.hk/weatherAPI/cis/csvfile/HKO/ALL/daily_HKO_RF_ALL.csv"
TEMPERATURE_URL = (
    "https://data.weather.gov.hk/weatherAPI/opendata/opendata.php?dataType=CLMTEMP&rformat=csv&station=HKO"
)
FORECAST_RSS = "https://rss.weather.gov.hk/rss/SeveralDaysWeatherForecast_v2.xml"
ARCHIVE_API = "https://app.data.gov.hk/v1/historical-archive/get-file"
MONTHLY_WARNING_URL = "https://www.hko.gov.hk/en/wxinfo/pastwx/mws{year}/mws{month}.htm"
MONTHS = [
    f"{year:04d}{month:02d}" for year in range(START.year - 1, END.year + 1)
    for month in range(1, 13)
    if (START - timedelta(days=1)).replace(day=1) <= date(year, month, 1) <= END
]
DAYS = [START + timedelta(days=i) for i in range((END - START).days + 1)]
RAINSTORM_LEVELS = {"amber": 1, "red": 2, "black": 3}


def source_urls():
    sources = {"rain.csv": RAIN_URL, "mean_temp.csv": TEMPERATURE_URL}
    for month in MONTHS:
        query = urlencode({"url": FORECAST_RSS, "time": month + "01"})
        sources[f"forecast_{month}.zip"] = f"{ARCHIVE_API}?{query}"
        sources[f"warnings_{month}.html"] = MONTHLY_WARNING_URL.format(year=month[:4], month=month)
    return sources


def fetch_source(source_dir, filename, url):
    path = source_dir / filename
    if path.is_file() and path.stat().st_size:
        return

    request = Request(url, headers={"User-Agent": "Traffic weather EDA (public data retrieval)"})
    for attempt in range(2):
        try:
            with urlopen(request, timeout=25) as response:
                data = response.read()
            with TemporaryDirectory(prefix=".weather-source-", dir=source_dir) as temporary:
                downloaded = Path(temporary) / filename
                downloaded.write_bytes(data)
                publish_artifact(downloaded, source_dir)
            return
        except (TimeoutError, URLError) as error:
            if attempt or (isinstance(error, HTTPError) and error.code < 500 and error.code != 429):
                raise
            sleep(1.5)


def read_observations(payload, rain=False):
    values = {}
    reader = csv.reader(io.StringIO(payload.decode("utf-8-sig")))
    for cells in reader:
        if len(cells) < 5 or not re.fullmatch(r"\d{4}", cells[0]):
            continue
        year, month, day = map(int, cells[:3])
        if not START.year <= year <= END.year:
            continue
        observed_date = date(year, month, day)
        if not START <= observed_date <= END:
            continue
        if observed_date in values or cells[4] != "C":
            raise ValueError(f"Duplicate or incomplete weather observation: {observed_date}")
        trace = rain and cells[3].strip().lower() == "trace"
        values[observed_date] = (0.0 if trace else float(cells[3]), int(trace))
    if values.keys() != set(DAYS):
        raise ValueError("Observation dates do not cover the full project period.")
    return values


def warning_time(day_month, clock, period):
    day, month = map(int, day_month.split("/"))
    year, report_month = int(period[:4]), int(period[4:])
    if month == 1 and report_month == 12:
        year += 1
    elif month == 12 and report_month == 1:
        year -= 1
    if not re.fullmatch(r"\d{4}", clock):
        raise ValueError(f"Invalid warning time: {clock}")
    hour, minute = divmod(int(clock), 100)
    if hour > 24 or minute >= 60 or (hour == 24 and minute):
        raise ValueError(f"Invalid warning time: {clock}")
    midnight = datetime(year, month, day, tzinfo=HKT)
    return midnight + timedelta(hours=hour, minutes=minute)


def read_warnings(payload, period):
    root = html.fromstring(payload)
    title = str(root.xpath("string(//title)"))
    month = month_name[int(period[4:])]
    if f"{month} {period[:4]}" not in title:
        raise ValueError(f"Warning page does not match its expected month: {period}")

    events = []
    headings = root.xpath("//caption | //p | //h3 | //h4 | //h5 | //h6")
    for heading in headings:
        text = " ".join(heading.text_content().split())
        label = re.fullmatch(r"Table 1\.\d+\s+(Tropical Cyclone Warning Signals?|Rainstorm Warning Signals?)", text)
        if label is None:
            continue
        kind = "tc" if label[1].startswith("Tropical") else "rainstorm"
        tables = heading.xpath("ancestor::table[1]") if heading.tag == "caption" else heading.xpath("following::table[1]")
        if not tables:
            raise ValueError(f"Missing {kind} warning table: {period}")

        observations = []
        for row in tables[0].xpath("./thead/tr | ./tbody/tr | ./tr"):
            cells = [" ".join(cell.text_content().split()) for cell in row.xpath("./td")]
            if len(cells) < 5 or not re.fullmatch(r"\d{1,2}\s*/\s*\d{1,2}", cells[-4]):
                continue
            signal, start_day, start_time, end_day, end_time = cells[-5:]
            if kind == "tc":
                signal = int(re.match(r"\d+", signal)[0])
                if signal not in (1, 3, 8, 9, 10):
                    raise ValueError(f"Invalid cyclone signal: {signal}")
            else:
                signal = RAINSTORM_LEVELS[signal.lower()]
            start = warning_time(start_day, start_time, period)
            end = warning_time(end_day, end_time, period)
            if start >= end or (start.month != int(period[4:]) and end.month != int(period[4:])):
                raise ValueError(f"Invalid warning interval in {period}: {start}, {end}")
            observations.append((kind, signal, start, end))
        if not observations:
            raise ValueError(f"No readable rows in the {kind} warning table: {period}")
        events.extend(observations)
    return events


def read_forecast(payload, target):
    item = ElementTree.fromstring(payload).find("./channel/item")
    published = parsedate_to_datetime(item.findtext("pubDate")).astimezone(HKT)
    if not 1 <= (target - published.date()).days <= 9:
        return None
    text = item.findtext("description")
    for block in re.split(r"Date/Month:\s*", text)[1:]:
        day_month = re.match(r"(\d{1,2})/(\d{1,2})\s*\(", block)
        if not day_month or (int(day_month[1]), int(day_month[2])) != (target.day, target.month):
            continue
        temperature = re.search(r"Temp range:\s*(-?\d+)\s*-\s*(-?\d+)\s*C\b", block)
        rain_probability = re.search(r"PSR:\s*([A-Za-z ]+)", block)
        if not temperature or not rain_probability:
            return None
        low, high = map(int, temperature.groups())
        psr = rain_probability[1].strip()
        if not low <= high or psr not in PSR_LEVELS:
            raise ValueError(f"Invalid forecast values for {target}: {low}, {high}, {psr!r}")
        return published, low, high, psr
    return None


def read_forecast_archive(payload):
    forecasts = {}
    with ZipFile(io.BytesIO(payload)) as archive:
        for member in archive.namelist():
            match = re.fullmatch(
                r"(\d{8}-\d{4})-SeveralDaysWeatherForecast_v2\.xml", PurePosixPath(member).name
            )
            if match is None:
                continue
            archived_at = datetime.strptime(match[1], "%Y%m%d-%H%M").replace(tzinfo=HKT)
            target = archived_at.date() + timedelta(days=1)
            if not START <= target <= END or archived_at.time() > time(18):
                continue
            values = read_forecast(archive.read(member), target)
            if values is None:
                continue
            published, low, high, psr = values
            cutoff = datetime.combine(archived_at.date(), time(18), tzinfo=HKT)
            if published > cutoff or published.replace(second=0, microsecond=0) > archived_at:
                raise ValueError(f"Inconsistent publication time for {member}: {published}")
            previous = forecasts.get(target)
            if previous is None or (published, archived_at) > previous[:2]:
                forecasts[target] = (published, archived_at, low, high, psr)
    return forecasts


def daily_rows(observations, temperatures, warnings, forecasts):
    by_kind = {
        kind: [(level, start, end) for event_kind, level, start, end in warnings if event_kind == kind]
        for kind in ("tc", "rainstorm")
    }
    for day in DAYS:
        start = datetime.combine(day, time(0), tzinfo=HKT)
        end = start + timedelta(days=1)
        cutoff = start - timedelta(hours=6)
        row = {"date": day.isoformat(), "rain_mm": observations[day][0],
               "rain_trace": observations[day][1], "mean_temp_c": temperatures[day][0]}
        for kind, events in by_kind.items():
            daily_key = "tc_signal_on_date" if kind == "tc" else "rainstorm_on_date"
            cutoff_key = "tc_signal_at_cutoff" if kind == "tc" else "rainstorm_at_cutoff"
            row[daily_key] = max((level for level, first, last in events if first < end and last > start), default=0)
            row[cutoff_key] = max((level for level, first, last in events if first <= cutoff < last), default=0)
        if day in forecasts:
            published, archived, low, high, psr = forecasts[day]
            row.update(forecast_min_c=low, forecast_max_c=high, forecast_psr=psr,
                       forecast_published_at_hkt=published.isoformat(),
                       forecast_archived_at_hkt=archived.isoformat())
        yield row


def rebuild(source_dir, output):
    sources = source_urls()
    payloads = {name: (source_dir / name).read_bytes() for name in sources}
    rain = read_observations(payloads["rain.csv"], rain=True)
    temperature = read_observations(payloads["mean_temp.csv"])
    warnings = set()
    forecasts = {}
    for month in MONTHS:
        warnings.update(read_warnings(payloads[f"warnings_{month}.html"], month))
        for day, forecast in read_forecast_archive(payloads[f"forecast_{month}.zip"]).items():
            if day not in forecasts or forecast[:2] > forecasts[day][:2]:
                forecasts[day] = forecast

    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".weather-", dir=output) as temporary:
        staged = Path(temporary)
        daily_path = staged / WEATHER.name
        with daily_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=WEATHER_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(daily_rows(rain, temperature, warnings, forecasts))
        manifest = staged / "weather_sources.json"
        manifest.write_bytes(json_bytes({
            "sources": {name: {"url": url, "sha256": sha256(payloads[name])} for name, url in sources.items()},
            "weather_daily_sha256": sha256(daily_path.read_bytes()),
            "days_with_observations": len(rain),
            "warning_intervals": len(warnings),
            "days_with_pre_cutoff_forecast": len(forecasts),
            "dates_without_pre_cutoff_forecast": [day.isoformat() for day in DAYS if day not in forecasts],
        }))
        for file in (daily_path, manifest):
            publish_artifact(file, output)
    print(f"{len(rain)} observation dates, {len(warnings)} warning intervals, {len(forecasts)} pre-cutoff forecasts.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="Fetch public HKO sources missing from the cache.")
    parser.add_argument("--source-dir", type=Path, default=SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.download:
        args.source_dir.mkdir(parents=True, exist_ok=True)
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [
                pool.submit(fetch_source, args.source_dir, name, url) for name, url in source_urls().items()
            ]
            for future in futures:
                future.result()
    rebuild(args.source_dir, args.output_dir)


if __name__ == "__main__":
    main()
