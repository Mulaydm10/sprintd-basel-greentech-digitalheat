"""#21 hardening: decide() rejects invalid input with scheduler.InvalidInput (red team F1-F6)."""
from __future__ import annotations

import dataclasses
import math
import time

import pytest

from common.config import load_assumptions
from scheduler import Assign, Hold, InvalidInput, Params, Refuse, SiteState, Unit, decide

A = load_assumptions()
P = Params.from_assumptions(A)
ALL = frozenset({"public", "swiss-only", "certified"})


def site(sid="S0", **kw) -> SiteState:
    h, s = A["house"], A["scheduler"]
    d = dict(site_id=sid, hour_index=0, demand_kw=h["design_kw"], tank_level_kwh=s["tank_band_low_kwh"],
             tank_cap_kwh=h["tank_kwh"], servers=4, server_kw_el=A["server"]["electric_kw"],
             heat_recovery=A["server"]["heat_recovery_fraction"], p_el_chf_kwh=A["price"]["chf_per_kwh"],
             heat_value_chf_kwh=A["price"]["chf_per_kwh"] / A["price"]["heat_value_divisor"], eligible_classes=ALL,
             night_cap_kw=None, has_dump=False, band_low_kwh=s["tank_band_low_kwh"],
             band_high_kwh=s["tank_band_high_kwh"], mode_running=True)
    d.update(kw)
    return SiteState(**d)


def unit(i=0, **kw) -> Unit:
    d = dict(unit_id=f"u{i:06d}", job_id=f"j{i}", job_class="t", access_class="public",
             kwh_el=A["server"]["electric_kw"] * A["scheduler"]["unit_minutes"] / 60,
             bid_chf_per_server_h=2 * A["price"]["chf_per_kwh"], deadline_hour=48, slack_h=0.0, checkpointable=True)
    d.update(kw)
    return Unit(**d)


def test_invalid_input_is_a_value_error():
    assert issubclass(InvalidInput, ValueError)


@pytest.mark.parametrize("kw", [dict(kwh_el=-1.0), dict(kwh_el=0.0), dict(kwh_el=math.nan), dict(kwh_el=math.inf),
                                dict(bid_chf_per_server_h=math.nan), dict(slack_h=math.nan), dict(slack_h=-1.0)])
def test_bad_unit_rejected(kw):
    with pytest.raises(InvalidInput, match="u000000"):
        decide([site()], [unit(**kw)], 0, P)


def test_inf_bid_is_allowed():
    d = decide([site()], [unit(bid_chf_per_server_h=math.inf)], 0, P)
    assert d.of(Assign)


def test_duplicate_unit_ids_rejected_not_deduped():
    with pytest.raises(InvalidInput, match="duplicate unit_id"):
        decide([site()], [unit(0), unit(0, job_id="other")], 0, P)


@pytest.mark.parametrize("kw", [
    dict(server_kw_el=0.0), dict(server_kw_el=-1.0), dict(server_kw_el=math.nan),
    dict(heat_recovery=1.5), dict(heat_recovery=-0.1), dict(heat_recovery=math.nan),
    dict(band_low_kwh=20.0, band_high_kwh=10.0), dict(servers=-1), dict(servers=2.5),
    dict(demand_kw=math.nan), dict(demand_kw=-1.0), dict(tank_level_kwh=math.inf), dict(tank_cap_kwh=-1.0),
    dict(p_el_chf_kwh=math.nan), dict(heat_value_chf_kwh=math.inf), dict(night_cap_kw=-1.0),
])
def test_bad_site_rejected(kw):
    with pytest.raises(InvalidInput, match="S0"):
        decide([site(**kw)], [unit()], 0, P)


def test_duplicate_site_ids_rejected():
    with pytest.raises(InvalidInput, match="duplicate site_id"):
        decide([site("A"), site("A")], [], 0, P)


