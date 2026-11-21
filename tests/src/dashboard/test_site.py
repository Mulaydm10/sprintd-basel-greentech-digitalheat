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
            undo = undo.replace(site_build.NAV_NEW, site_build.NAV_OLD).replace(site_build.NAV_MAX_NEW, site_build.NAV_MAX_OLD)
        if name == site_build.LIVE_PAGE:
            for old, newer in ((site_build.LIVE_ANCHOR, site_build.LIVE_ROW), (site_build.POLL_OLD, site_build.POLL_NEW),
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
    assert client.post("/api/live/kill", headers=H).json()["summary"] == "pulled the plug on node-omen2"
    assert client.post("/api/live/heat", json={"replay": "july"}, headers=H).status_code == 200
    assert client.post("/api/live/tamper", headers=H).status_code == 200
    calls = [(r.method, r.url.path, r.content) for r in live_on]
    assert calls == [("POST", "/v1/ops/nodes/node-omen2/kill", b""),
                     ("POST", "/v1/ops/sites/site-mac/scenario", b'{"replay":"july"}'),
                     ("POST", "/v1/ops/nodes/node-demo-tamper/tamper", b"")]
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

    def relay(req: httpx.Request) -> httpx.Response:
        return cc.request(req.method, req.url.path, content=req.content, headers=dict(req.headers))
    monkeypatch.setattr(live, "transport", httpx.MockTransport(relay))
    assert client.post("/api/live/kill", headers=H).status_code == 200
    assert client.post("/api/live/heat", json={"replay": "july"}, headers=H).status_code == 200
    assert (tmp_path / "coord" / "scenario" / "site-mac").read_text().strip() == "july"
    assert client.post("/api/live/tamper", headers=H).status_code == 200
    st = client.get("/api/live/state").json()
    assert st["overview"]["audit"]["ok"] is True and st["events"]
    lease = cc.post("/v1/nodes/node-demo-tamper/lease", headers={"Authorization": "Bearer tok-t"}).json()
    assert lease.get("hold") and "tampered" in lease["reason"]
