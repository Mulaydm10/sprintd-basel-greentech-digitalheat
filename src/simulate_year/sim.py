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

import gc
import hashlib
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from common.config import ROOT
from jobs.catalogue import JobType, load_catalogue
from scheduler import Assign, Params, Route, SetPower, SiteState, Unit, decide, heat_value_chf_kwh
from scheduler.admit import admit, net_of_backlog, persistence_forecast
from scheduler.policy import used_capacity_kwh_el

POLICIES = ("merit", "thermostat", "always_on")
TOL = 1e-6


def assumptions_hash(path=None) -> str:
    return hashlib.sha256((path or ROOT / "data" / "assumptions.yaml").read_bytes()).hexdigest()


def ballast_bid(a: dict, check: bool = True) -> tuple[float | None, str]:
    """(bid, access_class) of the unlimited filler stream from `ballast:`. With check, assert the contract
    v2 band at the reference server: MC_used <= bid < MC_dump (else the filler would dump or never run)."""
    cfg = a.get("ballast") or {}
    if "bid_chf_per_server_h" not in cfg:
        if check:
            raise ValueError("--ballast needs `ballast.bid_chf_per_server_h` in assumptions.yaml")
        return None, "public"
    b = float(cfg["bid_chf_per_server_h"])
    if check:
        p, kw = float(a["price"]["chf_per_kwh"]), float(a["server"]["electric_kw"])
        rec, div = float(a["server"]["heat_recovery_fraction"]), float(a["price"]["heat_value_divisor"])
        mc_used, mc_dump = p * kw - rec * kw * p / div, p * kw
        if not (mc_used <= b < mc_dump):
            raise ValueError(f"ballast bid {b} must satisfy MC_used {mc_used:.4f} <= bid < MC_dump {mc_dump:.4f}")
    return b, str(cfg.get("access_class", "public"))


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
    ballast_kwh: float = 0.0
    rejected: int = 0
    units_done: int = 0
    missed: int = 0
    transitions: int = 0


def simulate(profile: pd.DataFrame, a: dict, servers: int, policy: str, slack_h: float = 0.0, load: float = 0.0,
             seed: int = 0, a_hash: str = "", hourly: bool = True,
             ballast: bool = False, admission: bool = False) -> tuple[dict, pd.DataFrame | None]:
    """Run one year. ballast=True (merit only, #37) offers unlimited heat-backed filler work each hour at
    `ballast.bid_chf_per_server_h`, which must satisfy MC_used <= bid < MC_dump, so it runs only where its
    heat is used and never dumps; unassigned filler is dropped each hour (never queued, never missed).
    admission=True gates every arriving job with scheduler.admit (contract v2.2): persistence forecast of the
    last 24 h of heat-used capacity, net of queued work; rejected units never enter the queue and are not
    counted as missed. Both off by default (golden numbers unchanged). Defers the cyclic GC for the loop (8,760 decide() calls allocate many short-lived
    actions; refcounting still frees them) and restores its previous state. scheduler.decide() itself
    never touches GC (#21 review)."""
    was = gc.isenabled()
    gc.disable()
    try:
        return _simulate(profile, a, servers, policy, slack_h, load, seed, a_hash, hourly, ballast, admission)
    finally:
        if was:
            gc.enable()


def _simulate(profile: pd.DataFrame, a: dict, servers: int, policy: str, slack_h: float, load: float,
              seed: int, a_hash: str, hourly: bool, ballast: bool = False,
              admission: bool = False) -> tuple[dict, pd.DataFrame | None]:
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

    ballast_t = ballast_type(a)
    if load > 0 and ballast_t is None:
        raise ValueError("load > 0 needs a public interruptible job type in assumptions.yaml `jobs:`")
    bid = ballast_t.price_chf_per_h if ballast_t else 0.0
    job_class = ballast_t.name if ballast_t else "none"
    access = ballast_t.access_class if ballast_t else "public"

    params = Params.from_assumptions(a, policy=policy, slack_enabled=slack_h > 0)
    use_ballast = ballast and policy == "merit"
    b_bid, b_access = ballast_bid(a, check=use_ballast)
    units_per_server_h = int(round(1.0 / unit_h))
    far = 10 ** 9  # filler deadline: never forced, never missed

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
    history: list[float] = []  # heat-used electric capacity per past hour (admission forecast input)

    for h in range(H):
        # site state at the start of hour h (does not depend on this hour's arrivals)
        dem = space[h] + dhw[h]
        site = SiteState("house", h, space[h], lvl, cap, servers, kw, rec, p_el,
                         heat_value_chf_kwh(p_el, div, dem, lvl, high), frozenset({access}), None, False,
                         low, high, mode, dhw[h])
        # 1. arrivals (optionally gated by admission at submit)
        acc_units += rate
        fc = None
        while acc_units >= 1.0 - 1e-12:
            u = Unit(f"u{k}", f"j{k}", job_class, access, unit_kwh, bid, h + slack_int + 1, slack_h, True)
            k += 1
            acc_units -= 1.0
            if admission:
                if fc is None:
                    fc = net_of_backlog(persistence_forecast(history, slack_int + 2), sum(q.kwh_el for q in queue))
                if not admit([u], [site], h, {"house": fc}, params).accepted:
                    t.rejected += 1
                    continue
                fc = net_of_backlog(fc, u.kwh_el)
            queue.append(u)
        history.append(used_capacity_kwh_el(site))
        # 3. decide + apply
        offer = queue
        if use_ballast and servers > 0:
            filler = [Unit(f"b{h}_{i}", f"ballast{h}_{i}", "ballast", b_access, unit_kwh, b_bid, far, float(far), True)
                      for i in range(servers * units_per_server_h)]
            offer = queue + filler
            site = SiteState(site.site_id, site.hour_index, site.demand_kw, site.tank_level_kwh, site.tank_cap_kwh,
                             site.servers, site.server_kw_el, site.heat_recovery, site.p_el_chf_kwh,
                             site.heat_value_chf_kwh, site.eligible_classes | {b_access}, site.night_cap_kw,
                             site.has_dump, site.band_low_kwh, site.band_high_kwh, site.mode_running,
                             site.dhw_demand_kw)
        dec = decide([site], offer, h, params, seed=seed)
        on = next(x.servers_on for x in dec.actions if isinstance(x, SetPower))
        r = next(x for x in dec.actions if isinstance(x, Route))
        done = {x.unit_id for x in dec.actions if isinstance(x, Assign)}
        n_ballast = sum(1 for uid in done if uid[0] == "b")
        if n_ballast:
            t.ballast_kwh += n_ballast * unit_kwh
            done = {uid for uid in done if uid[0] != "b"}
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

    bal = _balance(a, servers, policy, slack_h, load, seed, a_hash, H, space, dhw, t, bid, unit_h, ballast_t is not None)
    paid_run_h = t.units_done * unit_h
    bal["ballast"] = use_ballast
    bal["paid_run_h"] = _r(paid_run_h, 3)
    # thermostat/always_on run servers without paid work: that is implicit ballast
    bal["ballast_run_h"] = _r(max(0.0, t.run_h - paid_run_h), 3)
    bal["ballast_income_chf"] = _r(max(0.0, t.run_h - paid_run_h) * b_bid, 3) if b_bid is not None else None
    bal["admission"] = admission
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
        "admitted_units": t.units_in - t.rejected,
        "rejected_units": t.rejected,
        "units_done": t.units_done,
        "missed_deadline_pct": _r(100.0 * t.missed / (t.units_in - t.rejected) if t.units_in - t.rejected else 0.0, 4),
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
