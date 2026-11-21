"""Red team (#17): attack merged code under production-like inputs. Lane: tests/redteam only, never src/.

Expected behaviour for every attack: correct handling OR a clear typed error (ValueError/TypeError).
Never a silent wrong number, a raw crash (ZeroDivisionError) or an eligibility violation.
Tests named ``test_finding_*`` FAIL on main at the time of writing: each one is a finding reported on #17.
The other tests are attacks the code already survives; they stay as regression guards.
"""
from __future__ import annotations

import math
import time
from dataclasses import replace

import pytest

from scheduler import decide
from scheduler.actions import Assign, Hold, Refuse, Route, SetPower
from scheduler.types import Params, SiteState, Unit

ALL = frozenset({"public", "swiss-only", "certified"})
MERIT = Params("merit", 0.9, True, 0.0, 1.0)
POLICIES = [MERIT, replace(MERIT, policy="thermostat"), replace(MERIT, policy="always_on")]
TYPED = (ValueError, TypeError)


def site(i: int = 0, **kw) -> SiteState:
    d = dict(site_id=f"S{i:02d}", hour_index=0, demand_kw=5.0, tank_level_kwh=10.0, tank_cap_kwh=35.0, servers=4,
             server_kw_el=1.0, heat_recovery=0.8, p_el_chf_kwh=0.3, heat_value_chf_kwh=0.12, eligible_classes=ALL,
             night_cap_kw=None, has_dump=True, band_low_kwh=5.0, band_high_kwh=30.0, mode_running=True)
    d.update(kw)
    return SiteState(**d)


def unit(i: int = 0, **kw) -> Unit:
    d = dict(unit_id=f"u{i:06d}", job_id=f"j{i // 4}", job_class="t", access_class="public", kwh_el=0.25,
             bid_chf_per_server_h=1.0, deadline_hour=48, slack_h=0.0, checkpointable=True)
    d.update(kw)
    return Unit(**d)


def rejects_or_holds(sites, queue, params=MERIT) -> bool:
    """True if decide() raises a typed error or holds every unit (no Assign)."""
    try:
        r = decide(sites, queue, 0, params)
    except TYPED:
        return True
    return not r.of(Assign)


# ============================================================ 3. adversarial jobs
def test_finding_negative_kwh_unit_yields_negative_power():
    """policy.py:174-182: kwh_el<0 is subtracted from capacity and divided into servers_on -> SetPower < 0."""
    try:
        r = decide([site()], [unit(kwh_el=-5.0)], 0, MERIT)
    except TYPED:
        return
    assert all(a.servers_on >= 0 for a in r.of(SetPower)), r.of(SetPower)
    assert all(rt.space_kwh >= 0 and rt.total_kwh >= 0 for rt in r.of(Route))


def test_finding_nan_bid_is_assigned():
    """policy.py:166: `bid < mc` is False for NaN, so a NaN-priced unit is scheduled (and billed as NaN)."""
    assert rejects_or_holds([site()], [unit(bid_chf_per_server_h=float("nan"))])


def test_nan_kwh_unit_is_not_assigned():
    assert rejects_or_holds([site()], [unit(kwh_el=float("nan"))])


def test_finding_duplicate_unit_ids_assigned_twice():
    """decide() accepts two units with the same unit_id and emits two Assigns for one id: ambiguous for the caller."""
    try:
        r = decide([site()], [unit(0), unit(0)], 0, MERIT)
    except TYPED:
        return
    ids = [a.unit_id for a in r.of(Assign)]
    assert len(ids) == len(set(ids)), ids


@pytest.mark.parametrize("p", POLICIES, ids=lambda p: p.policy)
def test_unknown_access_class_never_assigned(p):
    r = decide([site(0), site(1)], [unit(access_class="top-secret")], 0, p)
    assert not r.of(Assign)
    assert len(r.of(Refuse)) == 2


@pytest.mark.parametrize("p", POLICIES, ids=lambda p: p.policy)
def test_certified_unit_never_lands_on_public_only_site_even_with_inf_bid(p):
    sites = [site(0, eligible_classes=frozenset({"public"})), site(1, eligible_classes=frozenset({"public", "swiss-only"}))]
    r = decide(sites, [unit(access_class="certified", job_class="public-filler", bid_chf_per_server_h=float("inf"))], 0, p)
    assert not r.of(Assign)


def test_deadline_in_the_past_still_runs_when_capacity_exists():
    r = decide([site()], [unit(deadline_hour=-10, slack_h=5.0)], 0, MERIT)
    assert r.of(Assign)


def test_same_deadline_hour_for_all_units_respects_capacity():
    q = [unit(i, deadline_hour=3) for i in range(200)]  # 50 kWh asked, 4 kWh available
    r = decide([site()], q, 0, MERIT)
    on = r.of(SetPower)[0].servers_on
    assert on <= 4 + 1e-9 and len(r.of(Assign)) == 16


