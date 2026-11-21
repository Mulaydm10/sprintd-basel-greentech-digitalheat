"""Red team round 2 (#17, parth-cloud): attack simulate_year (#19/#25) and the merged hardening (#21/#27).

Same convention as test_redteam.py: ``test_finding_*`` tests are findings listed on #17, marked
xfail(strict=True) so a fix flips them to XPASS and the fixer removes the marker in the same PR.
Everything else is an attack the code already survives, kept as a regression guard.
Expected behaviour: correct handling or a clear typed error. Never a silent wrong number or a raw crash.
"""
from __future__ import annotations

import copy
import dataclasses
import gc
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pandas as pd
import pytest

import simulate_year.cli as cli
import simulate_year.sim as sim
from common.config import ROOT, load_assumptions
from house_model.profile import load_reference_profile
from scheduler import Route, SetPower

A = load_assumptions()
TYPED = (ValueError, TypeError)
SRC = str(ROOT / "src")


@pytest.fixture(scope="module")
def profile():
    return load_reference_profile(assumptions=A)


def _with(path: tuple[str, str], value) -> dict:
    a = copy.deepcopy(A)
    a[path[0]][path[1]] = value
    return a


def _year(profile, a=A, **kw):
    args = dict(servers=1, policy="merit", slack_h=0.0, load=0.4, seed=0, hourly=False)
    args.update(kw)
    return sim.simulate(profile, a, **args)[0]


# ============================================================ weather input (DST, 25-h day)
def _wall_clock_csv(path: Path) -> list[str]:
    """Write the real 2025 data with Europe/Zurich wall-clock stamps (a DST export), no metadata header."""
    raw = pd.read_csv(ROOT / "data" / "raw" / "basel_2025_hourly.csv", skiprows=3)
    idx = pd.date_range("2025-01-01", periods=len(raw), freq="h", tz="Europe/Zurich")
    wall = list(idx.tz_localize(None).strftime("%Y-%m-%dT%H:%M"))
    pd.DataFrame({"time": wall, "t": raw.iloc[:, 1], "g": raw.iloc[:, 2]}).to_csv(path, index=False)
    return wall


def test_dst_wallclock_csv_with_duplicate_hour_is_rejected(tmp_path):
    p = tmp_path / "dst.csv"
    wall = _wall_clock_csv(p)
    assert pd.Series(wall).duplicated().sum() == 1  # 26 Oct 02:00 twice
    for kw in ({}, {"allow_partial": True}):
        with pytest.raises(ValueError, match="unique"):
            load_reference_profile(p, A, **kw)


def test_25h_and_23h_days_keep_the_annual_total(profile):
    """The real file in Europe/Zurich has one 25-h and one 23-h local day; yearly DHW must still be 365 x daily."""
    per_day = profile.groupby(profile.index.date).size()
    assert sorted(per_day.unique()) == [23, 24, 25]
    dhw = profile["hot_water_kw"].sum()
    assert dhw == pytest.approx(365 * A["house"]["hot_water_kwh_per_day"])


# ============================================================ load and seeds
def test_load_5_overload_keeps_unit_accounting(profile):
    b = _year(profile, servers=2, load=5.0)
    assert b["units_done"] <= b["jobs_total"]
    assert 0.0 < b["missed_deadline_pct"] <= 100.0
    assert b["utilisation"] <= 1.0 + 1e-9
    missed = round(b["missed_deadline_pct"] / 100 * b["jobs_total"])
    assert b["jobs_total"] - b["units_done"] - missed >= 0  # the rest is still queued at year end


def test_seed_changes_arrival_phase_but_not_capacity(profile):
    b0, b1 = _year(profile, seed=0), _year(profile, seed=1)
    assert b0["assumptions_hash"] == b1["assumptions_hash"]
    assert abs(b0["jobs_total"] - b1["jobs_total"]) <= 1


def test_negative_seed_is_a_typed_error(profile):
    with pytest.raises(TYPED):
        _year(profile, seed=-1)


def test_finding_run_id_collides_for_distinct_inputs():
    """cli.py _run_id formats load with :g (6 significant digits): load 0.4 and 0.4000001 map to the same
    runs/<id>/ directory, so the second run silently overwrites the first one's balance.json."""
    assert cli._run_id(1, "merit", 0.0, 0.4, 0) != cli._run_id(1, "merit", 0.0, 0.4000001, 0)


# ============================================================ corrupt or missing assumptions
def test_finding_zero_heat_value_divisor_raw_zero_division(profile):
    with pytest.raises(TYPED):
        _year(profile, _with(("price", "heat_value_divisor"), 0))


def test_finding_negative_heat_value_divisor_gives_negative_heat_value(profile):
    try:
        b = _year(profile, _with(("price", "heat_value_divisor"), -2.5))
    except TYPED:
        return
    assert b["heat_value_chf"] >= 0, b["heat_value_chf"]


