"""#106 tools.e2e, in-process: a real coordinator (create_app) + two simulated nodes driven by the e2e's tick hook,
a simulated sitesim that honours the operator's scenario file, and a fake website. No network."""
from __future__ import annotations

import base64
import hashlib
import json
import time

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from fastapi.testclient import TestClient

import trust
from coordinator.app import create_app
from live_agent import wire
from tools.demo.e2e import E2E, STEPS, Config
from tools.demo.e2e_cli import main as cli_main

TOK = {"t-admin": "admin", "t-obs": "observer", "t-c1": "client:c1", "t-c2": "client:c2", "t-ha": "host:site-a",
       "t-hb": "host:site-b", "t-na": "node:node-a", "t-nb": "node:node-b", "t-sa": "site:site-a", "t-sb": "site:site-b"}
REG = {"node-a": {"certified": True, "max_classes": ["public", "swiss-only", "certified"], "region": "CH-BS",
                  "site_id": "site-a"},
       "node-b": {"certified": False, "max_classes": ["public"], "region": "CH-BS", "site_id": "site-b"}}
CHUNKS = 4


def out_log(chunks: int) -> bytes:  # the simulated runner: output depends only on the chunk ids (like jobs.runner)
    return b"".join(f"{i} {hashlib.sha256(str(i).encode()).hexdigest()}\n".encode() for i in range(chunks))


def relay(tc: TestClient):
    def handle(req: httpx.Request) -> httpx.Response:
        r = tc.request(req.method, req.url.raw_path.decode(), content=req.content, headers=dict(req.headers))
        h = {k: v for k, v in r.headers.items() if k.lower() not in ("content-encoding", "content-length")}
        return httpx.Response(r.status_code, headers=h, content=r.content)
    return httpx.MockTransport(handle)


class World:
    def __init__(self, tmp):
        self.dir = tmp / "coord"
        self.app = create_app(self.dir, tokens=TOK, registry=REG)
        self.app.state.limiter.allow = lambda key: True  # test seam: the e2e polls without sleeping
        self.tc = TestClient(self.app)
        self.nodes = {"node-a": {"tok": "t-na", "lease": None, "p": 0.0}, "node-b": {"tok": "t-nb", "lease": None, "p": 0.0}}
        for n, s in (("node-a", "t-na"), ("node-b", "t-nb")):
            ev = {"node_id": n, "region": "CH-BS", "measurement": "digitalheat-node-image-v1", "certified": n == "node-a"}
            classes = REG[n]["max_classes"]
            assert self.call(s, "post", "/v1/nodes/register", json={
                "node_id": n, "site_id": REG[n]["site_id"], "eligible_classes": classes, "server_kw_el": 1.0,
                "attestation": wire.attestation_to_json(trust.attest(n, ev))}).status_code == 200
        self.sitesim()

    def call(self, tok, method, path, **kw):
        return getattr(self.tc, method)(path, headers={"Authorization": f"Bearer {tok}", **kw.pop("headers", {})}, **kw)

    def sitesim(self):
        for site, tok in (("site-a", "t-sa"), ("site-b", "t-sb")):
            f = self.dir / "scenario" / site
            july = f.exists() and f.read_text().strip() == "july"
            self.call(tok, "post", f"/v1/sites/{site}/signal",
                      json={"demand_kw": 0.5 if july else 8.0, "tank_level_kwh": 0.0, "ts": 1.0})

    def tick(self):
        now = time.monotonic()  # the e2e polls with poll_s=0: advance the simulated world at most every 20 ms
        if now - getattr(self, "_last", 0.0) < 0.02:
            return
        self._last = now
        self.sitesim()
        for n, st in self.nodes.items():
            tok = st["tok"]
            if st["lease"] is None:
                L = self.call(tok, "post", f"/v1/nodes/{n}/lease").json()
                if "unit" in L:
                    st.update(lease=L, p=0.0)
                self.call(tok, "post", f"/v1/nodes/{n}/heartbeat", json={"watts": 10.0})
                continue
            L = st["lease"]
            r = self.call(tok, "post", f"/v1/leases/{L['lease_id']}/renew")
            if r.status_code != 200 or r.json().get("hold"):
                st["lease"] = None
                continue
            st["p"] = min(1.0, st["p"] + (0.004 if (L["unit"].get("rounds") or 0) > 10 else 0.25))  # long units run longer
            self.call(tok, "post", f"/v1/nodes/{n}/heartbeat",
                      json={"watts": 30.0, "running_unit": L["unit"]["unit_id"], "progress": st["p"]})
            if st["p"] >= 1.0:
                ch = L["unit"]["chunks"]
                data = out_log(ch)
                priv = X25519PrivateKey.from_private_bytes(base64.b64decode(L["key_release"]["key_b64"]))
                env = wire.envelope_to_bytes(trust.seal(wire.bundle_to_bytes(
                    {"next_chunk": ch, "out_bytes": len(data), "chunks": ch, "done": True}, data), priv.public_key()))
                self.call(tok, "post", f"/v1/leases/{L['lease_id']}/checkpoint", content=env, headers={
                    "X-Next-Chunk": str(ch), "X-Out-Bytes": str(len(data)), "X-Sha256": hashlib.sha256(env).hexdigest()})
                self.call(tok, "post", f"/v1/leases/{L['lease_id']}/complete",
                          json={"result_sha256": hashlib.sha256(data).hexdigest(), "chunk_ids": list(range(ch))})
                st["lease"] = None


