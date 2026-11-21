"""coordinator v1.1: site signals, sitesim replay against an in-process coordinator, monotonic rate limiter."""
from __future__ import annotations

import random

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from coordinator import sitesim
from coordinator.__main__ import make_tokens
from coordinator.auth import load_tokens

from test_coordinator import H, ROLES, TOK, Clock, env, lease, register, submit  # noqa: F401

SITE_TOK = "s" * 40
ROLES_S = {**ROLES, SITE_TOK: "site:site-a", "t" * 40: "site:site-b"}


@pytest.fixture
def senv(tmp_path):
    from coordinator.app import create_app
    clock = Clock()
    app = create_app(tmp_path, tokens=ROLES_S, clock=clock)
    return type("E", (), {"clock": clock, "app": app, "c": TestClient(app)})


def sig(c, site="site-a", hdr=None, **kw):
    body = {"demand_kw": 5.0, "tank_level_kwh": 5.0, "ts": 1.0, **kw}
    return c.post(f"/v1/sites/{site}/signal", headers=hdr or {"Authorization": f"Bearer {SITE_TOK}"}, json=body)


def test_signal_auth(senv):
    c = senv.c
    assert c.post("/v1/sites/site-a/signal", json={"demand_kw": 1, "tank_level_kwh": 1, "ts": 1}).status_code == 401
    assert sig(c).status_code == 200
    assert sig(c, hdr=H("admin")).status_code == 200
    assert sig(c, site="site-b").status_code == 403  # another site's token
    assert sig(c, hdr=H("node-a")).status_code == 403
    assert sig(c, hdr=H("observer")).status_code == 403


@pytest.mark.parametrize("bad", [{"demand_kw": -1}, {"tank_level_kwh": -0.1}, {"tank_level_kwh": 35.1},
                                 {"ts": -1}, {"extra": 1}, {"demand_kw": "x"}])
def test_signal_validation(senv, bad):
    assert sig(senv.c, **bad).status_code == 422


def test_signal_nan_is_422(senv):
    r = senv.c.post("/v1/sites/site-a/signal", headers={"Authorization": f"Bearer {SITE_TOK}",
                                                         "Content-Type": "application/json"},
                    content=b'{"demand_kw": NaN, "tank_level_kwh": 1, "ts": 1}')
    assert r.status_code == 422


def test_signal_is_durable_and_stale_signal_degrades(senv, tmp_path):
    c = senv.c
    register(c, "node-a")  # site-a; heartbeat carries legacy fields too
    assert sig(c, demand_kw=4.0, tank_level_kwh=7.0).status_code == 200
    st = c.get("/v1/status", headers=H("observer")).json()
    assert st["sites"][0]["site_id"] == "site-a" and st["sites"][0]["tank_level_kwh"] == 7.0
    assert st["degraded"] == []
    senv.clock.t += 10  # > 2 ticks without a site signal; a legacy heartbeat does not refresh it
    c.post("/v1/nodes/node-a/heartbeat", headers=H("node-a"), json={"demand_kw": 5.0, "tank_level_kwh": 5.0})
    st = c.get("/v1/status", headers=H("observer")).json()
    assert st["degraded"] == ["node-a"] and st["sites"][0]["degraded"] is True
    from coordinator.app import create_app  # restart: the signal survives (timers frozen while down)
    app2 = create_app(tmp_path, tokens=ROLES_S, clock=senv.clock)
    st = TestClient(app2).get("/v1/status", headers=H("observer")).json()
    assert st["sites"][0]["demand_kw"] == 4.0
    assert sig(TestClient(app2)).status_code == 200
    assert TestClient(app2).get("/v1/status", headers=H("observer")).json()["degraded"] == []


def test_warm_site_signal_makes_renew_hold(senv):
    c = senv.c
    register(c, "node-a")
    sig(c, demand_kw=5.0, tank_level_kwh=5.0)
    submit(c)
    L = lease(c, "node-a")
    lid = L["lease_id"]
    assert c.post(f"/v1/leases/{lid}/renew", headers=H("node-a")).json().get("ok") is True
    st = c.get("/v1/status", headers=H("admin")).json()
    assert st["sites"][0]["heat_produced_kw"] > 0
    sig(c, demand_kw=0.0, tank_level_kwh=35.0)  # warm: the site signal wins over the cold heartbeat values
    assert c.post(f"/v1/leases/{lid}/renew", headers=H("node-a")).json()["hold"] is True


# ------------------------------------------------------------------ rate limiter (red team: app.py:86)
def test_rate_limiter_ignores_frozen_injected_clock(tmp_path):
    from coordinator.app import create_app
    app_clock, mono = Clock(), [0.0]  # both frozen: the bucket can only refill when `mono` advances
    c = TestClient(create_app(tmp_path, tokens=ROLES_S, clock=app_clock, monotonic=lambda: mono[0]))
    codes = [c.get("/v1/status", headers=H("observer")).status_code for _ in range(45)]
    assert codes[:40] == [200] * 40 and set(codes[40:]) == {429}
    app_clock.t += 3600  # app clock jumping does not refill the limiter
    assert c.get("/v1/status", headers=H("observer")).status_code == 429
    mono[0] += 0.2  # monotonic source refills ~4 tokens at 20/s
    assert c.get("/v1/status", headers=H("observer")).status_code == 200


