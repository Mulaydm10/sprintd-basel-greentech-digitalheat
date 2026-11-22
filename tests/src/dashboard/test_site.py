"""#91: Dhruv's frontend served as-is from the dashboard, offline, with a local-only LIVE proxy to the coordinator."""
from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import dashboard.app as dash
import dashboard.live as live
from dashboard import site_build

SITE = site_build.DST
PAGES = sorted(p.name for p in site_build.SRC.glob("*.dc.html"))
LOCAL = ("127.0.0.1", 50000)


@pytest.fixture
def client():
    return TestClient(dash.app, client=LOCAL)


# ------------------------------------------------------------------ as-is
def test_committed_site_is_exactly_the_build_of_the_export(tmp_path):
    """The shipped site = design/frontend + the WIRING edits only (no visual/copy change can sneak in)."""
    built = site_build.build(dst=tmp_path)
    extras = sorted(p.name for p in site_build.EXTRA.glob("*.dc.html"))
    assert sorted(built) == sorted(PAGES + list(site_build.RUNTIME) + extras)
    for name in built:
        assert (tmp_path / name).read_bytes() == (SITE / name).read_bytes(), f"{name}: rerun python -m dashboard.site_build"


def test_runtime_files_are_verbatim():
    for f in site_build.RUNTIME:
        assert (SITE / f).read_bytes() == (site_build.SRC / f).read_bytes()


def test_only_the_listed_wiring_differs():
    for name in PAGES:
        orig = (site_build.SRC / name).read_text(encoding="utf-8")
        new = (SITE / name).read_text(encoding="utf-8")
        undo = new.replace(site_build.SUPPORT_LOCAL, site_build.SUPPORT)
        if site_build.FONT_LINKS in orig:
            undo = undo.replace(site_build.FONT_LOCAL, site_build.FONT_LINKS)
        if name in site_build.API_PAGES:
            undo = undo.replace(site_build.API_LOCAL, site_build.API_DEFAULT)
        if name == site_build.NAV_PAGE:
            for old, newer in reversed(site_build.NAV_LAYOUT):
                undo = undo.replace(newer, old)
            undo = undo.replace(site_build.NAV_NEW, site_build.NAV_OLD).replace(site_build.NAV_MAX_NEW, site_build.NAV_MAX_OLD)
        if name == site_build.LIVE_PAGE:
            for old, newer in ((site_build.FLEET_SCRIPT_OLD, site_build.FLEET_SCRIPT_NEW),   # undo in reverse build order
                               (site_build.FLEET_ANCHOR, site_build.FLEET_ROW),
                               (site_build.LIVE_ANCHOR, site_build.LIVE_ROW), (site_build.POLL_OLD, site_build.POLL_NEW),
                               (site_build.ACT_METHOD, site_build.ACT_NEW), (site_build.RET_OLD, site_build.RET_NEW)):
                undo = undo.replace(newer, old)
        assert undo == orig, name


# ------------------------------------------------------------------ served + offline
@pytest.mark.parametrize("path", ["/", "/dashboard", "/support.js", "/deck-stage.js", "/vendor/resources.js",
                                  "/vendor/react.production.min.js", "/vendor/react-dom.production.min.js",
                                  "/vendor/babel.min.js", "/vendor/fonts/fonts.css"] + ["/" + p for p in PAGES])
def test_every_page_and_asset_is_served(client, path):
    r = client.get(path)
    assert r.status_code == 200, path
    if path == "/":
        assert "Pitch Deck" in r.text or "<x-dc" in r.text


def test_api_routes_still_win_over_the_static_mount(client):
    assert client.get("/api/balance").status_code == 200
    assert client.get("/api/live/state").status_code == 200
    assert client.get("/no-such-file.html").status_code == 404


def test_no_external_fetch_at_runtime():
    """Pages and CSS reference no other host; the only absolute URLs left are support.js's CDN constants, and every
    one of those is overridden by vendor/resources.js (the runtime's own window.__resources hook)."""
    for f in list(SITE.glob("*.html")) + [SITE / "vendor" / "fonts" / "fonts.css", SITE / "vendor" / "resources.js"]:
        text = f.read_text(encoding="utf-8")
        hosts = {m for m in re.findall(r"""(?:src|href)=["']https?://([^/"']+)""", text)}
        assert not hosts, (f.name, hosts)
        if f.suffix == ".css":
            assert "http" not in text
    cdn = set(re.findall(r'"(https://unpkg\.com/[^"]+)"', (SITE / "support.js").read_text()))
    res = (SITE / "vendor" / "resources.js").read_text()
    assert cdn and all(u in res for u in cdn), cdn
    for f in (SITE / "vendor" / "fonts").glob("*.woff2"):
        assert f.stat().st_size > 1000


