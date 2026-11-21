"""Contract v2 tests for scheduler.decide (contracts/src/scheduler.md). One test per rule + extras.

All numbers come from data/assumptions.yaml (loaded once via common.config, the single source of
truth); bids are expressed relative to the computed marginal costs, never as magic constants.
"""
from __future__ import annotations

import dataclasses

import pytest

from common.config import load_assumptions
from scheduler import Assign, Hold, Params, Refuse, Route, SetPower, SiteState, Unit, decide, heat_value_chf_kwh
from scheduler.policy import R_BID, R_IDLE, R_NO_ELIGIBLE, R_WAIT_HEAT, mc_dump, mc_used

A = load_assumptions()
P_EL = A["price"]["chf_per_kwh"]
DIV = A["price"]["heat_value_divisor"]
KW = A["server"]["electric_kw"]
ETA = A["server"]["heat_recovery_fraction"]
TANK = A["house"]["tank_kwh"]
LOW = A["scheduler"]["tank_band_low_kwh"]
HIGH = A["scheduler"]["tank_band_high_kwh"]
UNIT_KWH = KW * A["scheduler"]["unit_minutes"] / 60
UNITS_PER_SERVER_H = round(KW / UNIT_KWH)
DESIGN_KW = A["house"]["design_kw"]
SAFETY = A["scheduler"]["deadline_safety_h"]
HOUR = 4000  # arbitrary tick index


def merit(**kw) -> Params:
    return dataclasses.replace(Params.from_assumptions(A, policy="merit"), **kw)


def site(site_id="A", demand_kw=0.0, tank=LOW, running=True, servers=1, classes=("public",), night_cap_kw=None,
         high=HIGH, **kw) -> SiteState:
    return SiteState(
        site_id=site_id, hour_index=HOUR, demand_kw=demand_kw, tank_level_kwh=tank, tank_cap_kwh=TANK,
        servers=servers, server_kw_el=KW, heat_recovery=ETA, p_el_chf_kwh=P_EL,
        heat_value_chf_kwh=heat_value_chf_kwh(P_EL, DIV, demand_kw, tank, high),
        eligible_classes=frozenset(classes), night_cap_kw=night_cap_kw, has_dump=False,
        band_low_kwh=LOW, band_high_kwh=high, mode_running=running, **kw,
    )


def high_bid() -> float:
    return 2 * P_EL * KW  # clears even MC_dump


def unit(uid, job="j1", access="public", bid=None, deadline=HOUR + 24 * 7, slack=0.0, kwh=UNIT_KWH) -> Unit:
    return Unit(uid, job, "batch", access, kwh, high_bid() if bid is None else bid, deadline, slack, True)


def units(n, prefix="u", **kw) -> list[Unit]:
    return [unit(f"{prefix}{i:03d}", **kw) for i in range(n)]


def assigned(d) -> dict[str, str]:
    return {a.unit_id: a.site_id for a in d.of(Assign)}


def holds(d) -> dict[str, str]:
    return {a.unit_id: a.reason for a in d.of(Hold)}


def routes(d) -> dict[str, Route]:
    return {r.site_id: r for r in d.of(Route)}


def power(d) -> dict[str, float]:
    return {a.site_id: a.servers_on for a in d.of(SetPower)}


# ------------------------------------------------------------------ rule 1: eligibility
def test_rule1_certified_unit_refused_on_public_only_site():
    d = decide([site(classes=("public",))], [unit("c1", access="certified")], HOUR, merit())
    assert Refuse("c1", "A", d.of(Refuse)[0].reason) in d.of(Refuse)
    assert "c1" not in assigned(d)
    assert holds(d)["c1"] == R_NO_ELIGIBLE


def test_rule1_refuse_once_per_unit_site_and_goes_to_eligible_site():
    sites = [site("A", demand_kw=DESIGN_KW, classes=("public",)),
             site("B", demand_kw=DESIGN_KW, classes=("public", "certified"))]
    d = decide(sites, [unit("c1", access="certified")], HOUR, merit())
    assert assigned(d) == {"c1": "B"}
    assert [(r.unit_id, r.site_id) for r in d.of(Refuse)] == [("c1", "A")]


# ------------------------------------------------------------------ rule 2: marginal cost
def test_rule2_marginal_costs():
    s = site(demand_kw=DESIGN_KW)
    hv = P_EL / DIV
    assert mc_dump(s) == pytest.approx(P_EL * KW)
    assert mc_used(s) == pytest.approx(P_EL * KW - ETA * KW * hv)
    assert mc_used(s) < mc_dump(s)
    no_heat = site(demand_kw=0.0, tank=TANK)
    assert no_heat.heat_value_chf_kwh == 0.0
    assert mc_used(no_heat) == pytest.approx(mc_dump(no_heat))


# Sliver-of-room scenarios set band_high = tank cap: with the default band (33 of 35 kWh) a running
# site always has >2 kWh room, so a 1 kW server cannot dump within one hour.

