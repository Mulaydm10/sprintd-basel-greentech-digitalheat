"""#101: the 3D year helix (static/site/year3d.js) is offline, wired into the 07 Year page and served."""
from __future__ import annotations

import re

from fastapi.testclient import TestClient

from dashboard.app import SITE, app

PAGE = "DigitalHeat 07 Year.dc.html"


def test_year3d_is_offline_and_dependency_free():
    js = (SITE / "year3d.js").read_text(encoding="utf-8")
    assert "webgl2" in js and "window.DHYear3D" in js
    assert not re.search(r"https?://", js)  # no CDN, no network: offline like #94
    assert "import " not in js and "require(" not in js


def test_page_loads_it_from_helmet_and_hosts_the_canvas():
    html = (SITE / PAGE).read_text(encoding="utf-8")
    helmet = html[html.index("<helmet>"):html.index("</helmet>")]
    assert '<script src="./year3d.js"></script>' in helmet  # head scripts outside <helmet> never run in the dc runtime
    assert 'id="dh-year-3d-host"' in html and "sync3d(" in html
    assert "3D needs WebGL2" in html  # fallback note; the 2D view keeps working without WebGL2


def test_served():
    c = TestClient(app)
    r = c.get("/year3d.js")
    assert r.status_code == 200 and "DHYear3D" in r.text
