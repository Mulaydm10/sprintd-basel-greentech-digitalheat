"""Red team round 3 (#17, parth-cloud): scheduler.admit (#40), ballast + pays_off accounting (#42/#50), the dashboard
API (#9), tools/pitch (#48).

Same convention as test_redteam.py: ``test_finding_*`` tests are findings listed on #17, marked xfail(strict=True)
so a fix flips them to XPASS and the fixer removes the marker in the same PR. Everything else is an attack the code
already survives, kept as a regression guard. Expected: correct handling or a clear typed error. Never a silent wrong
number, a broken promise, or a raw crash. For the HTTP API, "typed" means an HTTPException with a `detail` message,
not an unhandled exception (a plain-text "Internal Server Error").
"""
from __future__ import annotations

import copy
import json
import shutil
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import dashboard.app as dash
from common.config import ConfigError, load_assumptions, validate_assumptions
from scheduler import Params, SiteState, Unit
from scheduler.admit import R_DEADLINE, admit, net_of_backlog
from simulate_year.sim import simulate

A = load_assumptions()
TYPED = (ValueError, TypeError)
P = Params("merit", 0.8, True, 0.05, 1.0)


def site(sid: str = "a", classes=("public",), servers: int = 1) -> SiteState:
    return SiteState(sid, 0, 3.0, 10.0, 35.0, servers, 1.0, 0.8, 0.33, 0.13, frozenset(classes), None, False,
                     10.0, 33.0, False)


def unit(i: int = 0, kwh: float = 0.25, deadline: int = 10, job: str = "j", cls: str = "public") -> Unit:
    return Unit(f"u{i}", job, "x", cls, kwh, 0.5, deadline, 5.0, True)