# ============================================================ 4. sites
def test_finding_heat_recovery_above_one_creates_energy():
    """types.py/policy.py:67: heat_recovery is not validated; 1.5 routes 1.5 kWh of heat from 1 kWh of electricity."""
    try:
        r = decide([site(heat_recovery=1.5)], [unit(kwh_el=1.0)], 0, MERIT)
    except TYPED:
        return
    el = sum(a.servers_on for a in r.of(SetPower)) * 1.0
    heat = sum(rt.total_kwh for rt in r.of(Route))
    assert heat <= el + 1e-9, f"{heat} kWh heat from {el} kWh electricity"


def test_finding_zero_server_kw_raises_raw_zero_division():
    """policy.py:44/155/182 divide by server_kw_el: 0 gives ZeroDivisionError instead of a typed input error."""
    try:
        decide([site(server_kw_el=0.0)], [unit()], 0, MERIT)
    except TYPED:
        return
    except ZeroDivisionError as e:
        pytest.fail(f"raw ZeroDivisionError: {e}")


def test_finding_inverted_band_flaps_every_tick():
    """policy.py:57-62: band_low > band_high is accepted; with the tank between them the mode flips every tick
    (running->idle->running), defeating the hysteresis the contract requires."""
    s = site(band_low_kwh=20.0, band_high_kwh=10.0, tank_level_kwh=15.0, mode_running=True)
    try:
        m1 = decide([s], [], 0, MERIT).next_mode[s.site_id]
    except TYPED:
        return
    m2 = decide([replace(s, mode_running=m1)], [], 1, MERIT).next_mode[s.site_id]
    assert m1 == m2, "mode flips every tick"


@pytest.mark.parametrize("p", POLICIES, ids=lambda p: p.policy)
def test_zero_servers_and_zero_night_cap_run_nothing(p):
    for s in (site(servers=0), site(night_cap_kw=0.0)):
        r = decide([s], [unit()], 0, p)
        assert not r.of(Assign) and r.of(SetPower)[0].servers_on == 0


@pytest.mark.parametrize("p", POLICIES, ids=lambda p: p.policy)
def test_empty_eligible_classes_assigns_nothing(p):
    assert not decide([site(eligible_classes=frozenset())], [unit()], 0, p).of(Assign)


def test_tank_over_capacity_on_input_does_not_route_into_tank():
    r = decide([site(tank_level_kwh=50.0)], [unit(kwh_el=1.0)], 0, MERIT)
    assert r.of(Route)[0].tank_kwh == 0


@pytest.mark.parametrize("p", POLICIES, ids=lambda p: p.policy)
def test_route_conserves_energy(p):
    q = [unit(i) for i in range(40)]
    for s in (site(), site(demand_kw=0.0, tank_level_kwh=35.0), site(demand_kw=50.0)):
        r = decide([s], q, 0, p)
        el = r.of(SetPower)[0].servers_on * s.server_kw_el
        assert math.isclose(r.of(Route)[0].total_kwh, el * s.heat_recovery, abs_tol=1e-9)


# ============================================================ 2. load
def test_finding_100k_queue_50_sites_misses_50ms_budget():
    """#17 budget: decide() < 50 ms/tick for 50 sites. policy.py:147-160 is O(units x sites) per tick
    (eligibility scan + block list comprehension per unit): ~3.7 s measured on parth-hp for 100k units."""
    sites = [site(i) for i in range(50)]
    q = [unit(i) for i in range(100_000)]
    t = time.perf_counter()
    decide(sites, q, 0, MERIT)
    dt = time.perf_counter() - t
    assert dt < 0.050, f"{dt * 1000:.0f} ms per tick"


def test_zero_jobs_is_fine():
    r = decide([site(i) for i in range(5)], [], 0, MERIT)
    assert not r.of(Assign) and all(a.servers_on == 0 for a in r.of(SetPower))


def test_decision_independent_of_input_order():
    q = [unit(i, deadline_hour=10 + i % 7, bid_chf_per_server_h=0.5 + (i % 3) / 10) for i in range(60)]
    s = [site(i, p_el_chf_kwh=0.2 + i / 100) for i in range(4)]
    a = decide(s, q, 0, MERIT, seed=3)
    b = decide(list(reversed(s)), list(reversed(q)), 0, MERIT, seed=3)
    assert a.actions == b.actions


# ============================================================ 1. data faults (house_model)
def _write_csv(path, temps):
    rows = ["time,temperature_2m,shortwave_radiation"]
    for h, t in enumerate(temps):
        d, hh = divmod(h, 24)
        rows.append(f"2025-01-{1 + d:02d}T{hh:02d}:00,{t},0")
    path.write_text("\n".join(rows) + "\n")