def test_finding_zero_unit_minutes_raw_zero_division(profile):
    with pytest.raises(TYPED):
        _year(profile, _with(("scheduler", "unit_minutes"), 0))


def test_finding_missing_assumptions_section_raw_keyerror(profile):
    a = copy.deepcopy(A)
    del a["scheduler"]
    with pytest.raises(TYPED):
        _year(profile, a)


@pytest.mark.parametrize("path,value", [(("house", "tank_kwh"), -5.0), (("price", "chf_per_kwh"), float("nan")),
                                        (("server", "heat_recovery_fraction"), 1.5),
                                        (("price", "chf_per_kwh"), "abc")])
def test_corrupt_values_are_typed_errors(profile, path, value):
    with pytest.raises(TYPED):
        _year(profile, _with(path, value))


# ============================================================ sweep resilience
def test_finding_one_crashing_cell_kills_the_sweep(tmp_path, monkeypatch):
    """cli.sweep uses list(ex.map(...)): the first exception propagates and every other cell's result is lost.
    Expected: the sweep finishes and records the failed cell (error column or separate log)."""
    monkeypatch.setattr(cli, "SWEEP_SERVERS", range(1, 2))
    monkeypatch.setattr(cli, "SWEEP_SLACK_H", (0,))
    monkeypatch.setattr(cli, "SWEEP_LOAD", (0.4, -1.0))  # -1.0 makes every cell with it raise
    path = cli.sweep(tmp_path, seed=0, workers=2)
    rows = pd.read_csv(path)
    assert len(rows) >= 3  # the three policies at load 0.4 survived


# ============================================================ outputs
def test_hourly_csv_equals_parquet(tmp_path):
    cli.run_one(1, "merit", 0.0, 0.4, 0, tmp_path)
    pq = pd.read_parquet(tmp_path / "hourly.parquet")
    cs = pd.read_csv(tmp_path / "hourly.csv", index_col=0)
    assert list(cs.columns) == list(pq.columns)
    assert (pd.to_datetime(cs.index, utc=True) == pq.index.tz_convert("UTC")).all()
    num = [c for c in pq.columns if c != "mode"]
    assert float((cs[num] - pq[num].to_numpy()).abs().max().max()) <= 5e-7 + 1e-12  # 6 dp rounding
    assert (cs["mode"].to_numpy() == pq["mode"].to_numpy()).all()


# ============================================================ decide() misbehaving inside the loop
def test_decide_exception_propagates_and_gc_is_restored(profile, monkeypatch):
    orig = sim.decide

    def boom(sites, queue, h, params, **kw):
        if h == 100:
            raise RuntimeError("boom at h=100")
        return orig(sites, queue, h, params, **kw)

    monkeypatch.setattr(sim, "decide", boom)
    gc.enable()
    with pytest.raises(RuntimeError, match="boom"):
        _year(profile)
    assert gc.isenabled()


def test_non_conserving_route_is_caught(profile, monkeypatch):
    orig = sim.decide

    def leaky(*a, **kw):
        d = orig(*a, **kw)
        acts = [dataclasses.replace(x, dump_kwh=x.dump_kwh + 5.0) if isinstance(x, Route) else x for x in d.actions]
        return dataclasses.replace(d, actions=acts)

    monkeypatch.setattr(sim, "decide", leaky)
    with pytest.raises(AssertionError):
        _year(profile)


def test_finding_decision_without_setpower_raw_stopiteration(profile, monkeypatch):
    orig = sim.decide

    def no_power(*a, **kw):
        d = orig(*a, **kw)
        return dataclasses.replace(d, actions=[x for x in d.actions if not isinstance(x, SetPower)])

    monkeypatch.setattr(sim, "decide", no_power)
    with pytest.raises((*TYPED, AssertionError)):
        _year(profile)


def test_finding_conservation_checks_vanish_under_python_O():
    """sim.py step 4 guards energy conservation with `assert`. Under `python -O` (or PYTHONOPTIMIZE) a decide()
    that dumps 5 kWh/h it never produced runs to completion and reports 43,800 kWh of phantom dumped heat."""
    code = textwrap.dedent("""
        import dataclasses
        from common.config import load_assumptions
        from house_model.profile import load_reference_profile
        import simulate_year.sim as S
        from scheduler import Route
        A = load_assumptions(); P = load_reference_profile(assumptions=A)
        orig = S.decide
        def leaky(*a, **k):
            d = orig(*a, **k)
            return dataclasses.replace(d, actions=[dataclasses.replace(x, dump_kwh=x.dump_kwh + 5.0)
                                                    if isinstance(x, Route) else x for x in d.actions])
        S.decide = leaky
        S.simulate(P, A, 1, "merit", 0.0, 0.4, 0, hourly=False)
    """)
    env = {**os.environ, "PYTHONPATH": SRC}
    r = subprocess.run([sys.executable, "-O", "-c", code], env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode != 0, "non-conserving decisions were accepted under -O"
