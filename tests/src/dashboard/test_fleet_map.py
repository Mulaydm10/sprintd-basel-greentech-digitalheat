"""#118 on-map half: /api/fleet serves fleetview-v1 (fixture fallback), the map layer + page events are wired."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from dashboard import fleet
from dashboard.app import SITE, app


def test_api_fleet_serves_the_fixture_when_no_run(monkeypatch, tmp_path):
    monkeypatch.setenv("DH_FLEETVIEW_DIR", str(fleet.FIXTURE))
    c = TestClient(app)
    ix = c.get("/api/fleet/index")
    assert ix.status_code == 200 and ix.json()["schema"] == "fleetview-v1" and ix.json()["fixture"] is True
    raw = c.get("/api/fleet/houses.u16").content
    assert len(raw) == 2 * len(ix.json()["series"]["fields"]) * len(ix.json()["houses"]) * ix.json()["hours"]
    assert c.get("/api/fleet/fleet").status_code == 200 and c.get("/api/fleet/jobs").json()["tracked"]
    assert c.get("/api/fleet/../etc").status_code == 404 and c.get("/api/fleet/nope").status_code == 404
    etag = ix.headers["etag"]
    assert c.get("/api/fleet/index", headers={"If-None-Match": etag}).status_code == 304
    monkeypatch.setenv("DH_FLEETVIEW_DIR", str(tmp_path))
    assert c.get("/api/fleet/index").status_code == 404


def test_map_layer_and_events_are_wired():
    js = (SITE / "basel3d.js").read_text(encoding="utf-8")
    for needle in ("setFleet(d)", '"dh:select-job"', "mc_chf_per_server_h", "waiting ", "removeEventListener(\"dh:select-job\""):
        assert needle in js, needle
    html = (SITE / "DigitalHeat 07 Year.dc.html").read_text(encoding="utf-8")
    assert '"dh:tick"' in html and '"/api/fleet/"' in html and "fleetKey" in html
