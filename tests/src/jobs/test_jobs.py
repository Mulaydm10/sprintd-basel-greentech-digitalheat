"""jobs tests (contracts/src/jobs.md): catalogue + arrivals + unit split. No model downloads, no network.

The catalogue numbers are not yet in data/assumptions.yaml (design adds them), so tests use the
PROPOSED block in fixtures/jobs_proposed.yaml merged into the real assumptions.
"""
from __future__ import annotations

import copy
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest
import yaml

import jobs.catalogue as catalogue_mod
from common.config import load_assumptions
from jobs.arrivals import JOBS_PER_DAY_SOURCE, Job, daily_arrivals, jobs_per_day, to_units
from jobs.catalogue import ACCESS_CLASSES, JobType, by_name, load_catalogue
from scheduler import Assign, Params, SiteState, decide, heat_value_chf_kwh

BASE = load_assumptions()
PROPOSED = yaml.safe_load((Path(__file__).parent / "fixtures" / "jobs_proposed.yaml").read_text())["jobs"]
A = {**copy.deepcopy(BASE), "jobs": PROPOSED}
TZ = ZoneInfo(A["location"]["tz"])
KW = A["server"]["electric_kw"]
UNIT_MIN = A["scheduler"]["unit_minutes"]


@pytest.fixture(scope="module")
def cat() -> list[JobType]:
    return load_catalogue(A)


# ------------------------------------------------------------------ catalogue
def test_catalogue_has_two_valid_types(cat):
    assert len(cat) >= 2
    for j in cat:
        assert j.access_class in ACCESS_CLASSES
        assert j.runtime_h > 0 and j.deadline_h >= j.runtime_h and j.price_chf_per_h >= 0
        assert j.energy_kwh == pytest.approx(j.runtime_h * KW)  # derived on the 1 kW ref server
        assert j.source.strip()
    classes = {j.access_class for j in cat}
    assert "swiss-only" in classes and "public" in classes  # one sovereign, one ballast


def test_placeholders_are_marked_assumed(cat):
    for j in cat:
        if not j.measured:
            assert "ASSUMED" in j.source


def test_slack(cat):
    for j in cat:
        assert j.slack_h == pytest.approx(j.deadline_h - j.runtime_h)


@pytest.mark.parametrize("patch", [
    {"access_class": "secret"}, {"runtime_h": 0}, {"deadline_h": 0.1, "runtime_h": 1.0}, {"source": " "},
    {"price_chf_per_h": -1},
])
def test_invalid_entries_rejected(patch):
    bad = copy.deepcopy(PROPOSED)
    bad[0].update(patch)
    with pytest.raises(ValueError):
        load_catalogue({**A, "jobs": bad})


def test_needs_two_types_and_unique_names():
    with pytest.raises(ValueError, match=">= 2"):
        load_catalogue({**A, "jobs": PROPOSED[:1]})
    with pytest.raises(ValueError, match="duplicate"):
        load_catalogue({**A, "jobs": [PROPOSED[0], PROPOSED[0]]})


def test_main_assumptions_catalogue_state():
    """Before design adds the block: clear error. After: it must load and satisfy the same rules."""
    if len(BASE.get("jobs") or []) < 2:
        with pytest.raises(ValueError, match="needs >= 2"):
            catalogue_mod.CATALOGUE
    else:
        assert len(catalogue_mod.CATALOGUE) >= 2


# ------------------------------------------------------------------ arrivals
def test_arrivals_deterministic_sorted_and_on_day(cat):
    d = date(2025, 1, 15)
    a1 = daily_arrivals(d, np.random.default_rng(7), cat)
    a2 = daily_arrivals(d, np.random.default_rng(7), cat)
    assert a1 == a2
    assert a1 == sorted(a1, key=lambda j: (j.arrival, j.id))
    assert all(j.arrival.date() == d and j.arrival.tzinfo is not None for j in a1)
    assert len({j.id for j in a1}) == len(a1)
    assert all(j.remaining_h == j.type.runtime_h for j in a1)


@pytest.mark.parametrize("d", [date(2025, 3, 30), date(2025, 10, 26)])
def test_arrivals_on_dst_days_stay_on_local_day(cat, d):
    rng = np.random.default_rng(1)
    for _ in range(20):
        for j in daily_arrivals(d, rng, cat):
            assert j.arrival.astimezone(TZ).date() == d


