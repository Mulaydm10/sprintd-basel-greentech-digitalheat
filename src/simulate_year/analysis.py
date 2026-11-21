"""Tuning, sensitivity and decision-card data (#31). Every number is computed by simulate(); nothing typed.

    python -m simulate_year --band-sweep    [--out runs/<id>/]   -> band_sweep.csv
    python -m simulate_year --sensitivity   [--out runs/<id>/]   -> sensitivity.csv (+ tornado.png if matplotlib)
    python -m simulate_year --decision-card [--out runs/<id>/]   -> decision_card.json

Cells run in a process pool. A cell = (servers, policy, slack_h, load, seed, overrides) where overrides
patches a copy of data/assumptions.yaml (e.g. {"price": {"chf_per_kwh": 0.399}}). Hardware capex/life do
not change the physics, so their variants are recomputed from one balance (`break_even_with_capex`).
"""
from __future__ import annotations

import copy
import csv
import json
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from common.config import load_assumptions
from house_model.profile import load_reference_profile

from .sim import assumptions_hash, simulate

# Grids are the study design asked for in #31 (not physical assumptions).
BAND_LOWS = (0.0, 5.0, 10.0, 15.0, 20.0)
BAND_HIGHS = (25.0, 30.0, 33.0, 35.0)
REF_N, REF_POLICY, REF_SLACK, REF_LOAD = 4, "merit", 24.0, 0.6
PRICE_FACTORS = (0.8, 1.2)
DIVISORS = (2.0, 3.0)
LOADS = (0.4, 0.8)
SLACKS = (0.0, 168.0)
LIVES = (3.0, 5.0)
CARD_SERVERS = range(1, 14)
PATIENCE_SLACKS = (0.0, 24.0, 168.0)
MAX_TRANSITIONS_PER_DAY = 2.0  # band choice: no more than 2 on/off switches a day (actuator wear; stated rule)


def _patch(a: dict, overrides: dict) -> dict:
    out = copy.deepcopy(a)
    for k, v in overrides.items():
        if isinstance(v, dict):
            out[k] = {**out.get(k, {}), **v}
        else:
            out[k] = v
    return out


def _cell(args) -> dict:
    servers, policy, slack_h, load, seed, overrides = args
    a = _patch(load_assumptions(), overrides)
    b, _ = simulate(load_reference_profile(assumptions=a), a, servers, policy, slack_h, load, seed,
                    a_hash=assumptions_hash(), hourly=False)
    b["overrides"] = overrides
    return b


def run_cells(cells: list[tuple], workers: int | None = None) -> list[dict]:
    if workers == 1:
        return [_cell(c) for c in cells]
    with ProcessPoolExecutor(max_workers=workers or os.cpu_count()) as ex:
        return list(ex.map(_cell, cells, chunksize=1))


def break_even_with_capex(b: dict, capex_chf: float, life_y: float, hours: float = 8760.0) -> float | None:
    """(electricity - heat value + N * capex / life * years) / server-hours run, from one balance."""
    if not b["run_h"]:
        return None
    years = hours / 8760.0
    return (b["electricity_cost_chf"] - b["heat_value_chf"]
            + b["servers_per_house"] * capex_chf / life_y * years) / b["run_h"]


# ------------------------------------------------------------------ 1. tank band
def band_sweep(seed: int = 0, workers: int | None = None) -> list[dict]:
    cells = [(REF_N, REF_POLICY, REF_SLACK, REF_LOAD, seed,
              {"scheduler": {"tank_band_low_kwh": lo, "tank_band_high_kwh": hi}})
             for lo in BAND_LOWS for hi in BAND_HIGHS if lo <= hi]
    rows = []
    for b in run_cells(cells, workers):
        s = b["overrides"]["scheduler"]
        rows.append({"band_low_kwh": s["tank_band_low_kwh"], "band_high_kwh": s["tank_band_high_kwh"],
                     "share_covered": b["share_covered"], "heat_dumped_kwh": b["heat_dumped_kwh"],
                     "transitions_per_day": b["transitions_per_day"], "missed_deadline_pct": b["missed_deadline_pct"],
                     "break_even_chf_per_server_h": b["break_even_chf_per_server_h"]})
    return rows