def synthetic(days: int = 10, seed: int = 0) -> pd.DataFrame:
    """Cold first half, warm second half, daily sine, +-3 C hourly noise; demand from the house formula."""
    h = A["house"]
    idx = pd.date_range("2025-01-01", periods=days * 24, freq="h", tz=A["location"]["tz"])
    rng = np.random.default_rng(seed)
    t = np.where(np.arange(len(idx)) < len(idx) // 2, 2.0, 20.0) + 4 * np.sin(2 * np.pi * np.arange(len(idx)) / 24) \
        + rng.uniform(-3, 3, len(idx))
    dm = pd.Series(t, index=idx).groupby(idx.date).transform("mean").to_numpy()
    sp = np.where(dm < h["heating_day_mean_t_c"], np.clip(h["design_kw"] * (h["t_base_c"] - t) / h["t_design_span_c"],
                                                          0, None), 0.0)
    return pd.DataFrame({"space_heat_kw": sp, "hot_water_kw": h["hot_water_kwh_per_day"] / 24}, index=idx)


# ============================================================ scheduler.admit + simulate_year --admission
@pytest.mark.xfail(strict=True, reason="#17 r3 F20: admitted jobs miss their deadline under overload")
def test_finding_admitted_jobs_miss_deadlines_under_overload():
    """Admission's promise (#33/#40): accept only what conservative capacity finishes by deadline - safety, so an
    admitted job is never late. Under overload it breaks: N=4, load 1.0, slack 24 h on a 10-day synthetic year
    misses 0.034% of admitted units (N=2, load 1.5: 1.71%), with and without ballast. Found in 48 of 216
    seed x N x load x slack x ballast cases, all at load >= 1.0 and slack 24."""
    b, _ = simulate(synthetic(), A, 4, "merit", 24, 1.0, 0, hourly=False, admission=True)
    assert b["admitted_units"] > 0
    assert b["missed_deadline_pct"] == 0, b["missed_deadline_pct"]


@pytest.mark.xfail(strict=True, reason="#17 r3 F21: slack < deadline_safety_h silently rejects 100% of jobs")
def test_finding_slack_below_safety_margin_rejects_everything_silently():
    """deadline = arrival + slack + 1 and latest finish = deadline - deadline_safety_h (1 h), so with slack 0 no job can
    ever be admitted. The real year at N=4, load 1.0 rejects 140,160 of 140,160 units, and the run still writes a
    balance (coverage, pays_off ...) that looks like a result. Expected: a typed error naming deadline_safety_h."""
    with pytest.raises(TYPED, match="deadline_safety_h"):
        simulate(synthetic(), A, 4, "merit", 0, 0.6, 0, hourly=False, admission=True)


@pytest.mark.xfail(strict=True, reason="#17 r3 F22: one unit split across sites in the same hour")
def test_finding_admit_splits_one_unit_across_sites():
    """admit() sums capacity over sites and hours, but a unit is atomic and runs on one server. A 2 kWh unit with two
    1 kWh/h sites is admitted to finish at hour 1, which is impossible: one 1 kW server needs 2 hours."""
    a = admit([unit(kwh=2.0)], [site("a"), site("b")], 0, {"a": [1.0] * 5, "b": [1.0] * 5}, P)
    assert not a.accepted or a.earliest_finish_hour >= 2, a


@pytest.mark.xfail(strict=True, reason="#17 r3 F23: NaN backlog silently ignored -> double-booking")
def test_finding_net_of_backlog_nan_is_silently_zero():
    """max(0.0, nan) == 0.0, so a NaN backlog (e.g. a corrupt queue sum) frees the whole forecast and admission
    double-books capacity that queued work will use. Expected: InvalidInput/ValueError."""
    with pytest.raises(TYPED):
        net_of_backlog([1.0, 1.0], float("nan"))


@pytest.mark.xfail(strict=True, reason="#17 r3 F24: past-deadline job rejected with the 'horizon' reason")
def test_finding_admit_reason_for_past_deadline_job():
    a = admit([unit(deadline=0)], [site()], 5, {"a": []}, P)
    assert not a.accepted and a.reason == R_DEADLINE, a.reason


@pytest.mark.xfail(strict=True, reason="#17 r3 F25: admit accepts a negative hour and bool capacities")
def test_finding_admit_accepts_negative_hour_and_bool_capacity():
    with pytest.raises(TYPED):
        admit([unit(deadline=-40)], [site()], -50, {"a": [1.0] * 5}, P)
    with pytest.raises(TYPED):
        admit([unit()], [site()], 0, {"a": [True] * 5}, P)


def test_admit_guards():
    """Attacks admit already survives."""
    assert admit([unit(kwh=2.0)], [site("a")], 0, {"a": [1.0] * 5}, P).earliest_finish_hour == 2  # one site: right
    with pytest.raises(TYPED):
        admit([unit()], [site()], 0, {"a": [float("inf")]}, P)  # inf capacity rejected
    with pytest.raises(TYPED):
        admit([unit(job="j1"), unit(1, job="j2")], [site()], 0, {"a": [1.0]}, P)  # two jobs in one call
    a = admit([unit(cls="swiss-only")], [site("a", ("public",))], 0, {"a": [9.0] * 5}, P)
    assert not a.accepted  # no eligible site, capacity elsewhere is not borrowed


# ============================================================ ballast + pays_off accounting
PROPS = settings(max_examples=60, deadline=None, suppress_health_check=list(HealthCheck))


@PROPS
@given(seed=st.integers(0, 999), n=st.integers(0, 6), load=st.floats(0, 1.5), slack=st.sampled_from([0, 6, 24, 168]),
       pol=st.sampled_from(["merit", "thermostat", "always_on"]), ballast=st.booleans(), adm=st.booleans(),
       p=st.floats(0.05, 1.0), div=st.floats(1.0, 6.0), capex=st.floats(0, 30000), life=st.floats(1, 10),
       bid_pos=st.floats(0, 0.999), paid=st.floats(0, 2), unit_min=st.sampled_from([5, 10, 15, 20, 30, 45, 60]))
def test_pays_off_iff_net_income_non_negative(seed, n, load, slack, pol, ballast, adm, p, div, capex, life, bid_pos,
                                             paid, unit_min):
    """Design's #30 question: can any input make pays_off True while the year loses money (or False while it
    earns)? Net = paid income + filler income + heat value - electricity - hardware. 300 cases in the exploration,
    60 per run here: never."""
    a = copy.deepcopy(A)
    a["price"].update(chf_per_kwh=p, heat_value_divisor=div)
    a["hardware"].update(capex_chf_per_server=capex, life_years=life)
    a["scheduler"]["unit_minutes"] = unit_min
    for j in a["jobs"]:
        j["price_chf_per_h"] = paid
    lo = p - a["server"]["heat_recovery_fraction"] * a["server"]["electric_kw"] * p / div
    a["ballast"]["bid_chf_per_server_h"] = lo + bid_pos * (p - lo)
    try:
        validate_assumptions(a)
    except ConfigError:
        return
    prof = synthetic(days=4, seed=seed)
    b, _ = simulate(prof, a, n, pol, slack, load, seed, hourly=False, ballast=ballast, admission=adm)
    hw = n * capex / life * len(prof) / 8760
    net = (b["compute_income_chf"] or 0) + (b["ballast_income_chf"] or 0) + b["heat_value_chf"] \
        - b["electricity_cost_chf"] - hw
    tol = 1e-3 * max(1.0, b["paid_run_h"])  # balance values are rounded to 3 dp
    if b["pays_off"]:
        assert net >= -tol, (net, b["pays_off_conditions"])
    elif b["paid_run_h"] > 0:
        assert net <= tol, (net, b["pays_off_conditions"])
    assert b["run_h"] == pytest.approx(b["paid_run_h"] + b["ballast_run_h"], abs=1e-3)
    assert b["ballast_hours_with_dump"] == 0


def test_ballast_flag_is_ignored_for_baselines_and_reported():
    b, _ = simulate(synthetic(4), A, 2, "thermostat", 0, 0.5, 0, hourly=False, ballast=True)
    assert b["ballast"] is False and b["ballast_income_chf"] is None  # never sells filler it does not run


# ============================================================ dashboard API
@pytest.fixture
def run(tmp_path, monkeypatch):
    """A writable copy of the dashboard fixture run under tmp/runs/r1, served via DH_RUN_DIR."""
    d = tmp_path / "runs" / "r1"
    d.mkdir(parents=True)
    for f in ("balance.json", "hourly.csv"):
        shutil.copy(dash.FIXTURE_DIR / f, d / f)
    monkeypatch.setenv("DH_RUN_DIR", str(d))
    return d


@pytest.fixture
def client():
    return TestClient(dash.app, raise_server_exceptions=False)


def _typed(r) -> bool:
    """A handled error: JSON with a detail message (HTTPException), not an unhandled 'Internal Server Error'."""
    try:
        return r.status_code < 500 or "detail" in r.json()
    except ValueError:
        return False


@pytest.mark.parametrize("path", ["/api/day/..%2F..%2Fetc%2Fpasswd", "/api/day/january%00", "/api/day/JANUARY",
                                  "/api/day/" + "a" * 5000, "/api/day/%2e%2e"])
def test_dashboard_day_rejects_traversal_and_junk(run, client, path):
    r = client.get(path)
    assert r.status_code == 404 and "passwd" not in r.text


def test_dashboard_missing_run_dir_is_404_not_crash(run, client):
    shutil.rmtree(run)
    for p in ("/api/balance", "/api/day/january", "/api/provenance", "/api/ab_like_for_like"):
        assert client.get(p).status_code == 404, p
    assert client.get("/api/sweep").json() == []


def test_dashboard_huge_sweep_stays_fast(run, client):
    n = 300_000
    pd.DataFrame({"policy": "merit", "servers_per_house": np.arange(n) % 9, "slack_h": 24, "load": 0.6,
                  "share_covered": 0.5, "break_even_incl_hardware_chf_per_server_h": 0.5}).to_csv(run / "sweep.csv",
                                                                                                    index=False)
    t0 = time.time()
    assert client.get("/api/decision").status_code == 200
    assert time.time() - t0 < 10


def test_dashboard_unreadable_parquet_falls_back_to_csv(run, client):
    (run / "hourly.parquet").write_bytes(b"PAR1 not a parquet file")
    assert client.get("/api/day/january").status_code == 200


@pytest.mark.xfail(strict=True, reason="#17 r3 F26: corrupt balance.json -> unhandled 500 on 5 endpoints")
@pytest.mark.parametrize("content", ["{not json", "[1, 2]", ""], ids=["garbage", "json-list", "empty"])
def test_finding_dashboard_corrupt_balance_is_unhandled(run, client, content):
    (run / "balance.json").write_text(content)
    bad = [p for p in ("/api/balance", "/api/ab", "/api/decision", "/api/provenance", "/api/ab_like_for_like")
           if not _typed(client.get(p))]
    assert not bad, bad


@pytest.mark.xfail(strict=True, reason="#17 r3 F27: one corrupt sibling run breaks the like-for-like view")
def test_finding_dashboard_one_bad_sibling_breaks_ab_like_for_like(run, client):
    """runs/<other>/balance.json is read for the A/B. One half-written run (e.g. a sweep killed mid-write) turns the
    whole view into a 500. Expected: skip it and say so (like the sweep's failed cells, F17)."""
    bad = run.parent / "half-written"
    bad.mkdir()
    (bad / "balance.json").write_text('{"policy": "merit", "servers_per')
    r = client.get("/api/ab_like_for_like")
    assert r.status_code == 200, r.status_code


@pytest.mark.xfail(strict=True, reason="#17 r3 F28: malformed hourly.csv -> unhandled 500")
@pytest.mark.parametrize("csv", ["hour,x\n0,1\n1,2\n", "hour,demand,dump\na,1,2\n"], ids=["no-columns", "text-hour"])
def test_finding_dashboard_malformed_hourly_is_unhandled(run, client, csv):
    (run / "hourly.csv").write_text(csv)
    assert _typed(client.get("/api/day/january"))


@pytest.mark.xfail(strict=True, reason="#17 r3 F29: corrupt sweep/sensitivity/decision_card -> unhandled 500")
@pytest.mark.parametrize("name,content,path", [
    ("sweep.csv", '\x00\xff,\n"unterminated', "/api/sweep"),
    ("sensitivity.csv", "parameter,metric_low,metric_high\nx,abc,1\n", "/api/sensitivity"),
    ("decision_card.json", "{", "/api/decision_card"),
], ids=["sweep", "sensitivity", "decision_card"])
def test_finding_dashboard_corrupt_outputs_are_unhandled(run, client, name, content, path):
    (run / name).write_text(content)
    assert _typed(client.get(path))


@pytest.mark.xfail(strict=True, reason="#17 r3 F30: /api/decision ranks N by the run-hour break-even, not #50's")
def test_finding_dashboard_decision_uses_pre_50_break_even(run, client):
    """#50 made pays_off_above the pay-off test (filler and heat-led hours do not earn the paid price). /api/decision
    still picks 'the' N by the lowest break_even_incl_hardware, which said merit+ballast and always_on pay at N=4
    when they lose money. The page's decision then disagrees with pays_off on the same run."""
    rule = client.get("/api/decision").json()["rule"]
    assert "pays_off_above" in rule, rule


# ============================================================ tools/pitch ASSUMED detection (#48)
@pytest.mark.xfail(strict=True, reason="#17 r3 F31: ASSUMED comment on the line above a key is not attributed")
def test_finding_pitch_misses_assumed_comment_above_key():
    """Under-flagging is the dangerous direction: the number is quoted on stage as 'not ASSUMED'. A full-line comment
    directly above a key is the common YAML style for a caveat, and assumed_paths() drops it."""
    from tools.pitch.numbers import assumed_paths
    assert "server.electric_kw" in assumed_paths("server:\n  # ASSUMED: placeholder until measured\n  electric_kw: 1.0\n")


@pytest.mark.xfail(strict=True, reason="#17 r3 F32: 'NOT ASSUMED' is flagged as ASSUMED")
def test_finding_pitch_flags_not_assumed():
    from tools.pitch.numbers import assumed_paths
    assert assumed_paths("price:\n  chf_per_kwh: 0.33  # verified (ElCom), NOT ASSUMED\n") == set()


def test_pitch_assumed_guards():
    from tools.pitch.numbers import assumed_paths
    assert assumed_paths("jobs:\n  - name: a\n    runtime_h: 1\n  - name: b\n    runtime_h: 2  # ASSUMED\n") == {"jobs[1]"}
    assert assumed_paths("jobs:\n  - name: a\n    source: |\n      measured\n      ASSUMED runtime\n") == {"jobs[0]"}
    assert "house" in assumed_paths("house: {design_kw: 10.0}  # ASSUMED\n")
    real = assumed_paths((Path(__file__).resolve().parents[2] / "data" / "assumptions.yaml").read_text())
    assert {"hardware", "ballast.bid_chf_per_server_h"} <= real
