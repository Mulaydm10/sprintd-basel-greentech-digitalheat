"""#102: 08 Client + 09 GPU Server pages: served offline, in the Nav, token in sessionStorage only, talk to the
coordinator with an Authorization header (SSE via fetch, poll fallback), and only call routes that exist."""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

import dashboard.app as dash
from dashboard import site_build

CLIENT, HOST = "DigitalHeat 08 Client.dc.html", "DigitalHeat 09 GPU Server.dc.html"
SRC = {p: (site_build.EXTRA / p).read_text(encoding="utf-8") for p in (CLIENT, HOST)}
JS = {p: s.split("data-dc-script", 1)[1] for p, s in SRC.items()}
ORIGIN = "https://dhruvs-mac-mini.tailaf7ebe.ts.net:8443"


@pytest.fixture
def client():
    return TestClient(dash.app, client=("127.0.0.1", 5000))


@pytest.mark.parametrize("page,label", [(CLIENT, "Client"), (HOST, "GPU Server")])
def test_page_is_served_offline_and_in_nav(client, page, label):
    r = client.get("/" + page)
    assert r.status_code == 200
    html = r.text
    assert "./vendor/resources.js" in html and "./vendor/fonts/fonts.css" in html and "__NAV" not in html
    assert not re.findall(r"""(?:src|href)=["']https?://""", html)  # the coordinator URL is data, not a resource
    assert "fonts.googleapis" not in html and "unpkg" not in html and "cdn" not in html.lower().replace("cdnjs", "")
    i = [f for _n, _l, f in site_build.NAV_EXTRA].index(page)
    num = site_build.NAV_EXTRA[i][0]
    assert f"const pos = {6 + i + 1};" in html and f"/ {6 + len(site_build.NAV_EXTRA):02d}</span>" in html
    nav = client.get("/Nav.dc.html").text
    assert f'["{num}", "{label}", "{page.replace(" ", "%20")}"]' in nav


def test_nav_order_is_07_to_10():
    assert [n for n, _l, _f in site_build.NAV_EXTRA] == ["07", "08", "09", "10"]


@pytest.mark.parametrize("page", [CLIENT, HOST])
def test_token_lives_in_session_storage_only(page):
    js, src = JS[page], SRC[page]
    assert "sessionStorage.setItem(Component.TOK" in js and "sessionStorage.removeItem(Component.TOK" in js
    assert "localStorage" not in js and "document.cookie" not in js and "indexedDB" not in js
    assert not re.search(r"[?&](token|access_token|auth)=|location\.(href|search|hash)\s*=", js)  # never in a URL
    assert 'type="password"' in src and 'autocomplete="off"' in src
    assert 'credentials: "omit"' in js and 'name="referrer" content="no-referrer"' in src
    assert "console.log" not in js  # nothing (a token included) is logged


@pytest.mark.parametrize("page", [CLIENT, HOST])
def test_sign_out_clears_everything(page):
    body = re.search(r"signOut\(why\) \{(.*?)\n  \}", JS[page], re.S).group(1)
    assert "removeItem(Component.TOK)" in body and "tok: null" in body and "stopStream()" in body
    if page == CLIENT:
        assert "dropLinks()" in body  # downloaded result/receipt blobs are revoked too


@pytest.mark.parametrize("page", [CLIENT, HOST])
def test_auth_header_sse_via_fetch_with_poll_fallback(page):
    js = JS[page]
    assert "EventSource" not in js.replace("EventSource cannot", "")  # cannot send Authorization
    assert 'Authorization: "Bearer " + tok' in js
    assert '"/v1/events"' in js and "getReader()" in js and "Last-Event-ID" in js
    assert '"/v1/events/poll?after="' in js and "this.poll(gen)" in js


@pytest.mark.parametrize("page", [CLIENT, HOST])
def test_signed_out_view_is_labelled_sample(page):
    assert '"SAMPLE · NOT LIVE"' in JS[page] and "static SAMPLE" in JS[page]


@pytest.mark.parametrize("page", [CLIENT, HOST])
def test_wrong_role_gets_a_clear_message(page):
    other = "Hosts sign in on 09 GPU Server" if page == CLIENT else "Customers sign in on 08 Client"
    assert "(403)" in JS[page] and other in JS[page]


# ------------------------------------------------------------------ 08 Client specifics
def test_client_cancel_needs_in_page_confirmation():
    js = JS[CLIENT]
    assert js.count('method: "DELETE"') == 1
    cancel = re.search(r"async cancel\(\) \{(.*?)\n  \}", js, re.S).group(1)
    assert 'method: "DELETE"' in cancel and "this.state.pending" in cancel
    assert "confirmYes: () => this.cancel()" in js  # the only caller
    assert 'this.setState({ pending: { id: D.job_id' in js  # the button only asks


def test_client_idempotency_key_matches_the_contract():
    js = JS[CLIENT]
    m = re.search(r'static newKey\(\) \{ const b = new Uint8Array\((\d+)\);.*?return "([a-z0-9-]+)" \+', js)
    n, prefix = int(m.group(1)), m.group(2)
    key = prefix + "ab" * n  # hex of n random bytes
    assert re.fullmatch(r"[a-z0-9-]{1,64}", key)
    # the key survives a network error (retry replays) and is renewed only after a definite answer
    sub = re.search(r"async submit\(\) \{(.*?)\n  \}", js, re.S).group(1)
    assert "idempotency_key: key" in sub and "key: Component.newKey()" in sub
    assert "retry is safe: same key" in sub


