"""Year view (#95): the scheduler running the whole Basel 2025 year for N = 1..8 servers, as data for the frontend.

    python -m simulate_year.yearview [--out runs/yearview] [--workers W] [--force]

For each N: *ours* = merit + heat-backed ballast, slack 24 h, load 0.6 (the decision card's reference, analysis.REF_*),
and *baseline* = thermostat with the same slack and the SAME paid load (like-for-like: both are offered the same
paid work; the thermostat runs only when the house wants heat, so it misses deadlines instead of dumping heat).
Both on the reference house and data/raw/basel_2025_hourly.csv.

Writes (schema `yearview-v1`, agreed on #95):
    <out>/<key>/index.json   settings, per-N summaries, sizing recommendation   -> GET /api/year/sizing
    <out>/<key>/n<N>.json    8760-hour columnar series for N (ours + baseline)   -> GET /api/year?n=N
    <out>/LATEST             the key of the newest complete run
    <out>/balance.json, hourly.csv, hourly.parquet, sweep.csv   the recommended N's run and a sweep (merit / thermostat
                                                                / always_on at the reference slack and load, N=1..8),
                                                                so the dashboard's existing panels fill
key = sha256 of the schema, the assumptions, the weather file, the settings and the simulator/scheduler source:
the same key always means the same numbers, so a complete <key> folder is reused unless --force.

Every number comes from data/assumptions.yaml and the run. The two sizing thresholds below are stated rules (like
analysis.MAX_TRANSITIONS_PER_DAY), not physical assumptions, and are printed with the recommendation.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from common.config import ROOT, load_assumptions
from house_model.profile import DEFAULT_CSV, load_reference_profile

from .analysis import COVERAGE_TOL, REF_LOAD, REF_SLACK
from .sim import assumptions_hash, ballast_bid, ballast_type, simulate

SCHEMA = "yearview-v1"
SERVERS = tuple(range(1, 9))
OURS = {"policy": "merit", "ballast": True, "slack_h": REF_SLACK, "load": REF_LOAD}
BASELINE = {"policy": "thermostat", "ballast": False, "slack_h": REF_SLACK, "load": REF_LOAD,
            "load_basis": "same paid load as ours"}
MAX_DUMP_SHARE = 0.01  # sizing rule: dumped heat at most 1 % of the year's heat demand (stated rule, #95)
SERIES = ("heat_used_kwh", "dumped_kwh", "backup_kwh", "tank_kwh", "servers_on", "paused", "units_done",
          "ballast_units", "missed", "net_chf_cum", "heat_used_kwh_cum")
ND = 3  # decimals in the JSON series


def _sha_file(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def _code_sha() -> str:
    h = hashlib.sha256()
    for d in ("simulate_year", "scheduler", "house_model"):
        for f in sorted((ROOT / "src" / d).glob("*.py")):
            h.update(f.name.encode() + f.read_bytes())
    return h.hexdigest()


def cache_key(max_dump_share: float = MAX_DUMP_SHARE) -> str:
    blob = json.dumps({"schema": SCHEMA, "assumptions": assumptions_hash(), "profile": _sha_file(DEFAULT_CSV),
                       "servers": SERVERS, "ours": OURS, "baseline": BASELINE, "max_dump_share": max_dump_share,
                       "coverage_tol": COVERAGE_TOL, "code": _code_sha()}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _r(x, nd: int = 6):
    return None if x is None else round(float(x), nd)


def summary(b: dict) -> dict:
    """The Summary object of the schema, from one balance (simulate())."""
    net = (b["heat_value_chf"] + (b["compute_income_chf"] or 0.0) + (b.get("ballast_income_chf") or 0.0)
           - b["electricity_cost_chf"])
    return {"coverage_pct": _r(None if b["share_covered"] is None else 100 * b["share_covered"], 4),
            "heat_demand_kwh": b["heat_demand_kwh"], "heat_used_kwh": b["server_heat_used_kwh"],
            "dumped_kwh": b["heat_dumped_kwh"], "backup_kwh": b["backup_heat_kwh"], "run_h": b["run_h"],
            "paid_run_h": b["paid_run_h"], "ballast_run_h": b["ballast_run_h"],
            "utilisation_pct": _r(None if b["utilisation"] is None else 100 * b["utilisation"], 4),
            "missed_pct": b["missed_deadline_pct"], "electricity_cost_chf": b["electricity_cost_chf"],
            "heat_value_chf": b["heat_value_chf"], "compute_income_chf": b["compute_income_chf"],
            "ballast_income_chf": b.get("ballast_income_chf"), "net_chf_excl_hardware": _r(net, 3),
            "break_even_chf_per_server_h": b["break_even_chf_per_server_h"],
            "break_even_incl_hardware_chf_per_server_h": b["break_even_incl_hardware_chf_per_server_h"],
            "pays_off_above_chf_per_server_h": b["pays_off_above_chf_per_server_h"], "pays_off": b["pays_off"],
            "pays_off_conditions": b["pays_off_conditions"]}


def series(df, a: dict, ballast: bool) -> dict[str, list]:
    """Per-hour arrays from simulate(..., detail=True); every energy is kWh in that hour."""
    p_el, div = float(a["price"]["chf_per_kwh"]), float(a["price"]["heat_value_divisor"])
    kw, unit_h = float(a["server"]["electric_kw"]), float(a["scheduler"]["unit_minutes"]) / 60.0
    bt = ballast_type(a)
    bid = bt.price_chf_per_h if bt else 0.0
    b_bid = (ballast_bid(a, check=False)[0] or 0.0) if ballast else 0.0
    used = df["space"] + df["dhw"] + df["tank_in"]
    net = used * p_el / div + df["units_done"] * unit_h * bid + df["ballast_units"] * unit_h * b_bid \
        - df["servers_on"] * kw * p_el
    cols = {"heat_used_kwh": used, "dumped_kwh": df["dump"], "backup_kwh": df["backup"], "tank_kwh": df["tank_level"],
            "servers_on": df["servers_on"], "paused": (~df["mode"].astype(bool)).astype(int),
            "units_done": df["units_done"], "ballast_units": df["ballast_units"], "missed": df["missed"],
            "net_chf_cum": net.cumsum(), "heat_used_kwh_cum": used.cumsum()}
    out = {}
    for k in SERIES:
        v = cols[k]
        out[k] = [int(x) for x in v] if k in ("paused", "units_done", "ballast_units", "missed") \
            else [round(float(x), ND) for x in v]
    return out


def _cell(args: tuple) -> dict:
    """One run in a worker process: (n, kind) with kind ours | baseline | sweep-<policy>."""
    n, kind = args
    a = load_assumptions()
    profile = load_reference_profile(assumptions=a)
    ah = assumptions_hash()
    if kind == "ours":
        bal, df = simulate(profile, a, n, "merit", OURS["slack_h"], OURS["load"], 0, ah, hourly=True, ballast=True,
                           detail=True)
        bal["load_basis"] = "explicit"
        return {"n": n, "kind": kind, "balance": bal, "series": series(df, a, True),
                "hourly_csv": df.drop(columns=["units_done", "ballast_units"]).to_csv(float_format="%.6f")}
    if kind == "baseline":
        bal, df = simulate(profile, a, n, "thermostat", BASELINE["slack_h"], BASELINE["load"], 0, ah, hourly=True,
                           detail=True)
        bal["load_basis"] = "explicit"
        return {"n": n, "kind": kind, "balance": bal, "series": series(df, a, False)}
    policy = kind.split("-", 1)[1]
    bal, _ = simulate(profile, a, n, policy, OURS["slack_h"], OURS["load"], 0, ah, hourly=False,
                      ballast=policy == "merit")
    return {"n": n, "kind": kind, "balance": bal}


def sizing(by_n: list[dict], a: dict, max_dump_share: float = MAX_DUMP_SHARE) -> dict:
    """Recommended N: among N with 0 % missed and dumped <= MAX_DUMP_SHARE x demand, the smallest N whose
    coverage is within COVERAGE_TOL (0.1 pp) of the best. Plus the N with the lowest paid price to pay off."""
    rows = [(r["n"], r["ours"]) for r in by_n]
    ok = [(n, s) for n, s in rows if (s["missed_pct"] or 0) == 0 and s["dumped_kwh"] <= max_dump_share * s["heat_demand_kwh"]]
    rule = (f"among N = {SERVERS[0]}..{SERVERS[-1]} with 0 % missed deadlines and dumped heat <= "
            f"{max_dump_share:.0%} of the year's heat demand, the smallest N whose heat coverage is within "
            f"{100 * COVERAGE_TOL:.1f} pp of the best (merit + ballast, slack {OURS['slack_h']:g} h, load {OURS['load']:g})")
    if ok:
        best = max(s["coverage_pct"] for _, s in ok)
        n_rec, s = min((x for x in ok if x[1]["coverage_pct"] >= best - 100 * COVERAGE_TOL - 1e-9), key=lambda x: x[0])
        larger = [m for m, t in ok if m > n_rec]
        reason = (f"N={n_rec} covers {s['coverage_pct']:.1f} % of the reference house's heat with "
                  f"{s['dumped_kwh']:,.0f} kWh dumped ({s['dumped_kwh'] / s['heat_demand_kwh']:.1%} of demand) and no "
                  f"missed deadlines; " + (f"N={larger[0]}..{larger[-1]} add less than {100 * COVERAGE_TOL:.1f} pp "
                                           f"coverage" if larger else "no larger N stays within the dump limit")
                  + ".")
    else:
        n_rec, s = None, None
        reason = "no N meets the rule (missed deadlines or too much dumped heat at every N)."
    priced = [(n, s2) for n, s2 in rows if s2["pays_off_above_chf_per_server_h"] is not None]
    if priced:
        n_be, s_be = min(priced, key=lambda x: (x[1]["pays_off_above_chf_per_server_h"], x[0]))
        bt = ballast_type(a)
        price = bt.price_chf_per_h if bt else None
        be_reason = (f"N={n_be} needs the lowest paid-work price to pay off incl. hardware: "
                     f"{s_be['pays_off_above_chf_per_server_h']:.3f} CHF/server-h"
                     + (f" (paid work bids {price:.3f}, so it {'pays' if s_be['pays_off'] else 'does not pay'} off)"
                        if price is not None else "") + ".")
    else:
        n_be, s_be, be_reason = None, None, "no N does paid work, so no break-even."
    return {"recommended_n": n_rec, "reason": reason, "lowest_break_even_n": n_be,
            "lowest_break_even_chf_per_server_h": s_be["pays_off_above_chf_per_server_h"] if s_be else None,
            "lowest_break_even_reason": be_reason, "rule": rule}


def _commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              timeout=5).stdout.strip() or None
    except Exception:  # noqa: BLE001 - provenance only
        return None


def _write(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp{os.getpid()}")
    tmp.write_text(text)
    os.replace(tmp, path)


def latest(out: Path) -> Path | None:
    """The newest complete <out>/<key>/ folder (from <out>/LATEST), or None."""
    try:
        d = out / (out / "LATEST").read_text().strip()
    except OSError:
        return None
    return d if (d / "index.json").exists() else None


def build(out: Path, workers: int | None = None, force: bool = False, log=print,
          max_dump_share: float = MAX_DUMP_SHARE) -> Path:
    a = load_assumptions()
    key = cache_key(max_dump_share)
    d = out / key
    if not force and (d / "index.json").exists() and all((d / f"n{n}.json").exists() for n in SERVERS):
        log(f"yearview: {d} is complete for this key; reusing it (--force to recompute)")
        _write(out / "LATEST", key + "\n")
        return d
    t0 = time.time()
    cells = [(n, k) for n in SERVERS for k in ("ours", "baseline", "sweep-thermostat", "sweep-always_on")]
    with ProcessPoolExecutor(max_workers=workers or os.cpu_count()) as ex:
        res = list(ex.map(_cell, cells))
    got = {(r["n"], r["kind"]): r for r in res}
    prov = {"key": key, "assumptions_hash": assumptions_hash(), "profile": str(DEFAULT_CSV.relative_to(ROOT)),
            "profile_sha256": _sha_file(DEFAULT_CSV), "commit": _commit(),
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    profile = load_reference_profile(assumptions=a)
    weather = {"temp_c": [round(float(x), 2) for x in profile["temp_c"]],
               "demand_kwh": [round(float(x), ND) for x in profile["space_heat_kw"] + profile["hot_water_kw"]]}
    by_n = [{"n": n, "ours": summary(got[(n, "ours")]["balance"]), "baseline": summary(got[(n, "baseline")]["balance"])}
            for n in SERVERS]
    bt = ballast_type(a)
    hw = a["hardware"]
    index = {"schema": SCHEMA, "provenance": prov,
             "settings": {"servers": list(SERVERS), "ours": OURS, "baseline": BASELINE,
                          "paid_price_chf_per_server_h": bt.price_chf_per_h if bt else None,
                          "ballast_bid_chf_per_server_h": float(a["ballast"]["bid_chf_per_server_h"]),
                          "capex_chf_per_server": float(hw["capex_chf_per_server"]),
                          "life_years": float(hw["life_years"]), "max_dump_share": max_dump_share,
                          "coverage_tol_pp": 100 * COVERAGE_TOL,
                          "constants": {"price_chf_per_kwh": float(a["price"]["chf_per_kwh"]),
                                        "heat_value_divisor": float(a["price"]["heat_value_divisor"]),
                                        "server_kw_el": float(a["server"]["electric_kw"]),
                                        "heat_recovery": float(a["server"]["heat_recovery_fraction"]),
                                        "tank_kwh": float(a["house"]["tank_kwh"]),
                                        "unit_minutes": float(a["scheduler"]["unit_minutes"])}},
             "by_n": by_n, "sizing": sizing(by_n, a, max_dump_share)}
    d.mkdir(parents=True, exist_ok=True)
    start = profile.index[0].isoformat()
    for n, row in zip(SERVERS, by_n):
        doc = {"schema": SCHEMA, "n": n, "provenance": prov, "start": start, "tz": str(profile.index.tz),
               "step_h": 1, "hours": len(profile), "summary": {"ours": row["ours"], "baseline": row["baseline"]},
               "weather": weather, "ours": got[(n, "ours")]["series"], "baseline": got[(n, "baseline")]["series"]}
        _write(d / f"n{n}.json", json.dumps(doc, separators=(",", ":")))
    _write(d / "index.json", json.dumps(index, indent=2))  # last: its presence marks the folder complete
    # dashboard panels (#31/#36 views read the newest runs/*/balance.json folder)
    rec = index["sizing"]["recommended_n"] or 4
    ours = got[(rec, "ours")]
    _write(out / "balance.json", json.dumps(ours["balance"], indent=2, sort_keys=True) + "\n")
    _write(out / "hourly.csv", ours["hourly_csv"])
    _write(out / "sweep.csv", _sweep_csv([got[(n, k)]["balance"] for n in SERVERS
                                          for k in ("ours", "sweep-thermostat", "sweep-always_on")]))
    _write(out / "LATEST", key + "\n")
    log(f"yearview: {len(cells)} runs in {time.time() - t0:.1f} s -> {d} (recommended N={rec})")
    return d


def _sweep_csv(rows: list[dict]) -> str:
    import io
    keys = [k for k in rows[0] if k not in ("break_even_incl_hardware_table", "pays_off_above_table")]
    tk = sorted(rows[0]["break_even_incl_hardware_table"])
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(keys + [f"be_hw_{k}" for k in tk] + ["error"])
    for r in rows:
        w.writerow([r.get(k, "") for k in keys] + [r["break_even_incl_hardware_table"].get(k, "") for k in tk] + [""])
    return buf.getvalue()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m simulate_year.yearview", description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=ROOT / "runs" / "yearview")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--force", action="store_true", help="recompute even if this key's folder is complete")
    ap.add_argument("--max-dump-share", type=float, default=MAX_DUMP_SHARE,
                    help=f"sizing rule: dumped heat <= this share of the heat demand (default {MAX_DUMP_SHARE})")
    ns = ap.parse_args(argv)
    if not 0 <= ns.max_dump_share <= 1:
        raise SystemExit("--max-dump-share must be in [0, 1]")
    d = build(ns.out, ns.workers, ns.force, max_dump_share=ns.max_dump_share)
    s = json.loads((d / "index.json").read_text())["sizing"]
    print(f"recommended N={s['recommended_n']}: {s['reason']}")
    print(f"lowest break-even: {s['lowest_break_even_reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
