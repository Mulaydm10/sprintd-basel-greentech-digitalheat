"""#125 traceability on the map: arcs, job trace card, eligibility, ghost, story chips, URL hash, source tags."""
from __future__ import annotations

from dashboard.app import SITE


def test_trace_layer_is_wired():
    js = (SITE / "basel3d.js").read_text(encoding="utf-8")
    for needle in ("function selectJob(", "function jobCard(", "hour → house → why", "all eligible ✓", "🔒", "TubeGeometry",
                   "baseline_missed", "function stories(", "setCamera(a)", "houses sharing a job this hour", "fleetview "):
        assert needle in js, needle


def test_page_has_ghost_stories_hash_and_source_tags():
    html = (SITE / "DigitalHeat 07 Year.dc.html").read_text(encoding="utf-8")
    for needle in ("data-dh-ghost", "data-dh-stories", "applyHash(", "history.replaceState", "houses_baseline.u16", "estSrc"):
        assert needle in html, needle


def test_129_polish_is_wired():  # design's live check on #126
    js = (SITE / "basel3d.js").read_text(encoding="utf-8")
    assert "if (h < 24) continue" in js and "unit: wideUnit" in js  # chips skip the start-up burst, carry the job
    assert "hour → houses → why" in js and '" ×" + c' in js  # rows grouped by hour
    assert "data-close" in js and "min(300px,38%)" in js  # narrower card with ×
    assert "0.9, 6, false" in js and "long arcs fade" in js  # calmer light
    html = (SITE / "DigitalHeat 07 Year.dc.html").read_text(encoding="utf-8")
    assert "this.vm.selectJob(st.unit)" in html
