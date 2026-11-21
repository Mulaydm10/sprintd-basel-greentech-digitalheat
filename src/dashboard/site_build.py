"""Build ``static/site/`` from Dhruv's verbatim export in ``design/frontend/`` (#91). Wiring only, never visuals or copy.

    python -m dashboard.site_build          # rewrites src/dashboard/static/site/*.html, support.js, deck-stage.js

Every change applied to the export is listed in ``WIRING`` below, so the shipped site is provably "as is":
``tests/src/dashboard/test_site.py`` rebuilds it and checks the committed copy equals this output byte for byte.

1. Offline runtime: one ``<script src="./vendor/resources.js">`` before ``support.js``. It fills
   ``window.__resources``, the runtime's own hook for replacing its CDN URLs (React 18.3.1, ReactDOM 18.3.1,
   Babel 7.29.0, byte-identical vendored copies; their SRI hashes match support.js).
2. Offline fonts: the two Google Fonts ``<link>`` lines → ``./vendor/fonts/fonts.css`` (Geist + Geist Mono woff2).
3. Same-origin backend: the ``apiBase`` default on 04 Live and 06 Simulator goes from ``""`` (replay only) to ``"."``.
   The site is served at the dashboard root, so ``./api/...`` is same-origin; the replay fallback stays when the
   backend is unreachable.
4. 04 Live only: a LIVE controls row (see ``LIVE_PATCH``) that calls the dashboard's local-only proxy
   ``/api/live/*``. Scripted scenes stay as the fallback.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from common.config import ROOT

SRC = ROOT / "design" / "frontend"
DST = Path(__file__).resolve().parent / "static" / "site"
EXTRA = Path(__file__).resolve().parent / "site_extra"  # our own pages in the same visual language (#96: 07 Year)
RUNTIME = ("support.js", "deck-stage.js")

# Nav: extra tabs after 06, in order. Each PR that adds a page appends ONE row (#96 07 Year, #102 08/09, #103 10);
# the props' max follows, so arrow paging reaches every tab.
NAV_PAGE = "Nav.dc.html"
NAV_EXTRA = [
    ("07", "Year", "DigitalHeat 07 Year.dc.html"),
    ("10", "Coordinator", "DigitalHeat 10 Coordinator.dc.html"),
]
NAV_OLD = '    ["06", "Simulator", "DigitalHeat%2006%20Simulator.dc.html"]\n  ];'
NAV_NEW = ('    ["06", "Simulator", "DigitalHeat%2006%20Simulator.dc.html"],\n'
           + ",\n".join(f'    ["{n}", "{label}", "{f.replace(" ", "%20")}"]' for n, label, f in NAV_EXTRA) + "\n  ];")
NAV_MAX_OLD = "&quot;min&quot;:1,&quot;max&quot;:6,"
NAV_MAX_NEW = f"&quot;min&quot;:1,&quot;max&quot;:{6 + len(NAV_EXTRA)},"

FONT_LINKS = ('<link rel="preconnect" href="https://fonts.googleapis.com">\n'
              '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@100..900&family='
              'Geist+Mono:wght@400..700&display=swap">')
FONT_LOCAL = '<link rel="stylesheet" href="./vendor/fonts/fonts.css">'
SUPPORT = '<script src="./support.js"></script>'
SUPPORT_LOCAL = '<script src="./vendor/resources.js"></script>\n' + SUPPORT
API_DEFAULT = '&quot;apiBase&quot;:{&quot;editor&quot;:&quot;text&quot;,&quot;default&quot;:&quot;&quot;'
API_LOCAL = '&quot;apiBase&quot;:{&quot;editor&quot;:&quot;text&quot;,&quot;default&quot;:&quot;.&quot;'
LIVE_PAGE = "DigitalHeat 04 Live.dc.html"
API_PAGES = (LIVE_PAGE, "DigitalHeat 06 Simulator.dc.html")

# 04 Live: the LIVE row is inserted right after the live-telemetry table, reusing the page's own button style.
LIVE_ANCHOR = '''      </sc-for>
    </div>
  </section>

  <section style="padding:40px clamp(16px,4vw,40px) 180px;max-width:1400px;margin:0 auto">'''
LIVE_ROW = '''      </sc-for>
    </div>
    <sc-if value="{{ liveOn }}" hint-placeholder-val="{{ false }}">
      <div data-dh-live style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:16px;font-family:'Geist Mono',monospace;font-size:12px">
        <sc-for list="{{ liveActions }}" as="a" hint-placeholder-count="3">
          <button onClick="{{ a.on }}" style="cursor:pointer;padding:10px 16px;border-radius:999px;border:1px solid #c4bcae;background:#f8f6f1;color:#141414;font:inherit">{{ a.label }}</button>
        </sc-for>
        <span style="color:{{ liveActC }}">{{ liveActMsg }}</span>
      </div>
    </sc-if>
  </section>

  <section style="padding:40px clamp(16px,4vw,40px) 180px;max-width:1400px;margin:0 auto">'''
# logic: poll /api/live/state with the node poll; actions POST with the X-DH-Live header (forces a CORS preflight,
# so another website cannot drive them through the presenter's browser).
POLL_OLD = '''      const r = await fetch(base.replace(/\\/$/, "") + "/api/nodes");
      const j = await r.json();
      this.setState({ live: j, liveErr: null });'''
POLL_NEW = '''      const r = await fetch(base.replace(/\\/$/, "") + "/api/nodes");
      const j = await r.json();
      this.setState({ live: j, liveErr: null });
      try { const a = await fetch(base.replace(/\\/$/, "") + "/api/live/state"); this.setState({ liveCtl: a.ok ? await a.json() : null }); } catch (e) { this.setState({ liveCtl: null }); }'''
ACT_METHOD = '''  sceneMigrate(s) {'''
ACT_NEW = '''  async liveAct(path, body) {
    const base = (this.props.apiBase ?? "").trim().replace(/\\/$/, "");
    this.setState({ liveActMsg: "sending " + path + " …", liveActC: "#a86400" });
    try {
      const r = await fetch(base + "/api/live/" + path, { method: "POST", headers: { "Content-Type": "application/json", "X-DH-Live": "1" }, body: JSON.stringify(body || {}) });
      const j = await r.json().catch(() => ({}));
      this.setState({ liveActMsg: r.ok ? "✓ " + (j.summary || path) : "✗ " + (j.detail || r.status), liveActC: r.ok ? "#157a43" : "#d1173a" });
      this.poll();
    } catch (e) { this.setState({ liveActMsg: "✗ " + String(e.message || e), liveActC: "#d1173a" }); }
  }
  sceneMigrate(s) {'''
RET_OLD = '''    return {
'''
RET_NEW = '''    const ctl = this.state.liveCtl;
    const liveOn = !!(ctl && ctl.enabled);
    const heatTo = ctl && ctl.heat === "july" ? "coldest" : "july";
    const liveActions = liveOn ? [
      { label: "Pull the plug · " + ctl.kill_node, on: () => this.liveAct("kill") },
      { label: heatTo === "july" ? "Heat pause · July" : "Heat back · coldest", on: () => this.liveAct("heat", { replay: heatTo }) },
      { label: "Tamper · " + ctl.tamper_node, on: () => this.liveAct("tamper") },
    ] : [];
    const liveActMsg = this.state.liveActMsg || (liveOn ? "LIVE · actions go to " + ctl.coordinator : "");
    const liveActC = this.state.liveActC || "#55524c";
    return {
      liveOn, liveActions, liveActMsg, liveActC,
'''
WIRING = ["vendor/resources.js before support.js", "local fonts.css", "apiBase default '.' on 04 and 06",
          "04 Live: LIVE controls row + liveAct()", "Nav: 07 Year tab (#96)"]


def wire(name: str, html: str) -> str:
    def sub(text: str, old: str, new: str, count: int = 1) -> str:
        if text.count(old) != count:
            raise ValueError(f"{name}: expected {count}x {old[:60]!r}, found {text.count(old)}; the export changed")
        return text.replace(old, new)

    if FONT_LINKS in html:
        html = sub(html, FONT_LINKS, FONT_LOCAL)
    html = sub(html, SUPPORT, SUPPORT_LOCAL)
    if name in API_PAGES:
        html = sub(html, API_DEFAULT, API_LOCAL)
    if name == NAV_PAGE:
        html = sub(html, NAV_OLD, NAV_NEW)
        html = sub(html, NAV_MAX_OLD, NAV_MAX_NEW)
    if name == LIVE_PAGE:
        html = sub(html, LIVE_ANCHOR, LIVE_ROW)
        html = sub(html, POLL_OLD, POLL_NEW)
        html = sub(html, ACT_METHOD, ACT_NEW)
        html = sub(html, RET_OLD, RET_NEW)
    return html


def build(src: Path = SRC, dst: Path = DST) -> list[str]:
    dst.mkdir(parents=True, exist_ok=True)
    out = []
    for p in sorted(src.glob("*.dc.html")):
        (dst / p.name).write_text(wire(p.name, p.read_text(encoding="utf-8")), encoding="utf-8")
        out.append(p.name)
    for f in RUNTIME:
        shutil.copyfile(src / f, dst / f)
        out.append(f)
    total = 6 + len(NAV_EXTRA)
    for p in sorted(EXTRA.glob("*.dc.html")):  # our own pages: written offline-ready; only the Nav position is filled in
        pos = next((6 + i + 1 for i, (_n, _l, f) in enumerate(NAV_EXTRA) if f == p.name), None)
        html = p.read_text(encoding="utf-8")
        if pos is not None:
            html = html.replace("__NAV_INDEX__", str(pos)).replace("__NAV_TOTAL__", f"{total:02d}")
        (dst / p.name).write_text(html, encoding="utf-8")
        out.append(p.name)
    return out


if __name__ == "__main__":
    for n in build():
        print("wrote", DST / n)
