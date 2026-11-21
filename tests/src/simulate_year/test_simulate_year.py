"""simulate_year robustness requirements (contracts/src/simulate_year.md v2, reqs 1-7).

Fast tests use a synthetic profile; golden/speed/determinism use the committed CSV. No network.
"""
from __future__ import annotations

import copy
import json
import math
import time

import numpy as np
import pandas as pd
import pytest

from common.config import load_assumptions
from house_model.profile import load_reference_profile
import simulate_year.cli as cli
from simulate_year.cli import main
from simulate_year.sim import simulate, thermostat_load

A = load_assumptions()
KW, REC = A["server"]["electric_kw"], A["server"]["heat_recovery_fraction"]
CAP = A["house"]["tank_kwh"]
GOLD = {1: (0.195, 0.871), 4: (0.580, 0.647), 8: (0.929, 0.518)}  # contract req. 1
GOLD_BE = 0.2261
CONTRACT_KEYS = {
    "servers_per_house", "policy", "slack_h", "load", "seed", "heat_demand_kwh", "server_heat_used_kwh",
    "share_covered", "backup_heat_kwh", "heat_dumped_kwh", "run_h", "utilisation", "jobs_total", "units_done",
    "missed_deadline_pct", "transitions_per_day", "electricity_cost_chf", "heat_value_chf", "compute_income_chf",
    "break_even_chf_per_server_h", "break_even_incl_hardware_chf_per_server_h", "assumptions_hash", "pays_off",
    "pays_off_conditions",
}
HOURLY_COLS = ["demand", "servers_on", "space", "dhw", "tank_in", "tank_draw", "dump", "backup", "tank_level",
               "mode", "queue_len", "missed"]


