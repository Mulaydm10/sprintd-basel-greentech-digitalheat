"""scheduler.admit (contract v2.2, #33): conservative admission at submit. Pure, no I/O."""
from __future__ import annotations

import dataclasses
import math

import pytest

from common.config import load_assumptions
from scheduler import InvalidInput, Params, SiteState, Unit
from scheduler.admit import (R_DEADLINE, R_EMPTY, R_HORIZON, R_NO_ELIGIBLE, R_OK, admit, net_of_backlog,
                             persistence_forecast)

A = load_assumptions()
P = Params.from_assumptions(A)
SAFE = P.deadline_safety_h
KW = A["server"]["electric_kw"]
UNIT = KW * A["scheduler"]["unit_minutes"] / 60
H0 = 100


def site(sid="S", classes=("public", "swiss-only")) -> SiteState:
    h, s = A["house"], A["scheduler"]
    return SiteState(sid, H0, h["design_kw"], s["tank_band_low_kwh"], h["tank_kwh"], 1, KW,
                     A["server"]["heat_recovery_fraction"], A["price"]["chf_per_kwh"], 0.0, frozenset(classes), None,
                     False, s["tank_band_low_kwh"], s["tank_band_high_kwh"], True)


def job(n, deadline, access="public", jid="j1") -> list[Unit]:
    return [Unit(f"{jid}#{i}", jid, "t", access, UNIT, 1.0, deadline, 1.0, True) for i in range(n)]


def test_accepts_when_capacity_finishes_before_deadline_minus_margin():
    a = admit(job(8, H0 + 10), [site()], H0, {"S": [KW] * 24}, P)  # 2 kWh at 1 kWh/h -> finish H0+2
    assert a == dataclasses.replace(a, accepted=True, reason=R_OK) and a.earliest_finish_hour == H0 + 2


def test_rejects_when_finish_misses_margin():
    d = H0 + 2  # finish H0+2 would need margin 0, but safety > 0
    a = admit(job(8, d), [site()], H0, {"S": [KW] * 24}, P)
    assert not a.accepted and a.reason == R_DEADLINE
    assert a.earliest_finish_hour is None or a.earliest_finish_hour > d - SAFE


def test_exact_margin_boundary_is_admitted():
    finish = H0 + 2
    a = admit(job(8, finish + math.ceil(SAFE)), [site()], H0, {"S": [KW] * 24}, P)
    assert a.accepted and a.earliest_finish_hour == finish


def test_zero_capacity_hours_delay_finish():
    fc = [0.0] * 5 + [KW] * 19
    a = admit(job(4, H0 + 20), [site()], H0, {"S": fc}, P)
    assert a.accepted and a.earliest_finish_hour == H0 + 6


def test_ineligible_and_empty_and_short_horizon():
    assert admit(job(1, H0 + 50, access="certified"), [site()], H0, {"S": [KW] * 24}, P).reason == R_NO_ELIGIBLE
    assert admit([], [site()], H0, {"S": [KW]}, P).reason == R_EMPTY
    a = admit(job(40, H0 + 500), [site()], H0, {"S": [KW] * 3}, P)
    assert not a.accepted and a.reason == R_HORIZON


def test_only_eligible_sites_capacity_counts():
    sites = [site("pub", ("public",)), site("ch", ("public", "swiss-only"))]
    fc = {"pub": [10 * KW] * 24, "ch": [0.0] * 24}
    assert not admit(job(4, H0 + 20, access="swiss-only"), sites, H0, fc, P).accepted
    assert admit(job(4, H0 + 20, access="public"), sites, H0, fc, P).accepted


@pytest.mark.parametrize("fc", [{"S": [math.nan]}, {"S": [-1.0]}, {"S": [math.inf]}])
def test_bad_forecast_rejected(fc):
    with pytest.raises(InvalidInput):
        admit(job(1, H0 + 5), [site()], H0, fc, P)


def test_units_of_several_jobs_rejected():
    with pytest.raises(InvalidInput, match="exactly one job"):
        admit(job(2, H0 + 9, jid="a") + job(2, H0 + 9, jid="b"), [site()], H0, {"S": [KW] * 24}, P)


def test_persistence_repeats_last_day_and_pads_with_zero():
    hist = list(range(30))  # last 24 = 6..29
    assert persistence_forecast(hist, 26) == [float(x) for x in list(range(6, 30)) + [6, 7]]
    assert persistence_forecast([5.0, 7.0], 3) == [0.0, 0.0, 0.0]  # oldest hours padded with 0
    assert persistence_forecast([5.0, 7.0], 24)[-2:] == [5.0, 7.0]
    assert persistence_forecast([-3.0] * 24, 2) == [0.0, 0.0]


def test_net_of_backlog_consumes_front():
    assert net_of_backlog([1.0, 1.0, 1.0], 1.5) == [0.0, 0.5, 1.0]
    assert net_of_backlog([1.0], 0.0) == [1.0]


def test_backlog_makes_admission_stricter():
    fc = [KW] * 24
    free = admit(job(4, H0 + 4), [site()], H0, {"S": fc}, P)
    busy = admit(job(4, H0 + 4), [site()], H0, {"S": net_of_backlog(fc, 3 * KW)}, P)
    assert free.accepted and not busy.accepted
