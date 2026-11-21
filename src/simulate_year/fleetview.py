"""fleetview (#119): OUR scheduler running a whole-city DigitalHeat fleet through Basel 2025.

    python -m simulate_year.fleetview [--houses 200] [--seed 0] [--servers N] [--out runs/fleetview] [--hours 8760]

ASSUMED (labelled in the output's "assumed" block and on the page): the fleet itself (how many houses, which
buildings, their size scaling and server counts, which sites are certified) and the job volume (the city's paid
stream = the reference paid load x the fleet's server capacity, a share of it certified). REAL: the weather (Basel
2025), the reference-house heat model and the algorithm: every hour ONE `scheduler.decide()` call over ALL sites
decides which house runs which unit (merit order: heat wanted first), what is deferred, held or dumped; the hourly
physics (routing, tank, backup heater) is applied per site exactly as `simulate_year.sim.simulate` does, so a fleet
of one reference house reproduces the yearview reference run (tested).

The baseline is the thermostat policy on the same fleet and the same job stream (no filler).
Output: schema fleetview-v1 (simulate_year/fleetview_schema.py), in <out>/<key>/, <out>/LATEST names the newest.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from common.config import ROOT, load_assumptions, validate_assumptions
from house_model.profile import DEFAULT_CSV, load_reference_profile
from scheduler import Assign, Params, Route, SetPower, SiteState, Unit, decide, heat_value_chf_kwh

from . import fleetview_schema as fs
from .analysis import REF_LOAD, REF_SLACK
from .sim import TOL, ConservationError, DecisionError, assumptions_hash, ballast_bid, ballast_type

MAP = ROOT / "src" / "dashboard" / "static" / "site" / "data" / "basel3d.json"
# ASSUMED fleet parameters (the page labels them; a real fleet would replace them with registry data)
DEFAULT_HOUSES = 200
SPACING_M = 60.0  # extra houses beyond the map's fleet: at least this far apart
SCALE_RANGE = (0.5, 3.0)  # house size vs the reference house (footprint ratio, clipped)
VARIATION = (0.85, 1.15)  # seeded per-house demand variation
REF_SERVERS = 3  # the yearview sizing rule's recommendation for the reference house (#95, X = 10 %)
MAX_SERVERS = 8
CERTIFIED_EVERY_SITE = 10  # every 10th house is a certified site
CERTIFIED_EVERY_UNIT = 10  # every 10th paid unit needs a certified site
TRACK_EVERY = 25  # jobs.json traces every 25th paid unit fully


def _ring_centroid(b: list[int], q: float) -> tuple[float, float]:
    x, y, sx, sy, n = b[2], b[3], 0.0, 0.0, 0
    sx, sy, n = x, y, 1
    for i in range(4, len(b) - 1, 2):
        x += b[i]
        y += b[i + 1]
        sx += x
        sy += y
        n += 1
    return sx / n * q, sy / n * q


def place_houses(k: int, seed: int, servers: int | None = None) -> list[dict]:
    """Reference house first, then the map's fleet, then more residential buildings (seeded, >= SPACING_M apart)."""
    m = json.loads(MAP.read_text(encoding="utf-8"))
    q, areas = m["q"], m["areas_m2"]
    cent = {}

    def c(i):
        if i not in cent:
            cent[i] = _ring_centroid(m["buildings"][i], q)
        return cent[i]
    order = [m["reference"], *m["fleet"]]
    taken = set(order) | set((m.get("live") or {}).values())
    pool = [i for i, b in enumerate(m["buildings"]) if b[1] == 1 and 90 <= areas[i] <= 400 and i not in taken]
    rng = random.Random(seed)
    rng.shuffle(pool)
    for i in pool:
        if len(order) >= k:
            break
        xi, yi = c(i)
        if all(math.hypot(xi - c(j)[0], yi - c(j)[1]) >= SPACING_M for j in order[-400:]):
            order.append(i)
    order = order[:k]
    dist = m.get("districts") or []
    vr = random.Random(seed + 1)
    ref_a = areas[m["reference"]]
    houses = []
    for hid, b in enumerate(order):
        scale = 1.0 if hid == 0 else max(SCALE_RANGE[0], min(SCALE_RANGE[1], areas[b] / ref_a)) * vr.uniform(*VARIATION)
        n = servers if servers is not None else max(1, min(MAX_SERVERS, round(REF_SERVERS * scale)))
        x, y = c(b)
        houses.append({"id": hid, "building": b, "x": round(x, 1), "y": round(y, 1), "footprint_m2": areas[b],
                       "scale": round(scale, 4), "servers": n, "tank_kwh": None,
                       "certified": hid > 0 and hid % CERTIFIED_EVERY_SITE == 0, "district": next(
                           (d["name"] for d in dist if hid in d.get("houses", [])), None)})
    return houses


