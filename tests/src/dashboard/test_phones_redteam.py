"""#138 red-team of the wow #2 phone fleet (src/dashboard/phones.py): every attack that broke it on c9be69d is a test
here (they failed before the fix in this PR)."""
import importlib
import json
import threading

import pytest
from fastapi.testclient import TestClient

from dashboard import phones
from dashboard.app import app

CODE = "basel-2026"


@pytest.fixture()
def c(tmp_path, monkeypatch):
    monkeypatch.setenv("DH_EVENT_CODE", CODE)
    monkeypatch.setattr(phones, "TOTAL_STEPS", 25)  # tests pin the old short job
    monkeypatch.setenv("DH_PHONES_ADMIN", "adm-secret")
    monkeypatch.setenv("DH_PHONES_STATE", str(tmp_path / "s.json"))
    t = [1000.0]
    monkeypatch.setattr(phones, "_clock", lambda: t[0])
    phones.S.update(devices={}, jobs={}, events=[], seq=0, joined=0)
    cl = TestClient(app, raise_server_exceptions=False)
    cl.t = t
    return cl


def J(c, name=None):
    r = c.post("/api/phones/join", json={"code": CODE, **({"name": name} if name else {})})
    assert r.status_code == 200, r.text
    j = r.json()
    return {"device_id": j["device_id"], "token": j["token"]}, j["role"]


def fleet(c, servers=3):
    """1 client + `servers` server phones (roles go client, server, server, server, client, ...)."""
    cl, role = J(c)
    assert role == "client"
    sv = [J(c)[0] for _ in range(servers)]
    return cl, sv


def held(c, sv):
    for s in sv:
        h = c.post("/api/phones/hb", json=s).json()
        if h.get("job"):
            return s, h["job"]
    return None, None


def run(c, s, job, steps):
    for _ in range(steps):
        c.t[0] += 1.0
        for x in [s]:
            c.post("/api/phones/hb", json=x)
        r = c.post("/api/phones/progress", json={**s, "job_id": job["job_id"], "step": job["step"] + 1})
        if r.status_code != 200:
            return r
        job = {**job, "step": r.json()["step"]}
    return job


def test_non_ascii_or_odd_event_code_is_403_not_500(c):
    for code in ("bäsel", "🔥", "x" * 64, " "):
        assert c.post("/api/phones/join", json={"code": code}).status_code == 403


def test_resume_while_holding_a_job_does_not_orphan_it(c):
    cl, sv = fleet(c, 2)
    jid = c.post("/api/phones/submit", json=cl).json()["job_id"]
    s, job = held(c, sv)
    assert job["job_id"] == jid
    c.post("/api/phones/resume", json=s)  # a double tap on the page, or a malicious phone
    jid2 = c.post("/api/phones/submit", json=cl).json()["job_id"]
    for _ in range(80):  # every job must still finish
        c.t[0] += 1.0
        for x in sv:
            h = c.post("/api/phones/hb", json=x).json()
            if h.get("job"):
                c.post("/api/phones/progress", json={**x, "job_id": h["job"]["job_id"], "step": h["job"]["step"] + 1})
    st = {j["id"]: j["state"] for j in c.get("/api/phones/state").json()["jobs"]}
    assert st == {jid: "done", jid2: "done"}


def test_progress_cannot_skip_work(c):
    cl, sv = fleet(c, 1)
    c.post("/api/phones/submit", json=cl)
    s, job = held(c, sv)
    r = c.post("/api/phones/progress", json={**s, "job_id": job["job_id"], "step": phones.TOTAL_STEPS})
    assert r.status_code == 200 and r.json()["step"] <= 2 and r.json()["state"] == "running"  # 1 step per second
    c.t[0] += 5.0
    c.post("/api/phones/hb", json=s)
    r = c.post("/api/phones/progress", json={**s, "job_id": job["job_id"], "step": phones.TOTAL_STEPS})
    assert r.json()["step"] <= 7


def test_progress_backwards_and_out_of_range(c):
    cl, sv = fleet(c, 1)
    c.post("/api/phones/submit", json=cl)
    s, job = held(c, sv)
    job = run(c, s, job, 5)
    r = c.post("/api/phones/progress", json={**s, "job_id": job["job_id"], "step": 1})
    assert r.json()["step"] == 5  # never back
    for bad in (-1, 10_001, "x", 2.5):
        assert c.post("/api/phones/progress", json={**s, "job_id": job["job_id"], "step": bad}).status_code == 422


