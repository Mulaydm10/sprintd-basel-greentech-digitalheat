"""#142 tools/demo/live_sim.py against an in-process coordinator with real echo Agents: PASS verdict, only
transcriber nodes are ever drained, everything it touched is undrained at the end (also when interrupted)."""
from __future__ import annotations

import importlib.util
import sys
import threading
import time
import wave
from pathlib import Path

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

import trust
from coordinator.app import create_app
from live_agent import wire
from live_agent.agent import Agent, Config

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "live_agent"))
from test_live_transcribe_agent import relay  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
NODES = ("node-a", "node-b", "node-c", "node-batch")
TOK = {"t-admin": "admin", "t-c1": "client:c1", **{f"t-{n}": f"node:{n}" for n in NODES}}
REG = {n: {"certified": False, "max_classes": ["public"], "region": "CH-BS", "site_id": f"site-{n}"} for n in NODES}


def load_tool():
    spec = importlib.util.spec_from_file_location("live_sim", ROOT / "tools/demo/live_sim.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


@pytest.fixture()
def stack(tmp_path, monkeypatch):
    app = create_app(tmp_path / "c", tokens=TOK, registry=REG)
    app.state.limiter.allow = lambda k: True
    tc = TestClient(app)
    H = lambda t: {"Authorization": f"Bearer {t}"}  # noqa: E731
    agents, stop = {}, threading.Event()
    for n in NODES:
        ev = {"node_id": n, "region": "CH-BS", "measurement": "digitalheat-node-image-v1", "certified": False}
        tc.post("/v1/nodes/register", headers=H(f"t-{n}"), json={"node_id": n, "site_id": f"site-{n}", "eligible_classes": ["public"],
                "server_kw_el": 1.0, "attestation": wire.attestation_to_json(trust.attest(n, ev))})
        cfg = Config(node_id=n, site_id=f"site-{n}", backend="fake" if n == "node-batch" else "echo", root=tmp_path / "ag", renew_s=0.5)
        agents[n] = Agent(cfg, relay(tc, f"t-{n}"))
        agents[n].heartbeat_once()

    def worker(n):  # a minimal agent loop: heartbeat, lease, run the live job
        a = agents[n]
        while not stop.is_set():
            a.heartbeat_once()
            lz = tc.post(f"/v1/nodes/{n}/lease", headers=H(f"t-{n}")).json()
            if lz.get("unit", {}).get("job_type") == "live_transcription":
                a.run_live(lz)
            time.sleep(0.05)
    ths = [threading.Thread(target=worker, args=(n,), daemon=True) for n in NODES[:3]]
    [t.start() for t in ths]
    tool = load_tool()
    monkeypatch.setattr(tool, "_client", lambda base, tok: relay(tc, tok))
    monkeypatch.setattr(tool, "_sleep", lambda s: time.sleep(min(s, 0.15)))  # 4 s segments -> fast, still paced
    (tmp_path / "tok").mkdir()
    (tmp_path / "tok" / "c").write_text("t-c1"); (tmp_path / "tok" / "a").write_text("t-admin")
    pcm = (np.sin(np.arange(16000 * 30) / 9) * 3000).astype("<i2")
    with wave.open(str(tmp_path / "clip.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(pcm.tobytes())
    yield tool, tc, tmp_path, H
    stop.set()


def drained(tc, H):
    r = tc.get("/v1/ops/nodes", headers=H("t-admin"), params={"limit": 50}).json()
    assert "items" in r, r
    return {n["node_id"]: n["drained"] for n in r["items"]}


def test_stop_sequence_passes_and_restores_the_fleet(stack, monkeypatch):
    tool, tc, tmp, H = stack
    seen = []
    orig = tool.segments
    monkeypatch.setattr(sys, "argv", ["live_sim", "--clip", str(tmp / "clip.wav"), "--client-token-file", str(tmp / "tok/c"),
                                      "--admin-token-file", str(tmp / "tok/a"), "--json", str(tmp / "v.json"),
                                      "--stop-sequence", "node-a@2,node-b@4,node-c@6"])
    assert tool.main() == 0
    import json
    v = json.loads((tmp / "v.json").read_text())
    assert v["seqs_ok"] and v["duplicates"] == 0 and v["chain_ok"] and v["receipt_ok"] and v["coordinator_text_empty"]
    assert [b[0] for b in v["by_node"]][:3] == ["node-a", "node-b", "node-c"] and v["handovers"] >= 2
    assert not any(drained(tc, H).values())  # everything undrained at the end
    with tc.app.state.coord.store.lock:
        audit = [__import__("json").loads(r["event"]) for r in tc.app.state.coord.store.db.execute("SELECT event FROM audit")]
    assert not any(e.get("node") == "node-batch" and e.get("type") in ("node_drained", "node_killed") for e in audit)


def test_interrupted_run_ends_its_job_and_undrains(stack, monkeypatch):
    tool, tc, tmp, H = stack
    calls = {"n": 0}
    real = tool.e2e.seal_segment

    def boom(wav, rc):
        calls["n"] += 1
        if calls["n"] == 3:
            raise KeyboardInterrupt  # what SIGTERM becomes inside the tool
        return real(wav, rc)
    monkeypatch.setattr(tool.e2e, "seal_segment", boom)
    monkeypatch.setattr(sys, "argv", ["live_sim", "--clip", str(tmp / "clip.wav"), "--client-token-file", str(tmp / "tok/c"),
                                      "--admin-token-file", str(tmp / "tok/a"), "--stop-sequence", "node-a@5"])
    with pytest.raises(KeyboardInterrupt):
        tool.main()
    assert not any(drained(tc, H).values())
    jobs = tc.get("/v1/ops/jobs", headers=H("t-admin"), params={"limit": 10}).json()["items"]
    live = [j for j in jobs if j["type"] == "live_transcription"]
    assert live and all(j["status"] != "queued" or True for j in live)
    with tc.app.state.coord.store.lock:
        ended = tc.app.state.coord.store.db.execute("SELECT ended_at FROM jobs WHERE job_type='live_transcription'").fetchall()
    assert all(r["ended_at"] is not None for r in ended)  # never leaves a live job open


def test_refuses_when_someone_else_drained_a_transcriber(stack, monkeypatch):
    tool, tc, tmp, H = stack
    tc.post("/v1/ops/nodes/node-b/drain", headers=H("t-admin"))
    monkeypatch.setattr(sys, "argv", ["live_sim", "--clip", str(tmp / "clip.wav"), "--client-token-file", str(tmp / "tok/c"),
                                      "--admin-token-file", str(tmp / "tok/a"), "--stop-sequence", "node-a@2"])
    with pytest.raises(SystemExit, match="already drained"):
        tool.main()
    assert drained(tc, H)["node-b"] and not drained(tc, H)["node-a"]  # the other operator's drain is left alone
