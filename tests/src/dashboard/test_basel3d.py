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


def test_districts_hexes_and_live_nodes_are_baked():  # #112
    d = json.loads((SITE / "data" / "basel3d.json").read_text())
    names = {x["name"] for x in d["districts"]}
    assert len(d["districts"]) == 19 and {"Gundeldingen", "St. Johann", "Altstadt Grossbasel"} <= names
    assert len(d["hexes"]) > 300 and all(0 <= h[2] < 19 for h in d["hexes"])
    sims = 1 + len(d["fleet"])
    assert all(0 <= k < sims for x in d["districts"] for k in x["houses"])
    assert set(d["live"]) == {"node-mac", "node-omen2"}
    assert not ({*d["live"].values()} & {d["reference"], *d["fleet"]})  # live houses are separate from the fleet


def test_live_overlay_is_wired_and_falls_back_to_replay():
    js = (SITE / "basel3d.js").read_text()
    assert "setLive(feed)" in js and '"REPLAY"' in js and '"LIVE"' in js
    html = (SITE / PAGE).read_text()
    assert '"/api/nodes"' in html and "setLive(" in html and "placed for illustration" in html


def test_stitch_joins_segments_in_any_direction():
    ring = bb.stitch([[(0, 0), (1, 0)], [(1, 1), (1, 0)], [(1, 1), (0, 1)], [(0, 1), (0, 0)]])
    assert len(ring) == 1 and sorted(ring[0]) == [(0, 0), (0, 1), (1, 0), (1, 1)]
    assert bb.inside(0.5, 0.5, ring[0]) and not bb.inside(2, 2, ring[0])