def _profile(path):
    from house_model.profile import load_reference_profile
    return load_reference_profile(path)


def test_finding_nan_temperature_gives_nan_demand_silently(tmp_path):
    """profile.py:60-67: one missing temperature becomes a NaN demand_kw row, no error; NaN then poisons
    every yearly sum downstream."""
    temps = [5.0] * 48
    temps[10] = "nan"
    p = tmp_path / "w.csv"
    _write_csv(p, temps)
    try:
        df = _profile(p)
    except TYPED:
        return
    assert not df["demand_kw"].isna().any(), "NaN demand passed through"


def test_finding_short_year_accepted_without_error(tmp_path):
    """profile.py:56-58 checks unique/monotonic only; a 48-row (or 8,759-row) file loads as if it were the year."""
    p = tmp_path / "w.csv"
    _write_csv(p, [5.0] * 48)
    try:
        df = _profile(p)
    except TYPED:
        return
    assert len(df) == 8760, f"{len(df)} rows accepted as a year"


def test_duplicate_hour_is_rejected(tmp_path):
    p = tmp_path / "w.csv"
    _write_csv(p, [5.0] * 24)
    lines = p.read_text().splitlines()
    p.write_text("\n".join(lines + [lines[5]]) + "\n")
    with pytest.raises(ValueError):
        _profile(p)


def test_temperature_extremes_give_sane_demand(tmp_path):
    p = tmp_path / "w.csv"
    _write_csv(p, [-30.0] * 24 + [45.0] * 24)
    df = _profile(p)
    d = df["demand_kw"].to_numpy()
    assert (d >= 0).all() and (d[:24] > d[24:]).all()


# ============================================================ 3b. adversarial catalogue entries (jobs)
def _jobtype(**kw):
    from jobs.catalogue import JobType
    d = dict(name="x", runtime_h=1.0, energy_kwh=1.0, interruptible=True, deadline_h=4.0, access_class="public",
             price_chf_per_h=0.5, source="test")
    d.update(kw)
    return JobType(**d)


@pytest.mark.parametrize("field,value", [("runtime_h", float("nan")), ("price_chf_per_h", float("nan")),
                                         ("deadline_h", float("nan")), ("price_chf_per_h", float("inf")),
                                         ("energy_kwh", float("nan"))])
def test_finding_nan_or_inf_jobtype_fields_pass_validation(field, value):
    """catalogue.py:30-33: comparisons with NaN are False, so NaN/inf slip through __post_init__."""
    with pytest.raises(ValueError):
        _jobtype(**{field: value})


def test_jobtype_rejects_unknown_class_and_negative_values():
    with pytest.raises(ValueError):
        _jobtype(access_class="secret")
    with pytest.raises(ValueError):
        _jobtype(runtime_h=-1.0)


# ============================================================ 5. trust
def test_finding_audit_log_tail_truncation_not_detected():
    """trust/__init__.py AuditLog.verify(): the chain head is not anchored anywhere, so dropping the newest
    entries (e.g. the 'deny' that proves a refusal) still verifies."""
    from trust import AuditLog
    log = AuditLog()
    for i in range(5):
        log.append({"i": i})
    head = log.head
    del log.entries[-2:]
    assert not log.verify() or log.head == head, "truncated log still verifies"


def test_trust_replay_modify_reorder_shred_reuse():
    from trust import AuditLog, Denied, KeyBroker, ReleasedKey, attest
    ev = {"measurement": "digitalheat-node-image-v1", "certified": False, "region": "CH-BL"}
    b = KeyBroker()
    b.register_job("j1", "c1", "swiss-only")
    b.register_job("j2", "c2", "swiss-only")
    a = attest("N1", ev)
    assert isinstance(b.release("j1", "N2", a, "CH-BL"), Denied)               # replay for another node
    a.evidence["region"] = "CH-BS"                                              # modify after signing
    assert b.release("j1", "N1", a, "CH-BS").reason == "bad_attestation"
    k1 = b.release("j1", "N1", attest("N1", ev), "CH-BL")
    k2 = b.release("j2", "N1", attest("N1", ev), "CH-BL")
    assert isinstance(k1, ReleasedKey) and isinstance(k2, ReleasedKey)
    assert k1.key.private_bytes_raw() != k2.key.private_bytes_raw()             # no key reuse across jobs
    b.shred("c1")
    assert b.release("j1", "N1", attest("N1", ev), "CH-BL").reason == "shredded"
    b.tamper("N1")
    assert not hasattr(b, "untamper")                                           # no public way back
    log = AuditLog()
    for i in range(4):
        log.append({"i": i})
    log.entries[1], log.entries[2] = log.entries[2], log.entries[1]             # reorder
    assert not log.verify()