def test_vendored_bytes_match_the_runtime_sri():
    js = (SITE / "support.js").read_text()
    for const, f in (("REACT_SRI", "react.production.min.js"), ("REACT_DOM_SRI", "react-dom.production.min.js"),
                     ("BABEL_SRI", "babel.min.js")):
        want = re.search(rf'var {const} = "([^"]+)"', js).group(1)
        got = "sha384-" + base64.b64encode(hashlib.sha384((SITE / "vendor" / f).read_bytes()).digest()).decode()
        assert got == want, f


def test_api_base_defaults_to_same_origin():
    for name in site_build.API_PAGES:
        assert site_build.API_LOCAL in (SITE / name).read_text(encoding="utf-8")


# ------------------------------------------------------------------ LIVE proxy guards
@pytest.fixture
def live_on(monkeypatch, tmp_path):
    tok = tmp_path / "admin"
    tok.write_text("tok-admin\n")
    monkeypatch.setenv("DH_LIVE_ACTIONS", "1")
    monkeypatch.setenv("DH_ADMIN_TOKEN_FILE", str(tok))
    monkeypatch.setenv("DH_COORDINATOR_URL", "http://coord.test")
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        assert req.headers["authorization"] == "Bearer tok-admin"
        if req.url.path == "/v1/ops/overview":
            return httpx.Response(200, json={"nodes": {}, "audit": {"ok": True}})
        if req.url.path == "/v1/events/poll":
            return httpx.Response(200, json={"events": [{"id": 1, "type": "x", "ts": "t"}], "last_id": 1})
        return httpx.Response(200, json={"ok": True})
    monkeypatch.setattr(live, "transport", httpx.MockTransport(handler))
    return seen


H = {"X-DH-Live": "1"}