# ------------------------------------------------------------------ rule 3: merit order
def test_rule3_prefers_site_with_heat_demand():
    sites = [site("A", demand_kw=0.0, tank=HIGH - 1.0), site("B", demand_kw=DESIGN_KW)]
    # A only has a little tank room; B has full demand -> B is the cheaper (used) block first.
    d = decide(sites, units(2), HOUR, merit())
    assert set(assigned(d).values()) <= {"A", "B"}
    assert all(r.dump_kwh == pytest.approx(0.0) for r in d.of(Route))


def test_rule3_bid_must_clear_mc():
    s = site(demand_kw=0.0, tank=TANK - ETA * UNIT_KWH, high=TANK)  # room for exactly one unit of used heat
    mid = (mc_used(s) + mc_dump(s)) / 2  # clears MC_used, not MC_dump
    q = units(2, bid=mid)
    d = decide([s], q, HOUR, merit(slack_enabled=False))
    assert assigned(d) == {"u000": "A"}
    assert holds(d)["u001"] == R_BID


def test_rule3_earliest_deadline_gets_cheap_capacity_first():
    s = site(demand_kw=0.0, tank=TANK - ETA * UNIT_KWH, high=TANK)
    mid = (mc_used(s) + mc_dump(s)) / 2
    late = unit("a_late", bid=mid, deadline=HOUR + 100)
    early = unit("z_early", bid=mid, deadline=HOUR + 50)
    d = decide([s], [late, early], HOUR, merit())
    assert assigned(d) == {"z_early": "A"}


# ------------------------------------------------------------------ rule 4: slack as storage
def test_rule4_july_day_holds_deferrable_units_instead_of_dumping():
    s = site(demand_kw=0.0, tank=TANK - ETA * UNIT_KWH, high=TANK)  # summer: only a sliver of tank room
    q = units(UNITS_PER_SERVER_H, slack=24.0)
    d = decide([s], q, HOUR, merit())
    assert len(assigned(d)) == 1
    assert all(r == R_WAIT_HEAT for r in holds(d).values()) and len(holds(d)) == UNITS_PER_SERVER_H - 1
    assert routes(d)["A"].dump_kwh == pytest.approx(0.0)
    assert any(R_WAIT_HEAT in t for t in d.trace)


def test_rule4_without_slack_the_same_day_dumps():
    s = site(demand_kw=0.0, tank=TANK - ETA * UNIT_KWH, high=TANK)
    d = decide([s], units(UNITS_PER_SERVER_H, slack=24.0), HOUR, merit(slack_enabled=False))
    assert len(assigned(d)) == UNITS_PER_SERVER_H
    assert routes(d)["A"].dump_kwh > 0


def test_rule4_deadline_forces_run_even_when_dumping_and_idle():
    s = site(demand_kw=0.0, tank=TANK, running=False)  # July, full tank, idle
    urgent = unit("urgent", slack=24.0, deadline=HOUR + 1)
    relaxed = unit("relaxed", job="j2", slack=24.0, deadline=HOUR + 48)
    d = decide([s], [urgent, relaxed], HOUR, merit())
    assert assigned(d) == {"urgent": "A"}
    assert holds(d)["relaxed"] == R_IDLE
    assert routes(d)["A"].dump_kwh > 0
    assert any("deadline forces run" in t for t in d.trace)


def test_rule4_forcing_counts_remaining_work_of_the_whole_job():
    # 8 units of one job = 2 h of work; deadline in 2 h + safety -> must run now.
    s = site(demand_kw=0.0, tank=TANK, running=False)
    q = units(8, slack=24.0, deadline=HOUR + int(8 * UNIT_KWH / KW + SAFETY))
    d = decide([s], q, HOUR, merit())
    assert len(assigned(d)) == UNITS_PER_SERVER_H


# ------------------------------------------------------------------ rule 5: hysteresis
@pytest.mark.parametrize("running,tank,expected", [
    (True, HIGH, False), (True, (LOW + HIGH) / 2, True), (False, (LOW + HIGH) / 2, False), (False, LOW, True),
])
def test_rule5_hysteresis_band(running, tank, expected):
    d = decide([site(running=running, tank=tank)], [], HOUR, merit())
    assert d.next_mode["A"] is expected


def test_rule5_at_most_one_transition_per_hour_over_a_day():
    mode, tank, transitions = True, (LOW + HIGH) / 2, []
    for h in range(48):
        demand = DESIGN_KW / 4 if h % 24 < 12 else 0.0
        s = site(demand_kw=demand, tank=tank, running=mode)
        d = decide([s], units(UNITS_PER_SERVER_H, slack=0.0), h, merit())
        r = routes(d)["A"]
        transitions.append(int(d.next_mode["A"] != mode))
        mode = d.next_mode["A"]
        tank = min(TANK, max(0.0, tank + r.tank_kwh - max(0.0, demand - r.space_kwh)))
    assert max(transitions) <= 1
    assert sum(transitions) <= 4  # no flapping