def test_mean_jobs_per_day_matches_catalogue(cat):
    rng = np.random.default_rng(0)
    days = 400
    counts = {j.name: 0 for j in cat}
    for k in range(days):
        for j in daily_arrivals(date(2025, 1, 1), rng, cat):
            counts[j.type.name] += 1
    for name, mean in jobs_per_day(cat).items():
        assert counts[name] / days == pytest.approx(mean, rel=0.1)
    assert "ASSUMED" in JOBS_PER_DAY_SOURCE


def test_unlimited_backlog_is_explicit_and_fills_servers(cat):
    d = date(2025, 7, 1)
    plain = daily_arrivals(d, np.random.default_rng(3), cat)
    full = daily_arrivals(d, np.random.default_rng(3), cat, unlimited_backlog=True, servers=3)
    backlog = [j for j in full if j.id.startswith("backlog-")]
    assert len(full) == len(plain) + 3 and len(backlog) == 3
    assert all(j.type.access_class == "public" and j.type.interruptible and j.remaining_h == 24 for j in backlog)


# ------------------------------------------------------------------ units for the scheduler
def test_to_units_split_and_fields(cat):
    jt = by_name(cat)["whisper_transcription"]
    start = datetime(2025, 1, 1, tzinfo=TZ)
    job = Job("w1", jt, datetime(2025, 1, 2, 5, tzinfo=TZ), jt.runtime_h)
    us = to_units(job, start, UNIT_MIN, KW)
    assert len(us) == round(jt.runtime_h * 60 / UNIT_MIN)
    assert sum(u.kwh_el for u in us) == pytest.approx(jt.runtime_h * KW)
    assert {u.deadline_hour for u in us} == {29 + int(jt.deadline_h)}
    assert all(u.access_class == jt.access_class and u.bid_chf_per_server_h == jt.price_chf_per_h for u in us)
    assert all(u.slack_h == jt.slack_h and u.checkpointable == jt.interruptible for u in us)
    assert len({u.unit_id for u in us}) == len(us)


def test_to_units_partial_last_unit(cat):
    jt = by_name(cat)["image_tagging"]
    job = Job("t1", jt, datetime(2025, 1, 1, tzinfo=TZ), 0.4)
    us = to_units(job, datetime(2025, 1, 1, tzinfo=TZ), UNIT_MIN, KW)
    assert len(us) == 2 and sum(u.kwh_el for u in us) == pytest.approx(0.4 * KW)


def test_units_feed_scheduler_and_eligibility_holds(cat):
    """End to end: a day's arrivals -> units -> decide(); swiss-only never lands on a public-only site."""
    start = datetime(2025, 1, 1, tzinfo=TZ)
    arr = daily_arrivals(date(2025, 1, 1), np.random.default_rng(5), cat)
    units = [u for j in arr for u in to_units(j, start, UNIT_MIN, KW)]
    h, s = A["house"], A["scheduler"]
    p = A["price"]["chf_per_kwh"]
    sites = [
        SiteState(sid, 0, h["design_kw"], 0.0, h["tank_kwh"], 4, KW, A["server"]["heat_recovery_fraction"], p,
                  heat_value_chf_kwh(p, A["price"]["heat_value_divisor"], h["design_kw"], 0.0, s["tank_band_high_kwh"]),
                  frozenset(cls), None, False, s["tank_band_low_kwh"], s["tank_band_high_kwh"], True)
        for sid, cls in (("pub", {"public"}), ("ch", {"public", "swiss-only"}))
    ]
    d = decide(sites, units, 0, Params.from_assumptions(A))
    by_id = {u.unit_id: u for u in units}
    for a in d.of(Assign):
        if by_id[a.unit_id].access_class == "swiss-only":
            assert a.site_id == "ch"


# ------------------------------------------------------------------ #22 hardening (red team F10)
@pytest.mark.parametrize("field", ["runtime_h", "energy_kwh", "deadline_h", "price_chf_per_h", "jobs_per_day"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_numeric_fields_rejected(field, value):
    e = dict(PROPOSED[0])
    e.update({"energy_kwh": e["runtime_h"] * KW}, **{field: value})
    bad = copy.deepcopy(PROPOSED)
    bad[0] = e
    with pytest.raises(ValueError, match=field):
        load_catalogue({**A, "jobs": bad})
