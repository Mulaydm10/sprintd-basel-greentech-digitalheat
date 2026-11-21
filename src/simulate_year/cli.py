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
import sys
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


def _run_id(servers, policy, slack_h, load, seed, ballast: bool = False, admission: bool = False) -> str:
    """Collision-free run folder name (#39, red team F12): floats in full precision (repr), every flag."""
    lt = load if isinstance(load, str) else repr(float(load))
    flags = ("-ballast" if ballast else "") + ("-admission" if admission else "")
    return f"{policy}-n{servers}-slack{float(slack_h)!r}-load{lt}-seed{seed}{flags}"


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


CELL_KEYS = ("servers_per_house", "policy", "slack_h", "load", "seed")


def sweep(out: Path, seed: int, workers: int | None) -> Path:
    """One row per cell. A crashing cell does not kill the sweep (#39, red team F17): it becomes a row with
    its inputs and an `error` message, every other cell still runs, and `sweep.failed` counts the failures."""
    cells = [(n, p, float(s), float(l), seed) for n, p, s, l in product(SWEEP_SERVERS, POLICIES, SWEEP_SLACK_H, SWEEP_LOAD)]
    rows: list[dict] = []
    with ProcessPoolExecutor(max_workers=workers or os.cpu_count()) as ex:
        futs = [ex.submit(_sweep_cell, c) for c in cells]
        for c, f in zip(cells, futs):
            try:
                rows.append({**f.result(), "error": ""})
            except Exception as e:  # noqa: BLE001 - isolate any cell failure, report it in the row
                rows.append({**dict(zip(CELL_KEYS, c)), "error": f"{type(e).__name__}: {e}"})
    sweep.failed = sum(1 for r in rows if r["error"])
    out.mkdir(parents=True, exist_ok=True)
    ok = next((r for r in rows if not r["error"]), None)
    keys = [k for k in (ok or rows[0]) if k not in ("break_even_incl_hardware_table", "error")]
    table_keys = sorted(ok["break_even_incl_hardware_table"]) if ok else []
    path = out / "sweep.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(keys + [f"be_hw_{k}" for k in table_keys] + ["error"])
        for r in rows:
            tbl = r.get("break_even_incl_hardware_table") or {}
            w.writerow([r.get(k, "") for k in keys] + [tbl.get(k, "") for k in table_keys] + [r["error"]])
    return path


sweep.failed = 0


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
    ap.add_argument("--force", action="store_true", help="overwrite an existing run folder")
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
        detail = None
        if ns.sensitivity or ns.decision_card:
            detail = an.sensitivity_detail(ns.seed, ns.workers)
        if ns.sensitivity:
            print(f"wrote {an.write_csv(detail, out / 'sensitivity_detail.csv')}")
            rows = an.sensitivity(detail=detail)
            print(f"wrote {an.write_csv(rows, out / 'sensitivity.csv')}")
            print("wrote tornado.png" if an.tornado_png(rows, out / "tornado.png") else "matplotlib missing: no png")
        if ns.decision_card:
            card = an.decision_card(ns.seed, ns.workers, detail=detail)
            print(f"wrote {an.write_json(card, out / 'decision_card.json')}")
        return 0
    if ns.sweep:
        out = ns.out or ROOT / "runs" / f"sweep-seed{ns.seed}"
        print(f"wrote {sweep(out, ns.seed, ns.workers)}")
        if sweep.failed:
            print(f"{sweep.failed} cell(s) failed; see the `error` column", file=sys.stderr)
            return 1
        return 0
    tag = ns.load if ns.load is not None else _default_load(load_assumptions())
    out = ns.out or ROOT / "runs" / _run_id(ns.servers, ns.policy, ns.slack_h, tag, ns.seed, ns.ballast, ns.admission)
    if (out / "balance.json").exists() and not ns.force:
        raise SystemExit(f"{out} already holds a run; pass --force to overwrite (#39, F12)")
    bal = run_one(ns.servers, ns.policy, ns.slack_h, ns.load, ns.seed, out, ballast=ns.ballast,
                  admission=ns.admission)
    print(json.dumps({k: bal[k] for k in ("share_covered", "utilisation", "heat_dumped_kwh",
                                           "break_even_chf_per_server_h", "missed_deadline_pct", "admitted_units",
                                           "rejected_units")}))
    print(f"wrote {out}/balance.json")
    return 0

