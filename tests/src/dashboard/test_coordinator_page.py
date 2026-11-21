"""#103: 10 Coordinator (operator) page: served offline, in Nav, token kept in sessionStorage only, talks to the
coordinator with an Authorization header (SSE via fetch, poll fallback), admin actions confirmed in-page."""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

import dashboard.app as dash
from dashboard import site_build

PAGE = "DigitalHeat 10 Coordinator.dc.html"
SRC = (site_build.EXTRA / PAGE).read_text(encoding="utf-8")
JS = SRC.split("data-dc-script", 1)[1]


@pytest.fixture
def client():
    return TestClient(dash.app, client=("127.0.0.1", 5000))


def test_page_is_served_offline_and_in_nav(client):
    r = client.get("/" + PAGE)
    assert r.status_code == 200
    html = r.text
    assert "./vendor/resources.js" in html and "./vendor/fonts/fonts.css" in html and "__NAV" not in html
    assert not re.findall(r"""(?:src|href)=["']https?://""", html)  # the coordinator URL is data, not a resource
    pos = 6 + [f for _n, _l, f in site_build.NAV_EXTRA].index(PAGE) + 1
    assert f"const pos = {pos};" in html
    nav = client.get("/Nav.dc.html").text
    assert '["10", "Coordinator", "DigitalHeat%2010%20Coordinator.dc.html"]' in nav


def test_token_lives_in_session_storage_only():
    assert "sessionStorage.setItem(Component.TOK" in JS and "sessionStorage.removeItem(Component.TOK" in JS
    assert "localStorage" not in JS and "document.cookie" not in JS
    assert not re.search(r"[?&]token=|location\.(href|search|hash)\s*=", JS)  # never in a URL
    assert 'type="password"' in SRC and 'autocomplete="off"' in SRC
    assert 'credentials: "omit"' in JS and 'name="referrer" content="no-referrer"' in SRC


def test_sign_out_clears_everything():
    m = re.search(r"signOut\(why\) \{(.*?)\n  \}", JS, re.S)
    body = m.group(1)
    assert "removeItem(Component.TOK)" in body and "tok: null" in body and "stopStream()" in body


def test_auth_header_sse_via_fetch_with_poll_fallback():
    assert "EventSource" not in JS.replace("EventSource cannot", "")  # cannot send Authorization
    assert 'Authorization: "Bearer " + tok' in JS
    assert '"/v1/events"' in JS and "getReader()" in JS and "Last-Event-ID" in JS
    assert '"/v1/events/poll?after="' in JS and "this.poll(gen)" in JS


def test_admin_actions_need_admin_and_confirmation():
    assert "role-probe-nonexistent" in JS  # side-effect-free role probe (unknown node: admin 404, observer 403)
    assert "ask(kind, id, extra)" in JS and "pending:" in JS and "confirmYes" in JS
    # every action button goes through ask(): no direct POST from a click
    for verb in ("drain", "undrain", "kill", "tamper", "scenario"):
        assert f'this.ask("{verb}"' in JS
    assert "admin token required" in JS and "off: !admin" in JS


def test_signed_out_view_is_labelled_sample():
    assert '"SAMPLE · NOT LIVE"' in JS and "static SAMPLE" in JS


def test_coordinator_allows_the_page_cross_origin(monkeypatch, tmp_path):
    """The page calls the coordinator directly: its CORS must allow our origin and the headers we send."""
    capp = pytest.importorskip("coordinator.app")
    monkeypatch.setenv("DH_CORS_ORIGINS", "https://dhruvs-mac-mini.tailaf7ebe.ts.net:8443")
    c = TestClient(capp.create_app(tmp_path, tokens={"t": "admin"}, registry={}))
    for path, method in (("/v1/ops/overview", "GET"), ("/v1/events", "GET"), ("/v1/ops/nodes/x/kill", "POST")):
        r = c.options(path, headers={"Origin": "https://dhruvs-mac-mini.tailaf7ebe.ts.net:8443",
                                     "Access-Control-Request-Method": method,
                                     "Access-Control-Request-Headers": "authorization,content-type,last-event-id"})
        assert r.headers.get("access-control-allow-origin") == "https://dhruvs-mac-mini.tailaf7ebe.ts.net:8443", path
        assert r.headers.get("access-control-allow-credentials") in (None, "false")
