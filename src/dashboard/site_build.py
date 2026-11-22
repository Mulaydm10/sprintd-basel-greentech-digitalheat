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
4. 04 Live only: a LIVE controls row (see ``LIVE_ROW``) that calls the dashboard's local-only proxy
   ``/api/live/*`` (pull the plug = drain + kill; "Restore" appears while the killed node is drained, #97).
   Scripted scenes stay as the fallback.
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
    ("08", "Client", "DigitalHeat 08 Client.dc.html"),  # #102: compute customer (portal client API)
    ("09", "GPU Server", "DigitalHeat 09 GPU Server.dc.html"),  # #102: host / server owner (portal host API)
    ("10", "Coordinator", "DigitalHeat 10 Coordinator.dc.html"),
]
NAV_OLD = '    ["06", "Simulator", "DigitalHeat%2006%20Simulator.dc.html"]\n  ];'
NAV_NEW = ('    ["06", "Simulator", "DigitalHeat%2006%20Simulator.dc.html"],\n'
           + ",\n".join(f'    ["{n}", "{label}", "{f.replace(" ", "%20")}"]' for n, label, f in NAV_EXTRA) + "\n  ];")
NAV_MAX_OLD = "&quot;min&quot;:1,&quot;max&quot;:6,"
NAV_MAX_NEW = f"&quot;min&quot;:1,&quot;max&quot;:{6 + len(NAV_EXTRA)},"

# Nav layout with 10 tabs (#102): the export's pill row wraps to two lines below ~1150 px and then covers content.
# It now stays ONE line: under 1240 px the inactive tabs show only their number (label kept as title/aria-label),
# the active tab keeps its label; if even that does not fit (phones) the row scrolls sideways with the active tab
# centred. A spacer of the Nav's height ends every page (the Nav is each page's last element), so nothing at the
# bottom of a page can sit under it. Same look: colours, font, pill, blur and motion are unchanged.
NAV_LAYOUT = [
    ('<nav style="pointer-events:auto;display:flex;flex-wrap:wrap;justify-content:center;',
     '<nav data-dh-nav style="pointer-events:auto;display:flex;flex-wrap:nowrap;justify-content:flex-start;'
     'max-width:100%;overflow-x:auto;scrollbar-width:none;'),
    ('<a href="{{ t.href }}" onClick="{{ t.go }}" style="display:flex;align-items:center;gap:7px;padding:8px 13px;',
     '<a href="{{ t.href }}" onClick="{{ t.go }}" title="{{ t.label }}" aria-label="{{ t.n }} {{ t.label }}" '
     'data-dh-tab="{{ t.on }}" style="flex:none;white-space:nowrap;display:flex;align-items:center;gap:7px;'
     'padding:8px {{ t.px }}px;'),
    ('<span>{{ t.label }}</span>', '<span style="display:{{ t.disp }}">{{ t.label }}</span>'),
    ('<span style="padding:0 10px 0 8px;color:#6e6a63;', '<span style="flex:none;white-space:nowrap;padding:0 10px 0 8px;color:#6e6a63;'),
    ('  </nav>\n</div>\n</x-dc>',
     '  </nav>\n</div>\n<div aria-hidden="true" data-dh-nav-spacer style="height:80px"></div>\n</x-dc>'),
    ('  state = { progress: 0 };', '  state = { progress: 0, compact: false };'),
    ('    addEventListener("scroll", this.onScroll, { passive: true });\n    this.onScroll();\n',
     '    addEventListener("scroll", this.onScroll, { passive: true });\n    this.onScroll();\n'
     '    this.onResize = () => { const c = innerWidth < 1240; if (c !== this.state.compact) this.setState({ compact: c });'
     ' clearTimeout(this.navT); this.navT = setTimeout(() => this.centerTab(), 80); };\n'
     '    addEventListener("resize", this.onResize); this.onResize();\n'),
    ('  reveal(el, idx) {\n',
     '  centerTab() {\n'
     '    const n = document.querySelector("[data-dh-nav]"), t = n && n.querySelector(\'[data-dh-tab="1"]\');\n'
     '    if (n && t && n.scrollWidth > n.clientWidth) n.scrollLeft = t.offsetLeft - (n.clientWidth - t.offsetWidth) / 2;\n'
     '  }\n'
     '  reveal(el, idx) {\n'),
    ('    removeEventListener("scroll", this.onScroll);',
     '    removeEventListener("scroll", this.onScroll); removeEventListener("resize", this.onResize); clearTimeout(this.navT);'),
    ('        bg: i + 1 === a ? "#141414" : "transparent"\n',
     '        bg: i + 1 === a ? "#141414" : "transparent",\n'
     '        on: i + 1 === a ? "1" : "0", disp: !this.state.compact || i + 1 === a ? "inline" : "none",'
     ' px: this.state.compact ? 10 : 13\n'),
]

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
      ...((ctl.drained || []).includes(ctl.kill_node) ? [{ label: "Restore · " + ctl.kill_node, on: () => this.liveAct("restore") }] : []),
    ] : [];
    const liveActMsg = this.state.liveActMsg || (liveOn ? "LIVE · actions go to " + ctl.coordinator : "");
    const liveActC = this.state.liveActC || "#55524c";
    return {
      liveOn, liveActions, liveActMsg, liveActC,
'''
# 04 Live: the volunteer phone fleet (wow #2) section + its script, inserted above the page's closing notes
FLEET_ANCHOR = '  <section style="padding:40px clamp(16px,4vw,40px) 180px;max-width:1400px;margin:0 auto">'
FLEET_ROW = ('  <div data-dh-phone-fleet style="padding:0 clamp(16px,4vw,40px);max-width:1400px;margin:0 auto"></div>\n'
             + FLEET_ANCHOR)
FLEET_SCRIPT_OLD = "</body>"
FLEET_SCRIPT_NEW = '<script type="module" src="./phone-fleet.js"></script>\n</body>'

# 03 Scheduler: the three-layer story (long / mid / short term), inserted after the hero (Dhruv, 22 Nov)
SCHED_PAGE = "DigitalHeat 03 Scheduler.dc.html"
LAYERS_ANCHOR = "      </svg>\n    </div>\n  </section>\n"
_L = ("border:1px solid #dcd6cc;border-radius:20px;background:#ffffff;padding:22px;display:flex;flex-direction:column;gap:10px")
_K = "font-family:'Geist Mono',monospace;font-size:11px;letter-spacing:0.08em;text-transform:uppercase"
LAYERS_ROW = LAYERS_ANCHOR + f"""
  <section data-dh-layers style="padding:40px clamp(16px,4vw,40px) 80px;max-width:1400px;margin:0 auto;display:flex;flex-direction:column;gap:22px">
    <div style="{_K};color:#a86400">02 · Three horizons, three layers</div>
    <h2 style="margin:0;font-weight:760;font-size:clamp(32px,4.6vw,64px);line-height:.95;letter-spacing:-0.05em">Every scheduler faces three problems. <span style="color:#c93c05">We solve each one separately.</span></h2>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:16px">
      <div style="{_L};border-top:4px solid #1d6bb3">
        <span style="{_K};color:#1d6bb3">Long term · the year plan</span>
        <b style="font-size:22px;letter-spacing:-0.02em">How many servers, where, for a whole city year</b>
        <span style="color:#55524c;line-height:1.45">We run all 8,760 hours of Basel 2025 through the scheduler for every fleet size and recommend the plan (N = 3 servers per house for the reference house; a 100-house city fleet). <b>An operator approves the year plan</b> before it goes live.</span>
        <span style="{_K};color:#6e6a63">today: simulator + sizing rule · next: an AI planner proposes the plan, the operator approves</span>
      </div>
      <div style="{_L};border-top:4px solid #c93c05">
        <span style="{_K};color:#c93c05">Mid term · every hour</span>
        <b style="font-size:22px;letter-spacing:-0.02em">Which job runs in which house, this hour</b>
        <span style="color:#55524c;line-height:1.45">decide() prices every house's heat, dispatches work in merit order (heat wanted first), lets jobs with slack wait for colder hours, admits only work that can finish in time, and prefers local machines over cloud.</span>
        <span style="{_K};color:#6e6a63">deterministic · same code in the simulation and on the live machines</span>
      </div>
      <div style="{_L};border-top:4px solid #157a43">
        <span style="{_K};color:#157a43">Short term · seconds</span>
        <b style="font-size:22px;letter-spacing:-0.02em">Outages, overheating, a pulled plug</b>
        <span style="color:#55524c;line-height:1.45">The coordinator holds every job on a lease. A machine that stops, overheats or is tampered with loses its lease within seconds and the job continues elsewhere from its last checkpoint: nothing lost. Stale heat data switches to a safe degraded mode.</span>
        <span style="{_K};color:#6e6a63">deterministic · leases, checkpoints, exactly-once, signed audit log</span>
      </div>
    </div>
    <div style="border:1px solid #141414;border-radius:20px;background:#141414;color:#f2efe9;padding:18px 22px;display:flex;gap:16px;align-items:center;flex-wrap:wrap">
      <span style="{_K};color:#ff9a5a">🔒 End to end encrypted</span>
      <span style="line-height:1.45">Customer data is encrypted on the customer's device. Only the machine holding the job can open its piece; the coordinator stores locked boxes it cannot read. Every result is signed by the machine that made it and hash-linked to the one before, so nothing can be dropped, edited or reordered unnoticed.</span>
    </div>
    <div style="border:1px solid #dcd6cc;border-radius:20px;background:#f8f6f1;padding:18px 22px;display:flex;flex-direction:column;gap:10px">
      <span style="{_K};color:#a86400">Built from scheduling techniques the big platforms run in production</span>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,250px),1fr));gap:8px 18px;font-size:14px;line-height:1.4;color:#33302b">
        <span><b>Merit-order dispatch</b> · how electricity markets run power plants</span>
        <span><b>Leases + heartbeats</b> · cluster schedulers (HTCondor, Google-style lock services)</span>
        <span><b>Preemption + checkpoint/restart</b> · Borg / Kubernetes-style job eviction and resume</span>
        <span><b>Admission control</b> · accept only work that can meet its deadline (earliest-deadline-first)</span>
        <span><b>Work-fetch backpressure</b> · BOINC volunteer computing</span>
        <span><b>Exactly-once, content-addressed results</b> · stream processing (Kafka / Spark-style)</span>
      </div>
      <span style="font-family:'Geist Mono',monospace;font-size:12px;color:#6e6a63">These deterministic algorithms are the tools the AI planner calls; each one is implemented and tested in our code today.</span>
    </div>
    <div style="font-family:'Geist Mono',monospace;font-size:12px;color:#6e6a63">Plan (operator-approved) → hourly decisions → second-by-second safety. Anything that changes the year plan needs a human approval. End-to-end encryption shown live on the transcription demo; batch checkpoints are sealed with AES-GCM.</div>
  </section>
"""

# Brand: the project is now called Hearthbeat (Dhruv, 22 Nov). Visible text only; page file names stay "DigitalHeat NN …"
import re as _re
BRAND = [(_re.compile(r"DigitalHeat(?!(?:%20| )(?:\d\d|Pitch Deck))"), "Hearthbeat"), (_re.compile(r"DIGITALHEAT"), "HEARTHBEAT"),
         (_re.compile(r'Digital<span style="color:#c93c05">heat'), 'Hearth<span style="color:#c93c05">beat')]
BRAND_UNDO = [("Hearthbeat", "DigitalHeat"), ("HEARTHBEAT", "DIGITALHEAT"),
              ('Hearth<span style="color:#c93c05">beat', 'Digital<span style="color:#c93c05">heat')]


def brand(html: str) -> str:
    for rx, new in BRAND:
        html = rx.sub(new, html)
    return html


WIRING = ["vendor/resources.js before support.js", "local fonts.css", "apiBase default '.' on 04 and 06",
          "04 Live: LIVE controls row + liveAct()", "Nav: extra tabs 07-10 (#96, #102, #103)",
          "Nav: one line (compact numbers, sideways scroll) + bottom spacer (#102)",
          "04 Live: volunteer phone-fleet section + phone-fleet.js (wow #2)", "brand: DigitalHeat -> Hearthbeat (visible text)",
          "03 Scheduler: three-layer section (long / mid / short term)"]


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
        for old, new in NAV_LAYOUT:
            html = sub(html, old, new)
    if name == SCHED_PAGE:
        html = sub(html, LAYERS_ANCHOR, LAYERS_ROW)
    if name == LIVE_PAGE:
        html = sub(html, LIVE_ANCHOR, LIVE_ROW)
        html = sub(html, POLL_OLD, POLL_NEW)
        html = sub(html, ACT_METHOD, ACT_NEW)
        html = sub(html, RET_OLD, RET_NEW)
        html = sub(html, FLEET_ANCHOR, FLEET_ROW)
        html = sub(html, FLEET_SCRIPT_OLD, FLEET_SCRIPT_NEW)
    return brand(html)


def build(src: Path = SRC, dst: Path = DST) -> list[str]:
    dst.mkdir(parents=True, exist_ok=True)
    out = []
    for p in sorted(src.glob("*.dc.html")):
        (dst / p.name).write_text(wire(p.name, p.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
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
        (dst / p.name).write_text(brand(html), encoding="utf-8", newline="\n")
        out.append(p.name)
    return out


if __name__ == "__main__":
    for n in build():
        print("wrote", DST / n)
