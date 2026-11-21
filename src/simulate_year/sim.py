"""Yearly balance for the reference house (contracts/src/simulate_year.md v2).

hourly columns (kWh per 1-h step): demand, servers_on, space, dhw, tank_in, tank_draw, dump, backup,
tank_level, mode, queue_len, missed. break_even = (electricity - heat value) / server-hours RUN
(matches the briefing golden numbers; for merit, run == sold).

Port of research/scheduler/year_replay.py (validated against the briefing). The policy is NOT forked:
every hour calls scheduler.decide(). All numbers come from the assumptions dict.

Paid work stream ("load" mode, as in year_replay): each hour `servers * units_per_server_h * load`
units arrive (fractional accumulator; the seed sets its starting phase), each one unit_minutes of the
public ballast job type, bid = that type's price_chf_per_h, deadline = h + slack_h + 1.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from common.config import ROOT
from jobs.catalogue import JobType, load_catalogue
from scheduler import Assign, Params, Route, SetPower, SiteState, Unit, decide, heat_value_chf_kwh

POLICIES = ("merit", "thermostat", "always_on")
TOL = 1e-6


def assumptions_hash(path=None) -> str:
    return hashlib.sha256((path or ROOT / "data" / "assumptions.yaml").read_bytes()).hexdigest()


def ballast_type(a: dict) -> JobType | None:
    """Cheapest public, interruptible catalogue type (the paid stream), or None without a catalogue."""
    if len(a.get("jobs") or []) < 2:
        return None
    pool = [j for j in load_catalogue(a) if j.access_class == "public" and j.interruptible]
    return min(pool, key=lambda j: (j.price_chf_per_h, j.name)) if pool else None


@dataclass
class _Acc:
    used: float = 0.0
    dump: float = 0.0
    backup: float = 0.0
    run_h: float = 0.0
    units_in: int = 0
    units_done: int = 0
    missed: int = 0
    transitions: int = 0


def simulate(profile: pd.DataFrame, a: dict, servers: int, policy: str, slack_h: float = 0.0, load: float = 0.0,
             seed: int = 0, a_hash: str = "", hourly: bool = True) -> tuple[dict, pd.DataFrame | None]:
    if policy not in POLICIES:
        raise ValueError(f"policy {policy!r} not in {POLICIES}")
    if servers < 0 or load < 0 or slack_h < 0:
        raise ValueError("servers, load, slack_h must be >= 0")

    house, srv, price, sch, hw_cfg = a["house"], a["server"], a["price"], a["scheduler"], a["hardware"]
    p_el, div = float(price["chf_per_kwh"]), float(price["heat_value_divisor"])
    kw, rec = float(srv["electric_kw"]), float(srv["heat_recovery_fraction"])
    cap, low, high = float(house["tank_kwh"]), float(sch["tank_band_low_kwh"]), float(sch["tank_band_high_kwh"])
    unit_h = float(sch["unit_minutes"]) / 60.0
    unit_kwh = kw * unit_h

    ballast = ballast_type(a)
    if load > 0 and ballast is None:
        raise ValueError("load > 0 needs a public interruptible job type in assumptions.yaml `jobs:`")
    bid = ballast.price_chf_per_h if ballast else 0.0
    job_class = ballast.name if ballast else "none"
    access = ballast.access_class if ballast else "public"

    params = Params.from_assumptions(a, policy=policy, slack_enabled=slack_h > 0)

    space = profile["space_heat_kw"].to_numpy(float)
    dhw = profile["hot_water_kw"].to_numpy(float)
    H = len(space)

    rate = servers * (1.0 / unit_h) * load  # units per hour
    acc_units = float(np.random.default_rng(seed).uniform(0.0, 1.0)) if rate > 0 else 0.0
    lvl, mode, queue, k = 0.0, True, [], 0
    t = _Acc()
    rec_cols = {c: np.zeros(H) for c in ("demand", "servers_on", "space", "dhw", "tank_in", "tank_draw",
                                         "dump", "backup", "tank_level", "queue_len", "missed")} if hourly else None
    modes = np.zeros(H, dtype=bool) if hourly else None
    slack_int = int(math.ceil(slack_h))

    for h in range(H):
        # 1. arrivals
        acc_units += rate
        while acc_units >= 1.0 - 1e-12:
            queue.append(Unit(f"u{k}", f"j{k}", job_class, access, unit_kwh, bid, h + slack_int + 1, slack_h, True))
            k += 1
            acc_units -= 1.0
        # 2. site state
        dem = space[h] + dhw[h]
        site = SiteState("house", h, space[h], lvl, cap, servers, kw, rec, p_el,
                         heat_value_chf_kwh(p_el, div, dem, lvl, high), frozenset({access}), None, False,
                         low, high, mode, dhw[h])
        # 3. decide + apply
        dec = decide([site], queue, h, params, seed=seed)
        on = next(x.servers_on for x in dec.actions if isinstance(x, SetPower))
        r = next(x for x in dec.actions if isinstance(x, Route))
        done = {x.unit_id for x in dec.actions if isinstance(x, Assign)}
        if dec.next_mode["house"] != mode:
            t.transitions += 1
        mode = dec.next_mode["house"]
        # 4. tank + backup, with conservation asserts (robustness req. 2)
        produced = on * kw * rec
        assert abs(r.space_kwh + r.dhw_kwh + r.tank_kwh + r.dump_kwh - produced) < TOL, h
        lvl += r.tank_kwh
        unmet = dem - r.space_kwh - r.dhw_kwh
        draw = min(lvl, max(0.0, unmet))
        lvl -= draw
        backup = max(0.0, unmet - draw)
        assert abs(r.space_kwh + r.dhw_kwh + draw + backup - dem) < TOL, h
        assert -TOL <= lvl <= cap + TOL, (h, lvl)
        # 5. queue bookkeeping
        queue = [u for u in queue if u.unit_id not in done]
        late = sum(1 for u in queue if u.deadline_hour <= h)
        if late:
            queue = [u for u in queue if u.deadline_hour > h]

        t.used += r.space_kwh + r.dhw_kwh + r.tank_kwh
        t.dump += r.dump_kwh
        t.backup += backup
        t.run_h += on
        t.units_done += len(done)
        t.missed += late
        if hourly:
            for c, v in (("demand", dem), ("servers_on", on), ("space", r.space_kwh), ("dhw", r.dhw_kwh),
                         ("tank_in", r.tank_kwh), ("tank_draw", draw), ("dump", r.dump_kwh), ("backup", backup),
                         ("tank_level", lvl), ("queue_len", len(queue)), ("missed", late)):
                rec_cols[c][h] = v
            modes[h] = mode
    t.units_in = k

    bal = _balance(a, servers, policy, slack_h, load, seed, a_hash, H, space, dhw, t, bid, unit_h, ballast is not None)
    df = None
    if hourly:
        df = pd.DataFrame(rec_cols, index=profile.index)
        df["mode"] = modes
        df = df[["demand", "servers_on", "space", "dhw", "tank_in", "tank_draw", "dump", "backup", "tank_level",
                 "mode", "queue_len", "missed"]]
        df["queue_len"] = df["queue_len"].astype(int)
        df["missed"] = df["missed"].astype(int)
    return bal, df


def thermostat_load(profile: pd.DataFrame, a: dict, servers: int) -> float:
    """Like-for-like A/B: the load at which paid work equals the server-hours the thermostat baseline runs
    (its utilisation), so merit and thermostat sell the same work. 0 for N=0."""
    if servers <= 0:
        return 0.0
    bal, _ = simulate(profile, a, servers, "thermostat", 0.0, 0.0, 0, hourly=False)
    return float(bal["run_h"]) / (servers * len(profile))


def _r(x, nd=6):
    return None if x is None else round(float(x), nd)


def _balance(a, servers, policy, slack_h, load, seed, a_hash, H, space, dhw, t: _Acc, bid, unit_h, has_price) -> dict:
    p_el, div = float(a["price"]["chf_per_kwh"]), float(a["price"]["heat_value_divisor"])
    kw = float(a["server"]["electric_kw"])
    hw = a["hardware"]
    demand = float(space.sum() + dhw.sum())
    elec = t.run_h * kw * p_el
    heat_value = t.used * p_el / div
    sold_h = t.units_done * unit_h
    income = sold_h * bid if has_price else None
    be = (elec - heat_value) / t.run_h if t.run_h > 0 else None

    capex, life = float(hw["capex_chf_per_server"]), float(hw["life_years"])
    years = H / 8760.0

    def be_hw(c, l):
        return (elec - heat_value + servers * c / l * years) / t.run_h if t.run_h > 0 else None

    lives = [float(x) for x in hw.get("life_years_range", [life])]
    table = {f"capex_{int(c)}_life_{int(l)}y": _r(be_hw(c, l)) for c in hw["capex_range_chf"] for l in lives}
    be_inc = be_hw(capex, life)
    pays = bool(has_price and be_inc is not None and bid >= be_inc)
    if be_inc is None:
        cond = "no servers run, so there is no break-even"
    else:
        cond = (f"pays off if compute sells for >= {be_inc:.4f} CHF/server-h incl. hardware "
                f"(capex {capex:.0f} CHF over {life:.0f} y; {be:.4f} without hardware)")
        if has_price:
            cond += f"; paid work bids {bid:.4f} CHF/server-h, so it {'does' if pays else 'does not'}"
        cond += f"; heat covers {(demand - t.backup) / demand:.1%} of demand, {t.dump:.0f} kWh dumped"

    return {
        "servers_per_house": servers,
        "policy": policy,
        "slack_h": slack_h,
        "load": load,
        "seed": seed,
        "heat_demand_kwh": _r(demand, 3),
        "server_heat_used_kwh": _r(t.used, 3),
        "share_covered": _r((demand - t.backup) / demand if demand > 0 else None),
        "backup_heat_kwh": _r(t.backup, 3),
        "heat_dumped_kwh": _r(t.dump, 3),
        "run_h": _r(t.run_h, 3),
        "utilisation": _r(t.run_h / (servers * H) if servers > 0 else None),
        "jobs_total": t.units_in,
        "units_done": t.units_done,
        "missed_deadline_pct": _r(100.0 * t.missed / t.units_in if t.units_in else 0.0, 4),
        "transitions_per_day": _r(t.transitions / (H / 24.0), 4),
        "electricity_cost_chf": _r(elec, 3),
        "heat_value_chf": _r(heat_value, 3),
        "compute_income_chf": _r(income, 3),
        "break_even_chf_per_server_h": _r(be),
        "break_even_incl_hardware_chf_per_server_h": _r(be_inc),
        "break_even_incl_hardware_table": table,
        "assumptions_hash": a_hash,
        "pays_off": pays,
        "pays_off_conditions": cond,
    }
