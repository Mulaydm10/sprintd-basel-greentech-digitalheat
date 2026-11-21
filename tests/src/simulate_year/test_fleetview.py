"""#119 fleetview: one decide() over a whole-city fleet. Short horizons (speed); the full-year K=1 equality is
checked against simulate() for a week here, and for the whole year in the PR."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from common.config import load_assumptions
from house_model.profile import load_reference_profile
from simulate_year import fleetview as fv
from simulate_year import fleetview_schema as fs
from simulate_year.sim import simulate

FIX = Path(__file__).parent / "fixtures" / "fleetview"
WEEK = 168


def test_fixture_has_the_schema_shape():
    ix = json.loads((FIX / "index.json").read_text(encoding="utf-8"))
    assert ix["schema"] == fs.SCHEMA and ix["fixture"] is True
    s = fs.read_series(FIX, ix)
    assert set(s) == {f[0] for f in fs.FIELDS} and len(s["heat_used_kwh"]) == len(ix["houses"])
    assert all(len(row) == ix["hours"] for row in s["tank_kwh"])
    fleet = json.loads((FIX / "fleet.json").read_text())
    assert set(fleet) == set(fs.FLEET_KEYS) and all(len(v) == ix["hours"] for v in fleet.values())
    assert json.loads((FIX / "jobs.json").read_text())["tracked"]


@pytest.mark.parametrize("policy,ballast", [("merit", True), ("thermostat", False)])
def test_one_reference_house_equals_simulate(policy, ballast):
    a = load_assumptions()
    prof = load_reference_profile(assumptions=a).iloc[:WEEK]
    r = fv.run_fleet(fv.place_houses(1, 0, servers=3), policy, ballast, WEEK, 0, cert_every_unit=0)["totals"]
    b, _ = simulate(prof, a, 3, policy, 24.0, 0.6, 0, hourly=False, ballast=ballast)
    assert r["heat_used_kwh"] == pytest.approx(b["server_heat_used_kwh"], abs=1e-3)
    assert r["dumped_kwh"] == pytest.approx(b["heat_dumped_kwh"], abs=1e-3)
    assert r["backup_kwh"] == pytest.approx(b["backup_heat_kwh"], abs=1e-3)
    assert r["run_h"] == pytest.approx(b["run_h"], abs=1e-3) and r["units_done"] == b["units_done"]


@pytest.fixture(scope="module")
def small():
    houses = fv.place_houses(12, 0)
    return houses, fv.run_fleet(houses, "merit", True, 48, 0)


def test_fleet_totals_are_the_sum_of_the_houses(small):
    _, r = small
    F, t = r["F"], r["totals"]
    assert F["heat_used_kwh"].sum() == pytest.approx(t["heat_used_kwh"], abs=1e-2)
    assert F["dumped_kwh"].sum() == pytest.approx(t["dumped_kwh"], abs=1e-2)
    assert F["unmet_kwh"].sum() == pytest.approx(t["backup_kwh"], abs=1e-2)
    assert F["servers_on"].sum() == pytest.approx(t["run_h"], abs=1e-6)
    assert sum(r["fleet"]["heat_used_kwh"]) == pytest.approx(t["heat_used_kwh"], abs=1e-2)
    assert (F["tank_kwh"] <= r["cap"] + 1e-6).all() and (F["tank_kwh"] >= -1e-6).all()


def test_the_scheduler_spreads_work_across_houses(small):
    houses, r = small
    assert len(houses) == 12 and houses[0]["scale"] == 1.0
    assert (r["F"]["servers_on"].sum(axis=1) > 0).sum() >= 6  # work reaches many houses, not one
    assert all(h["servers"] >= 1 for h in houses)


def test_deterministic():
    h1, h2 = fv.place_houses(8, 3), fv.place_houses(8, 3)
    assert h1 == h2
    a, b = fv.run_fleet(h1, "merit", True, 24, 3), fv.run_fleet(h2, "merit", True, 24, 3)
    assert a["totals"] == b["totals"] and (a["F"]["heat_used_kwh"] == b["F"]["heat_used_kwh"]).all()


def test_build_writes_fleetview_v1_with_assumed_labels(tmp_path):
    d = fv.build(tmp_path, k=6, seed=0, hours=24, log=lambda *_: None)
    ix = json.loads((d / "index.json").read_text(encoding="utf-8"))
    assert ix["schema"] == fs.SCHEMA and ix["fixture"] is False and ix["hours"] == 24 and len(ix["houses"]) == 6
    assert all(v.startswith(("ASSUMED", "REAL")) for v in ix["assumed"].values())
    s = fs.read_series(d, ix)
    assert sum(map(sum, s["heat_used_kwh"])) == pytest.approx(ix["totals"]["ours"]["heat_used_kwh"], rel=1e-3, abs=0.05)
    assert (tmp_path / "LATEST").read_text().strip() == d.name
    assert fv.build(tmp_path, k=6, seed=0, hours=24, log=lambda *_: None) == d  # cache reuse
