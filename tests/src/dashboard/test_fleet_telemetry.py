"""#118 design half: /api/fleet/* serves the #119 fleetview-v1 files verbatim; the telemetry panel is wired + offline."""
import json
import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dashboard.app import app

SITE = Path(__file__).resolve().parents[3] / "src" / "dashboard" / "static" / "site"


def _fixture(d: Path) -> Path:
    k = d / "k1"
    k.mkdir(parents=True)
    idx = {"schema": "fleetview-v1", "fixture": True, "provenance": {"key": "k1"}, "hours": 2,
           "houses": [{"id": 0}], "series": {"file": "houses.u16", "fields": [{"name": "state", "unit": "code", "scale": 1}]},
           "totals": {"ours": {}, "baseline": {}}}
    (k / "index.json").write_text(json.dumps(idx))
    (k / "fleet.json").write_text(json.dumps({"queue": [1, 2]}))
    (k / "jobs.json").write_text(json.dumps({"tracked": []}))
    (k / "houses.u16").write_bytes(struct.pack("<2H", 1, 2))
    (d / "LATEST").write_text("k1")
    return k


@pytest.fixture()
def client():
    return TestClient(app)


def test_fleet_files_served_verbatim(tmp_path, monkeypatch, client):
    k = _fixture(tmp_path)
    monkeypatch.setenv("DH_FLEETVIEW_DIR", str(k))
    for name in ("index", "fleet", "jobs", "houses.u16"):
        r = client.get(f"/api/fleet/{name}")
        assert r.status_code == 200, name
        assert r.headers["etag"].startswith('"k1-')
    assert client.get("/api/fleet/houses.u16").content == struct.pack("<2H", 1, 2)


def test_no_fleet_data_is_404_with_the_command(tmp_path, monkeypatch, client):
    monkeypatch.setenv("DH_FLEETVIEW_DIR", str(tmp_path / "missing"))
    r = client.get("/api/fleet/index")
    assert r.status_code == 404


def test_wrong_schema_is_refused(tmp_path, monkeypatch, client):
    k = _fixture(tmp_path)
    (k / "index.json").write_text(json.dumps({"schema": "other"}))
    monkeypatch.setenv("DH_FLEETVIEW_DIR", str(k))
    assert client.get("/api/fleet/fleet").status_code == 502


def test_no_path_from_the_request_reaches_the_disk(tmp_path, monkeypatch, client):
    monkeypatch.setenv("DH_FLEETVIEW_DIR", str(_fixture(tmp_path)))
    for p in ("/api/fleet/../index", "/api/fleet/%2e%2e%2findex.json", "/api/fleet/LATEST", "/api/fleet/index.json"):
        assert client.get(p).status_code in (404, 405), p


def test_panel_is_wired_offline_and_uses_the_agreed_events():
    page = (SITE / "DigitalHeat 07 Year.dc.html").read_text()
    js = (SITE / "fleet-telemetry.js").read_text()
    assert "data-dh-fleet-telemetry" in page and "./fleet-telemetry.js" in page
    for ev in ("dh:tick", "dh:select-job", "dh:select-house"):
        assert ev in js
    assert "http://" not in js and "https://" not in js  # no external fetches
    assert "ASSUMED" in js


@pytest.mark.parametrize("page", ["phone-client.html", "phone-server.html"])
def test_phone_pages_served_offline_token_in_session_only(client, page):
    r = client.get("/" + page)
    assert r.status_code == 200
    js = (SITE / "phone.js").read_text()
    assert "sessionStorage" in js and "localStorage" not in js
    body = r.text
    assert "https://unpkg" not in body and "googleapis" not in body
    assert client.get("/phone.js").status_code == 200 and client.get("/phone-base.css").status_code == 200


def test_live_events_never_pass_text(monkeypatch, client):
    import httpx
    from dashboard import app as appmod

    def handler(req):
        return httpx.Response(200, json={"last_id": 9, "events": [
            {"id": 8, "type": "transcript.segment", "ts": "t", "data": {"job": "j", "seq": 3, "node": "mac-live", "text": "SECRET WORDS"}},
            {"id": 9, "type": "site.signal", "data": {"demand_kw": 1}}]})
    monkeypatch.setenv("DH_LIVE_NODES", "1")
    monkeypatch.setenv("DH_OBSERVER_TOKEN_FILE", __file__)
    monkeypatch.setattr(appmod, "_live_transport", httpx.MockTransport(handler))
    d = client.get("/api/live-events?after=0").json()
    assert d["last_id"] == 9 and len(d["events"]) == 1
    assert "SECRET" not in str(d) and d["events"][0]["data"]["seq"] == 3
