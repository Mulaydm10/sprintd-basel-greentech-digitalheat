"""CLI for simulate_year (kept out of __main__ so spawned sweep workers can import _sweep_cell).

python -m simulate_year --servers N --policy {merit,thermostat,always_on} [--slack-h H] [--load F|thermostat] [--seed S] [--out DIR]

--load thermostat = like-for-like A/B: paid work equal to the thermostat baseline's server-hours for this N.
python -m simulate_year --sweep [--out DIR] [--workers W]

Writes <out>/balance.json + <out>/hourly.parquet + <out>/hourly.csv (single run) or <out>/sweep.csv (sweep).
All inputs from data/assumptions.yaml; balance.json carries its sha256 as assumptions_hash.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from concurrent.futures import ProcessPoolExecutor
from itertools import product
from pathlib import Path

from common.config import ROOT, load_assumptions
from house_model.profile import load_reference_profile

from .sim import POLICIES, assumptions_hash, simulate, thermostat_load

# Sweep grid as specified in contracts/src/simulate_year.md (grid shape, not a physical assumption).
SWEEP_SERVERS = range(1, 14)
SWEEP_SLACK_H = (0, 24, 168)
SWEEP_LOAD = (0.4, 0.6, 0.8)


def _default_load(a: dict) -> float:
    return float((a.get("simulate_year") or {}).get("default_load", 0.0))


def _run_id(servers, policy, slack_h, load, seed) -> str:
    lt = load if isinstance(load, str) else f"{load:g}"
    return f"{policy}-n{servers}-slack{slack_h:g}-load{lt}-seed{seed}"


def _write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def resolve_load(load: str | float | None, a: dict, profile, servers: int) -> tuple[float, str]:
    """-> (load fraction, basis). basis: explicit | default | thermostat."""
    if load is None:
        return _default_load(a), "default"
    if isinstance(load, str) and load.strip().lower() == "thermostat":
        return thermostat_load(profile, a, servers), "thermostat"
    try:
        return float(load), "explicit"
    except ValueError:
        raise SystemExit(f"--load must be a number or 'thermostat', got {load!r}") from None


def run_one(servers: int, policy: str, slack_h: float, load: str | float | None, seed: int, out: Path | None,
            hourly: bool = True, ballast: bool = False, admission: bool = False) -> dict:
    a = load_assumptions()
    profile = load_reference_profile(assumptions=a)
    load_f, basis = resolve_load(load, a, profile, servers)
    bal, df = simulate(profile, a, servers, policy, slack_h, load_f, seed, a_hash=assumptions_hash(), hourly=hourly,
                       ballast=ballast, admission=admission)
    bal["load_basis"] = basis
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        _write_json(out / "balance.json", bal)
        if df is not None:
            df.to_parquet(out / "hourly.parquet")
            df.to_csv(out / "hourly.csv", float_format="%.6f")
    return bal


def _sweep_cell(args) -> dict:
    servers, policy, slack_h, load, seed = args
    return run_one(servers, policy, slack_h, load, seed, out=None, hourly=False)


def sweep(out: Path, seed: int, workers: int | None) -> Path:
    cells = [(n, p, float(s), float(l), seed) for n, p, s, l in product(SWEEP_SERVERS, POLICIES, SWEEP_SLACK_H, SWEEP_LOAD)]
    with ProcessPoolExecutor(max_workers=workers or os.cpu_count()) as ex:
        rows = list(ex.map(_sweep_cell, cells, chunksize=1))
    out.mkdir(parents=True, exist_ok=True)
    keys = [k for k in rows[0] if k != "break_even_incl_hardware_table"]
    table_keys = sorted(rows[0]["break_even_incl_hardware_table"])
    path = out / "sweep.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(keys + [f"be_hw_{k}" for k in table_keys])
        for r in rows:
            w.writerow([r[k] for k in keys] + [r["break_even_incl_hardware_table"][k] for k in table_keys])
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m simulate_year", description="Yearly heat/compute balance.")
    ap.add_argument("--servers", type=int, default=1)
    ap.add_argument("--policy", choices=POLICIES, default="merit")
    ap.add_argument("--slack-h", type=float, default=0.0)
    ap.add_argument("--load", default=None,
                    help="paid work as a fraction of server capacity, or 'thermostat' for a like-for-like A/B")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--ballast", action="store_true",
                    help="merit: add unlimited heat-backed filler work at ballast.bid (#37)")
    ap.add_argument("--admission", action="store_true", help="gate arriving jobs with scheduler.admit (v2.2)")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--band-sweep", action="store_true", help="#31: tank-band grid -> band_sweep.csv")
    ap.add_argument("--sensitivity", action="store_true", help="#31: tornado at N=4 -> sensitivity.csv (+png)")
    ap.add_argument("--decision-card", action="store_true", help="#31: -> decision_card.json")
    ns = ap.parse_args(argv)

    if ns.band_sweep or ns.sensitivity or ns.decision_card:
        from . import analysis as an
        out = ns.out or ROOT / "runs" / f"analysis-seed{ns.seed}"
        if ns.band_sweep:
            rows = an.band_sweep(ns.seed, ns.workers)
            print(f"wrote {an.write_csv(rows, out / 'band_sweep.csv')}; chosen: {an.choose_band(rows)}")
        if ns.sensitivity:
            rows = an.sensitivity(ns.seed, ns.workers)
            print(f"wrote {an.write_csv(rows, out / 'sensitivity.csv')}")
            print("wrote tornado.png" if an.tornado_png(rows, out / "tornado.png") else "matplotlib missing: no png")
        if ns.decision_card:
            print(f"wrote {an.write_json(an.decision_card(ns.seed, ns.workers), out / 'decision_card.json')}")
        return 0
    if ns.sweep:
        out = ns.out or ROOT / "runs" / f"sweep-seed{ns.seed}"
        print(f"wrote {sweep(out, ns.seed, ns.workers)}")
        return 0
    tag = ns.load if ns.load is not None else _default_load(load_assumptions())
    out = ns.out or ROOT / "runs" / _run_id(ns.servers, ns.policy, ns.slack_h, tag, ns.seed)
    bal = run_one(ns.servers, ns.policy, ns.slack_h, ns.load, ns.seed, out, ballast=ns.ballast,
                  admission=ns.admission)
    print(json.dumps({k: bal[k] for k in ("share_covered", "utilisation", "heat_dumped_kwh",
                                           "break_even_chf_per_server_h", "missed_deadline_pct", "admitted_units",
                                           "rejected_units")}))
    print(f"wrote {out}/balance.json")
    return 0