def run_fleet(houses: list[dict], policy: str, ballast: bool, hours: int | None = None, seed: int = 0,
              load: float = REF_LOAD, slack_h: float = REF_SLACK, cert_every_unit: int = CERTIFIED_EVERY_UNIT,
              track_every: int = TRACK_EVERY) -> dict:
    """One policy over the whole fleet. Returns per-site arrays, fleet arrays, tracked jobs and totals."""
    a = load_assumptions()
    validate_assumptions(a)
    prof = load_reference_profile(assumptions=a)
    H = min(hours or len(prof), len(prof))
    space0, dhw0 = prof["space_heat_kw"].to_numpy(float)[:H], prof["hot_water_kw"].to_numpy(float)[:H]
    house, srv, price, sch = a["house"], a["server"], a["price"], a["scheduler"]
    p_el, div = float(price["chf_per_kwh"]), float(price["heat_value_divisor"])
    kw, rec = float(srv["electric_kw"]), float(srv["heat_recovery_fraction"])
    cap, low, high = float(house["tank_kwh"]), float(sch["tank_band_low_kwh"]), float(sch["tank_band_high_kwh"])
    unit_h = float(sch["unit_minutes"]) / 60.0
    unit_kwh = kw * unit_h
    bt = ballast_type(a)
    bid, job_class, access = bt.price_chf_per_h, bt.name, bt.access_class
    params = Params.from_assumptions(a, policy=policy, slack_enabled=slack_h > 0)
    use_ballast = ballast and policy == "merit"
    b_bid, b_access = ballast_bid(a, check=use_ballast)
    ups = math.ceil(1.0 / unit_h - 1e-9)
    far = 10 ** 9
    K = len(houses)
    sid = [f"h{h['id']}" for h in houses]
    idx = {s: i for i, s in enumerate(sid)}
    scale = np.array([h["scale"] for h in houses])
    nserv = [int(h["servers"]) for h in houses]
    classes = [frozenset({access} | ({"certified"} if h["certified"] else set())) for h in houses]
    rate = sum(nserv) * (1.0 / unit_h) * load
    acc = float(np.random.default_rng(seed).uniform(0.0, 1.0)) if rate > 0 else 0.0
    lvl, mode = np.zeros(K), [True] * K
    queue: list[Unit] = []
    k = 0
    F = {n: np.zeros((K, H)) for n, *_ in fs.FIELDS}
    fleet = {n: np.zeros(H) for n in fs.FLEET_KEYS}
    tracked: dict[str, dict] = {}
    tot = dict(used=0.0, dump=0.0, backup=0.0, run_h=0.0, done=0, missed=0, ballast_kwh=0.0, demand=0.0)
    net = 0.0
    was = gc.isenabled()
    gc.disable()
    try:
        for h in range(H):
            sites, offer, filler = [], list(queue), set()
            for i in range(K):
                sp, dw = space0[h] * scale[i], dhw0[h] * scale[i]
                hv = heat_value_chf_kwh(p_el, div, sp + dw, lvl[i], high)
                el = classes[i] | ({b_access} if use_ballast else frozenset())
                sites.append(SiteState(sid[i], h, sp, lvl[i], cap, nserv[i], kw, rec, p_el, hv, frozenset(el), None, False,
                                       low, high, mode[i], dw))
                F["mc_chf_per_server_h"][i, h] = p_el * kw - rec * kw * hv
                if use_ballast and nserv[i] > 0:
                    for j in range(nserv[i] * ups):
                        u = Unit(f"b{h}-{i}-{j}", f"b{h}-{i}-{j}", "ballast", b_access, unit_kwh, b_bid, far, float(far), True)
                        offer.append(u)
                        filler.add(u.unit_id)
            # arrivals: one shared paid stream for the city (same accumulator as simulate())
            acc += rate
            arrived = 0
            while acc >= 1.0 - 1e-12:
                cls = "certified" if cert_every_unit and k % cert_every_unit == cert_every_unit - 1 else access
                u = Unit(f"u{k}", f"j{k}", job_class, cls, unit_kwh, bid, h + int(math.ceil(slack_h)) + 1, slack_h, True)
                if track_every and k % track_every == 0:
                    tracked[u.unit_id] = {"job": u.job_id, "type": job_class, "class": cls, "bid": bid, "arrival_h": h,
                                          "deadline_h": u.deadline_hour, "slack_h": slack_h, "state": "queued",
                                          "units": [{"unit": u.unit_id, "runs": []}]}
                queue.append(u)
                offer.append(u)
                k += 1
                acc -= 1.0
                arrived += 1
            dec = decide(sites, offer, h, params, seed=seed)
            on = {x.site_id: x.servers_on for x in dec.actions if isinstance(x, SetPower)}
            route = {x.site_id: x for x in dec.actions if isinstance(x, Route)}
            done = {}
            for x in dec.actions:
                if isinstance(x, Assign):
                    done[x.unit_id] = x.site_id
            n_ball = sum(1 for u in done if u in filler)
            for u, s in done.items():
                if u in tracked:
                    tracked[u]["units"][0]["runs"].append([h, idx[s]])
                    tracked[u]["state"] = "done"
            hour_used = hour_dump = hour_back = 0.0
            for i in range(K):
                s = sid[i]
                o, r = on.get(s), route.get(s)
                if o is None or r is None:
                    raise DecisionError(f"hour {h}: decide() returned no SetPower/Route for {s}")
                produced = o * kw * rec
                if not abs(r.space_kwh + r.dhw_kwh + r.tank_kwh + r.dump_kwh - produced) < TOL:
                    raise ConservationError(f"hour {h} {s}: routed heat != produced heat")
                dem = sites[i].demand_kw + sites[i].dhw_demand_kw
                lvl[i] += r.tank_kwh
                unmet = dem - r.space_kwh - r.dhw_kwh
                draw = min(lvl[i], max(0.0, unmet))
                lvl[i] -= draw
                back = max(0.0, unmet - draw)
                used = r.space_kwh + r.dhw_kwh + r.tank_kwh
                was_mode = mode[i]
                mode[i] = dec.next_mode[s]
                F["servers_on"][i, h] = o
                F["heat_used_kwh"][i, h] = used
                F["unmet_kwh"][i, h] = back
                F["dumped_kwh"][i, h] = r.dump_kwh
                F["tank_kwh"][i, h] = lvl[i]
                F["state"][i, h] = (2 if r.dump_kwh > TOL else 1) if o > 0 else (3 if not mode[i] else 0)
                hour_used += used
                hour_dump += r.dump_kwh
                hour_back += back
                tot["demand"] += dem
                tot["run_h"] += o
                del was_mode
            queue = [u for u in queue if u.unit_id not in done]
            late = [u for u in queue if u.deadline_hour <= h]
            if late:
                for u in late:
                    if u.unit_id in tracked:
                        tracked[u.unit_id]["state"] = "missed"
                queue = [u for u in queue if u.deadline_hour > h]
            paid = len(done) - n_ball
            tot["used"] += hour_used
            tot["dump"] += hour_dump
            tot["backup"] += hour_back
            tot["done"] += paid
            tot["missed"] += len(late)
            tot["ballast_kwh"] += n_ball * unit_kwh
            hour_on = sum(on.values())
            net += hour_used * p_el / div + paid * unit_h * bid + (n_ball * unit_h * b_bid if use_ballast else 0.0) \
                - hour_on * kw * p_el
            for key, v in (("queue", len(queue)), ("arrivals", arrived), ("assigned", paid), ("deferred", len(queue)),
                           ("rejected", 0), ("missed", len(late)), ("ballast_units", n_ball),
                           ("paid_price_chf_per_server_h", bid), ("heat_used_kwh", hour_used), ("dumped_kwh", hour_dump),
                           ("unmet_kwh", hour_back), ("net_chf_cum", net)):
                fleet[key][h] = v
    finally:
        if was:
            gc.enable()
    elec = tot["run_h"] * kw * p_el
    heat_value = tot["used"] * p_el / div
    income = tot["done"] * unit_h * bid
    b_inc = tot["ballast_kwh"] / kw * b_bid if use_ballast else 0.0
    totals = {"coverage_pct": round(100 * (tot["demand"] - tot["backup"]) / tot["demand"], 4) if tot["demand"] else None,
              "heat_demand_kwh": round(tot["demand"], 3), "heat_used_kwh": round(tot["used"], 3),
              "dumped_kwh": round(tot["dump"], 3), "backup_kwh": round(tot["backup"], 3), "run_h": round(tot["run_h"], 3),
              "utilisation_pct": round(100 * tot["run_h"] / (sum(nserv) * H), 4) if sum(nserv) else None,
              "units_arrived": k, "units_done": tot["done"], "units_rejected": 0, "units_missed": tot["missed"],
              "missed_pct": round(100 * tot["missed"] / k, 4) if k else 0.0,
              "net_chf_excl_hardware": round(heat_value + income + b_inc - elec, 3)}
    for t in tracked.values():
        if t["state"] == "queued":
            t["state"] = "pending at year end"
    return {"F": F, "fleet": fleet, "tracked": list(tracked.values()), "totals": totals, "H": H, "cap": cap}


