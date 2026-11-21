"""#31 analysis: band sweep, sensitivity, decision card (fast: synthetic profile, in-process cells),
plus seeded property tests on simulate() (no hypothesis dependency; same properties)."""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

import simulate_year.analysis as an
from common.config import load_assumptions
from simulate_year.sim import simulate

A = load_assumptions()
KW, REC, CAP = A["server"]["electric_kw"], A["server"]["heat_recovery_fraction"], A["house"]["tank_kwh"]


def synthetic(days=14, temps=None, seed=0) -> pd.DataFrame:
    h = A["house"]
    idx = pd.date_range("2025-01-01", periods=days * 24, freq="h", tz=A["location"]["tz"])
    rng = np.random.default_rng(seed)
    if temps is None:
        base = np.where(np.arange(len(idx)) < len(idx) // 2, 2.0, 20.0)
        temps = base + 4 * np.sin(2 * np.pi * np.arange(len(idx)) / 24) + rng.uniform(-3, 3, len(idx))
    day_mean = pd.Series(temps, index=idx).groupby(idx.date).transform("mean").to_numpy()
    space = np.where(day_mean < h["heating_day_mean_t_c"],
                     np.clip(h["design_kw"] * (h["t_base_c"] - temps) / h["t_design_span_c"], 0, None), 0.0)
    return pd.DataFrame({"space_heat_kw": space, "hot_water_kw": h["hot_water_kwh_per_day"] / 24}, index=idx)


@pytest.fixture
def fast(monkeypatch):
    """Cells run in-process on a 14-day synthetic profile."""
    prof = synthetic()
    monkeypatch.setattr(an, "load_reference_profile", lambda assumptions=None: prof)
    return prof


def test_patch_is_deep_and_non_mutating():
    p = an._patch(A, {"price": {"chf_per_kwh": 1.0}})
    assert p["price"]["chf_per_kwh"] == 1.0 and p["price"]["heat_value_divisor"] == A["price"]["heat_value_divisor"]
    assert A["price"]["chf_per_kwh"] != 1.0


def test_break_even_with_capex_matches_simulate(fast):
    b, _ = simulate(fast, A, 3, "merit", 24, 0.6, 0, hourly=False)
    hw = A["hardware"]
    years = len(fast) / 8760
    got = an.break_even_with_capex(b, hw["capex_chf_per_server"], hw["life_years"], hours=len(fast))
    assert got == pytest.approx(b["break_even_incl_hardware_chf_per_server_h"], abs=1e-5)
    assert an.break_even_with_capex({**b, "run_h": 0}, 1, 1) is None
    assert years < 1


def test_band_sweep_rows_and_override_applied(fast):
    rows = an.band_sweep(workers=1)
    assert len(rows) == sum(1 for lo in an.BAND_LOWS for hi in an.BAND_HIGHS if lo <= hi)
    assert {(r["band_low_kwh"], r["band_high_kwh"]) for r in rows} >= {(10.0, 33.0), (0.0, 35.0)}
    # the override really reaches the scheduler: transitions depend on the band
    assert len({r["transitions_per_day"] for r in rows}) > 1


def test_choose_band_rule():
    rows = [dict(band_low_kwh=0, band_high_kwh=35, share_covered=0.5, heat_dumped_kwh=10, transitions_per_day=9),
            dict(band_low_kwh=10, band_high_kwh=33, share_covered=0.5, heat_dumped_kwh=8, transitions_per_day=1),
            dict(band_low_kwh=5, band_high_kwh=30, share_covered=0.4, heat_dumped_kwh=1, transitions_per_day=0.5)]
    assert an.choose_band(rows)["band_low_kwh"] == 10  # flapping row excluded, then coverage, then dump


def test_sensitivity_rows_and_directions(fast):
    rows = an.sensitivity(workers=1)
    params = {r["param"] for r in rows}
    assert params == {"base", "price_chf_per_kwh", "heat_value_divisor", "load", "slack_h", "capex_chf_x_life_y"}
    be = {(r["param"], str(r["value"])): r["break_even_incl_hardware_chf_per_server_h"] for r in rows}
    p0 = A["price"]["chf_per_kwh"]
    assert be[("price_chf_per_kwh", str(p0 * 1.2))] > be[("price_chf_per_kwh", str(p0 * 0.8))]  # dearer power
    caps = sorted(A["hardware"]["capex_range_chf"])
    assert be[("capex_chf_x_life_y", f"{caps[-1]}x3")] > be[("capex_chf_x_life_y", f"{caps[0]}x5")]
    base = next(r for r in rows if r["param"] == "base")
    assert base["delta_be_hw_vs_base"] == 0


def test_decision_card_is_computed_and_consistent(fast, tmp_path):
    d = an.decision_card(workers=1)
    json.dumps(d)  # serialisable
    ns = [r["servers"] for r in d["by_servers"]]
    assert ns == list(an.CARD_SERVERS) and d["recommended_servers"] in ns
    rec = next(r for r in d["by_servers"] if r["servers"] == d["recommended_servers"])
    assert d["pays_off_at_price_chf_per_server_h"] == rec["break_even_incl_hardware_chf_per_server_h"]
    price = d["reference"]["paid_work_price_chf_per_server_h"]
    for line in d["does_not_pay_when"]:
        assert float(line.split("break-even ")[1].split(" >")[0]) > price
    assert set(d["first_pilot_measurement"]["dump_kwh_by_slack_h"]) == {str(int(s)) for s in an.PATIENCE_SLACKS}
    assert an.write_json(d, tmp_path / "decision_card.json").exists()


def test_tornado_png_optional(tmp_path):
    rows = [{"param": "base", "delta_be_hw_vs_base": 0.0}, {"param": "load", "delta_be_hw_vs_base": 0.1}]
    made = an.tornado_png(rows, tmp_path / "t.png")
    assert made == (tmp_path / "t.png").exists()


# ------------------------------------------------------------------ property tests (seeded random cases)
CASES = [dict(seed=s, n=int(np.random.default_rng(s).integers(0, 6)),
              load=float(np.random.default_rng(s + 100).uniform(0, 1.2)),
              slack=float(np.random.default_rng(s + 200).choice([0, 6, 24, 168])),
              policy=("merit", "thermostat", "always_on")[s % 3]) for s in range(12)]


@pytest.mark.parametrize("c", CASES, ids=lambda c: f"s{c['seed']}-{c['policy']}-n{c['n']}")
def test_property_conservation_and_tank_bounds(c):
    prof = synthetic(days=7, seed=c["seed"])  # weather perturbed by +-3 C per hour
    _, df = simulate(prof, A, c["n"], c["policy"], c["slack"], c["load"], c["seed"], hourly=True)
    assert np.allclose(df.servers_on * KW * REC, df.space + df.dhw + df.tank_in + df.dump, atol=1e-6)
    assert np.allclose(df.demand, df.space + df.dhw + df.tank_draw + df.backup, atol=1e-6)
    assert (df.tank_level >= -1e-9).all() and (df.tank_level <= CAP + 1e-9).all()
    assert (df.servers_on <= c["n"] + 1e-9).all()


@pytest.mark.parametrize("seed", range(4))
@pytest.mark.parametrize("policy", ["thermostat", "always_on"])
def test_property_coverage_monotone_in_servers(seed, policy):
    prof = synthetic(days=7, seed=seed)
    cov = [simulate(prof, A, n, policy, 0, 0.6, seed, hourly=False)[0]["share_covered"] for n in range(0, 6)]
    assert all(b >= a - 1e-9 for a, b in zip(cov, cov[1:])), cov