def choose_band(rows: list[dict]) -> dict:
    """Highest coverage among bands with <= MAX_TRANSITIONS_PER_DAY; ties -> less dump, then wider band."""
    ok = [r for r in rows if r["transitions_per_day"] <= MAX_TRANSITIONS_PER_DAY] or rows
    return max(ok, key=lambda r: (r["share_covered"], -r["heat_dumped_kwh"],
                                  r["band_high_kwh"] - r["band_low_kwh"]))


# ------------------------------------------------------------------ 2. sensitivity
def sensitivity(seed: int = 0, workers: int | None = None) -> list[dict]:
    a = load_assumptions()
    p0, d0 = float(a["price"]["chf_per_kwh"]), float(a["price"]["heat_value_divisor"])
    base_cell = (REF_N, REF_POLICY, REF_SLACK, REF_LOAD, seed, {})
    plan = [("price_chf_per_kwh", f, (REF_N, REF_POLICY, REF_SLACK, REF_LOAD, seed,
                                       {"price": {"chf_per_kwh": round(p0 * f, 6)}}), p0 * f) for f in PRICE_FACTORS]
    plan += [("heat_value_divisor", d, (REF_N, REF_POLICY, REF_SLACK, REF_LOAD, seed,
                                         {"price": {"heat_value_divisor": d}}), d) for d in DIVISORS]
    plan += [("load", l, (REF_N, REF_POLICY, REF_SLACK, l, seed, {}), l) for l in LOADS]
    plan += [("slack_h", s, (REF_N, REF_POLICY, s, REF_LOAD, seed, {}), s) for s in SLACKS]
    res = run_cells([base_cell] + [p[2] for p in plan], workers)
    base, var = res[0], res[1:]
    hw = a["hardware"]
    capex0, life0 = float(hw["capex_chf_per_server"]), float(hw["life_years"])
    base_be = break_even_with_capex(base, capex0, life0)
    rows = [_srow("base", "", base, base_be, base)]
    for (param, _f, _c, value), b in zip(plan, var):
        rows.append(_srow(param, value, b, break_even_with_capex(b, capex0, life0), base))
    for capex in hw["capex_range_chf"]:
        for life in LIVES:
            be = break_even_with_capex(base, float(capex), life)
            rows.append(_srow("capex_chf_x_life_y", f"{int(capex)}x{int(life)}", base, be, base))
    return rows


def _srow(param, value, b, be_hw, base) -> dict:
    return {"param": param, "value": value, "share_covered": b["share_covered"],
            "heat_dumped_kwh": b["heat_dumped_kwh"], "break_even_chf_per_server_h": b["break_even_chf_per_server_h"],
            "break_even_incl_hardware_chf_per_server_h": None if be_hw is None else round(be_hw, 6),
            "missed_deadline_pct": b["missed_deadline_pct"],
            "delta_be_hw_vs_base": None if be_hw is None else round(
                be_hw - break_even_with_capex(base, *_capex0()), 6)}


def _capex0() -> tuple[float, float]:
    hw = load_assumptions()["hardware"]
    return float(hw["capex_chf_per_server"]), float(hw["life_years"])