def _run(args):
    houses, policy, ballast, hours, seed = args
    return run_fleet(houses, policy, ballast, hours, seed)


def cache_key(houses: list[dict], hours: int, seed: int) -> str:
    code = hashlib.sha256()
    for d in ("simulate_year", "scheduler", "house_model"):
        for f in sorted((ROOT / "src" / d).glob("*.py")):
            code.update(f.name.encode() + f.read_bytes())
    blob = json.dumps({"schema": fs.SCHEMA, "a": assumptions_hash(), "map": hashlib.sha256(MAP.read_bytes()).hexdigest(),
                       "houses": houses, "hours": hours, "seed": seed, "code": code.hexdigest()}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def build(out: Path, k: int = DEFAULT_HOUSES, seed: int = 0, servers: int | None = None, hours: int | None = None,
          force: bool = False, log=print) -> Path:
    houses = place_houses(k, seed, servers)
    H = hours or 8760
    key = cache_key(houses, H, seed)
    d = out / key
    if not force and (d / "index.json").exists():
        log(f"fleetview: {d} complete for this key; reusing it")
        (out / "LATEST").write_text(key + "\n")
        return d
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=2) as ex:
        ours, base = ex.map(_run, [(houses, "merit", True, H, seed), (houses, "thermostat", False, H, seed)])
    a = load_assumptions()
    for h in houses:
        h["tank_kwh"] = ours["cap"]
        h["classes"] = sorted({"public"} | ({"certified"} if h.pop("certified") else set()))
    prov = {"key": key, "assumptions_hash": assumptions_hash(), "profile_sha256": hashlib.sha256(DEFAULT_CSV.read_bytes()).hexdigest(),
            "commit": None, "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "runtime_s": None}
    total_servers = sum(h["servers"] for h in houses)
    index = {"schema": fs.SCHEMA, "fixture": False, "provenance": prov,
             "assumed": {
                 "houses": f"ASSUMED: {len(houses)} houses: the reference house, the map's 48-house fleet, then seeded "
                           f"residential buildings >= {SPACING_M:g} m apart (OSM footprints 90-400 m2)",
                 "placement": "ASSUMED: real OSM residential buildings; no real household is implied",
                 "servers": f"ASSUMED: round({REF_SERVERS} x house scale), 1..{MAX_SERVERS} per house ({total_servers} in total); "
                            f"scale = footprint / reference footprint ({SCALE_RANGE[0]}-{SCALE_RANGE[1]}) x seeded {VARIATION}",
                 "access_classes": f"ASSUMED: every {CERTIFIED_EVERY_SITE}th house is a certified site; every "
                                   f"{CERTIFIED_EVERY_UNIT}th paid unit needs one",
                 "job_stream": f"ASSUMED: one city-wide paid stream = paid load {REF_LOAD} x the fleet's server capacity, "
                               f"slack {REF_SLACK:g} h, bid = {ballast_type(a).price_chf_per_h} CHF/server-h; heat-backed "
                               f"filler on (merit) as in the reference run",
                 "real": "REAL: Basel 2025 hourly weather, the reference-house heat model, scheduler.decide() over all sites "
                         "every hour"},
             "start": "2025-01-01T00:00:00+01:00", "tz": "Europe/Zurich", "step_h": 1, "hours": ours["H"],
             "houses": houses,
             "series": {"file": "houses.u16", "layout": "[field][house][hour]", "dtype": "uint16-le",
                        "fields": [{"name": n, "unit": u, "scale": s} for n, u, s in fs.FIELDS]},
             "fleet": {"file": "fleet.json"}, "jobs": {"file": "jobs.json", "tracked_every": TRACK_EVERY},
             "totals": {"ours": ours["totals"], "baseline": base["totals"]}}
    prov["runtime_s"] = round(time.time() - t0, 1)
    series = [[list(ours["F"][n][i]) for i in range(len(houses))] for n, *_ in fs.FIELDS]
    fleet = {k2: [round(float(v), 4) for v in ours["fleet"][k2]] for k2 in fs.FLEET_KEYS}
    fs.write(d, index, series, fleet, {"tracked": ours["tracked"]})
    (out / "LATEST").write_text(key + "\n")
    log(f"fleetview: {len(houses)} houses, {ours['H']} h, both policies in {prov['runtime_s']} s -> {d}")
    return d


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m simulate_year.fleetview", description=__doc__.splitlines()[0])
    ap.add_argument("--houses", type=int, default=DEFAULT_HOUSES)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--servers", type=int, default=None, help="fixed servers per house (default: sized per house)")
    ap.add_argument("--hours", type=int, default=None, help="simulate only the first H hours (testing)")
    ap.add_argument("--out", type=Path, default=ROOT / "runs" / "fleetview")
    ap.add_argument("--force", action="store_true")
    ns = ap.parse_args(argv)
    if not 1 <= ns.houses <= 2000:
        raise SystemExit("--houses must be in [1, 2000]")
    d = build(ns.out, ns.houses, ns.seed, ns.servers, ns.hours, ns.force)
    t = json.loads((d / "index.json").read_text())["totals"]
    for p in ("ours", "baseline"):
        x = t[p]
        print(f"{p:8} coverage {x['coverage_pct']} %, dumped {x['dumped_kwh']:.0f} kWh, missed {x['missed_pct']} %, "
              f"net {x['net_chf_excl_hardware']:.0f} CHF")
    return 0


if __name__ == "__main__":
    sys.exit(main())
