"""Tuning, sensitivity and decision-card data (#31). Every number is computed by simulate(); nothing typed.

    python -m simulate_year --band-sweep    [--out runs/<id>/]   -> band_sweep.csv
    python -m simulate_year --sensitivity   [--out runs/<id>/]   -> sensitivity.csv, sensitivity_detail.csv, tornado.png
    python -m simulate_year --decision-card [--out runs/<id>/]   -> decision_card.json

Reference case: merit, N=4, slack 24 h, load 0.6, **heat-backed ballast on** (#37). Ballast changes the
conclusions (merit without it has no work to make winter heat with), so every study runs with it.

Economics with ballast. Filler earns only its bid (`ballast.bid_chf_per_server_h`, below MC_dump), so the
run-hour break-even (`break_even_*_chf_per_server_h`, cost per server-hour run) is NOT the price paid work must
fetch. The decision number is

    pays_off_above_chf_per_server_h = (electricity - heat value + hardware - ballast income) / paid server-hours

i.e. the paid-work price at which the year breaks even including hardware, given the filler income.

Cells run in a process pool. A cell = (servers, policy, slack_h, load, seed, overrides, ballast) where overrides
patches a copy of data/assumptions.yaml (e.g. {"price": {"chf_per_kwh": 0.399}}). Hardware capex/life do
not change the physics, so their variants are recomputed from one balance.
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

from .sim import assumptions_hash, ballast_type, simulate

# Grids are the study design asked for in #31 (not physical assumptions).
BAND_LOWS = (0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 33.0)  # #31 grid + 25-33 (coverage rises with low)
BAND_HIGHS = (25.0, 30.0, 33.0, 35.0)
REF_N, REF_POLICY, REF_SLACK, REF_LOAD, REF_BALLAST = 4, "merit", 24.0, 0.6, True
PRICE_FACTORS = (0.8, 1.2)
DIVISORS = (2.0, 3.0)
LOADS = (0.4, 0.8)
SLACKS = (0.0, 168.0)
LIVES = (3.0, 5.0)
CARD_SERVERS = range(1, 9)
PATIENCE_SLACKS = (0.0, 24.0, 168.0)
MAX_TRANSITIONS_PER_DAY = 2.0  # band choice: no more than 2 on/off switches a day (actuator wear; stated rule)
TORNADO_METRIC = "pays_off_above_chf_per_server_h"


def _patch(a: dict, overrides: dict) -> dict:
    out = copy.deepcopy(a)
    for k, v in overrides.items():
        if isinstance(v, dict):
            out[k] = {**out.get(k, {}), **v}
        else:
            out[k] = v
    return out


def _ref(seed: int, servers: int = REF_N, slack: float = REF_SLACK, load: float = REF_LOAD,
         overrides: dict | None = None, policy: str = REF_POLICY, ballast: bool = REF_BALLAST) -> tuple:
    return (servers, policy, slack, load, seed, overrides or {}, ballast)


def _cell(args) -> dict:
    servers, policy, slack_h, load, seed, overrides, ballast = args
    a = _patch(load_assumptions(), overrides)
    b, _ = simulate(load_reference_profile(assumptions=a), a, servers, policy, slack_h, load, seed,
                    a_hash=assumptions_hash(), hourly=False, ballast=ballast)
    b["overrides"] = overrides
    return b


def run_cells(cells: list[tuple], workers: int | None = None) -> list[dict]:
    if workers == 1:
        return [_cell(c) for c in cells]
    with ProcessPoolExecutor(max_workers=workers or os.cpu_count()) as ex:
        return list(ex.map(_cell, cells, chunksize=1))


# ------------------------------------------------------------------ economics from one balance
def _hardware_chf(b: dict, capex_chf: float, life_y: float, hours: float) -> float:
    return b["servers_per_house"] * capex_chf / life_y * (hours / 8760.0)


def break_even_with_capex(b: dict, capex_chf: float, life_y: float, hours: float = 8760.0) -> float | None:
    """(electricity - heat value + hardware) / server-hours run (paid + ballast), from one balance."""
    if not b["run_h"]:
        return None
    return (b["electricity_cost_chf"] - b["heat_value_chf"] + _hardware_chf(b, capex_chf, life_y, hours)) / b["run_h"]


def paid_price_to_break_even(b: dict, capex_chf: float, life_y: float, hours: float = 8760.0) -> float | None:
    """Paid-work price (CHF/server-h) at which the year breaks even incl. hardware, counting filler income."""
    paid_h = b.get("paid_run_h") or 0.0
    if paid_h <= 0:
        return None
    cost = b["electricity_cost_chf"] - b["heat_value_chf"] + _hardware_chf(b, capex_chf, life_y, hours)
    return (cost - (b.get("ballast_income_chf") or 0.0)) / paid_h


def _capex0(a: dict | None = None) -> tuple[float, float]:
    hw = (a or load_assumptions())["hardware"]
    return float(hw["capex_chf_per_server"]), float(hw["life_years"])


def _rnd(x, nd: int = 6):
    return None if x is None else round(float(x), nd)


# ------------------------------------------------------------------ 1. tank band
def band_sweep(seed: int = 0, workers: int | None = None) -> list[dict]:
    a = load_assumptions()
    capex, life = _capex0(a)
    cells = [_ref(seed, overrides={"scheduler": {"tank_band_low_kwh": lo, "tank_band_high_kwh": hi}})
             for lo in BAND_LOWS for hi in BAND_HIGHS if lo <= hi <= a["house"]["tank_kwh"]]
    rows = []
    for b in run_cells(cells, workers):
        s = b["overrides"]["scheduler"]
        rows.append({"band_low_kwh": s["tank_band_low_kwh"], "band_high_kwh": s["tank_band_high_kwh"],
                     "share_covered": b["share_covered"], "heat_dumped_kwh": b["heat_dumped_kwh"],
                     "transitions_per_day": b["transitions_per_day"], "missed_deadline_pct": b["missed_deadline_pct"],
                     "ballast_run_h": b["ballast_run_h"],
                     "break_even_chf_per_server_h": b["break_even_chf_per_server_h"],
                     TORNADO_METRIC: _rnd(paid_price_to_break_even(b, capex, life))})
    return rows


def choose_band(rows: list[dict]) -> dict:
    """Highest coverage among bands with <= MAX_TRANSITIONS_PER_DAY; ties -> less dump, then wider band."""
    ok = [r for r in rows if r["transitions_per_day"] <= MAX_TRANSITIONS_PER_DAY] or rows
    return max(ok, key=lambda r: (round(r["share_covered"], 6), -r["heat_dumped_kwh"],
                                  r["band_high_kwh"] - r["band_low_kwh"]))


# ------------------------------------------------------------------ 2. sensitivity
def sensitivity_detail(seed: int = 0, workers: int | None = None) -> list[dict]:
    """One row per variant (all metrics). `sensitivity()` folds these into the dashboard's tornado rows."""
    a = load_assumptions()
    p0, bid0 = float(a["price"]["chf_per_kwh"]), float(a["ballast"]["bid_chf_per_server_h"])
    # The ballast bid is a price, not physics: it must stay inside [MC_used, MC_dump), which scales with the
    # electricity price, so the price variants scale it by the same factor (a fixed 0.25 at +20% would sit below
    # MC_used 0.271 and filler would never run).
    plan = [("electricity price", f"{f - 1:+.0%}",
             _ref(seed, overrides={"price": {"chf_per_kwh": round(p0 * f, 6)},
                                   "ballast": {"bid_chf_per_server_h": round(bid0 * f, 6)}}))
            for f in PRICE_FACTORS]
    plan += [("heat value divisor", f"{d:g}", _ref(seed, overrides={"price": {"heat_value_divisor": d}}))
             for d in DIVISORS]
    plan += [("load", f"{x:g}", _ref(seed, load=x)) for x in LOADS]
    plan += [("slack h", f"{s:g}", _ref(seed, slack=s)) for s in SLACKS]
    res = run_cells([_ref(seed)] + [p[2] for p in plan], workers)
    base, var = res[0], res[1:]
    capex0, life0 = _capex0(a)
    rows = [_drow("base", "", base, capex0, life0)]
    rows += [_drow(param, setting, b, capex0, life0) for (param, setting, _c), b in zip(plan, var)]
    for capex in a["hardware"]["capex_range_chf"]:
        for life in LIVES:
            rows.append(_drow("capex", f"{int(capex) // 1000}k/{int(life)}y", base, float(capex), life))
    return rows