def tornado_png(rows: list[dict], path: Path) -> bool:
    """Optional figure; returns False when matplotlib is not installed (CSV is the source of truth)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    spans: dict[str, list[float]] = {}
    for r in rows:
        if r["param"] != "base" and r["delta_be_hw_vs_base"] is not None:
            spans.setdefault(r["param"], []).append(r["delta_be_hw_vs_base"])
    order = sorted(spans, key=lambda k: max(abs(x) for x in spans[k]))
    fig, ax = plt.subplots(figsize=(7, 0.5 * len(order) + 1.5))
    for i, k in enumerate(order):
        lo, hi = min(spans[k] + [0.0]), max(spans[k] + [0.0])
        ax.barh(i, hi - lo, left=lo, color="#4a7bd0")
    ax.set_yticks(range(len(order)), order)
    ax.axvline(0, color="k", lw=0.8)
    ax.set_xlabel("Δ break-even incl. hardware vs base (CHF/server-h), merit N=4")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return True


# ------------------------------------------------------------------ 3. decision card
def decision_card(seed: int = 0, workers: int | None = None) -> dict:
    a = load_assumptions()
    capex, life = _capex0()
    cells = [(n, REF_POLICY, REF_SLACK, REF_LOAD, seed, {}) for n in CARD_SERVERS]
    cells += [(REF_N, REF_POLICY, s, REF_LOAD, seed, {}) for s in PATIENCE_SLACKS]
    res = run_cells(cells, workers)
    by_n, patience = res[:len(CARD_SERVERS)], res[len(CARD_SERVERS):]
    bid = _bid(a)
    table = [{"servers": b["servers_per_house"], "share_covered": b["share_covered"],
              "break_even_incl_hardware_chf_per_server_h": _rnd(break_even_with_capex(b, capex, life)),
              "heat_dumped_kwh": b["heat_dumped_kwh"]} for b in by_n]
    paying = [r for r in table if r["break_even_incl_hardware_chf_per_server_h"] is not None
              and r["break_even_incl_hardware_chf_per_server_h"] <= bid]
    if paying:
        rec = max(paying, key=lambda r: (r["share_covered"], -r["servers"]))
        why = (f"highest coverage ({rec['share_covered']:.1%}) among N whose break-even incl. hardware "
               f"<= the paid-work price {bid:.3f} CHF/server-h")
    else:
        rec = min((r for r in table if r["break_even_incl_hardware_chf_per_server_h"] is not None),
                  key=lambda r: r["break_even_incl_hardware_chf_per_server_h"])
        why = (f"no N pays at {bid:.3f} CHF/server-h; N with the lowest break-even incl. hardware "
               f"({rec['break_even_incl_hardware_chf_per_server_h']:.3f})")
    sens = sensitivity(seed, workers)
    not_paying = [f"{r['param']}={r['value']}: break-even {r['break_even_incl_hardware_chf_per_server_h']:.3f} > "
                  f"{bid:.3f}" for r in sens if r["param"] != "base"
                  and r["break_even_incl_hardware_chf_per_server_h"] is not None
                  and r["break_even_incl_hardware_chf_per_server_h"] > bid]
    d = {s: b["heat_dumped_kwh"] for s, b in zip(PATIENCE_SLACKS, patience)}
    d0 = d[PATIENCE_SLACKS[0]] or 1.0
    patience_txt = "; ".join(f"slack {int(s)} h -> dump {d[s]:.0f} kWh ({(d[s] - d0) / d0:+.1%})"
                             for s in PATIENCE_SLACKS)
    return {
        "assumptions_hash": assumptions_hash(),
        "reference": {"policy": REF_POLICY, "slack_h": REF_SLACK, "load": REF_LOAD, "seed": seed,
                      "capex_chf_per_server": capex, "life_years": life, "paid_work_price_chf_per_server_h": bid},
        "by_servers": table,
        "recommended_servers": rec["servers"],
        "recommended_why": why,
        "pays_off_at_price_chf_per_server_h": rec["break_even_incl_hardware_chf_per_server_h"],
        "does_not_pay_when": not_paying,
        "first_pilot_measurement": {
            "what": "buyer patience: share of jobs that accept a deadline slack >= 24 h",
            "why": f"at N={REF_N}, load {REF_LOAD}: {patience_txt}",
            "dump_kwh_by_slack_h": {str(int(k)): v for k, v in d.items()},
        },
    }


def _bid(a: dict) -> float:
    from .sim import ballast_type
    bt = ballast_type(a)
    if bt is None:
        raise SystemExit("decision card needs `jobs:` in assumptions.yaml (paid-work price)")
    return bt.price_chf_per_h


def _rnd(x):
    return None if x is None else round(x, 6)


def write_csv(rows: list[dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return path


def write_json(obj: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")
    return path