def test_rule5_idle_site_holds_non_urgent_work():
    d = decide([site(running=False, tank=(LOW + HIGH) / 2, demand_kw=DESIGN_KW)], units(2), HOUR, merit())
    assert assigned(d) == {}
    assert set(holds(d).values()) == {R_IDLE}


# ------------------------------------------------------------------ rule 6: routing
@pytest.mark.parametrize("demand,dhw,tank", [
    (DESIGN_KW, 0.0, LOW), (ETA * KW / 2, 0.0, LOW), (ETA * KW / 4, ETA * KW / 4, LOW), (0.0, 0.0, TANK - 0.1),
])
def test_rule6_route_order_and_energy_conservation(demand, dhw, tank):
    s = site(demand_kw=demand, tank=tank, dhw_demand_kw=dhw)
    d = decide([s], units(UNITS_PER_SERVER_H), HOUR, merit(slack_enabled=False))
    r = routes(d)["A"]
    heat = power(d)["A"] * KW * ETA
    assert r.total_kwh == pytest.approx(heat, abs=1e-12)
    assert r.space_kwh == pytest.approx(min(heat, demand))
    assert r.dhw_kwh == pytest.approx(min(heat - r.space_kwh, dhw))
    assert r.tank_kwh <= TANK - tank + 1e-12
    assert min(r.space_kwh, r.dhw_kwh, r.tank_kwh, r.dump_kwh) >= 0


# ------------------------------------------------------------------ rule 7: night cap
def test_rule7_night_cap_limits_servers():
    s = site(servers=4, demand_kw=DESIGN_KW, night_cap_kw=2 * KW)
    d = decide([s], units(4 * UNITS_PER_SERVER_H), HOUR, merit())
    assert power(d)["A"] <= 2 + 1e-9
    assert len(assigned(d)) == 2 * UNITS_PER_SERVER_H
    ao = decide([s], [], HOUR, merit(policy="always_on"))
    assert power(ao)["A"] == pytest.approx(2)


# ------------------------------------------------------------------ rule 8: determinism
def test_rule8_deterministic_and_order_independent():
    sites = [site("A", demand_kw=DESIGN_KW), site("B", demand_kw=DESIGN_KW, classes=("public", "certified"))]
    q = units(6) + units(3, prefix="c", access="certified", slack=12.0)
    d1 = decide(sites, q, HOUR, merit(), seed=7)
    d2 = decide(list(reversed(sites)), list(reversed(q)), HOUR, merit(), seed=7)
    assert d1 == d2


# ------------------------------------------------------------------ issue #6 acceptance + baselines
def test_january_hour_all_units_run_no_dump():
    d = decide([site(demand_kw=DESIGN_KW, tank=LOW)], units(UNITS_PER_SERVER_H), HOUR, merit())
    assert len(assigned(d)) == UNITS_PER_SERVER_H
    assert power(d)["A"] == pytest.approx(1.0)
    assert routes(d)["A"].dump_kwh == pytest.approx(0.0)


def test_baselines_share_types_and_differ_in_july():
    s = site(demand_kw=0.0, tank=TANK, running=False)
    q = units(UNITS_PER_SERVER_H, slack=24.0)
    th = decide([s], q, HOUR, merit(policy="thermostat"))
    ao = decide([s], q, HOUR, merit(policy="always_on"))
    me = decide([s], q, HOUR, merit())
    assert power(th)["A"] == 0 and routes(th)["A"].dump_kwh == 0 and len(holds(th)) == UNITS_PER_SERVER_H
    assert power(ao)["A"] == 1 and routes(ao)["A"].dump_kwh == pytest.approx(KW * ETA)
    assert len(assigned(ao)) == UNITS_PER_SERVER_H
    assert power(me)["A"] == 0 and routes(me)["A"].dump_kwh == 0


def test_thermostat_runs_only_to_heat_room():
    s = site(demand_kw=ETA * KW / 2, tank=TANK)
    d = decide([s], units(UNITS_PER_SERVER_H), HOUR, merit(policy="thermostat"))
    assert power(d)["A"] == pytest.approx(0.5)
    assert routes(d)["A"].dump_kwh == pytest.approx(0.0)


def test_params_from_assumptions_and_bad_policy():
    p = Params.from_assumptions(A)
    assert p.eta_heat_used == A["scheduler"]["eta_heat_used"]
    assert p.deadline_safety_h == SAFETY
    with pytest.raises(ValueError):
        Params.from_assumptions(A, policy="follow")


def test_trace_explains_every_hold_and_assign():
    sites = [site("A", demand_kw=0.0, tank=TANK - ETA * UNIT_KWH, high=TANK)]
    d = decide(sites, units(3, slack=24.0) + [unit("c1", access="certified")], HOUR, merit())
    for uid in list(assigned(d)) + list(holds(d)):
        assert any(uid in t for t in d.trace), uid
