"""Measure descriptive weather–traffic associations for Issue #10."""

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

from clean_passenger import HKT, ROOT
from explore_traffic import TRAFFIC_CSV, publish_artifact, read_traffic
from merge_traffic_calendar import PSR_LEVELS, TC_SIGNAL_LEVELS, WEATHER

OUTPUT = ROOT / "docs" / "探索分析" / "天气关联"
FOCAL_DATE = pd.Timestamp("2025-09-24")
FORECAST_COLUMNS = [
    "forecast_min_c", "forecast_max_c", "forecast_psr",
    "forecast_published_at_hkt", "forecast_archived_at_hkt",
]
WARNING_COLUMNS = {
    "tc_signal_on_date": TC_SIGNAL_LEVELS,
    "tc_signal_at_cutoff": TC_SIGNAL_LEVELS,
    "rainstorm_on_date": (0, 1, 2, 3),
    "rainstorm_at_cutoff": (0, 1, 2, 3),
}
BINARY_FACTORS = {
    "rain_at_least_25mm", "target_day_tc8_or_higher", "target_day_rainstorm_signal",
    "cutoff_tc3_or_higher", "cutoff_tc8_or_higher", "cutoff_rainstorm_signal",
    "forecast_psr_medium_high_or_high",
}


def read_weather(path, expected_dates):
    weather = pd.read_csv(path, parse_dates=["date"]).set_index("date").sort_index()
    if not weather.index.equals(expected_dates):
        raise ValueError("Weather must include each traffic date exactly once.")
    observations = weather[["rain_mm", "mean_temp_c"]].to_numpy(dtype=float)
    if not np.isfinite(observations).all() or weather["rain_mm"].lt(0).any():
        raise ValueError("Rainfall and temperature observations must be complete.")
    for field, levels in WARNING_COLUMNS.items():
        if not weather[field].isin(levels).all():
            raise ValueError(f"Unexpected warning signal in {field}.")

    available = weather[FORECAST_COLUMNS].notna()
    if not available.all(axis=1).eq(available.any(axis=1)).all():
        raise ValueError("Each forecast must include both timestamps and its data values.")
    forecast = weather.loc[available.all(axis=1)]
    if not forecast["forecast_psr"].isin(PSR_LEVELS).all():
        raise ValueError("Unexpected forecast rainfall probability.")
    temperature = forecast[["forecast_min_c", "forecast_max_c"]].to_numpy(dtype=float)
    if not np.isfinite(temperature).all() or not forecast["forecast_min_c"].le(forecast["forecast_max_c"]).all():
        raise ValueError("Forecast temperatures must be finite and ordered.")
    published = pd.to_datetime(forecast["forecast_published_at_hkt"], utc=True)
    archived = pd.to_datetime(forecast["forecast_archived_at_hkt"], utc=True)
    cutoff = (forecast.index - pd.Timedelta(hours=6)).tz_localize(HKT).tz_convert("UTC")
    if (published.dt.floor("min") > archived).any() or (archived > cutoff).any() or (published > cutoff).any():
        raise ValueError("Forecast publication or capture is inconsistent with the cutoff.")
    return weather


def factors(weather):
    high_rain_forecast = weather["forecast_psr"].isin(["Medium High", "High"])
    return pd.DataFrame({
        "rain_per_10mm": weather["rain_mm"] / 10,
        "rain_at_least_25mm": weather["rain_mm"].ge(25).astype(float),
        "mean_temp_per_5c": weather["mean_temp_c"] / 5,
        "target_day_tc8_or_higher": weather["tc_signal_on_date"].ge(8).astype(float),
        "target_day_rainstorm_signal": weather["rainstorm_on_date"].gt(0).astype(float),
        "cutoff_tc3_or_higher": weather["tc_signal_at_cutoff"].ge(3).astype(float),
        "cutoff_tc8_or_higher": weather["tc_signal_at_cutoff"].ge(8).astype(float),
        "cutoff_rainstorm_signal": weather["rainstorm_at_cutoff"].gt(0).astype(float),
        "forecast_psr_medium_high_or_high": high_rain_forecast.astype(float).where(weather["forecast_psr"].notna()),
        "forecast_max_temp_per_5c": weather["forecast_max_c"] / 5,
    })


def calendar_controls(calendar):
    month = pd.get_dummies(calendar.index.strftime("%Y-%m"), drop_first=True, dtype=float)
    weekday = pd.get_dummies(calendar.index.dayofweek, drop_first=True, dtype=float)
    holidays = calendar[["hk_holiday", "mainland_holiday", "mainland_makeup_workday"]]
    return np.column_stack([np.ones(len(calendar)), month, weekday, holidays])


def relative_difference(weather, responses, controls):
    """Fit one weather variable and return the associated percentage difference."""
    if np.ptp(weather) == 0:
        return np.full(responses.shape[1], np.nan)
    design = np.column_stack([controls, weather])
    coef, _, rank, _ = np.linalg.lstsq(design, responses, rcond=None)
    if rank == np.linalg.matrix_rank(controls):
        return np.full(responses.shape[1], np.nan)
    return 100 * np.expm1(coef[-1])


def measure(traffic, calendar, weather):
    counts = traffic.pivot(index="date", columns=["control_point", "direction"], values="passengers")
    counts["All three ports", "both"] = counts.sum(axis=1)
    if counts.le(0).any().any():
        raise ValueError("The log passenger analysis requires positive daily totals.")
    responses = np.log(counts.to_numpy())
    controls = calendar_controls(calendar)
    weather_factors = factors(weather)
    results = []

    for sample, include in (
        ("all_available_dates", np.ones(len(weather), dtype=bool)),
        ("exclude_2025_09_24", weather.index != FOCAL_DATE),
    ):
        for factor, values in weather_factors.items():
            valid = include & values.notna().to_numpy()
            x = values.to_numpy()[valid]
            y = responses[valid]
            if not len(x):
                raise ValueError(f"No dates available for {factor}.")
            raw = relative_difference(x, y, np.ones((len(x), 1)))
            adjusted = relative_difference(x, y, controls[valid])
            event_days = int(x.sum()) if factor in BINARY_FACTORS else None
            for i, (port, direction) in enumerate(counts.columns):
                results.append({
                    "sample": sample,
                    "weather_factor": factor,
                    "control_point": port,
                    "direction": direction,
                    "days": len(x),
                    "event_days": event_days,
                    "other_days": len(x) - event_days if event_days is not None else None,
                    "unadjusted_pct": raw[i],
                    "adjusted_pct": adjusted[i],
                })
    return pd.DataFrame(results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weather", type=Path, default=WEATHER)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    args = parser.parse_args()
    traffic, calendar = read_traffic(TRAFFIC_CSV.read_bytes())
    weather = read_weather(args.weather, calendar.index)
    result = measure(traffic, calendar, weather)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".weather-", dir=args.output_dir) as temporary:
        staged = Path(temporary) / "weather_associations.csv"
        for field in ("event_days", "other_days"):
            result[field] = result[field].astype("Int64")
        result.to_csv(staged, index=False, encoding="utf-8", lineterminator="\n", float_format="%.3f")
        publish_artifact(staged, args.output_dir)
    print(f"Saved {len(result)} associations from {len(weather):,} dates.")


if __name__ == "__main__":
    main()