def site_transport():
    nav = '<script>["01","Overview","DigitalHeat%2001%20Overview.dc.html"]</script>'
    page = '<script src="./support.js"></script><link rel="stylesheet" href="./vendor/fonts/fonts.css">'
    files = {"/Nav.dc.html": nav, "/DigitalHeat%2001%20Overview.dc.html": page, "/support.js": "//",
             "/vendor/fonts/fonts.css": "@font-face{src:url(a.woff2)}", "/vendor/fonts/a.woff2": "x",
             "/api/year/sizing": "{}", "/api/year": "{}", "/api/balance": "{}", "/api/nodes": "{}"}

    def handle(req: httpx.Request) -> httpx.Response:
        body = files.get(req.url.raw_path.decode().split("?")[0])
        return httpx.Response(200 if body is not None else 404, text=body or "missing")
    return httpx.MockTransport(handle)


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def cfg(w, **kw):
    t = relay(w.tc)
    return Config("http://coord.test", "http://site.test", "t-c1", "t-obs", host_token="t-ha", host_tokens=("t-ha", "t-hb"),
                  client2_token="t-c2", admin_token="t-admin", chunks=CHUNKS, rounds=10, rounds_long=11,
                  certified_nodes=("node-a",), timeout_s=30, pause_within_s=5, self_pause_grace_s=0.5, poll_s=0, sleep=lambda s: None,
                  transport=t, site_transport=site_transport(), tick=w.tick,
                  reference=lambda c, r: hashlib.sha256(out_log(c.chunks)).hexdigest(), **kw)


def test_all_steps_pass_in_process(world):
    lines = []
    e = E2E(cfg(world), out=lines.append)
    assert e.run(list(STEPS)), "\n".join(lines)
    assert [r[1] for r in e.results] == ["PASS"] * len(STEPS), lines
    assert lines[-1].startswith("SUMMARY 9 pass, 0 fail")
    nodes = {n["node_id"]: n for n in world.call("t-admin", "get", "/v1/ops/nodes").json()["items"]}
    assert not any(n["drained"] for n in nodes.values())  # left as found
    assert not (world.dir / "scenario" / "site-a").exists() or \
        (world.dir / "scenario" / "site-a").read_text().strip() == "coldest"
    assert all(not s["paused"] for s in world.call("t-admin", "get", "/v1/ops/sites").json()["items"])


def test_admin_steps_skip_without_admin_token(world):
    c = cfg(world)
    c.admin_token = None
    lines = []
    e = E2E(c, out=lines.append)
    assert e.run(["migrate", "pause", "certified", "audit"])
    assert {r[1] for r in e.results} == {"SKIP"}


def test_a_failure_exits_nonzero_and_cleanup_still_runs(world, monkeypatch):
    lines = []
    e = E2E(cfg(world), out=lines.append)

    def boom():
        e._drained.add("node-a")
        world.call("t-admin", "post", "/v1/ops/nodes/node-a/drain")
        raise httpx.ConnectError("coordinator down")
    monkeypatch.setattr(e, "step_audit", boom)
    assert e.run(["audit"]) is False
    assert lines[0].startswith("FAIL audit") and any("undrained node-a" in x for x in lines)
    assert not world.call("t-admin", "get", "/v1/ops/nodes").json()["items"][0]["drained"]


def test_cli_never_prints_tokens(tmp_path, capsys, monkeypatch):
    for n, t in (("c", "client-token-" + "x" * 20), ("o", "observer-token-" + "y" * 20)):
        (tmp_path / n).write_text(t)
    monkeypatch.setattr("tools.demo.e2e.E2E.run", lambda self, steps: True)
    assert cli_main(["--coordinator", "http://c", "--site", "http://s", "--client-token-file", str(tmp_path / "c"),
                     "--observer-token-file", str(tmp_path / "o"), "--only", "surface"]) == 0
    out = capsys.readouterr().out
    assert "x" * 20 not in out and "y" * 20 not in out
    with pytest.raises(SystemExit):
        cli_main(["--coordinator", "http://c", "--site", "http://s", "--client-token-file", str(tmp_path / "c"),
                  "--observer-token-file", str(tmp_path / "o"), "--only", "nope"])