def _drow(param: str, setting: str, b: dict, capex: float, life: float) -> dict:
    return {"parameter": param, "setting": setting, "share_covered": b["share_covered"],
            "heat_dumped_kwh": b["heat_dumped_kwh"], "missed_deadline_pct": b["missed_deadline_pct"],
            "paid_run_h": b["paid_run_h"], "ballast_run_h": b["ballast_run_h"],
            "break_even_chf_per_server_h": b["break_even_chf_per_server_h"],
            "break_even_incl_hardware_chf_per_server_h": _rnd(break_even_with_capex(b, capex, life)),
            TORNADO_METRIC: _rnd(paid_price_to_break_even(b, capex, life))}


def sensitivity(seed: int = 0, workers: int | None = None, detail: list[dict] | None = None) -> list[dict]:
    """Dashboard tornado rows (#36 columns): parameter, low, high, metric, metric_low, metric_high, metric_base.
    low/high are the two settings; for capex, low = cheapest capex x longest life, high = dearest x shortest."""
    d = detail if detail is not None else sensitivity_detail(seed, workers)
    base = next(r for r in d if r["parameter"] == "base")[TORNADO_METRIC]
    rows = []
    for param in dict.fromkeys(r["parameter"] for r in d if r["parameter"] != "base"):
        vs = [r for r in d if r["parameter"] == param]
        if param == "capex":
            vs = [min(vs, key=lambda r: r[TORNADO_METRIC]), max(vs, key=lambda r: r[TORNADO_METRIC])]
        lo, hi = vs[0], vs[-1]
        rows.append({"parameter": param, "low": lo["setting"], "high": hi["setting"], "metric": TORNADO_METRIC,
                     "metric_low": lo[TORNADO_METRIC], "metric_high": hi[TORNADO_METRIC], "metric_base": base})
    return rows