def synthetic(days=60, flat_temp: float | None = None) -> pd.DataFrame:
    """Half cold, half warm, with a daily swing (or flat weather). Demand from the house formula."""
    h = A["house"]
    idx = pd.date_range("2025-01-01", periods=days * 24, freq="h", tz=A["location"]["tz"])
    hours = np.arange(len(idx))
    if flat_temp is None:
        season = np.where(hours < len(idx) // 2, 2.0, 22.0)
        temp = season + 4 * np.sin(2 * np.pi * hours / 24)
    else:
        temp = np.full(len(idx), flat_temp)
    day_mean = pd.Series(temp, index=idx).groupby(idx.date).transform("mean").to_numpy()
    heating = day_mean < h["heating_day_mean_t_c"]
    space = np.where(heating, np.clip(h["design_kw"] * (h["t_base_c"] - temp) / h["t_design_span_c"], 0, None), 0.0)
    return pd.DataFrame({"space_heat_kw": space, "hot_water_kw": h["hot_water_kwh_per_day"] / 24}, index=idx)


SYN = synthetic()


@pytest.fixture(scope="module")
def year() -> pd.DataFrame:
    return load_reference_profile(assumptions=A)


def run(profile, n, policy, slack=0.0, load=0.0, seed=0, hourly=False, a=A):
    return simulate(profile, a, n, policy, slack, load, seed, hourly=hourly)


# ------------------------------------------------------------------ 1. golden numbers
@pytest.mark.parametrize("n", sorted(GOLD))
def test_req1_thermostat_golden(year, n):
    b, _ = run(year, n, "thermostat")
    cov, util = GOLD[n]
    assert b["share_covered"] == pytest.approx(cov, abs=0.002)
    assert b["utilisation"] == pytest.approx(util, abs=0.002)
    assert b["break_even_chf_per_server_h"] == pytest.approx(GOLD_BE, abs=0.0005)
    assert b["heat_dumped_kwh"] < 1


def test_req1_merit_slack_beats_no_slack_beats_always_on(year):
    d0 = run(year, 4, "merit", 0, 0.6)[0]["heat_dumped_kwh"]
    d24 = run(year, 4, "merit", 24, 0.6)[0]["heat_dumped_kwh"]
    ao = run(year, 4, "always_on", 0, 0.6)[0]["heat_dumped_kwh"]
    assert d24 < d0 < ao


# ------------------------------------------------------------------ 2. energy conservation (also asserted in the loop)
@pytest.mark.parametrize("policy,slack,load", [("merit", 24, 0.6), ("merit", 0, 1.5), ("thermostat", 0, 0.6),
                                               ("always_on", 0, 0.6)])
def test_req2_conservation_every_hour(policy, slack, load):
    _, df = run(SYN, 3, policy, slack, load, hourly=True)
    assert list(df.columns) == HOURLY_COLS
    produced = df.servers_on * KW * REC
    assert np.allclose(produced, df.space + df.dhw + df.tank_in + df.dump, atol=1e-6)
    assert np.allclose(df.demand, df.space + df.dhw + df.tank_draw + df.backup, atol=1e-6)
    assert (df.tank_level >= -1e-9).all() and (df.tank_level <= CAP + 1e-9).all()
    lvl = (df.tank_in - df.tank_draw).cumsum()
    assert np.allclose(lvl, df.tank_level, atol=1e-6)  # lossless tank, starts empty


# ------------------------------------------------------------------ 3. monotonicity
@pytest.mark.parametrize("policy", ["thermostat", "always_on"])
def test_req3_coverage_non_decreasing_in_servers(policy):
    cov = [run(SYN, n, policy, 0, 0.6)[0]["share_covered"] for n in range(0, 7)]
    assert all(b >= a - 1e-9 for a, b in zip(cov, cov[1:])), cov


def test_req3_dump_non_increasing_in_slack():
    d = [run(SYN, 4, "merit", s, 0.6)[0]["heat_dumped_kwh"] for s in (0, 24, 168)]
    assert d[0] >= d[1] >= d[2], d


# ------------------------------------------------------------------ 4. determinism
def test_req4_same_seed_byte_identical(tmp_path):
    for sub in ("a", "b"):
        assert main(["--servers", "2", "--policy", "merit", "--slack-h", "24", "--load", "0.6", "--seed", "3",
                     "--out", str(tmp_path / sub)]) == 0
    assert (tmp_path / "a/balance.json").read_bytes() == (tmp_path / "b/balance.json").read_bytes()
    assert list(pd.read_parquet(tmp_path / "a/hourly.parquet").columns) == HOURLY_COLS
    assert set(json.loads((tmp_path / "a/balance.json").read_text())) >= CONTRACT_KEYS


def test_req4_seed_changes_only_arrival_driven_keys():
    fixed = {"servers_per_house", "policy", "slack_h", "load", "heat_demand_kwh", "assumptions_hash"}
    b1, _ = run(SYN, 3, "thermostat", 0, 0.6, seed=1)
    b2, _ = run(SYN, 3, "thermostat", 0, 0.6, seed=2)
    diff = {k for k in b1 if b1[k] != b2[k]}
    assert diff <= {"seed", "jobs_total", "units_done", "missed_deadline_pct", "compute_income_chf",
                    "paid_run_h", "ballast_run_h", "ballast_income_chf"}  # implicit ballast = run - paid
    m1, _ = run(SYN, 3, "merit", 24, 0.6, seed=1)
    m2, _ = run(SYN, 3, "merit", 24, 0.6, seed=2)
    assert all(m1[k] == m2[k] for k in fixed)


# ------------------------------------------------------------------ 5. edge cases
def test_req5_zero_servers():
    b, _ = run(SYN, 0, "merit", 24, 0.6)
    assert b["backup_heat_kwh"] == pytest.approx(b["heat_demand_kwh"])
    assert b["share_covered"] == 0
    assert b["break_even_chf_per_server_h"] is None and b["utilisation"] is None
    assert b["pays_off"] is False and "no servers" in b["pays_off_conditions"]


def test_req5_zero_load_merit_runs_nothing():
    b, _ = run(SYN, 3, "merit", 24, 0.0)
    assert b["run_h"] == 0 and b["jobs_total"] == 0 and b["heat_dumped_kwh"] == 0


def test_req5_overload_misses_deadlines_without_crash():
    b, _ = run(SYN, 2, "merit", 0, 1.5)
    assert b["missed_deadline_pct"] > 0
    assert b["utilisation"] <= 1 + 1e-9


def test_req5_flat_weather_year():
    for t, heating in ((0.0, True), (25.0, False)):
        b, _ = run(synthetic(days=30, flat_temp=t), 2, "thermostat")
        assert b["server_heat_used_kwh"] > 0
        if not heating:  # hot water only
            assert b["heat_demand_kwh"] == pytest.approx(30 * A["house"]["hot_water_kwh_per_day"])


def test_req5_leap_free_8760_rows(year):
    assert len(year) == 8760
    b, _ = run(year, 1, "thermostat")
    assert b["heat_demand_kwh"] == pytest.approx(year.demand_kw.sum(), abs=1e-3)  # balance rounds to 3 dp


def test_bad_inputs_rejected():
    with pytest.raises(ValueError):
        run(SYN, 1, "follow")
    with pytest.raises(ValueError):
        run(SYN, -1, "merit")
    no_jobs = {**copy.deepcopy(A), "jobs": []}
    with pytest.raises(ValueError, match="jobs"):
        run(SYN, 1, "merit", 0, 0.5, a=no_jobs)


def test_economics_are_computed_not_typed():
    b, _ = run(SYN, 2, "merit", 24, 0.6)
    p, div = A["price"]["chf_per_kwh"], A["price"]["heat_value_divisor"]
    assert b["electricity_cost_chf"] == pytest.approx(b["run_h"] * KW * p, abs=1e-3)
    assert b["heat_value_chf"] == pytest.approx(b["server_heat_used_kwh"] * p / div, abs=1e-3)
    be = (b["electricity_cost_chf"] - b["heat_value_chf"]) / b["run_h"]
    assert b["break_even_chf_per_server_h"] == pytest.approx(be, abs=1e-5)
    assert b["break_even_incl_hardware_chf_per_server_h"] > b["break_even_chf_per_server_h"]
    assert f"{b['break_even_incl_hardware_chf_per_server_h']:.4f}" in b["pays_off_conditions"]
    assert len(b["break_even_incl_hardware_table"]) >= len(A["hardware"]["capex_range_chf"])


# ------------------------------------------------------------------ 6. speed
def test_req6_one_year_under_15s(year):
    t0 = time.perf_counter()
    run(year, 4, "merit", 24, 0.6)
    assert time.perf_counter() - t0 < 15


# ------------------------------------------------------------------ sweep (real process pool; regression for spawn pickling)
def test_sweep_runs_in_worker_processes(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "SWEEP_SERVERS", (1,))
    monkeypatch.setattr(cli, "SWEEP_SLACK_H", (0,))
    monkeypatch.setattr(cli, "SWEEP_LOAD", (0.4,))
    assert main(["--sweep", "--workers", "2", "--out", str(tmp_path)]) == 0
    rows = pd.read_csv(tmp_path / "sweep.csv")
    assert len(rows) == 3 and set(rows.policy) == {"merit", "thermostat", "always_on"}
    assert set(rows.columns) >= CONTRACT_KEYS


# ------------------------------------------------------------------ #19 follow-ups
def test_hourly_csv_written_and_matches_parquet(tmp_path):
    assert main(["--servers", "1", "--policy", "thermostat", "--out", str(tmp_path)]) == 0
    csv_df = pd.read_csv(tmp_path / "hourly.csv", index_col=0)
    pq = pd.read_parquet(tmp_path / "hourly.parquet")
    assert list(csv_df.columns) == HOURLY_COLS and len(csv_df) == len(pq)
    assert np.allclose(csv_df.dump, pq.dump, atol=1e-6)


def test_like_for_like_load_equals_thermostat_work():
    n = 3
    lf = thermostat_load(SYN, A, n)
    th, _ = run(SYN, n, "thermostat")
    assert lf == pytest.approx(th["run_h"] / (n * len(SYN)))
    me, _ = run(SYN, n, "merit", 168, lf)
    # same paid work offered as the thermostat runs (to within one unit of accumulator phase)
    unit_h = A["scheduler"]["unit_minutes"] / 60
    assert me["jobs_total"] * unit_h == pytest.approx(th["run_h"], abs=unit_h)
    assert thermostat_load(SYN, A, 0) == 0.0


def test_cli_load_thermostat_basis(tmp_path):
    assert main(["--servers", "2", "--policy", "merit", "--slack-h", "24", "--load", "thermostat",
                 "--out", str(tmp_path)]) == 0
    b = json.loads((tmp_path / "balance.json").read_text())
    assert b["load_basis"] == "thermostat" and 0 < b["load"] < 1
    with pytest.raises(SystemExit):
        main(["--servers", "1", "--load", "lots", "--out", str(tmp_path / "x")])


def test_simulate_restores_gc_state():
    import gc
    for enabled in (True, False):
        (gc.enable if enabled else gc.disable)()
        try:
            run(SYN, 1, "thermostat")
            assert gc.isenabled() is enabled
        finally:
            gc.enable()


# ------------------------------------------------------------------ #37 heat-backed ballast (fairness)
from simulate_year.sim import ballast_bid  # noqa: E402


def test_ballast_bid_band_enforced():
    b, acc = ballast_bid(A)
    p, kw = A["price"]["chf_per_kwh"], A["server"]["electric_kw"]
    mc_used = p * kw - REC * kw * p / A["price"]["heat_value_divisor"]
    assert mc_used <= b < p * kw and acc == "public"
    for bad in (mc_used - 0.01, p * kw):
        with pytest.raises(ValueError, match="MC_used"):
            ballast_bid({**A, "ballast": {"bid_chf_per_server_h": bad}})
    with pytest.raises(ValueError, match="ballast.bid"):
        ballast_bid({k: v for k, v in A.items() if k != "ballast"})
    assert ballast_bid({k: v for k, v in A.items() if k != "ballast"}, check=False) == (None, "public")


def test_ballast_off_is_default_and_unchanged():
    b0, _ = run(SYN, 3, "merit", 24, 0.6)
    b1, _ = simulate(SYN, A, 3, "merit", 24, 0.6, 0, hourly=False, ballast=False)
    assert b0 == b1 and b0["ballast"] is False and b0["ballast_run_h"] == 0


def test_ballast_raises_coverage_keeps_paid_deadlines_and_never_runs_on_dump():
    off, _ = run(SYN, 3, "merit", 24, 0.3)
    on, df = simulate(SYN, A, 3, "merit", 24, 0.3, 0, hourly=True, ballast=True)
    assert on["share_covered"] > off["share_covered"]
    assert on["missed_deadline_pct"] == off["missed_deadline_pct"] == 0
    assert on["paid_run_h"] == off["paid_run_h"]
    assert on["ballast_run_h"] > 0
    assert on["run_h"] == pytest.approx(on["paid_run_h"] + on["ballast_run_h"], abs=1e-3)
    assert on["ballast_income_chf"] == pytest.approx(on["ballast_run_h"] * ballast_bid(A)[0], abs=1e-3)
    # filler bid < MC_dump: where heat has nowhere to go (warm half, full tank) filler adds no dump
    warm = synthetic(days=20, flat_temp=25.0)
    w_off, _ = simulate(warm, A, 3, "merit", 0, 0.0, 0, hourly=False)
    w_on, _ = simulate(warm, A, 3, "merit", 0, 0.0, 0, hourly=False, ballast=True)
    assert w_on["heat_dumped_kwh"] == w_off["heat_dumped_kwh"] == 0
    assert w_on["share_covered"] >= w_off["share_covered"]


def test_baselines_report_implicit_ballast():
    th, _ = run(SYN, 3, "thermostat", 24, 0.3)
    assert th["ballast"] is False  # flag is merit-only
    assert th["run_h"] == pytest.approx(th["paid_run_h"] + th["ballast_run_h"], abs=1e-3)
    assert th["ballast_run_h"] > 0  # the thermostat runs servers without paid work: implicit ballast


def test_like_for_like_fairness_on_the_real_year(year):
    """#37 acceptance: same paid stream (load = thermostat utilisation, N=4). Merit + ballast meets every
    paid deadline (the thermostat misses many) and matches the thermostat's coverage to within 1 point
    (measured gap 0.7 pt at band 10/33, 0.07 pt at 33/35: hysteresis headroom, see PR #37)."""
    lf = thermostat_load(year, A, 4)
    th, _ = run(year, 4, "thermostat", 24, lf)
    me, _ = simulate(year, A, 4, "merit", 24, lf, 0, hourly=False, ballast=True)
    assert me["missed_deadline_pct"] == 0 < th["missed_deadline_pct"]
    assert me["share_covered"] >= th["share_covered"] - 0.01
    assert me["paid_run_h"] >= th["paid_run_h"]


# ------------------------------------------------------------------ #33 admission (contract v2.2)
def test_admission_off_is_default_and_counts_everything():
    b, _ = run(SYN, 2, "merit", 24, 0.6)
    assert b["admission"] is False and b["rejected_units"] == 0 and b["admitted_units"] == b["jobs_total"]


def test_admission_on_with_all_admissible_changes_nothing_physical(monkeypatch):
    """Golden numbers must not move when every job is admissible: with an ample forecast every unit is
    admitted and the run is identical to admission off (only the `admission` flag differs)."""
    import simulate_year.sim as sim
    monkeypatch.setattr(sim, "persistence_forecast", lambda hist, horizon: [1e9] * horizon)
    off, _ = simulate(SYN, A, 2, "merit", 24, 0.6, 0, hourly=False)
    on, _ = simulate(SYN, A, 2, "merit", 24, 0.6, 0, hourly=False, admission=True)
    assert on["rejected_units"] == 0
    assert {k: v for k, v in on.items() if k != "admission"} == {k: v for k, v in off.items() if k != "admission"}


def test_admission_cold_start_rejects_only_first_hour():
    """No history yet -> persistence forecast is 0 (never optimistic) -> hour-0 arrivals are rejected;
    from hour 1 on, ample cold-weather capacity admits everything."""
    cold = synthetic(days=20, flat_temp=0.0)
    n, load = 2, 0.3
    on, _ = simulate(cold, A, n, "merit", 168, load, 0, hourly=False, admission=True)
    per_h = n * 60 / A["scheduler"]["unit_minutes"] * load
    assert 0 < on["rejected_units"] <= math.ceil(per_h) + 1


def test_admission_rejects_instead_of_missing():
    """Overload with zero slack: without admission units miss deadlines; with admission they are rejected
    at submit and are not counted as missed."""
    off, _ = run(SYN, 1, "merit", 0, 1.5)
    on, _ = simulate(SYN, A, 1, "merit", 0, 1.5, 0, hourly=False, admission=True)
    assert off["missed_deadline_pct"] > 0
    assert on["rejected_units"] > 0
    assert on["admitted_units"] + on["rejected_units"] == on["jobs_total"]
    assert on["missed_deadline_pct"] <= off["missed_deadline_pct"]


def test_cli_admission_flag(tmp_path):
    assert main(["--servers", "1", "--policy", "merit", "--slack-h", "24", "--load", "0.5", "--admission",
                 "--out", str(tmp_path)]) == 0
    b = json.loads((tmp_path / "balance.json").read_text())
    assert b["admission"] is True and b["admitted_units"] + b["rejected_units"] == b["jobs_total"]
