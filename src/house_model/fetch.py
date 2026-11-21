"""Fetch Basel 2025 hourly weather from the Open-Meteo archive (public, no key).

    python -m house_model.fetch [--out PATH]

Location, year and variables come from data/assumptions.yaml (`location:`, `weather:`).
Writes Open-Meteo's CSV verbatim (3 metadata lines + header), which profile.py parses.
"""
from __future__ import annotations

import argparse
import urllib.parse
import urllib.request
from pathlib import Path

from common.config import load_assumptions

from .profile import DEFAULT_CSV

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def build_url(a: dict) -> str:
    loc, w = a["location"], a["weather"]
    year = loc["year"]
    q = {
        "latitude": loc["lat"],
        "longitude": loc["lon"],
        "start_date": f"{year}-01-01",
        "end_date": f"{year}-12-31",
        "hourly": ",".join(w["vars"]),
        "timezone": "auto",
        "format": "csv",
    }
    return f"{ARCHIVE_URL}?{urllib.parse.urlencode(q)}"


def fetch(out: Path = DEFAULT_CSV, a: dict | None = None) -> Path:
    url = build_url(a or load_assumptions())
    out.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=60) as r:
        out.write_bytes(r.read())
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=DEFAULT_CSV)
    path = fetch(ap.parse_args().out)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