def test_make_site_tokens(tmp_path):
    p = tmp_path / "tokens.json"
    assert make_tokens(p, ["node-a"], ["site-a", "site-b"])
    roles = sorted(load_tokens(p).values())
    assert roles == ["admin", "node:node-a", "observer", "site:site-a", "site:site-b"]
    with pytest.raises(SystemExit):
        make_tokens(tmp_path / "x.json", [], ["Bad/Id"])


def test_make_tokens_adds_missing_roles(tmp_path, capsys):
    import os
    import stat
    from coordinator.__main__ import main
    p = tmp_path / "tokens.json"
    assert make_tokens(p, ["node-a"])
    before = load_tokens(p)
    assert main(["--state", str(tmp_path), "--make-site-tokens", "site-a"]) == 0
    after = load_tokens(p)
    assert all(after[t] == r for t, r in before.items())  # existing tokens unchanged
    assert sorted(after.values()) == ["admin", "node:node-a", "observer", "site:site-a"]
    out = capsys.readouterr().out
    assert not any(t in out for t in after)  # never printed
    if os.name == "posix":
        assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert not make_tokens(p, ["node-a"], ["site-a"])  # nothing missing: no rewrite
    assert load_tokens(p) == after
    assert [x.name for x in tmp_path.iterdir()] == ["tokens.json"]  # no temp left behind


# ------------------------------------------------------------------ sitesim
def profile():
    from house_model import load_reference_profile
    return load_reference_profile()


def test_sitesim_replays_coldest_day_against_coordinator(senv):
    p = profile()
    rows = sitesim.replay_rows(p, "coldest")
    means = p["temp_c"].groupby(p.index.date).mean()
    assert rows.index[0].date() == means.idxmin() and len(rows) == 24
    coldest_hour = rows["temp_c"].idxmin()
    http = TestClient(senv.app, headers={"Authorization": f"Bearer {SITE_TOK}"})
    sleeps = []
    sim = sitesim.SiteSim(http, "site-a", rows, speed=3600, capacity_kwh=35.0, tank_kwh=10.0, sleep=sleeps.append)
    sim.run()
    assert len(sim.posted) == 24 and sleeps == [1.0] * 24
    by_ts = {b["ts"]: b for b in sim.posted}
    b = by_ts[coldest_hour.timestamp()]
    assert b["demand_kw"] == pytest.approx(float(rows.loc[coldest_hour, "demand_kw"]))
    # no node runs: heat used = 0, so the tank drains by the demand each sim hour, clamped at 0
    assert sim.posted[1]["tank_level_kwh"] == pytest.approx(max(0.0, 10.0 - rows["demand_kw"].iloc[0]), abs=1e-5)
    st = senv.c.get("/v1/status", headers=H("observer")).json()
    assert st["sites"][0]["demand_kw"] == pytest.approx(sim.posted[-1]["demand_kw"])
    assert sitesim.replay_rows(p, "july").index[0].strftime("%Y-%m-%d") == "2025-07-15"


def test_sitesim_backs_off_with_jitter_on_network_errors():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] <= 3:
            raise httpx.ConnectError("down")
        if calls["n"] == 4:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True, "heat_used_kw": 2.0})

    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://x")
    rows = pd.DataFrame({"demand_kw": [1.0], "temp_c": [0.0]},
                        index=pd.DatetimeIndex([pd.Timestamp("2025-01-01", tz="Europe/Zurich")]))
    sleeps = []
    sim = sitesim.SiteSim(http, "site-a", rows, capacity_kwh=35.0, tank_kwh=0.0, sleep=sleeps.append,
                          rng=random.Random(1))
    sim.step()
    backoffs = sleeps[:4]
    assert len(sleeps) == 5 and sleeps[-1] == 1.0
    for i, d in enumerate(backoffs):
        base = 0.5 * 2 ** i
        assert base * 0.5 <= d <= base
    assert len(set(round(d / (0.5 * 2 ** i), 6) for i, d in enumerate(backoffs))) > 1  # jittered
    assert sim.tank_kwh == pytest.approx(1.0)  # (heat 2 - demand 1) * 1 h
    assert sim.failures == 0 and sim.done()


def test_sitesim_fatal_on_403():
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403)), base_url="http://x")
    rows = pd.DataFrame({"demand_kw": [1.0]}, index=pd.DatetimeIndex([pd.Timestamp("2025-01-01", tz="UTC")]))
    with pytest.raises(sitesim.Fatal):
        sitesim.SiteSim(http, "site-a", rows, sleep=lambda s: None).post()