def test_bad_params_rejected():
    with pytest.raises(InvalidInput):
        decide([site()], [], 0, dataclasses.replace(P, deadline_safety_h=math.nan))


@pytest.mark.parametrize("policy", ["merit", "thermostat", "always_on"])
def test_validation_applies_to_every_policy(policy):
    with pytest.raises(InvalidInput):
        decide([site()], [unit(kwh_el=-1.0)], 0, dataclasses.replace(P, policy=policy))


def test_tank_above_cap_is_tolerated_not_rejected():
    # a sensor can overshoot; routing must just not add to the tank (red team survived-attack)
    from scheduler import Route
    d = decide([site(tank_level_kwh=A["house"]["tank_kwh"] + 5)], [unit()], 0, P, )
    assert all(r.tank_kwh == 0 for r in d.of(Route))
    assert d.next_mode["S0"] is False  # above band_high -> idle, by hysteresis


# ------------------------------------------------------------------ scaling behaviour
def test_exhausted_class_units_held_without_per_site_refusals():
    """After capacity is used up, remaining units are held in O(1): no Refuse spam, one aggregated trace line."""
    sites = [site("pub", eligible_classes=frozenset({"public"})), site("all")]
    q = [unit(i, access_class="swiss-only") for i in range(500)]
    d = decide(sites, q, 0, P)
    per_server_h = round(1 / (A["scheduler"]["unit_minutes"] / 60))
    assert len(d.of(Assign)) == 4 * per_server_h  # "all" site: 4 servers
    refused_units = {r.unit_id for r in d.of(Refuse)}
    assert len(refused_units) <= 4 * per_server_h + 1  # only units actually considered
    assert len(d.of(Hold)) == 500 - 4 * per_server_h
    assert any("unit(s) of class swiss-only: no capacity" in t for t in d.trace)


def test_ordering_still_deadline_first_after_refactor():
    q = [unit(i, deadline_hour=100 - i) for i in range(40)]
    d = decide([site(servers=1)], q, 0, P)
    got = {a.unit_id for a in d.of(Assign)}
    expected = {f"u{i:06d}" for i in range(36, 40)}  # latest index = earliest deadline
    assert got == expected


# ------------------------------------------------------------------ performance (F7): generous bound; strict 50 ms is opt-in in tests/redteam (SCHEDULER_PERF=1)
GENEROUS_S = 1.0


@pytest.mark.parametrize("policy", ["merit", "thermostat", "always_on"])
def test_100k_units_50_sites_generous_bound(policy):
    sites = [site(f"S{i:02d}") for i in range(50)]
    q = [unit(i) for i in range(100_000)]
    p: Params = dataclasses.replace(P, policy=policy)
    t = time.perf_counter()
    d = decide(sites, q, 0, p)
    dt = time.perf_counter() - t
    assert dt < GENEROUS_S, f"{dt * 1000:.0f} ms"
    assert len(d.actions) >= 100_000


def test_mixed_classes_scale_without_refusal_explosion():
    sites = [site(f"S{i:02d}", eligible_classes=frozenset({"public"}) if i % 2 else frozenset({"public", "swiss-only", "certified"}))
             for i in range(50)]
    q = [unit(i, access_class=("public", "swiss-only", "certified")[i % 3]) for i in range(100_000)]
    t = time.perf_counter()
    d = decide(sites, q, 0, P)
    assert time.perf_counter() - t < 2 * GENEROUS_S
    assert len(d.actions) < 200_000  # was ~1.77M before refusals stopped after exhaustion


def test_gc_state_restored_even_on_error():
    import gc
    assert gc.isenabled()
    big = [unit(i) for i in range(10_000)] + [unit(10_000, kwh_el=-1.0)]
    with pytest.raises(InvalidInput):  # validation raises before the pause
        decide([site()], big, 0, P)
    decide([site()], [unit(i) for i in range(10_001)], 0, P)
    assert gc.isenabled()
