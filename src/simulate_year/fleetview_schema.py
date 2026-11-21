"""fleetview-v1: the output schema of `python -m simulate_year.fleetview` (#119), and a small fixture writer.

A whole-city DigitalHeat fleet for Basel 2025: ASSUMED fleet (size, placement, job volume), REAL algorithm
(`scheduler.decide()` across all sites every hour) and REAL weather. The #118 visual reads exactly these files.

<out>/<key>/index.json
  {
    "schema": "fleetview-v1", "fixture": bool,
    "provenance": {key, assumptions_hash, profile_sha256, commit, generated_at},
    "assumed": {"houses": K, "placement": "...", "servers": "...", "access_classes": "...", "job_stream": "..."},
    "start": "2025-01-01T00:00:00+01:00", "tz": "Europe/Zurich", "step_h": 1, "hours": H,
    "houses": [{"id", "building" (basel3d.json index), "x", "y" (local metres, as basel3d), "footprint_m2", "scale",
                "servers", "tank_kwh", "classes": [..], "district"}],
    "series": {"file": "houses.u16", "layout": "[field][house][hour]", "dtype": "uint16-le",
               "fields": [{"name", "unit", "scale"}]},      # value = raw * scale
    "fleet": {"file": "fleet.json"},
    "jobs": {"file": "jobs.json", "tracked_every": M},
    "totals": {"ours": Totals, "baseline": Totals}            # baseline = thermostat on the same fleet + job stream
  }
  Totals: {coverage_pct, heat_demand_kwh, heat_used_kwh, dumped_kwh, backup_kwh, run_h, utilisation_pct,
           units_arrived, units_done, units_rejected, units_missed, missed_pct, net_chf_excl_hardware}

houses.u16: uint16 little-endian, fields in index order, each H values per house:
  servers_on (1), heat_used_kwh (0.001), unmet_kwh (0.001) [backup heater], dumped_kwh (0.001), tank_kwh (0.01),
  state (1) [0 idle, 1 heat used, 2 dumping, 3 held by hysteresis], mc_chf_per_server_h (0.0001) [the site's
  marginal cost this hour = electricity - recovered heat value: the merit order; lower = heat wanted = wins work]

fleet.json (columnar, H values each): queue, arrivals, assigned, deferred, rejected, missed, ballast_units,
  paid_price_chf_per_server_h (the job stream's bid), heat_used_kwh, dumped_kwh, unmet_kwh, net_chf_cum

jobs.json: {"tracked": [{"job", "type", "class", "bid", "arrival_h", "deadline_h", "slack_h", "state" (done | missed |
  rejected), "units": [{"unit", "runs": [[hour, house], ...]}]}]}   every M-th job of the stream, fully traced
"""
from __future__ import annotations

import json
import math
import random
import struct
from pathlib import Path

SCHEMA = "fleetview-v1"
FIELDS = [("servers_on", "servers", 1.0), ("heat_used_kwh", "kWh", 0.001), ("unmet_kwh", "kWh", 0.001),
          ("dumped_kwh", "kWh", 0.001), ("tank_kwh", "kWh", 0.01), ("state", "code", 1.0),
          ("mc_chf_per_server_h", "CHF/server-h", 0.0001)]
FLEET_KEYS = ("queue", "arrivals", "assigned", "deferred", "rejected", "missed", "ballast_units",
              "paid_price_chf_per_server_h", "heat_used_kwh", "dumped_kwh", "unmet_kwh", "net_chf_cum")
TOTALS_KEYS = ("coverage_pct", "heat_demand_kwh", "heat_used_kwh", "dumped_kwh", "backup_kwh", "run_h",
               "utilisation_pct", "units_arrived", "units_done", "units_rejected", "units_missed", "missed_pct",
               "net_chf_excl_hardware")


def write(d: Path, index: dict, series: list[list[list[float]]], fleet: dict, jobs: dict) -> None:
    """series[field][house][hour] in natural units -> houses.u16 (quantised by each field's scale)."""
    d.mkdir(parents=True, exist_ok=True)
    buf = bytearray()
    for (name, _, scale), per_house in zip(FIELDS, series):
        for vals in per_house:
            buf += struct.pack(f"<{len(vals)}H", *(max(0, min(65535, round(v / scale))) for v in vals))
    (d / "houses.u16").write_bytes(bytes(buf))
    (d / "fleet.json").write_text(json.dumps(fleet, separators=(",", ":")))
    (d / "jobs.json").write_text(json.dumps(jobs, separators=(",", ":")))
    (d / "index.json").write_text(json.dumps(index, indent=1))


