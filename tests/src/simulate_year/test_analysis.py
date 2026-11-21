"""#31 analysis: band sweep, sensitivity, decision card (fast: synthetic profile, in-process cells),
plus hypothesis property tests on simulate()."""
from __future__ import annotations

import csv
import json

import numpy as np
import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import simulate_year.analysis as an
from common.config import load_assumptions
from simulate_year.sim import simulate

A = load_assumptions()
KW, REC, CAP = A["server"]["electric_kw"], A["server"]["heat_recovery_fraction"], A["house"]["tank_kwh"]
PRICE = next(j["price_chf_per_h"] for j in A["jobs"] if j["name"] == "image_tagging")
DASH_COLS = ["parameter", "low", "high", "metric", "metric_low", "metric_high", "metric_base"]  # #36
CARD_KEYS = {"recommended_n", "basis", "pays_off_above_chf_per_server_h", "does_not_pay_off_when",
             "first_pilot_measurement"}  # #36 flat keys


def synthetic(days=14, temps=None, seed=0, shift_c=0.0) -> pd.DataFrame:
    """First half cold (2 C), second half warm (20 C), daily sine, +-3 C hourly noise, plus a global shift."""
    h = A["house"]
    idx = pd.date_range("2025-01-01", periods=days * 24, freq="h", tz=A["location"]["tz"])
    rng = np.random.default_rng(seed)
    if temps is None:
        base = np.where(np.arange(len(idx)) < len(idx) // 2, 2.0, 20.0)
        temps = base + 4 * np.sin(2 * np.pi * np.arange(len(idx)) / 24) + rng.uniform(-3, 3, len(idx)) + shift_c
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


@pytest.fixture
def detail(fast):
    return an.sensitivity_detail(workers=1)


# ------------------------------------------------------------------ economics
def test_patch_is_deep_and_non_mutating():
    p = an._patch(A, {"price": {"chf_per_kwh": 1.0}})
    assert p["price"]["chf_per_kwh"] == 1.0 and p["price"]["heat_value_divisor"] == A["price"]["heat_value_divisor"]
    assert A["price"]["chf_per_kwh"] != 1.0


def test_break_even_with_capex_matches_simulate(fast):
    b, _ = simulate(fast, A, 3, "merit", 24, 0.6, 0, hourly=False, ballast=True)
    hw = A["hardware"]
    got = an.break_even_with_capex(b, hw["capex_chf_per_server"], hw["life_years"], hours=len(fast))
    assert got == pytest.approx(b["break_even_incl_hardware_chf_per_server_h"], abs=1e-5)
    assert an.break_even_with_capex({**b, "run_h": 0}, 1, 1) is None


def test_paid_price_closes_the_books(fast):
    """At the returned paid price, paid income + ballast income + heat value == electricity + hardware."""
    b, _ = simulate(fast, A, 3, "merit", 24, 0.6, 0, hourly=False, ballast=True)
    capex, life, hours = 8000.0, 5.0, len(fast)
    p = an.paid_price_to_break_even(b, capex, life, hours)
    hw = 3 * capex / life * hours / 8760
    income = p * b["paid_run_h"] + b["ballast_income_chf"] + b["heat_value_chf"]
    assert income == pytest.approx(b["electricity_cost_chf"] + hw, rel=1e-9)
    assert b["ballast_income_chf"] > 0 and p > an.break_even_with_capex(b, capex, life, hours)  # filler earns < BE
    assert an.paid_price_to_break_even({**b, "paid_run_h": 0}, capex, life) is None
    assert p == pytest.approx(b["pays_off_above_chf_per_server_h"], abs=1e-6)  # same definition as balance.json


# ------------------------------------------------------------------ 1. band
def test_band_sweep_rows_and_override_applied(fast):
    rows = an.band_sweep(workers=1)
    assert len(rows) == sum(1 for lo in an.BAND_LOWS for hi in an.BAND_HIGHS if lo <= hi <= CAP)
    assert {(r["band_low_kwh"], r["band_high_kwh"]) for r in rows} >= {(10.0, 33.0), (0.0, 35.0)}
    assert len({r["transitions_per_day"] for r in rows}) > 1  # the override really reaches the scheduler
    assert all(r["ballast_run_h"] > 0 and r["missed_deadline_pct"] == 0 for r in rows)  # ballast on, merit


def _band(lo, hi, cov, dump, tr):
    return dict(band_low_kwh=lo, band_high_kwh=hi, share_covered=cov, heat_dumped_kwh=dump, transitions_per_day=tr)


def test_choose_band_rule():
    rows = [_band(35, 35, 0.60, 10, 9.0),     # best coverage but flaps: excluded (> 2/day)
            _band(33, 35, 0.5009, 8, 0.12),   # best allowed coverage
            _band(20, 35, 0.5002, 8, 0.07),   # within 0.1 pp and fewer switches -> chosen
            _band(10, 35, 0.5002, 8, 0.07),   # same, lower band_low loses the last tie-break
            _band(5, 30, 0.4000, 1, 0.01)]    # fewest switches but 10 pp worse: not "equal"
    assert (an.choose_band(rows)["band_low_kwh"], an.choose_band(rows)["band_high_kwh"]) == (20, 35)
    assert an.choose_band(rows, tol=0.0)["band_low_kwh"] == 33  # no tolerance -> plain max coverage


# ------------------------------------------------------------------ 2. sensitivity
def test_sensitivity_detail_variants_and_directions(detail):
    params = {r["parameter"] for r in detail}
    assert params == {"base", "electricity price", "heat value divisor", "load", "slack h", "capex"}
    m = {(r["parameter"], r["setting"]): r[an.TORNADO_METRIC] for r in detail}
    assert m[("electricity price", "+20%")] > m[("electricity price", "-20%")]
    assert m[("capex", "15k/3y")] > m[("capex", "5k/5y")]
    assert m[("load", "0.8")] < m[("load", "0.4")]  # more paid hours spread the hardware
    base = next(r for r in detail if r["parameter"] == "base")
    hw = A["hardware"]
    assert m[("capex", f"{hw['capex_chf_per_server'] // 1000}k/{hw['life_years']}y")] == base[an.TORNADO_METRIC]


def test_price_variants_keep_ballast_inside_the_band(detail):
    """A fixed bid would fall below MC_used at +20% and filler would stop; the scaled bid keeps it running."""
    for r in detail:
        if r["parameter"] == "electricity price":
            assert r["ballast_run_h"] > 0


def test_sensitivity_has_dashboard_columns(detail, tmp_path):
    rows = an.sensitivity(detail=detail)
    p = an.write_csv(rows, tmp_path / "sensitivity.csv")
    with open(p) as f:
        r = csv.DictReader(f)
        assert r.fieldnames == DASH_COLS
        got = list(r)
    assert {x["parameter"] for x in got} == {"electricity price", "heat value divisor", "load", "slack h", "capex"}
    cap = next(x for x in got if x["parameter"] == "capex")
    assert (cap["low"], cap["high"]) == ("5k/5y", "15k/3y")
    assert len({x["metric_base"] for x in got}) == 1 and all(x["metric"] == an.TORNADO_METRIC for x in got)


def test_tornado_png_written(detail, tmp_path):
    assert an.tornado_png(an.sensitivity(detail=detail), tmp_path / "t.png")  # matplotlib is in requirements-dev
    assert (tmp_path / "t.png").stat().st_size > 1000


# ------------------------------------------------------------------ 3. decision card
def test_decision_card_is_computed_and_consistent(fast, detail, tmp_path):
    d = an.decision_card(workers=1, detail=detail)
    json.dumps(d)
    assert CARD_KEYS <= set(d)
    ns = [r["servers"] for r in d["by_servers"]]
    assert ns == list(an.CARD_SERVERS) and d["recommended_n"] in ns
    rec = next(r for r in d["by_servers"] if r["servers"] == d["recommended_n"])
    assert d["pays_off_above_chf_per_server_h"] == rec[an.TORNADO_METRIC]
    priced = [r[an.TORNADO_METRIC] for r in d["by_servers"]]
    if d["pays_off_above_chf_per_server_h"] > PRICE:
        assert d["basis"].startswith("no N") and rec[an.TORNADO_METRIC] == min(priced)
    for line in d["does_not_pay_off_when"][1:]:
        assert float(line.split("must fetch ")[1].split(" >")[0]) > PRICE
    assert isinstance(d["first_pilot_measurement"], str) and "slack 168 h" in d["first_pilot_measurement"]
    assert set(d["dump_kwh_by_slack_h"]) == {str(int(s)) for s in an.PATIENCE_SLACKS}
    assert an.write_json(d, tmp_path / "decision_card.json").exists()


# ------------------------------------------------------------------ 4. property tests (hypothesis)
PROPS = settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@PROPS
@given(seed=st.integers(0, 10_000), shift=st.floats(-3.0, 3.0), n=st.integers(0, 5), load=st.floats(0.0, 1.2),
       slack=st.sampled_from([0.0, 6.0, 24.0, 168.0]), policy=st.sampled_from(["merit", "thermostat", "always_on"]),
       ballast=st.booleans())
def test_property_conservation_and_bounds(seed, shift, n, load, slack, policy, ballast):
    prof = synthetic(days=5, seed=seed, shift_c=shift)
    b, df = simulate(prof, A, n, policy, slack, load, seed, hourly=True, ballast=ballast)
    assert np.allclose(df.servers_on * KW * REC, df.space + df.dhw + df.tank_in + df.dump, atol=1e-6)
    assert np.allclose(df.demand, df.space + df.dhw + df.tank_draw + df.backup, atol=1e-6)
    assert (df.tank_level >= -1e-9).all() and (df.tank_level <= CAP + 1e-9).all()
    assert (df.servers_on <= n + 1e-9).all()
    assert b["run_h"] == pytest.approx(b["paid_run_h"] + b["ballast_run_h"], abs=1e-3)
    assert b["ballast_hours_with_dump"] == 0


@PROPS
@given(seed=st.integers(0, 10_000), shift=st.floats(-3.0, 3.0), policy=st.sampled_from(["thermostat", "always_on"]))
def test_property_coverage_monotone_in_servers(seed, shift, policy):
    prof = synthetic(days=5, seed=seed, shift_c=shift)
    cov = [simulate(prof, A, n, policy, 0, 0.6, seed, hourly=False)[0]["share_covered"] for n in range(0, 6)]
    assert all(b >= a - 1e-9 for a, b in zip(cov, cov[1:])), cov


@PROPS
@given(seed=st.integers(0, 10_000), shift=st.floats(-3.0, 3.0), n=st.integers(1, 5), load=st.floats(0.1, 0.9))
def test_property_ballast_never_hurts_coverage_or_deadlines(seed, shift, n, load):
    prof = synthetic(days=5, seed=seed, shift_c=shift)
    off, _ = simulate(prof, A, n, "merit", 24, load, seed, hourly=False)
    on, _ = simulate(prof, A, n, "merit", 24, load, seed, hourly=False, ballast=True)
    assert on["share_covered"] >= off["share_covered"] - 1e-9
    assert on["missed_deadline_pct"] <= off["missed_deadline_pct"] + 1e-9
    assert on["jobs_total"] == off["jobs_total"]
    # Filler can take heat-backed capacity that merit was holding for paid work, so paid units wait until forced:
    # they are deferred, never lost. At the horizon the extra backlog is bounded by one slack window of N servers.
    # (Over the real year paid_run_h is identical with and without ballast; see test_simulate_year #37 golden.)
    assert off["paid_run_h"] - n * (24 + 2) <= on["paid_run_h"] <= off["paid_run_h"] + 1e-6
