"""Generate data/holidays.csv from the official schedules in data/README.md."""

import argparse
import csv
import io
from datetime import date, timedelta
from pathlib import Path


START = date(2024, 1, 1)
END = date(2026, 10, 31)
OUTPUT = Path(__file__).resolve().parents[1] / "data" / "holidays.csv"

HK_SOURCES = {
    2024: "https://www.info.gov.hk/gia/general/202305/25/P2023052500209.htm",
    2025: "https://www.info.gov.hk/gia/general/202405/03/P2024043000414.htm",
    2026: "https://www.info.gov.hk/gia/general/202505/16/P2025051300354.htm",
}
MAINLAND_SOURCES = {
    2024: "https://app.www.gov.cn/govdata/gov/202310/25/508678/article.html",
    2025: "https://www.gov.cn/gongbao/2024/issue_11726/material/gwygb202433.pdf",
    2026: "https://www.gov.cn/gongbao/2025/issue_12406/material/gwygb202532.pdf",
}

# Dates and names from the annual Hong Kong notices, excluding the recurring Sunday entry.
HK_HOLIDAYS = {
    2024: {
        "01-01": "一月一日",
        "02-10": "農曆年初一",
        "02-12": "農曆年初三",
        "02-13": "農曆年初四",
        "03-29": "耶穌受難節",
        "03-30": "耶穌受難節翌日",
        "04-01": "復活節星期一",
        "04-04": "清明節",
        "05-01": "勞動節",
        "05-15": "佛誕",
        "06-10": "端午節",
        "07-01": "香港特別行政區成立紀念日",
        "09-18": "中秋節翌日",
        "10-01": "國慶日",
        "10-11": "重陽節",
        "12-25": "聖誕節",
        "12-26": "聖誕節後第一個周日",
    },
    2025: {
        "01-01": "一月一日",
        "01-29": "農曆年初一",
        "01-30": "農曆年初二",
        "01-31": "農曆年初三",
        "04-04": "清明節",
        "04-18": "耶穌受難節",
        "04-19": "耶穌受難節翌日",
        "04-21": "復活節星期一",
        "05-01": "勞動節",
        "05-05": "佛誕",
        "05-31": "端午節",
        "07-01": "香港特別行政區成立紀念日",
        "10-01": "國慶日",
        "10-07": "中秋節翌日",
        "10-29": "重陽節",
        "12-25": "聖誕節",
        "12-26": "聖誕節後第一個周日",
    },
    2026: {
        "01-01": "一月一日",
        "02-17": "農曆年初一",
        "02-18": "農曆年初二",
        "02-19": "農曆年初三",
        "04-03": "耶穌受難節",
        "04-04": "耶穌受難節翌日",
        "04-06": "清明節翌日",
        "04-07": "復活節星期一翌日",
        "05-01": "勞動節",
        "05-25": "佛誕翌日",
        "06-19": "端午節",
        "07-01": "香港特別行政區成立紀念日",
        "09-26": "中秋節翌日",
        "10-01": "國慶日",
        "10-19": "重陽節翌日",
        "12-25": "聖誕節",
        "12-26": "聖誕節後第一個周日",
    },
}

# Holiday name, inclusive start and end, and the dates explicitly designated as workdays.
# The 2024 New Year's break started in December 2023. Only Jan 1 is in scope.
MAINLAND_SCHEDULES = {
    2024: (
        ("元旦", "01-01", "01-01", ()),
        ("春节", "02-10", "02-17", ("02-04", "02-18")),
        ("清明节", "04-04", "04-06", ("04-07",)),
        ("劳动节", "05-01", "05-05", ("04-28", "05-11")),
        ("端午节", "06-08", "06-10", ()),
        ("中秋节", "09-15", "09-17", ("09-14",)),
        ("国庆节", "10-01", "10-07", ("09-29", "10-12")),
    ),
    2025: (
        ("元旦", "01-01", "01-01", ()),
        ("春节", "01-28", "02-04", ("01-26", "02-08")),
        ("清明节", "04-04", "04-06", ()),
        ("劳动节", "05-01", "05-05", ("04-27",)),
        ("端午节", "05-31", "06-02", ()),
        ("国庆节、中秋节", "10-01", "10-08", ("09-28", "10-11")),
    ),
    2026: (
        ("元旦", "01-01", "01-03", ("01-04",)),
        ("春节", "02-15", "02-23", ("02-14", "02-28")),
        ("清明节", "04-04", "04-06", ()),
        ("劳动节", "05-01", "05-05", ("05-09",)),
        ("端午节", "06-19", "06-21", ()),
        ("中秋节", "09-25", "09-27", ()),
        ("国庆节", "10-01", "10-07", ("09-20", "10-10")),
    ),
}


def dates_between(first, last):
    if first > last:
        raise ValueError(f"Reversed date range: {first} to {last}")
    for offset in range((last - first).days + 1):
        yield first + timedelta(days=offset)


def mainland_dates():
    holidays = {}
    makeup_days = {}
    for year, schedules in MAINLAND_SCHEDULES.items():
        for name, start, end, makeup in schedules:
            first = date.fromisoformat(f"{year}-{start}")
            last = date.fromisoformat(f"{year}-{end}")
            for day in dates_between(first, last):
                if day in holidays:
                    raise ValueError(f"Repeated mainland holiday: {day}")
                holidays[day] = name
            for month_day in makeup:
                day = date.fromisoformat(f"{year}-{month_day}")
                if day in makeup_days or day.weekday() < 5:
                    raise ValueError(f"Invalid mainland makeup workday: {day}")
                makeup_days[day] = name
    if holidays.keys() & makeup_days.keys():
        raise ValueError("A mainland holiday and makeup workday share the same date")
    return holidays, makeup_days


def calendar_csv():
    mainland_holidays, mainland_makeup_days = mainland_dates()
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow((
        "date", "hk_holiday", "mainland_holiday", "mainland_makeup_workday",
        "is_weekend", "hk_holiday_name", "mainland_holiday_name",
        "mainland_makeup_workday_for", "hk_source_url", "mainland_source_url",
    ))
    for day in dates_between(START, END):
        hk_name = HK_HOLIDAYS[day.year].get(day.strftime("%m-%d"), "")
        mainland_name = mainland_holidays.get(day, "")
        makeup_for = mainland_makeup_days.get(day, "")
        writer.writerow((
            day.isoformat(), int(bool(hk_name)), int(bool(mainland_name)),
            int(bool(makeup_for)), int(day.weekday() >= 5), hk_name, mainland_name,
            makeup_for, HK_SOURCES[day.year] if hk_name else "",
            MAINLAND_SOURCES[day.year] if mainland_name or makeup_for else "",
        ))
    return output.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check the CSV without writing it.")
    args = parser.parse_args()
    content = calendar_csv()
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != content:
            parser.exit(1, "data/holidays.csv differs from the generated calendar.\n")
        print("data/holidays.csv matches the generated calendar.")
    else:
        OUTPUT.write_bytes(content.encode("utf-8"))
        print("Wrote data/holidays.csv.")


if __name__ == "__main__":
    main()
