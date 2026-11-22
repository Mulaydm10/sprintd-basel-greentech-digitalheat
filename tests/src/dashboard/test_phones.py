"""Wow #2 phone fleet: join by code, 3:1 roles, cap, STOP hands progress to the next phone, silent phone, auth."""
import pytest
from fastapi.testclient import TestClient

from dashboard import phones
from dashboard.app import app


@pytest.fixture()
def c(tmp_path, monkeypatch):
    monkeypatch.setenv("DH_EVENT_CODE", "basel-2026")
    monkeypatch.setattr(phones, "TOTAL_STEPS", 25)  # tests pin the old short job
    monkeypatch.setenv("DH_PHONES_ADMIN", "adm-secret")
    monkeypatch.setenv("DH_PHONES_STATE", str(tmp_path / "s.json"))
    t = [1000.0]
    monkeypatch.setattr(phones, "_clock", lambda: t[0])
    phones.S.update(devices={}, jobs={}, events=[], seq=0, joined=0)
    cl = TestClient(app)
    cl.t = t
    return cl


def join(c, code="basel-2026"):
    return c.post("/api/phones/join", json={"code": code})


def creds(r):
    j = r.json()
    return {"device_id": j["device_id"], "token": j["token"]}


def test_wrong_code_and_cap(c, monkeypatch):
    assert join(c, "nope").status_code == 403
    monkeypatch.setattr(phones, "CAP", 3)
    for _ in range(3):
        assert join(c).status_code == 200
    assert join(c).status_code == 429


def test_roles_three_servers_per_client(c):
    roles = [join(c).json()["role"] for _ in range(8)]
    assert roles.count("client") == 2 and roles.count("server") == 6 and roles[0] == "client"


def test_job_runs_stop_moves_with_progress_and_completes(c):
    cli = creds(join(c))
    a, b = creds(join(c)), creds(join(c))
    for s in (a, b):
        c.post("/api/phones/hb", json=s)
    jid = c.post("/api/phones/submit", json=cli).json()["job_id"]
    ha, hb_ = c.post("/api/phones/hb", json=a).json(), c.post("/api/phones/hb", json=b).json()
    first, second = (a, b) if "job" in ha else (b, a)
    c.t[0] += 10  # 10 s of heating = 10 steps (faster reports are capped, #138)
    assert c.post("/api/phones/progress", json={**first, "job_id": jid, "step": 10}).json()["step"] == 10
    c.post("/api/phones/hb", json=second)  # still online
    r = c.post("/api/phones/stop", json=first).json()
    assert r["released"] == jid and r["step"] == 10 and r["now_on"] == second["device_id"]
    job = c.post("/api/phones/hb", json=second).json()["job"]
    assert job["step"] == 10 and job["hops"] == 2                 # progress kept across the handover
    assert c.post("/api/phones/progress", json={**first, "job_id": jid, "step": 20}).status_code == 410
    c.t[0] += phones.TOTAL_STEPS
    done = c.post("/api/phones/progress", json={**second, "job_id": jid, "step": phones.TOTAL_STEPS}).json()
    assert done["state"] == "done"
    my = c.get("/api/phones/my", params=cli).json()["jobs"][0]
    assert my["state"] == "done" and my["hops"] == 2


def test_silent_phone_releases_job(c):
    cli, a, b = creds(join(c)), creds(join(c)), creds(join(c))
    c.post("/api/phones/hb", json=a)
    jid = c.post("/api/phones/submit", json=cli).json()["job_id"]
    c.t[0] += 5
    c.post("/api/phones/progress", json={**a, "job_id": jid, "step": 5})
    c.t[0] += 3
    c.post("/api/phones/hb", json=b)                               # b online, a goes silent
    c.t[0] += phones.HB_TIMEOUT_S
    c.post("/api/phones/hb", json=b)
    job = c.post("/api/phones/hb", json=b).json()["job"]
    assert job["job_id"] == jid and job["step"] == 5


def test_auth_and_roles_enforced(c):
    cli, a = creds(join(c)), creds(join(c))
    assert c.post("/api/phones/hb", json={**a, "token": "x" * 20}).status_code == 403
    assert c.post("/api/phones/submit", json=a).status_code == 403  # servers don't submit
    assert c.post("/api/phones/reset").status_code == 403
    assert c.post("/api/phones/reset", headers={"x-dh-admin": "adm-secret"}).json()["ok"]


def test_state_is_anonymised_and_qr_served(c):
    join(c)
    st = c.get("/api/phones/state").json()
    assert "token" not in str(st) and "token_hash" not in str(st)
    assert c.get("/api/phones/qr.svg").headers["content-type"].startswith("image/svg")
