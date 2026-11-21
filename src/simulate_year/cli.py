"""CLI for simulate_year (kept out of __main__ so spawned sweep workers can import _sweep_cell).

python -m simulate_year --servers N --policy {merit,thermostat,always_on} [--slack-h H] [--load F] [--seed S] [--out DIR]
python -m simulate_year --sweep [--out DIR] [--workers W]

Writes <out>/balance.json + <out>/hourly.parquet (single run) or <out>/sweep.csv (sweep).
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

from .sim import POLICIES, assumptions_hash, simulate

# Sweep grid as specified in contracts/src/simulate_year.md (grid shape, not a physical assumption).
SWEEP_SERVERS = range(1, 14)
SWEEP_SLACK_H = (0, 24, 168)
SWEEP_LOAD = (0.4, 0.6, 0.8)


def _default_load(a: dict) -> float:
    return float((a.get("simulate_year") or {}).get("default_load", 0.0))


def _run_id(servers, policy, slack_h, load, seed) -> str:
    return f"{policy}-n{servers}-slack{slack_h:g}-load{load:g}-seed{seed}"


def _write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def run_one(servers: int, policy: str, slack_h: float, load: float, seed: int, out: Path | None,
            hourly: bool = True) -> dict:
    a = load_assumptions()
    bal, df = simulate(load_reference_profile(assumptions=a), a, servers, policy, slack_h, load, seed,
                       a_hash=assumptions_hash(), hourly=hourly)
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        _write_json(out / "balance.json", bal)
        if df is not None:
            df.to_parquet(out / "hourly.parquet")
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
    ap.add_argument("--load", type=float, default=None, help="paid work as a fraction of server capacity")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--workers", type=int, default=None)
    ns = ap.parse_args(argv)

    if ns.sweep:
        out = ns.out or ROOT / "runs" / f"sweep-seed{ns.seed}"
        print(f"wrote {sweep(out, ns.seed, ns.workers)}")
        return 0
    load = _default_load(load_assumptions()) if ns.load is None else ns.load
    out = ns.out or ROOT / "runs" / _run_id(ns.servers, ns.policy, ns.slack_h, load, ns.seed)
    bal = run_one(ns.servers, ns.policy, ns.slack_h, load, ns.seed, out)
    print(json.dumps({k: bal[k] for k in ("share_covered", "utilisation", "heat_dumped_kwh",
                                           "break_even_chf_per_server_h", "missed_deadline_pct")}))
    print(f"wrote {out}/balance.json")
    return 0

