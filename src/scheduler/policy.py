"""Heat-aware scheduling policy, contract v2 (contracts/src/scheduler.md).

Pure: no I/O, no clocks, no process control; randomness only from the passed seed.
One function, three policies (merit / thermostat / always_on) over the same types, so an A/B
comparison runs one job stream. The simulator (#7) and the live agent (#8) both call decide().

#21 hardening: decide() validates its input (raises InvalidInput) and runs in O(U log U + U·B_c + S),
where B_c is the number of capacity blocks eligible for a unit's access class: sites and blocks are
indexed once per tick per access class, exhausted blocks are skipped by a moving pointer, and once a
class has no capacity left its remaining units are held in O(1) each (one aggregated trace line).
decide() touches no process-global state (it runs inside #8's threaded server); callers that run many
big ticks may defer the cyclic GC around their own loop (simulate_year does).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .actions import Action, Assign, Decision, Hold, Refuse, Route, SetPower
from .types import Params, SiteState, Unit
from .validate import validate_params, validate_queue, validate_sites

STEP_H = 1.0  # decide() is one tick = one hour (definition of the tick, not an assumption)
EPS = 1e-9  # float tolerance

USED, DUMP = 0, 1  # block kinds; used heat sorts before dump at equal MC

R_NO_ELIGIBLE = "no eligible site"
R_NOT_ELIGIBLE = "access_class not eligible at site"
R_WAIT_HEAT = "waiting for heat demand"
R_BID = "bid below marginal cost"
R_IDLE = "site idle (hysteresis)"
R_NO_CAP = "no capacity"
R_THERMO = "thermostat: no heat demand"


# ---------------------------------------------------------------- pricing (rule 2)
def mc_used(s: SiteState) -> float:
    """CHF per server-hour when the heat is used."""
    return s.p_el_chf_kwh * s.server_kw_el - s.heat_recovery * s.server_kw_el * s.heat_value_chf_kwh


def mc_dump(s: SiteState) -> float:
    """CHF per server-hour when the heat is dumped."""
    return s.p_el_chf_kwh * s.server_kw_el


def max_servers(s: SiteState) -> float:
    """Server count allowed this tick (rule 7: night cap)."""
    m = float(s.servers)
    if s.night_cap_kw is not None:
        m = min(m, max(0.0, s.night_cap_kw / s.server_kw_el))
    return m


def used_capacity_kwh_el(s: SiteState) -> float:
    """Electric kWh whose heat can be used this tick (demand + hot water + tank room)."""
    max_el = max_servers(s) * s.server_kw_el * STEP_H
    if s.heat_recovery <= 0:
        return 0.0
    return min(max_el, s.heat_room_kwh(STEP_H) / s.heat_recovery)


# ---------------------------------------------------------------- hysteresis (rule 5)
def next_mode_hysteresis(s: SiteState) -> bool:
    """Rule 5 (contract v2.3): running -> idle at tank >= band_high; idle -> running at tank <= band_low,
    OR when space heat is wanted (demand_kw > 0) and the tank is below band_high (wake on space demand, #44).
    One evaluation per tick, so at most one transition per site per hour."""
    if s.mode_running and s.tank_level_kwh >= s.band_high_kwh:
        return False
    if not s.mode_running and (s.tank_level_kwh <= s.band_low_kwh
                               or (s.demand_kw > 0 and s.tank_level_kwh < s.band_high_kwh)):
        return True
    return s.mode_running


# ---------------------------------------------------------------- routing (rule 6)
def route(s: SiteState, servers_on: float) -> Route:
    heat = servers_on * s.server_kw_el * STEP_H * s.heat_recovery
    space = min(heat, max(0.0, s.demand_kw) * STEP_H)
    dhw = min(heat - space, max(0.0, s.dhw_demand_kw) * STEP_H)
    tank = min(heat - space - dhw, s.tank_room_kwh)
    dump = heat - space - dhw - tank
    return Route(s.site_id, space, dhw, tank, max(0.0, dump))


# ---------------------------------------------------------------- per-tick indices
@dataclass
class _Block:
    mc: float
    kind: int
    site_id: str
    tie: float
    rem_kwh_el: float

    def key(self) -> tuple:
        return (self.mc, self.kind, self.site_id, self.tie)


@dataclass
class _ClassIndex:
    """Everything one access class needs, built once per tick on first use."""
    elig: list[SiteState]
    inelig: list[SiteState]
    blocks: list  # merit: _Block in merit order; baselines: [site_id, remaining_kwh] in site order
    slowest_kw: float = 0.0
    start: int = 0  # first block that may still have capacity
    exhausted: bool = False
    held_no_cap: int = field(default=0)


def _class_index(c: str, sites: list[SiteState], blocks: list) -> _ClassIndex:
    elig = [s for s in sites if c in s.eligible_classes]
    ids = {s.site_id for s in elig}
    return _ClassIndex(
        elig=elig,
        inelig=[s for s in sites if c not in s.eligible_classes],
        blocks=[b for b in blocks if (b.site_id if isinstance(b, _Block) else b[0]) in ids],
        slowest_kw=min((s.server_kw_el for s in elig), default=0.0),
    )


def _order_units(queue: list[Unit]) -> list[Unit]:
    # unit_ids are unique (validated), so this key is a total order: input order never matters.
    return sorted(queue, key=lambda u: (u.deadline_hour, -u.bid_chf_per_server_h, u.unit_id))


def _refuse(u: Unit, ci: _ClassIndex, actions: list[Action], trace: list[str]) -> None:
    for s in ci.inelig:
        actions.append(Refuse(u.unit_id, s.site_id, R_NOT_ELIGIBLE))
        trace.append(f"refuse {u.unit_id} at {s.site_id}: {u.access_class} not in {sorted(s.eligible_classes)}")


def _aggregate_no_cap(index: dict[str, _ClassIndex], trace: list[str]) -> None:
    for c in sorted(index):
        n = index[c].held_no_cap
        if n:
            trace.append(f"hold {n} unit(s) of class {c}: {R_NO_CAP} (all eligible capacity used)")


def _finish(
    sites: list[SiteState],
    servers_on: dict[str, float],
    unit_actions: list[Action],
    next_mode: dict[str, bool],
    trace: list[str],
) -> Decision:
    actions: list[Action] = [SetPower(s.site_id, servers_on[s.site_id]) for s in sites]
    actions += unit_actions
    for s in sites:
        r = route(s, servers_on[s.site_id])
        actions.append(r)
        if r.dump_kwh > EPS:
            trace.append(f"{s.site_id}: dump {r.dump_kwh:.3f} kWh heat (has_dump={s.has_dump})")
        if max_servers(s) < s.servers - EPS:
            trace.append(f"{s.site_id}: night cap {s.night_cap_kw} kW limits to {max_servers(s):.2f} servers")
    return Decision(actions=actions, next_mode=next_mode, trace=trace)


# ---------------------------------------------------------------- policies
def _decide_merit(sites: list[SiteState], queue: list[Unit], hour: int, p: Params, rng: random.Random) -> Decision:
    trace: list[str] = []
    next_mode: dict[str, bool] = {}
    for s in sites:
        nm = next_mode_hysteresis(s)
        next_mode[s.site_id] = nm
        if nm != s.mode_running:
            band = f"band_high {s.band_high_kwh}" if not nm else f"band_low {s.band_low_kwh}"
            trace.append(f"{s.site_id}: tank {s.tank_level_kwh:.2f} kWh crosses {band} -> {'running' if nm else 'idle'}")

    blocks: list[_Block] = []
    for s in sites:
        max_el = max_servers(s) * s.server_kw_el * STEP_H
        used = used_capacity_kwh_el(s)
        blocks.append(_Block(mc_used(s), USED, s.site_id, rng.random(), used))
        blocks.append(_Block(mc_dump(s), DUMP, s.site_id, rng.random(), max(0.0, max_el - used)))
    blocks.sort(key=_Block.key)

    job_kwh: dict[str, float] | None = None  # built lazily: only deadline forcing needs it

    def is_forced(u: Unit, ci: _ClassIndex) -> bool:
        nonlocal job_kwh
        if job_kwh is None:
            job_kwh = {}
            for q in queue:
                job_kwh[q.job_id] = job_kwh.get(q.job_id, 0.0) + q.kwh_el
        return hour + job_kwh[u.job_id] / ci.slowest_kw >= u.deadline_hour - p.deadline_safety_h

    index: dict[str, _ClassIndex] = {}
    site_el = {s.site_id: 0.0 for s in sites}
    unit_actions: list[Action] = []
    append = unit_actions.append
    for u in _order_units(queue):
        ci = index.get(u.access_class)
        if ci is None:
            ci = index[u.access_class] = _class_index(u.access_class, sites, blocks)
        if ci.exhausted:  # not considered against any site any more: no Refuse, O(1)
            append(Hold(u.unit_id, R_NO_CAP))
            ci.held_no_cap += 1
            continue
        if ci.inelig:
            _refuse(u, ci, unit_actions, trace)
        if not ci.elig:
            append(Hold(u.unit_id, R_NO_ELIGIBLE))
            trace.append(f"hold {u.unit_id}: {R_NO_ELIGIBLE}")
            continue

        bl = ci.blocks
        while ci.start < len(bl) and bl[ci.start].rem_kwh_el <= EPS:
            ci.start += 1
        if ci.start >= len(bl):
            ci.exhausted = True
            append(Hold(u.unit_id, R_NO_CAP))
            ci.held_no_cap += 1
            continue

        need = u.kwh_el - EPS
        forced: bool | None = None
        best = None
        fits_any = False
        for i in range(ci.start, len(bl)):
            b = bl[i]
            if b.rem_kwh_el < need:
                continue
            fits_any = True
            if next_mode[b.site_id]:
                best = b
                break
            if forced is None:
                forced = is_forced(u, ci)
            if forced:
                best = b
                break
        if best is None:
            reason = R_IDLE if fits_any else R_NO_CAP
            append(Hold(u.unit_id, reason))
            trace.append(f"hold {u.unit_id}: {reason}")
            continue
        if u.bid_chf_per_server_h < best.mc - EPS:
            append(Hold(u.unit_id, R_BID))
            trace.append(f"hold {u.unit_id}: bid {u.bid_chf_per_server_h:.4f} < MC {best.mc:.4f} at {best.site_id}")
            continue
        if p.slack_enabled and u.slack_h > 0 and best.kind == DUMP:
            if forced is None:
                forced = is_forced(u, ci)
            if not forced:
                append(Hold(u.unit_id, R_WAIT_HEAT))
                trace.append(f"hold {u.unit_id}: {R_WAIT_HEAT} (slack {u.slack_h} h, deadline h{u.deadline_hour})")
                continue
        best.rem_kwh_el -= u.kwh_el
        site_el[best.site_id] += u.kwh_el
        append(Assign(u.unit_id, best.site_id))
        why = "heat used" if best.kind == USED else "heat dumped"
        if forced and (best.kind == DUMP or not next_mode[best.site_id]):
            why += ", deadline forces run"
        trace.append(f"assign {u.unit_id} -> {best.site_id} ({why}, MC {best.mc:.4f} <= bid {u.bid_chf_per_server_h:.4f})")

    _aggregate_no_cap(index, trace)
    servers_on = {s.site_id: site_el[s.site_id] / (s.server_kw_el * STEP_H) for s in sites}
    return _finish(sites, servers_on, unit_actions, next_mode, trace)


def _decide_fixed_capacity(
    sites: list[SiteState], queue: list[Unit], capacity_el: dict[str, float], hold_reason: str
) -> tuple[list[Action], list[str]]:
    """Baselines: fill given electric capacity in deadline order, ignoring bids and slack."""
    trace: list[str] = []
    cells = [[s.site_id, capacity_el[s.site_id]] for s in sites]  # shared, mutable remaining capacity
    index: dict[str, _ClassIndex] = {}
    unit_actions: list[Action] = []
    append = unit_actions.append
    for u in _order_units(queue):
        ci = index.get(u.access_class)
        if ci is None:
            ci = index[u.access_class] = _class_index(u.access_class, sites, cells)
        if ci.exhausted:  # not considered against any site any more: no Refuse, O(1)
            append(Hold(u.unit_id, hold_reason))
            ci.held_no_cap += 1
            continue
        if ci.inelig:
            _refuse(u, ci, unit_actions, trace)
        if not ci.elig:
            append(Hold(u.unit_id, R_NO_ELIGIBLE))
            trace.append(f"hold {u.unit_id}: {R_NO_ELIGIBLE}")
            continue
        cl = ci.blocks
        while ci.start < len(cl) and cl[ci.start][1] <= EPS:
            ci.start += 1
        if ci.start >= len(cl):
            ci.exhausted = True
            append(Hold(u.unit_id, hold_reason))
            ci.held_no_cap += 1
            continue
        need = u.kwh_el - EPS
        cell = next((c for c in cl[ci.start:] if c[1] >= need), None)
        if cell is None:
            append(Hold(u.unit_id, hold_reason))
            trace.append(f"hold {u.unit_id}: {hold_reason}")
            continue
        cell[1] -= u.kwh_el
        append(Assign(u.unit_id, cell[0]))
        trace.append(f"assign {u.unit_id} -> {cell[0]}")
    for c in sorted(index):
        if index[c].held_no_cap:
            trace.append(f"hold {index[c].held_no_cap} unit(s) of class {c}: {hold_reason} (all eligible capacity used)")
    return unit_actions, trace


def _decide_thermostat(sites: list[SiteState], queue: list[Unit]) -> Decision:
    """Old `follow`: servers run exactly as much as heat is wanted (demand + tank room)."""
    cap = {s.site_id: used_capacity_kwh_el(s) for s in sites}
    unit_actions, trace = _decide_fixed_capacity(sites, queue, cap, R_THERMO)
    servers_on = {s.site_id: cap[s.site_id] / (s.server_kw_el * STEP_H) for s in sites}
    next_mode = {s.site_id: s.heat_room_kwh(STEP_H) > EPS for s in sites}
    return _finish(sites, servers_on, unit_actions, next_mode, trace)


def _decide_always_on(sites: list[SiteState], queue: list[Unit]) -> Decision:
    """All servers every hour (night cap still applies)."""
    cap = {s.site_id: max_servers(s) * s.server_kw_el * STEP_H for s in sites}
    unit_actions, trace = _decide_fixed_capacity(sites, queue, cap, R_NO_CAP)
    servers_on = {s.site_id: max_servers(s) for s in sites}
    next_mode = {s.site_id: True for s in sites}
    return _finish(sites, servers_on, unit_actions, next_mode, trace)


def decide(sites: list[SiteState], queue: list[Unit], hour: int, params: Params, seed: int = 0) -> Decision:
    """One tick. Raises InvalidInput on bad input. Same inputs + seed -> identical Decision,
    independent of input list order."""
    validate_params(params)
    validate_sites(sites)
    validate_queue(queue)
    sites = sorted(sites, key=lambda s: s.site_id)
    if params.policy == "thermostat":
        return _decide_thermostat(sites, queue)
    if params.policy == "always_on":
        return _decide_always_on(sites, queue)
    return _decide_merit(sites, queue, hour, params, random.Random(seed))