def read_series(d: Path, index: dict) -> dict[str, list[list[float]]]:
    raw = (d / index["series"]["file"]).read_bytes()
    K, H, out, off = len(index["houses"]), index["hours"], {}, 0
    for f in index["series"]["fields"]:
        rows = []
        for _ in range(K):
            rows.append([v * f["scale"] for v in struct.unpack_from(f"<{H}H", raw, off)])
            off += 2 * H
        out[f["name"]] = rows
    return out


def write_fixture(d: Path, houses: int = 10, hours: int = 48, seed: int = 0) -> Path:
    """A SYNTHETIC fixture with the exact fleetview-v1 shape (fixture: true), for building the #118 visual before the
    real run lands. Numbers are plausible but invented: never show them as results."""
    rng = random.Random(seed)
    H = hours
    hs = [{"id": i, "building": i, "x": round(rng.uniform(-1800, 1800), 1), "y": round(rng.uniform(-1500, 1500), 1),
           "footprint_m2": rng.randint(90, 400), "scale": round(rng.uniform(0.6, 2.2), 3), "servers": rng.choice([2, 3, 4]),
           "tank_kwh": 35.0, "classes": ["public", "swiss-only"] + (["certified"] if i % 7 == 0 else []),
           "district": rng.choice(["Gundeldingen", "St. Johann", "Matthäus", "Bachletten"])} for i in range(houses)]
    S = {f[0]: [] for f in FIELDS}
    for h in hs:
        cols = {k: [] for k in S}
        tank = 17.5
        for t in range(H):
            demand = h["scale"] * (6.0 + 2.5 * math.cos(2 * math.pi * (t % 24) / 24))
            on = min(h["servers"], max(0, round(demand / 2.4 + rng.uniform(-0.6, 0.6))))
            used = min(on * 0.8, demand + max(0.0, 35 - tank))
            dump = max(0.0, on * 0.8 - used)
            tank = min(35.0, max(0.0, tank + used - demand))
            cols["servers_on"].append(on); cols["heat_used_kwh"].append(used); cols["unmet_kwh"].append(max(0.0, demand - used))
            cols["dumped_kwh"].append(dump); cols["tank_kwh"].append(tank)
            cols["state"].append(0 if on == 0 else 2 if dump > 0.01 else 1)
            cols["mc_chf_per_server_h"].append(0.3325 - (0.133 * 0.8 if demand > 0 else 0.0) + rng.uniform(0, 0.01))
        for k in S:
            S[k].append(cols[k])
    fleet = {k: [round(rng.uniform(0, 50), 3) for _ in range(H)] for k in FLEET_KEYS}
    fleet["paid_price_chf_per_server_h"] = [0.5] * H
    jobs = {"tracked": [{"job": f"j{j}", "type": "image_tagging", "class": "public", "bid": 0.5, "arrival_h": j,
                         "deadline_h": j + 24, "slack_h": 24, "state": "done",
                         "units": [{"unit": f"j{j}-u0", "runs": [[j + 1, j % houses], [j + 2, (j + 3) % houses]]}]}
                        for j in range(0, H, 4)]}
    tot = {k: 0 for k in TOTALS_KEYS}
    index = {"schema": SCHEMA, "fixture": True,
             "provenance": {"key": "fixture", "assumptions_hash": None, "profile_sha256": None, "commit": None,
                            "generated_at": None},
             "assumed": {"houses": f"{houses} (fixture)", "placement": "fixture", "servers": "fixture",
                         "access_classes": "fixture", "job_stream": "fixture"},
             "start": "2025-01-01T00:00:00+01:00", "tz": "Europe/Zurich", "step_h": 1, "hours": H, "houses": hs,
             "series": {"file": "houses.u16", "layout": "[field][house][hour]", "dtype": "uint16-le",
                        "fields": [{"name": n, "unit": u, "scale": s} for n, u, s in FIELDS]},
             "fleet": {"file": "fleet.json"}, "jobs": {"file": "jobs.json", "tracked_every": 4},
             "totals": {"ours": dict(tot), "baseline": dict(tot)}}
    write(d, index, [S[f[0]] for f in FIELDS], fleet, jobs)
    return d