def tornado_png(rows: list[dict], path: Path) -> bool:
    """Tornado of the dashboard rows. Returns False when matplotlib is not installed (CSV is the source of truth)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    rows = [r for r in rows if r["metric_low"] is not None and r["metric_high"] is not None]
    rows.sort(key=lambda r: abs(r["metric_high"] - r["metric_low"]))
    base = rows[0]["metric_base"] if rows else 0.0
    fig, ax = plt.subplots(figsize=(7.5, 0.55 * len(rows) + 1.6))
    for i, r in enumerate(rows):
        for v, colour in ((r["metric_low"], "#4a7bd0"), (r["metric_high"], "#d0784a")):
            ax.barh(i, v - base, left=base, color=colour, height=0.6)
        ax.text(min(r["metric_low"], r["metric_high"]), i, f"{r['low']} ", va="center", ha="right", fontsize=8)
        ax.text(max(r["metric_low"], r["metric_high"]), i, f" {r['high']}", va="center", ha="left", fontsize=8)
    ax.set_yticks(range(len(rows)), [r["parameter"] for r in rows])
    ax.axvline(base, color="k", lw=0.8)
    ax.set_xlabel(f"paid-work price to break even incl. hardware (CHF/server-h); base {base:.3f}\n"
                  f"merit N={REF_N}, slack {REF_SLACK:g} h, load {REF_LOAD:g}, heat-backed ballast on")
    ax.margins(x=0.15)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return True


# ------------------------------------------------------------------ 3. decision card
def _paid_price(a: dict) -> float:
    bt = ballast_type(a)
    if bt is None:
        raise SystemExit("decision card needs `jobs:` in assumptions.yaml (paid-work price)")
    return float(bt.price_chf_per_h)


def decision_card(seed: int = 0, workers: int | None = None, detail: list[dict] | None = None) -> dict:
    """Flat keys for the dashboard (#36) plus the computed tables behind them."""
    a = load_assumptions()
    capex, life = _capex0(a)
    price = _paid_price(a)
    cells = [_ref(seed, servers=n) for n in CARD_SERVERS] + [_ref(seed, slack=s) for s in PATIENCE_SLACKS]
    res = run_cells(cells, workers)
    by_n, patience = res[:len(CARD_SERVERS)], res[len(CARD_SERVERS):]
    table = [{"servers": b["servers_per_house"], "share_covered": b["share_covered"],
              "heat_dumped_kwh": b["heat_dumped_kwh"], "missed_deadline_pct": b["missed_deadline_pct"],
              "paid_run_h": b["paid_run_h"], "ballast_run_h": b["ballast_run_h"],
              "break_even_incl_hardware_chf_per_server_h": _rnd(break_even_with_capex(b, capex, life)),
              TORNADO_METRIC: _rnd(paid_price_to_break_even(b, capex, life))} for b in by_n]
    priced = [r for r in table if r[TORNADO_METRIC] is not None]
    paying = [r for r in priced if r[TORNADO_METRIC] <= price]
    if paying:
        rec = max(paying, key=lambda r: (r["share_covered"], -r["servers"]))
        basis = (f"highest heat coverage ({rec['share_covered']:.1%}) among N that break even incl. hardware at the "
                 f"paid-work price {price:.2f} CHF/server-h (merit, ballast on, slack {REF_SLACK:g} h, load {REF_LOAD:g})")
    else:
        rec = min(priced, key=lambda r: r[TORNADO_METRIC])
        basis = (f"no N breaks even at the paid-work price {price:.2f} CHF/server-h; N with the lowest required "
                 f"paid price (merit, ballast on, slack {REF_SLACK:g} h, load {REF_LOAD:g})")
    detail = detail if detail is not None else sensitivity_detail(seed, workers)
    not_paying = [f"{r['parameter']} {r['setting']}: paid work must fetch {r[TORNADO_METRIC]:.3f} > {price:.2f} CHF/server-h"
                  for r in detail if r["parameter"] != "base" and r[TORNADO_METRIC] is not None
                  and r[TORNADO_METRIC] > price and r["setting"] != f"{int(capex) // 1000}k/{int(life)}y"]
    not_paying.insert(0, f"paid work sells below {rec[TORNADO_METRIC]:.3f} CHF/server-h (N={rec['servers']})")
    dump = {s: b["heat_dumped_kwh"] for s, b in zip(PATIENCE_SLACKS, patience)}
    d0 = dump[PATIENCE_SLACKS[0]] or 1.0
    patience_txt = "; ".join(f"slack {int(s)} h: dump {dump[s]:,.0f} kWh ({(dump[s] - d0) / d0:+.0%})"
                             for s in PATIENCE_SLACKS)
    return {
        # flat keys read by the dashboard (#36)
        "recommended_n": rec["servers"],
        "basis": basis,
        "pays_off_above_chf_per_server_h": rec[TORNADO_METRIC],
        "does_not_pay_off_when": not_paying,
        "first_pilot_measurement": (f"buyer patience: what deadline slack paying customers accept. At N={REF_N}: "
                                    f"{patience_txt}"),
        # computed extras
        "assumptions_hash": assumptions_hash(),
        "reference": {"policy": REF_POLICY, "ballast": REF_BALLAST, "slack_h": REF_SLACK, "load": REF_LOAD,
                      "seed": seed, "capex_chf_per_server": capex, "life_years": life,
                      "paid_work_price_chf_per_server_h": price,
                      "ballast_bid_chf_per_server_h": float(a["ballast"]["bid_chf_per_server_h"])},
        "metric_definition": "pays_off_above = (electricity - heat value + hardware - ballast income) / paid server-hours",
        "by_servers": table,
        "dump_kwh_by_slack_h": {str(int(k)): v for k, v in dump.items()},
    }


def write_csv(rows: list[dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return path


def write_json(obj: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=False) + "\n")
    return path
