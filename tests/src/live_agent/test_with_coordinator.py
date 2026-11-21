"""live_agent v2 against the REAL coordinator v1 (coordinator.app.create_app, TestClient as httpx transport).

The coordinator clock is injected (lease expiry is driven by the test, not by waiting); the agent runs the real
jobs.runner subprocess with the cpu-hash backend. Heat signals are sent by the test (the agent itself reports
power/progress only), so the policy decisions are deterministic.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from common.config import ROOT
from coordinator.app import create_app
from coordinator.core import CHUNKS_PER_UNIT, LEASE_S
from live_agent.agent import Agent, Config

T0 = 1_764_000_000.0  # a winter hour: heat is wanted
TOK = {"admin": "A" * 40, "node-a": "a" * 40, "node-b": "b" * 40}
ROLES = {TOK["admin"]: "admin", TOK["node-a"]: "node:node-a", TOK["node-b"]: "node:node-b"}
ROUNDS = 3000  # ~0.15 s per chunk: long enough to act mid-unit, short enough to keep the test fast
FAST = dict(renew_s=0.25, upload_s=0.25,  # stays under the coordinator's 20 req/s per token
            stop_grace_s=5.0, poll_s=0.01, heartbeat_s=0.1)


class Clock:
    """Coordinator time: flows with real time (its rate limiter refills on this clock) plus a test-set offset
    (`clock.t += x` jumps forward, e.g. past a lease expiry)."""

    def __init__(self):
        self.t, self._m0 = T0, time.monotonic()

    def __call__(self):
        return self.t + (time.monotonic() - self._m0)


def H(who):
    return {"Authorization": f"Bearer {TOK[who]}"}


@pytest.fixture
def env(tmp_path):
    clock = Clock()
    app = create_app(tmp_path / "coord", tokens=ROLES, clock=clock)
    return type("Env", (), {"clock": clock, "app": app, "c": TestClient(app), "tmp": tmp_path})


def heat(env, node, warm=False):
    r = env.c.post(f"/v1/nodes/{node}/heartbeat", headers=H(node), json={
        "demand_kw": 0.0 if warm else 5.0, "tank_level_kwh": 35.0 if warm else 5.0})
    assert r.status_code == 200, r.text


def submit(env):
    r = env.c.post("/v1/jobs", headers=H("admin"), json={"job_type": "image_tagging", "customer_id": "cust-1",
                                                          "force": True})
    assert r.status_code == 200 and r.json()["admitted"], r.text
    return r.json()


def make_agent(env, node, sleeps=None, **cfg):
    hdr = H(node)
    http, hb = TestClient(env.app, headers=hdr), TestClient(env.app, headers=hdr)
    rec = sleeps if sleeps is not None else []

    def sleep(s):
        rec.append(s)
        time.sleep(min(s, 0.02))

    a = Agent(Config(node_id=node, site_id=f"site-{node[-1]}", eligible_classes=["public", "swiss-only"],
                     root=env.tmp / "agent", **{"default_rounds": ROUNDS, **FAST, **cfg}), http, hb_http=hb, sleep=sleep)
    a.register()
    heat(env, node)
    return a


def reference(tmp: Path) -> bytes:
    ck = tmp / "ref" / "job.ckpt"
    ck.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "jobs.runner", "image_tagging", "--checkpoint", str(ck), "--out",
                    str(ck.with_suffix(".out")), "--chunks", str(CHUNKS_PER_UNIT), "--rounds", str(ROUNDS)],
                   check=True, env={"PYTHONPATH": str(ROOT / "src")}, capture_output=True)
    return ck.with_suffix(".out").read_bytes()


def in_thread(fn):
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("r", fn()), daemon=True)
    t.start()
    return t, out


def wait_until(cond, timeout=60.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return
        time.sleep(0.005)
    raise AssertionError("condition not reached")


def status(env):
    return env.c.get("/v1/status", headers=H("admin")).json()


def done_units(env):
    import sqlite3
    db = sqlite3.connect(next((env.tmp / "coord").glob("*.db")))
    db.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in db.execute("SELECT * FROM units WHERE state='done'")]
    finally:
        db.close()


def ckpt_uploads(env, unit_id):
    import sqlite3
    db = sqlite3.connect(next((env.tmp / "coord").glob("*.db")))
    try:
        return db.execute("SELECT seq, next_chunk, node_id FROM checkpoints WHERE unit_id=? ORDER BY seq",
                          (unit_id,)).fetchall()
    finally:
        db.close()


# ------------------------------------------------------------------ happy path
def test_happy_path_against_real_coordinator(env):
    submit(env)
    a = make_agent(env, "node-a")
    assert a.step() == "completed"
    [u] = done_units(env)
    assert u["result_sha256"] == hashlib.sha256(reference(env.tmp)).hexdigest()
    assert u["completed_by"] == "node-a"
    assert ckpt_uploads(env, u["unit_id"]), "checkpoints were uploaded while running"
    assert a.heartbeat_once()
    assert a.step() == "hold"  # queue empty


# ------------------------------------------------------------------ lapse -> migrate exactly once
def test_lapse_then_other_node_resumes_from_checkpoint_exactly_once(env):
    submit(env)
    a = make_agent(env, "node-a")
    t, out = in_thread(a.step)
    wait_until(lambda: a.state["progress"] >= 0.15)
    wait_until(lambda: len(ckpt_uploads(env, a.state["running_unit"] or "x")) > 0 or out)
    unit = a.state["running_unit"]
    env.clock.t += LEASE_S + 1  # A missed its lease window (coordinator time)
    t.join(30)
    assert out["r"] == "lapsed" and not (a.workdir / unit).exists()
    assert "410" in a.state["last_error"]
    resumed_from = ckpt_uploads(env, unit)[-1][1]
    assert 0 < resumed_from < CHUNKS_PER_UNIT
    b = make_agent(env, "node-b")
    assert b.step() == "completed"
    [u] = done_units(env)
    assert u["completed_by"] == "node-b"
    ref = reference(env.tmp)
    assert u["result_sha256"] == hashlib.sha256(ref).hexdigest()  # == an uninterrupted run
    ref_ids = [int(x.split()[0]) for x in ref.decode().splitlines()]
    assert ref_ids == list(range(CHUNKS_PER_UNIT))  # complete() also enforced 0..N-1 each once
    a.heartbeat_once()  # A comes back: the coordinator sees why it stopped
    assert any(n["node_id"] == "node-a" and "410" in (n["last_error"] or "") for n in status(env)["nodes"])


# ------------------------------------------------------------------ pause on renew {hold}
def test_pause_on_hold_final_checkpoint_then_resume_on_other_node(env):
    submit(env)
    a = make_agent(env, "node-a")
    t, out = in_thread(a.step)
    wait_until(lambda: a.state["progress"] >= 0.1)
    unit = a.state["running_unit"]
    heat(env, "node-a", warm=True)  # house warm, tank full: next renew answers {hold, final_checkpoint_within_s}
    t.join(30)
    assert out["r"] == "paused"
    final = ckpt_uploads(env, unit)[-1]
    assert final[2] == "node-a" and 0 < final[1] < CHUNKS_PER_UNIT
    assert {"lease_paused", "lease_released"} <= {e["type"] for e in status(env)["recent_audit"]}
    b = make_agent(env, "node-b")
    assert b.step() == "completed"
    [u] = done_units(env)
    assert u["completed_by"] == "node-b"
    assert u["result_sha256"] == hashlib.sha256(reference(env.tmp)).hexdigest()


# ------------------------------------------------------------------ key denied
def test_key_denied_after_tamper(env):
    submit(env)
    a = make_agent(env, "node-a")
    assert env.c.post("/v1/nodes/node-a/tamper", headers=H("admin")).status_code == 200
    assert a.step() == "denied"
    assert "node_tampered" in a.state["last_error"]
    assert a.heartbeat_once()
    assert any(n["node_id"] == "node-a" and "node_tampered" in (n["last_error"] or "") for n in status(env)["nodes"])
    assert not [p for p in a.workdir.iterdir() if p.is_dir()]  # nothing ran
    assert not done_units(env)


# ------------------------------------------------------------------ backoff on 5xx
def test_backoff_on_5xx_no_busy_loop(env):
    sleeps: list[float] = []
    submit(env)
    a = make_agent(env, "node-a", sleeps=sleeps)
    real_post, fails = a.http.post, {"n": 6}

    def flaky(path, **kw):  # the real coordinator behind a proxy that 503s
        if fails["n"] > 0:
            fails["n"] -= 1
            import httpx
            return httpx.Response(503, request=httpx.Request("POST", path))
        return real_post(path, **kw)

    a.http.post = flaky
    assert [a.step() for _ in range(6)] == ["backoff"] * 6
    assert len(sleeps) == 6 and all(s >= 0.25 for s in sleeps) and max(sleeps) <= 10.0
    assert sleeps[-1] > sleeps[0]
    heat(env, "node-a")
    assert a.step() == "completed"