def test_client_shows_all_admission_outcomes():
    sub = re.search(r"async submit\(\) \{(.*?)\n  \}", JS[CLIENT], re.S).group(1)
    for marker in ("r.status === 201", "r.status === 200", 'r.status === 422 && j.status === "rejected"', "j.reason"):
        assert marker in sub


def test_client_result_is_checked_against_the_receipt():
    """X-Result-SHA256 is a custom header: cross-origin it is readable only if the coordinator exposes it, which
    its CORS does not today. So the page hashes the bytes itself and compares with the receipt's result_sha256."""
    fr = re.search(r"async fetchResult\(\) \{(.*?)\n  \}", JS[CLIENT], re.S).group(1)
    assert 'crypto.subtle.digest("SHA-256", buf)' in fr and "rc.result_sha256 === sha" in fr
    assert "URL.createObjectURL" in fr and "URL.revokeObjectURL" in fr


def test_client_job_size_presets_are_within_the_coordinator_bounds():
    from coordinator.core import MAX_CHUNKS, MAX_ROUNDS
    sizes = re.search(r"static SIZES = (\[\[.*?\]\]);", JS[CLIENT]).group(1)
    for _n, chunks, rounds in re.findall(r'\["(\w)", (\d+), (\d+)\]', sizes):
        assert 1 <= int(chunks) <= MAX_CHUNKS and 1 <= int(rounds) <= MAX_ROUNDS


# ------------------------------------------------------------------ 09 GPU Server specifics
def test_host_pause_presets_respect_the_routers_30_day_bound():
    from portal.host import MAX_PAUSE
    hours = [int(h) for h in re.findall(r"this\.override\(true, (\d+)\)", JS[HOST])]
    assert hours and all(0 <= h <= MAX_PAUSE.total_seconds() / 3600 for h in hours) and 0 in hours  # 0 = until resumed
    ov = re.search(r"async override\(paused, hours\) \{(.*?)\n  \}", JS[HOST], re.S).group(1)
    assert "toISOString()" in ov and '"/v1/host/site/resume"' in ov and '"/v1/host/site/pause"' in ov


def test_host_tank_size_is_read_not_hard_coded():
    js = JS[HOST]
    assert '"/api/year/sizing"' in js and "k.tank_kwh" in js
    assert not re.search(r"\b35(\.0)?\b", js)  # the reference tank lives in data/assumptions.yaml


def test_host_history_never_invents_missing_hours():
    slots = re.search(r"slots\(\) \{(.*?)\n  \}", JS[HOST], re.S).group(1)
    assert "by.get(t) || null" in slots
    assert '"/v1/host/history?hours=24"' in JS[HOST]


# ------------------------------------------------------------------ against the real routers
def _paths(js: str, prefix: str) -> set[str]:
    raw = re.findall(r'["`](/v1/' + prefix + r'[^"`?]*)', js)
    return {re.sub(r"\$\{[^}]*\}", "{id}", p).rstrip("/") for p in raw}


def test_every_route_the_pages_call_exists():
    capp = pytest.importorskip("coordinator.app")
    from portal import client as pclient, host as phost
    routes = [*pclient.make_router(lambda: None, lambda: None).routes, *phost.make_router(lambda: None, lambda: None).routes]
    have = {re.sub(r"\{[^}]*\}", "{id}", r.path) for r in routes if getattr(r, "path", "").startswith("/v1/")}
    want = _paths(JS[CLIENT], "client") | _paths(JS[HOST], "host")
    assert want and want <= have, sorted(want - have)
    assert capp  # coordinator importable: these routers are what create_app mounts


def test_coordinator_allows_the_pages_cross_origin(monkeypatch, tmp_path):
    """The pages call the coordinator directly: its CORS must allow the site origin, our headers and DELETE."""
    capp = pytest.importorskip("coordinator.app")
    monkeypatch.setenv("DH_CORS_ORIGINS", ORIGIN)
    c = TestClient(capp.create_app(tmp_path, tokens={"t" * 32: "client:acme"}, registry={}))
    for path, method in (("/v1/client/jobs", "POST"), ("/v1/client/jobs/job-x", "DELETE"), ("/v1/client/jobs/job-x/result", "GET"),
                         ("/v1/host/site", "GET"), ("/v1/host/site/pause", "POST"), ("/v1/events", "GET")):
        r = c.options(path, headers={"Origin": ORIGIN, "Access-Control-Request-Method": method,
                                     "Access-Control-Request-Headers": "authorization,content-type,last-event-id"})
        assert r.status_code == 200, (path, r.status_code)
        assert r.headers.get("access-control-allow-origin") == ORIGIN, path
        assert r.headers.get("access-control-allow-credentials") in (None, "false")
    r = c.get("/v1/client/me", headers={"Origin": "https://evil.example"})
    assert r.headers.get("access-control-allow-origin") is None
