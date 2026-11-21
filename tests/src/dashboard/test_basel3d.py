"""#109: the 3D Basel map: baked OSM data, offline module, vendored three.js, page wiring, and the baker itself."""
from __future__ import annotations

import hashlib
import json
import math
import re

from dashboard import basel_bake as bb
from dashboard.app import SITE

PAGE = "DigitalHeat 07 Year.dc.html"


def test_baked_map_is_small_complete_and_attributed():
    f = SITE / "data" / "basel3d.json"
    assert f.stat().st_size <= 5_000_000
    d = json.loads(f.read_text())
    assert d["schema"] == "basel3d-v1" and "OpenStreetMap" in d["attribution"] and "ODbL" in d["attribution"]
    assert len(d["buildings"]) > 10_000 and d["water"] and d["roads"]
    n = len(d["buildings"])
    assert 0 <= d["reference"] < n and len(d["fleet"]) == bb.FLEET and all(0 <= i < n for i in d["fleet"])
    assert d["reference"] not in d["fleet"] and "illustrative" in d["fleet_note"]
    assert all(b[1] in (0, 1) and b[0] > 0 for b in d["buildings"][:500])


def test_module_is_offline_and_uses_only_the_vendored_three():
    js = (SITE / "basel3d.js").read_text()
    assert not re.search(r"https?://", js)
    imports = re.findall(r'from "([^"]+)"', js)
    assert imports and all(i.startswith("./vendor/three/") for i in imports)
    assert "window.DHBasel3D" in js


def test_vendored_three_matches_its_recorded_checksums():
    d = SITE / "vendor" / "three"
    readme = (d / "README.md").read_text()
    sums = dict((p.strip(), h) for h, p in re.findall(r"^([0-9a-f]{64})\s+(\S+)$", readme, re.M))
    assert sums and "./three.module.js" in sums
    for p, h in sums.items():
        assert hashlib.sha256((d / p).read_bytes()).hexdigest() == h, p
    for f in (d / "addons").rglob("*.js"):
        assert "from 'three'" not in f.read_text(), f  # bare specifier would need an import map


def test_page_wires_the_map_view_by_default():
    html = (SITE / PAGE).read_text()
    helmet = html[html.index("<helmet>"):html.index("</helmet>")]
    assert '<script type="module" src="./basel3d.js"></script>' in helmet
    assert 'id="dh-basel-host"' in html and "syncMap(" in html and 'view: "map"' in html
    assert "ODbL" in html and "illustrative fleet" in html
    assert 'sp(24, "1x")' in html and 'sp(192, "8x")' in html
    assert "data-dh-year3d" in html  # the #105 helix is kept (Helix view)


def test_baker_on_a_tiny_synthetic_extract():
    def sq(lat, lon, d=0.0002, tags=None):
        g = [{"lat": lat, "lon": lon}, {"lat": lat, "lon": lon + d}, {"lat": lat + d, "lon": lon + d},
             {"lat": lat + d, "lon": lon}, {"lat": lat, "lon": lon}]
        return {"type": "way", "tags": tags or {"building": "house", "building:levels": "3"}, "geometry": g}
    els = [sq(bb.REF_SPOT[0] + i * 0.0025, bb.REF_SPOT[1] + j * 0.0025) for i in range(-6, 7) for j in range(-6, 7)]
    els += [sq(47.56, 7.59, 0.00001, {"building": "shed"}),  # below MIN_AREA: dropped
            {"type": "way", "tags": {"waterway": "river"}, "geometry": [{"lat": 47.56, "lon": 7.58}, {"lat": 47.565, "lon": 7.60}]}]
    d = bb.bake({"elements": els})
    assert len(d["buildings"]) == 169 and len(d["rivers"]) == 1
    assert d["buildings"][0][0] == round((3 * 3.1 + 1.5) * 10)  # height from building:levels
    assert d == bb.bake({"elements": els})  # deterministic (seeded fleet)
    pts = []
    for i in [d["reference"], *d["fleet"]]:
        b = d["buildings"][i]
        pts.append((b[2] * d["q"], b[3] * d["q"]))
    assert all(math.dist(a, b) >= bb.FLEET_MIN_SPACING_M - 30 for k, a in enumerate(pts) for b in pts[k + 1:])
