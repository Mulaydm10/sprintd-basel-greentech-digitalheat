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
  <section data-dh-layers style="padding:30px clamp(16px,4vw,40px) 80px;max-width:1400px;margin:0 auto;display:flex;flex-direction:column;gap:26px">
    <div style="{_K};color:#a86400">02 · Three horizons, three layers</div>
    <h2 style="margin:0;font-weight:760;font-size:clamp(32px,4.6vw,64px);line-height:.95;letter-spacing:-0.05em">One problem, <span style="color:#c93c05">three clocks.</span></h2>

    <div style="border:1px solid #dcd6cc;border-radius:24px;background:#fff;padding:clamp(16px,2.4vw,30px);overflow-x:auto">
      <svg viewBox="0 0 1200 330" style="width:100%;min-width:760px;height:auto;display:block" font-family="Geist Mono, monospace">
        <defs>
          <marker id="dhar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#c4bcae"/></marker>
          <linearGradient id="dhg1" x1="0" x2="1"><stop offset="0" stop-color="#1d6bb3" stop-opacity=".14"/><stop offset="1" stop-color="#1d6bb3" stop-opacity="0"/></linearGradient>
          <linearGradient id="dhg2" x1="0" x2="1"><stop offset="0" stop-color="#c93c05" stop-opacity=".14"/><stop offset="1" stop-color="#c93c05" stop-opacity="0"/></linearGradient>
          <linearGradient id="dhg3" x1="0" x2="1"><stop offset="0" stop-color="#157a43" stop-opacity=".14"/><stop offset="1" stop-color="#157a43" stop-opacity="0"/></linearGradient>
        </defs>
        <!-- three bands = three clocks -->
        <rect x="0" y="10" width="1200" height="92" rx="18" fill="url(#dhg1)"/>
        <rect x="0" y="118" width="1200" height="92" rx="18" fill="url(#dhg2)"/>
        <rect x="0" y="226" width="1200" height="92" rx="18" fill="url(#dhg3)"/>
        <g font-size="13" letter-spacing="1.5"><text x="24" y="40" fill="#1d6bb3">LONG TERM · A YEAR</text><text x="24" y="148" fill="#c93c05">MID TERM · EVERY HOUR</text><text x="24" y="256" fill="#157a43">SHORT TERM · SECONDS</text></g>
        <g font-family="Geist, system-ui" font-weight="700" font-size="24" fill="#141414"><text x="24" y="76">Plan the fleet</text><text x="24" y="184">Place the work</text><text x="24" y="292">Never lose it</text></g>

        <!-- year: 12 months of heat demand bars -> plan -> operator approves -->
        <g transform="translate(300,24)">
          <g fill="#1d6bb3">
            <rect x="0" y="6" width="14" height="58" rx="3"/><rect x="18" y="12" width="14" height="52" rx="3"/><rect x="36" y="24" width="14" height="40" rx="3"/><rect x="54" y="40" width="14" height="24" rx="3"/>
            <rect x="72" y="54" width="14" height="10" rx="3" opacity=".5"/><rect x="90" y="58" width="14" height="6" rx="3" opacity=".4"/><rect x="108" y="58" width="14" height="6" rx="3" opacity=".4"/><rect x="126" y="56" width="14" height="8" rx="3" opacity=".5"/>
            <rect x="144" y="44" width="14" height="20" rx="3"/><rect x="162" y="30" width="14" height="34" rx="3"/><rect x="180" y="16" width="14" height="48" rx="3"/><rect x="198" y="8" width="14" height="56" rx="3"/>
          </g>
          <text x="0" y="78" font-size="11" fill="#6e6a63">8,760 hours of Basel 2025</text>
          <line x1="232" y1="36" x2="300" y2="36" stroke="#c4bcae" stroke-width="2" marker-end="url(#dhar)"/>
          <rect x="310" y="8" width="170" height="56" rx="14" fill="#fff" stroke="#1d6bb3" stroke-width="1.5"/>
          <text x="395" y="32" text-anchor="middle" font-size="12" fill="#6e6a63">recommended plan</text>
          <text x="395" y="54" text-anchor="middle" font-family="Geist, system-ui" font-weight="700" font-size="20" fill="#1d6bb3">N = 3 / house</text>
          <line x1="490" y1="36" x2="558" y2="36" stroke="#c4bcae" stroke-width="2" marker-end="url(#dhar)"/>
          <circle cx="600" cy="36" r="30" fill="#141414"/><path d="M586,37 l9,9 l18,-20" stroke="#f2efe9" stroke-width="5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
          <text x="600" y="84" text-anchor="middle" font-size="11" fill="#141414">operator approves</text>
          <text x="660" y="32" font-size="11" fill="#6e6a63">today: simulator + sizing rule</text>
          <text x="660" y="50" font-size="11" fill="#a86400">next: AI planner proposes</text>
        </g>

        <!-- hour: houses with heat prices, the job goes to the cheapest heat -->
        <g transform="translate(300,132)">
          <g font-size="11" text-anchor="middle">
            <rect x="0" y="26" width="64" height="40" rx="10" fill="#fff" stroke="#157a43"/><text x="32" y="51" fill="#157a43">0.23</text><text x="32" y="82" fill="#6e6a63">heat wanted</text>
            <rect x="96" y="26" width="64" height="40" rx="10" fill="#fff" stroke="#a86400"/><text x="128" y="51" fill="#a86400">0.28</text><text x="128" y="82" fill="#6e6a63">tank half</text>
            <rect x="192" y="26" width="64" height="40" rx="10" fill="#fff" stroke="#d1173a"/><text x="224" y="51" fill="#d1173a">0.33</text><text x="224" y="82" fill="#6e6a63">would dump</text>
          </g>
          <circle cx="32" cy="8" r="7" fill="#c93c05"><animate attributeName="cy" values="-6;8;8" dur="2.4s" repeatCount="indefinite"/></circle>
          <text x="290" y="40" font-size="12" fill="#141414">price every kWh of heat · cheapest heat wins the job</text>
          <text x="290" y="60" font-size="12" fill="#6e6a63">jobs with slack wait for colder hours · only feasible work is admitted</text>
        </g>

        <!-- seconds: lease heartbeat, a node drops, the job jumps -->
        <g transform="translate(300,240)">
          <path d="M0,40 L60,40 L70,20 L80,60 L90,40 L150,40 L160,20 L170,60 L180,40 L230,40" stroke="#157a43" stroke-width="2.5" fill="none"/>
          <circle cx="260" cy="40" r="16" fill="#fff" stroke="#d1173a" stroke-width="2"/><path d="M252,32 l16,16 M268,32 l-16,16" stroke="#d1173a" stroke-width="2.5"/>
          <path d="M280,40 C320,0 360,0 400,40" stroke="#c93c05" stroke-width="2.5" fill="none" stroke-dasharray="6 5"><animate attributeName="stroke-dashoffset" from="22" to="0" dur="1s" repeatCount="indefinite"/></path>
          <circle cx="416" cy="40" r="16" fill="#157a43"/><path d="M409,40 l5,5 l10,-11" stroke="#fff" stroke-width="3" fill="none"/>
          <text x="460" y="34" font-size="12" fill="#141414">lease lost → job resumes elsewhere from its checkpoint</text>
          <text x="460" y="54" font-size="12" fill="#6e6a63">every segment once · signed · hash-linked</text>
        </g>
      </svg>
    </div>

    <div style="display:grid;grid-template-columns:minmax(0,1fr) minmax(280px,380px);gap:16px">
      <div style="border:1px solid #dcd6cc;border-radius:24px;background:#f8f6f1;padding:20px 22px">
        <div style="{_K};color:#a86400;margin-bottom:14px">The real algorithms inside · the planner's toolbox</div>
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px">
          {''.join(f'<div style="background:#fff;border:1px solid #e6e0d6;border-radius:14px;padding:12px 14px;display:flex;flex-direction:column;gap:4px;border-left:4px solid {c}"><b style="font-size:15px;letter-spacing:-0.01em">{n}</b><span style="font-family:Geist Mono,monospace;font-size:11px;color:#6e6a63">{u}</span></div>' for n, u, c in [
            ("Merit-order dispatch", "electricity markets · EPEX, Swissgrid", "#c93c05"),
            ("Earliest-deadline-first admission", "real-time OS schedulers", "#c93c05"),
            ("Slack time-shifting", "carbon-aware batch (Google CICS)", "#c93c05"),
            ("Hysteresis bands", "thermostats · Schmitt trigger", "#a86400"),
            ("Leases + heartbeats", "Google Chubby · HTCondor", "#157a43"),
            ("Preemption + checkpoint/restart", "Borg · Kubernetes", "#157a43"),
            ("Work-fetch backpressure", "BOINC volunteer computing", "#157a43"),
            ("Exactly-once, idempotent results", "Kafka · Spark", "#157a43"),
            ("Ed25519 signatures + hash chain", "Git · Certificate Transparency", "#1d6bb3"),
            ("Merkle receipt", "Bitcoin · Certificate Transparency", "#1d6bb3"),
            ("ECDH P-256 + AES-GCM", "TLS 1.3 · Signal", "#1d6bb3")])}
        </div>
      </div>
      <div style="border-radius:24px;background:#141414;color:#f2efe9;padding:22px;display:flex;flex-direction:column;gap:12px;justify-content:center">
        <svg viewBox="0 0 48 48" width="44" height="44"><rect x="10" y="20" width="28" height="22" rx="5" fill="#c93c05"/><path d="M16,20 v-5 a8,8 0 0 1 16,0 v5" stroke="#c93c05" stroke-width="4" fill="none"/><circle cx="24" cy="31" r="3" fill="#141414"/></svg>
        <b style="font-family:Geist,system-ui;font-size:26px;letter-spacing:-0.03em;line-height:1">Encrypted end to end</b>
        <span style="color:#d8cfc2;line-height:1.45">Encrypted on the customer's device. Only the machine holding the job can open its piece. The coordinator only stores locked boxes.</span>
        <span style="{_K};color:#ff9a5a">live on the transcription demo</span>
      </div>
    </div>
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