def test_token_reuse_and_cross_device(c):
    cl, sv = fleet(c, 2)
    a, b = sv
    assert c.post("/api/phones/hb", json={"device_id": a["device_id"], "token": b["token"]}).status_code == 403
    assert c.post("/api/phones/stop", json={"device_id": b["device_id"], "token": a["token"]}).status_code == 403
    assert c.get("/api/phones/my", params={"device_id": a["device_id"], "token": "x" * 20}).status_code == 403
    # after a reset, old tokens are dead
    assert c.post("/api/phones/reset", headers={"X-DH-Admin": "adm-secret"}).status_code == 200
    assert c.post("/api/phones/hb", json=a).status_code == 403
    assert c.post("/api/phones/reset", headers={"X-DH-Admin": "wrong"}).status_code == 403


def test_stop_racing_progress_never_loses_or_doubles_steps(c):
    cl, sv = fleet(c, 3)
    jid = c.post("/api/phones/submit", json=cl).json()["job_id"]
    s, job = held(c, sv)
    job = run(c, s, job, 6)
    c.post("/api/phones/stop", json=s)
    late = c.post("/api/phones/progress", json={**s, "job_id": jid, "step": 9})  # in flight when STOP landed
    assert late.status_code == 410
    s2, job2 = held(c, [x for x in sv if x != s])
    assert job2["job_id"] == jid and job2["step"] == 6  # exactly where it stopped
    st = c.get("/api/phones/state").json()
    assert sum(d["steps_done"] for d in st["devices"]) == 6


def test_twenty_plus_joins_and_reloads_do_not_lock_the_fleet(c):
    for _ in range(phones.CAP):
        J(c)
    assert c.post("/api/phones/join", json={"code": CODE}).status_code == 429  # really full
    c.t[0] += 120  # every phone closed its tab / reloaded: none heartbeat any more
    for _ in range(phones.CAP):
        J(c)  # the same volunteers rejoin: the fleet must not stay full of ghosts


def test_concurrent_joins_are_unique_and_capped(c):
    out = []
    ths = [threading.Thread(target=lambda: out.append(c.post("/api/phones/join", json={"code": CODE}))) for _ in range(40)]
    [t.start() for t in ths]; [t.join() for t in ths]
    ok = [r.json()["device_id"] for r in out if r.status_code == 200]
    assert len(ok) == phones.CAP == len(set(ok)) and all(r.status_code in (200, 429) for r in out)


def test_flood_is_bounded(c):
    cl, sv = fleet(c, 1)
    for _ in range(5):
        c.post("/api/phones/submit", json=cl)
    assert len(c.get("/api/phones/state").json()["jobs"]) == 2  # 2 per client
    assert all(c.post("/api/phones/submit", json=s).status_code == 403 for s in sv)  # servers can't submit
    for _ in range(500):
        c.post("/api/phones/hb", json=sv[0])
    assert len(phones.S["events"]) <= 300
    big = c.post("/api/phones/join", json={"code": CODE, "name": "<img src=x onerror=alert(1)>" * 5})
    assert big.status_code == 422  # name max 24


def test_restart_keeps_progress(c, monkeypatch):
    cl, sv = fleet(c, 2)
    jid = c.post("/api/phones/submit", json=cl).json()["job_id"]
    s, job = held(c, sv)
    run(c, s, job, 7)
    saved = json.loads(open(phones._state_file()).read())
    assert saved["jobs"][jid]["step"] == 7
    phones.S.update(devices={}, jobs={}, events=[], seq=0, joined=0)
    phones._load()  # the dashboard restarted
    assert phones.S["jobs"][jid]["step"] == 7
    c.t[0] += 30  # everyone went silent during the restart -> the job is re-queued with its progress, then reassigned
    for x in sv:
        c.post("/api/phones/hb", json=x)
    j = {x["id"]: x for x in c.get("/api/phones/state").json()["jobs"]}[jid]
    assert j["step"] == 7 and j["state"] == "running"
    run(c, *held(c, sv), phones.TOTAL_STEPS)
    assert {x["id"]: x for x in c.get("/api/phones/state").json()["jobs"]}[jid]["state"] == "done"