def relay_to(cc):
    """An httpx MockTransport handler that forwards to an in-process TestClient. Converts explicitly to httpx.Response:
    where Starlette's TestClient is built on httpx2 (macmini's venv, #91), its response is not an httpx.Response and
    MockTransport rejects it ("Cannot use an async handler in a sync Client")."""
    def handler(req: httpx.Request) -> httpx.Response:
        r = cc.request(req.method, req.url.raw_path.decode(), content=req.content, headers=dict(req.headers))
        hdrs = {k: v for k, v in r.headers.items() if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")}
        return httpx.Response(r.status_code, headers=hdrs, content=r.content)
    return handler


def test_live_off_by_default(client, monkeypatch):
    monkeypatch.delenv("DH_LIVE_ACTIONS", raising=False)
    assert client.get("/api/live/state").json()["enabled"] is False
    assert client.post("/api/live/kill", headers=H).status_code == 403


def test_non_local_client_is_refused(live_on):
    remote = TestClient(dash.app, client=("10.1.2.3", 40000))
    assert remote.get("/api/live/state").status_code == 403
    for p, body in (("/api/live/kill", None), ("/api/live/heat", {"replay": "july"}), ("/api/live/tamper", None)):
        assert remote.post(p, json=body, headers=H).status_code == 403
    assert not live_on  # never reached the coordinator


def test_actions_need_the_header_and_same_origin(client, live_on):
    assert client.post("/api/live/kill").status_code == 403
    assert client.post("/api/live/kill", headers={**H, "Origin": "https://evil.example"}).status_code == 403
    assert not live_on
    assert client.post("/api/live/kill", headers={**H, "Origin": "http://testserver"}).status_code == 200


def test_actions_hit_the_coordinator_ops_api(client, live_on, monkeypatch):
    monkeypatch.setenv("DH_LIVE_KILL_NODE", "node-omen2")
    monkeypatch.setenv("DH_LIVE_SITE", "site-mac")
    monkeypatch.setenv("DH_LIVE_TAMPER_NODE", "node-demo-tamper")
    assert client.post("/api/live/kill", headers=H).json()["summary"].startswith("pulled the plug on node-omen2")
    assert client.post("/api/live/heat", json={"replay": "july"}, headers=H).status_code == 200
    assert client.post("/api/live/tamper", headers=H).status_code == 200
    calls = [(r.method, r.url.path, r.content) for r in live_on]
    assert calls == [("GET", "/v1/ops/nodes", b""),  # which unit the node runs (to auto-restore once it moves)
                     ("POST", "/v1/ops/nodes/node-omen2/drain", b""),  # #97: drain first, so the unit moves
                     ("POST", "/v1/ops/nodes/node-omen2/kill", b""),
                     ("POST", "/v1/ops/sites/site-mac/scenario", b'{"replay":"july"}'),
                     ("POST", "/v1/ops/nodes/node-demo-tamper/tamper", b"")]
    live._undrain("node-omen2", "test cleanup")
    st = client.get("/api/live/state").json()
    assert st["heat"] == "july" and st["events"][0]["type"] == "x" and "tok-admin" not in str(st)


def test_heat_body_is_strict_and_targets_are_server_side(client, live_on):
    for body in ({"replay": "year"}, {"replay": "july", "site": "../x"}, {}):
        assert client.post("/api/live/heat", json=body, headers=H).status_code == 422
    assert client.post("/api/live/kill?node=node-mac", headers=H).status_code == 200
    assert live_on[-1].url.path == "/v1/ops/nodes/node-omen2/kill"  # the query cannot pick the target


@pytest.mark.parametrize("node", sorted(live.NEVER_TAMPER))
def test_demo_nodes_are_never_tampered(client, live_on, monkeypatch, node):
    monkeypatch.setenv("DH_LIVE_TAMPER_NODE", node)
    assert client.post("/api/live/tamper", headers=H).status_code == 403
    assert not live_on


def test_coordinator_errors_are_relayed_not_500(client, live_on, monkeypatch):
    monkeypatch.setattr(live, "transport", httpx.MockTransport(lambda r: httpx.Response(404, json={"detail": "unknown node"})))
    r = client.post("/api/live/kill", headers=H)
    assert r.status_code == 404 and "unknown node" in r.json()["detail"]

    def down(r):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(live, "transport", httpx.MockTransport(down))
    assert client.post("/api/live/kill", headers=H).status_code == 502
    assert "error" in client.get("/api/live/state").json()


def test_missing_token_file_is_503(client, live_on, monkeypatch):
    monkeypatch.setenv("DH_ADMIN_TOKEN_FILE", "")
    assert client.post("/api/live/kill", headers=H).status_code == 503


def test_admin_token_never_reaches_the_browser(client, live_on):
    for p in ["/", "/api/live/state", "/" + site_build.LIVE_PAGE, "/vendor/resources.js"]:
        assert "tok-admin" not in client.get(p).text


# ------------------------------------------------------------------ against the real coordinator (in-process)
def test_live_actions_against_a_real_coordinator(client, monkeypatch, tmp_path):
    coordinator_app = pytest.importorskip("coordinator.app")
    from live_agent import wire
    from trust import attest
    toks = {"tok-admin": "admin", "tok-n": "node:node-omen2", "tok-t": "node:node-demo-tamper", "tok-s": "site:site-mac"}
    reg = {n: {"certified": False, "max_classes": ["public"], "region": "CH-BS", "site_id": s}
           for n, s in (("node-omen2", "site-omen"), ("node-demo-tamper", "site-mac"))}
    capp = coordinator_app.create_app(tmp_path / "coord", tokens=toks, registry=reg)
    cc = TestClient(capp)
    for n, t in (("node-omen2", "tok-n"), ("node-demo-tamper", "tok-t")):
        ev = {"node_id": n, "region": "CH-BS", "measurement": "digitalheat-node-image-v1", "certified": False}
        site = reg[n]["site_id"]
        assert cc.post("/v1/nodes/register", headers={"Authorization": f"Bearer {t}"}, json={
            "node_id": n, "site_id": site, "eligible_classes": ["public"], "server_kw_el": 1.0,
            "attestation": wire.attestation_to_json(attest(n, ev))}).status_code == 200
    tok = tmp_path / "admin"
    tok.write_text("tok-admin")
    monkeypatch.setenv("DH_LIVE_ACTIONS", "1")
    monkeypatch.setenv("DH_ADMIN_TOKEN_FILE", str(tok))
    monkeypatch.setenv("DH_COORDINATOR_URL", "http://coord.test")

    monkeypatch.setattr(live, "transport", httpx.MockTransport(relay_to(cc)))
    assert client.post("/api/live/kill", headers=H).status_code == 200
    assert client.post("/api/live/heat", json={"replay": "july"}, headers=H).status_code == 200
    assert (tmp_path / "coord" / "scenario" / "site-mac").read_text().strip() == "july"
    assert client.post("/api/live/tamper", headers=H).status_code == 200
    st = client.get("/api/live/state").json()
    assert st["overview"]["audit"]["ok"] is True and st["events"]
    lease = cc.post("/v1/nodes/node-demo-tamper/lease", headers={"Authorization": "Bearer tok-t"}).json()
    assert lease.get("hold") and "tampered" in lease["reason"]


# ------------------------------------------------------------------ #97: pull the plug moves the unit to another node
@pytest.fixture
def nodes_api(monkeypatch, tmp_path):
    """A fake coordinator whose /v1/ops/nodes running units the test controls; records drain/undrain/kill."""
    tok = tmp_path / "admin"
    tok.write_text("tok-admin")
    monkeypatch.setenv("DH_LIVE_ACTIONS", "1")
    monkeypatch.setenv("DH_ADMIN_TOKEN_FILE", str(tok))
    monkeypatch.setenv("DH_COORDINATOR_URL", "http://coord.test")
    state = {"running": {"node-omen2": "job-1-u000", "node-mac": None}, "calls": []}

    def handler(req: httpx.Request) -> httpx.Response:
        state["calls"].append((req.method, req.url.path))
        if req.url.path == "/v1/ops/nodes":
            return httpx.Response(200, json={"items": [{"node_id": k, "running_unit": v} for k, v in state["running"].items()]})
        if req.url.path in ("/v1/ops/overview", "/v1/events/poll"):
            return httpx.Response(200, json={"events": []})
        return httpx.Response(200, json={"ok": True})
    monkeypatch.setattr(live, "transport", httpx.MockTransport(handler))
    yield state
    for n in list(live._drained):
        live._undrain(n, "cleanup")


def test_kill_drains_and_auto_restores_once_the_unit_runs_elsewhere(client, nodes_api):
    r = client.post("/api/live/kill", headers=H).json()
    assert r["drained"] is True and r["unit"] == "job-1-u000"
    assert ("POST", "/v1/ops/nodes/node-omen2/drain") in nodes_api["calls"]
    st = client.get("/api/live/state").json()
    assert st["drained"] == ["node-omen2"] and st["restored"] == []  # the unit has not moved yet
    nodes_api["running"] = {"node-omen2": None, "node-mac": "job-1-u000"}  # node-mac picked it up
    st = client.get("/api/live/state").json()
    assert st["drained"] == [] and st["restored"][0]["undrained"] and "node-mac" in st["restored"][0]["why"]
    assert nodes_api["calls"].count(("POST", "/v1/ops/nodes/node-omen2/undrain")) == 1


def test_restore_button_undrains_now(client, nodes_api):
    client.post("/api/live/kill", headers=H)
    assert client.post("/api/live/restore", headers=H).status_code == 200
    assert ("POST", "/v1/ops/nodes/node-omen2/undrain") in nodes_api["calls"] and not live._drained
    assert client.post("/api/live/restore", headers=H).status_code == 200  # idempotent (undrain at the coordinator)
    assert TestClient(dash.app, client=("10.0.0.9", 1)).post("/api/live/restore", headers=H).status_code == 403


def test_auto_restore_after_the_timeout(client, nodes_api, monkeypatch):
    monkeypatch.setattr(live, "DRAIN_RESTORE_S", 0.05)
    client.post("/api/live/kill", headers=H)
    import time as _t
    _t.sleep(0.3)  # the timer fires even if nobody polls (page closed)
    assert not live._drained
    assert ("POST", "/v1/ops/nodes/node-omen2/undrain") in nodes_api["calls"]


def test_page_shows_restore_while_drained():
    html = (SITE / site_build.LIVE_PAGE).read_text(encoding="utf-8")
    assert 'this.liveAct("restore")' in html and "ctl.drained" in html


def test_pull_the_plug_moves_the_unit_to_the_other_node_on_a_real_coordinator(client, monkeypatch, tmp_path):
    """#97 regression: kill alone let the scheduler re-lease the unit to the SAME node."""
    coordinator_app = pytest.importorskip("coordinator.app")
    import time as _t
    from live_agent import wire
    from trust import attest
    toks = {"tok-admin": "admin", "tok-o": "node:node-omen2", "tok-m": "node:node-mac", "tok-so": "site:site-omen",
            "tok-sm": "site:site-mac"}
    reg = {n: {"certified": False, "max_classes": ["public"], "region": "CH-BS", "site_id": s}
           for n, s in (("node-omen2", "site-omen"), ("node-mac", "site-mac"))}
    cc = TestClient(coordinator_app.create_app(tmp_path / "coord", tokens=toks, registry=reg))
    hdr = lambda t: {"Authorization": f"Bearer {t}"}  # noqa: E731
    for n, t in (("node-omen2", "tok-o"), ("node-mac", "tok-m")):
        ev = {"node_id": n, "region": "CH-BS", "measurement": "digitalheat-node-image-v1", "certified": False}
        assert cc.post("/v1/nodes/register", headers=hdr(t), json={
            "node_id": n, "site_id": reg[n]["site_id"], "eligible_classes": ["public"], "server_kw_el": 1.0,
            "attestation": wire.attestation_to_json(attest(n, ev))}).status_code == 200
        cc.post(f"/v1/nodes/{n}/heartbeat", headers=hdr(t), json={})
    for s, t in (("site-omen", "tok-so"), ("site-mac", "tok-sm")):  # both houses want heat
        cc.post(f"/v1/sites/{s}/signal", headers=hdr(t), json={"demand_kw": 6.0, "tank_level_kwh": 5.0, "ts": _t.time()})
    assert cc.post("/v1/jobs", headers=hdr("tok-admin"), json={"job_type": "image_tagging", "customer_id": "c",
                                                             "force": True}).status_code == 200
    toks_of = {"node-omen2": "tok-o", "node-mac": "tok-m"}
    victim = other_node = None
    for n in ("node-omen2", "node-mac"):  # whichever node the scheduler gives the unit to is the one we unplug
        lz = cc.post(f"/v1/nodes/{n}/lease", headers=hdr(toks_of[n])).json()
        if "lease_id" in lz:
            victim, unit = n, lz["unit"]["unit_id"]
            break
    assert victim, lz
    other_node = "node-mac" if victim == "node-omen2" else "node-omen2"
    monkeypatch.setenv("DH_LIVE_KILL_NODE", victim)
    cc.post(f"/v1/nodes/{victim}/heartbeat", headers=hdr(toks_of[victim]), json={"running_unit": unit, "progress": 0.3})
    tok = tmp_path / "admin"
    tok.write_text("tok-admin")
    monkeypatch.setenv("DH_LIVE_ACTIONS", "1")
    monkeypatch.setenv("DH_ADMIN_TOKEN_FILE", str(tok))
    monkeypatch.setenv("DH_COORDINATOR_URL", "http://coord.test")
    monkeypatch.setattr(live, "transport", httpx.MockTransport(relay_to(cc)))
    try:
        k = client.post("/api/live/kill", headers=H)
        assert k.status_code == 200, k.text
        assert k.json()["unit"] == unit, k.json()
        again = cc.post(f"/v1/nodes/{victim}/lease", headers=hdr(toks_of[victim])).json()
        assert "lease_id" not in again  # drained: the killed node does NOT get its unit back
        cc.post(f"/v1/nodes/{other_node}/heartbeat", headers=hdr(toks_of[other_node]), json={})
        other = cc.post(f"/v1/nodes/{other_node}/lease", headers=hdr(toks_of[other_node])).json()
        assert other.get("unit", {}).get("unit_id") == unit, other  # it moved to the OTHER node
        cc.post(f"/v1/nodes/{other_node}/heartbeat", headers=hdr(toks_of[other_node]),
                json={"running_unit": unit, "progress": 0.0})
        st = client.get("/api/live/state").json()
        assert st["drained"] == [] and other_node in st["restored"][0]["why"]  # auto-undrained
    finally:
        for n in list(live._drained):
            live._undrain(n, "cleanup")


def test_relay_returns_a_real_httpx_response():
    """Regression for #91 (macmini): the relay must hand MockTransport an httpx.Response on every httpx flavour."""
    class Fake:
        status_code = 200
        headers = {"content-type": "application/json", "content-encoding": "gzip", "content-length": "2"}
        content = b"{}"

    class CC:
        def request(self, *a, **k):
            return Fake()
    r = relay_to(CC())(httpx.Request("GET", "http://coord.test/x?y=1"))
    assert isinstance(r, httpx.Response) and r.status_code == 200 and r.json() == {}
