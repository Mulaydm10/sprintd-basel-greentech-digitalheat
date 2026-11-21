"""Hourly reference profile for the case house (contracts/src/house_model.md).

Source: Open-Meteo archive CSV (`python -m house_model.fetch`). Open-Meteo with timezone=auto exports
wall-clock times at a FIXED offset (utc_offset_seconds in the header; +3600 for Basel, no DST jump).
We localize at that offset and convert to Europe/Zurich, so the index is tz-aware, unique and has
8,760 rows. Heating days use the Europe/Zurich local date (gives 206 days and 26,851.0 kWh).
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from common.config import ROOT, load_assumptions

DEFAULT_CSV = ROOT / "data" / "raw" / "basel_2025_hourly.csv"
COLUMNS = ["temp_c", "ghi_wm2", "heating_day", "space_heat_kw", "hot_water_kw", "demand_kw"]


def _standard_offset_s(tz: str, year: int) -> int:
    """UTC offset (s) of `tz` on Jan 1 = the fixed offset Open-Meteo's timezone=auto export uses."""
    return int(datetime(year, 1, 1, tzinfo=ZoneInfo(tz)).utcoffset().total_seconds())


def _read_open_meteo(path: Path, a: dict) -> tuple[pd.DataFrame, int, str]:
    """Accepts the raw Open-Meteo export (2 metadata lines + blank + header) or a plain
    `time,temperature_2m,shortwave_radiation` CSV (as committed on main). Columns are positional."""
    with open(path, newline="") as f:
        first = f.readline()
    if first.startswith("latitude"):
        with open(path, newline="") as f:
            meta = next(csv.DictReader([f.readline(), f.readline()]))
        offset_s, tz = int(meta["utc_offset_seconds"]), meta.get("timezone") or a["location"]["tz"]
        df = pd.read_csv(path, skiprows=3)
    else:
        tz = a["location"]["tz"]
        offset_s = _standard_offset_s(tz, int(a["location"]["year"]))
        df = pd.read_csv(path)
    df = df.iloc[:, :3]
    df.columns = ["time", "temp_c", "ghi_wm2"]
    return df, offset_s, tz


def load_reference_profile(path: str | Path | None = None, assumptions: dict | None = None) -> pd.DataFrame:
    a = assumptions or load_assumptions()
    h = a["house"]
    p = Path(path) if path else DEFAULT_CSV
    if not p.exists():
        raise FileNotFoundError(f"{p} missing; run: python -m house_model.fetch")
    raw, offset_s, tz = _read_open_meteo(p, a)

    fixed = pd.to_datetime(raw["time"]).dt.tz_localize(timezone(timedelta(seconds=offset_s)))
    idx = pd.DatetimeIndex(fixed.dt.tz_convert(tz), name="time")
    if not idx.is_unique or not idx.is_monotonic_increasing:
        raise ValueError(f"{p}: timestamps not unique/increasing after tz conversion")

    df = pd.DataFrame({"temp_c": raw["temp_c"].to_numpy(float), "ghi_wm2": raw["ghi_wm2"].to_numpy(float)}, index=idx)
    local_date = idx.date
    day_mean = df["temp_c"].groupby(local_date).transform("mean")
    df["heating_day"] = (day_mean < h["heating_day_mean_t_c"]).to_numpy(bool)
    space = (h["design_kw"] * (h["t_base_c"] - df["temp_c"]) / h["t_design_span_c"]).clip(lower=0.0)
    df["space_heat_kw"] = space.where(df["heating_day"], 0.0)
    df["hot_water_kw"] = h["hot_water_kwh_per_day"] / 24.0
    df["demand_kw"] = df["space_heat_kw"] + df["hot_water_kw"]
    return df[COLUMNS]
