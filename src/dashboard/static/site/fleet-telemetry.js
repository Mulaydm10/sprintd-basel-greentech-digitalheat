/* DigitalHeat · 07 Year · city-fleet job telemetry (#118, design half). Vanilla JS, offline, no dependencies.
 *
 * Mounts into every element with [data-dh-fleet-telemetry]. Reads the #119 fleetview-v1 run from the dashboard:
 *   /api/fleet/index, /api/fleet/fleet, /api/fleet/jobs, /api/fleet/houses.u16
 * Follows the year page clock through window CustomEvents (contract agreed on #118):
 *   dh:tick        {hour, n, policy, playing, fleetKey}          (page -> everyone, on every hour change)
 *   dh:select-job  {unit_id | null, source: 'panel' | 'map'}     (both ways; we ignore our own)
 *   dh:select-house{house | null}                                (map -> us: filter the job table)
 * Until the page sends dh:tick, the panel runs its own small clock so it is never dead.
 * Every number shown is read from the run files; the fleet itself is ASSUMED and labelled so.
 */
(function () {
  "use strict";
  const C = { ink: "#141414", mute: "#6e6a63", line: "#dcd6cc", card: "#ffffff", cream: "#f8f6f1", heat: "#c93c05",
              dump: "#d1173a", held: "#a86400", cold: "#1d6bb3", ok: "#157a43", idle: "#c4bcae" };
  const MONO = "'Geist Mono', ui-monospace, monospace";
  const STATE = ["idle", "heat used", "dumping", "held"];
  const STATE_C = [C.idle, C.heat, C.dump, C.held];
  const fmt = (v, d = 0) => (v == null || !isFinite(v) ? "–" : Number(v).toLocaleString("de-CH", { maximumFractionDigits: d, minimumFractionDigits: d }));
  const el = (tag, css, html) => { const e = document.createElement(tag); if (css) e.style.cssText = css; if (html != null) e.innerHTML = html; return e; };
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function base() {
    const s = document.currentScript || document.querySelector('script[src*="fleet-telemetry.js"]');
    return (s && s.dataset.api) || ".";
  }
  const API = base().replace(/\/$/, "");

  async function load() {
    const get = async (p, bin) => { const r = await fetch(API + "/api/fleet/" + p); if (!r.ok) throw new Error(p + " " + r.status + " " + (await r.text()).slice(0, 160)); return bin ? r.arrayBuffer() : r.json(); };
    const [index, fleet, jobs, raw] = await Promise.all([get("index"), get("fleet"), get("jobs"), get("houses.u16", true)]);
    if (index.schema !== "fleetview-v1") throw new Error("unexpected schema " + index.schema);
    const K = index.houses.length, H = index.hours, u16 = new Uint16Array(raw), series = {};
    let off = 0;
    for (const f of index.series.fields) { series[f.name] = { off, scale: f.scale }; off += K * H; }
    const at = (name, house, hour) => { const s = series[name]; return s ? u16[s.off + house * H + hour] * s.scale : null; };
    // unit -> sorted runs, and per job its first/last run hour
    const units = [];
    for (const j of jobs.tracked || []) for (const u of j.units || []) {
      const runs = (u.runs || []).slice().sort((a, b) => a[0] - b[0]);
      units.push({ job: j, unit: u.unit, runs, first: runs.length ? runs[0][0] : null, last: runs.length ? runs[runs.length - 1][0] : null });
    }
    return { index, fleet, jobs, at, K, H, units };
  }

  function unitStateAt(u, h) {
    const j = u.job, arr = j.arrival_h, dl = j.arrival_h + (j.deadline_h ?? 0);
    if (h < arr) return null;                                     // not yet arrived: not shown
    const run = u.runs.find((r) => r[0] === h);
    if (run) return { s: "running", house: run[1], c: C.heat };
    if (j.state === "rejected") return h <= arr + 1 ? { s: "rejected", c: C.dump } : null;
    if (u.last != null && h > u.last) return h <= u.last + 3 ? { s: j.state === "missed" ? "missed" : "done", c: j.state === "missed" ? C.dump : C.ok } : null;
    if (j.state === "missed" && h > dl) return h <= dl + 3 ? { s: "missed", c: C.dump } : null;
    const left = Math.max(0, dl - h);
    return { s: u.first == null || h < u.first ? "waiting" : "paused", slack: left, c: C.held };
  }

  function decisionLine(d, h) {
    const f = d.fleet, g = (k) => (f[k] ? f[k][h] : null);
    let heat = 0, dump = 0, held = 0, idle = 0, on = 0;
    for (let k = 0; k < d.K; k++) {
      const st = d.at("state", k, h), s = d.at("servers_on", k, h) || 0;
      on += s;
      if (st === 1) heat++; else if (st === 2) dump++; else if (st === 3) held++; else idle++;
    }
    const parts = [];
    parts.push(`${fmt(g("assigned"))} units → ${heat + dump} houses (${on} servers on)`);
    if (heat) parts.push(`${heat} where heat is wanted`);
    if (dump) parts.push(`${dump} dumping to meet a deadline`);
    if (held) parts.push(`${held} held (tank full)`);
    if (g("deferred")) parts.push(`${fmt(g("deferred"))} deferred (slack)`);
    if (g("rejected")) parts.push(`${fmt(g("rejected"))} rejected at admission`);
    if (g("ballast_units")) parts.push(`${fmt(g("ballast_units"))} ballast filler`);
    return parts.join(" · ");
  }

  function hourLabel(d, h) {
    const t0 = Date.parse(d.index.start || "2025-01-01T00:00:00+01:00");
    const dt = new Date(t0 + h * 3600e3);
    return dt.toLocaleString("en-GB", { timeZone: d.index.tz || "Europe/Zurich", weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  }

  function mount(root) {
    root.innerHTML = "";
    root.style.cssText += `;font-family:${MONO};color:${C.ink};display:flex;flex-direction:column;gap:14px;margin-bottom:14px`;
    const card = (title, right) => {
      const c = el("div", `border:1px solid ${C.line};border-radius:20px;background:${C.card};padding:18px 20px;min-width:0`);
      const h = el("div", `display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;font-size:11px;letter-spacing:0.08em;text-transform:uppercase;color:${C.mute};margin-bottom:12px`);
      h.append(el("span", "", title)); const r = el("span", ""); if (right) r.innerHTML = right; h.append(r);
      c.append(h); c._right = r; return c;
    };
    const head = card("City fleet · job telemetry · our scheduler, every hour", "loading…");
    const tiles = el("div", "display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1px;background:" + C.line + ";border:1px solid " + C.line + ";border-radius:14px;overflow:hidden");
    head.append(tiles);
    const note = el("p", `margin:12px 0 0;font-size:11.5px;line-height:1.55;color:${C.mute}`);
    head.append(note);

    const row = el("div", "display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,460px),1fr));gap:14px");
    const merit = card("Merit order this hour · each bar = one house's cost per server-hour", "");
    const cv = el("canvas", "width:100%;height:220px;display:block");
    merit.append(cv);
    const legend = el("div", `display:flex;gap:12px;flex-wrap:wrap;font-size:11px;color:${C.mute};margin-top:10px`,
      STATE.map((s, i) => `<span style="display:flex;gap:6px;align-items:center"><span style="width:10px;height:10px;border-radius:3px;background:${STATE_C[i]}"></span>${s}</span>`).join("") +
      `<span style="display:flex;gap:6px;align-items:center"><span style="width:14px;height:2px;background:${C.ink}"></span>paid bid</span>`);
    merit.append(legend);
    const log = card("Decision log · plain words", "");
    const logList = el("div", "display:flex;flex-direction:column;gap:6px;font-size:12px;line-height:1.45;max-height:262px;overflow:auto");
    log.append(logList);
    row.append(merit, log);

    const jobsCard = card("Jobs · queue, running, done (every tracked job of the stream)", "");
    const filt = el("div", `font-size:11px;color:${C.mute};margin:-4px 0 10px`);
    const tbl = el("div", "overflow:auto;max-height:340px");
    jobsCard.append(filt, tbl);

    const tot = card("Year totals · same fleet, same jobs", "");
    const totGrid = el("div", "display:grid;grid-template-columns:minmax(0,1.4fr) repeat(2,minmax(0,1fr));gap:6px 14px;font-size:12px");
    tot.append(totGrid);

    root.append(head, row, jobsCard, tot);
    return { head, tiles, note, merit, cv, logList, jobsCard, filt, tbl, totGrid };
  }

  function tile(label, value, color) {
    return `<div style="background:${C.cream};padding:12px 14px"><div style="font-size:10.5px;letter-spacing:0.08em;text-transform:uppercase;color:${C.mute}">${label}</div><div style="font-size:20px;font-weight:600;margin-top:4px;color:${color || C.ink}">${value}</div></div>`;
  }

  function drawMerit(ui, d, h) {
    const cv = ui.cv, dpr = window.devicePixelRatio || 1, w = cv.clientWidth || 600, hh = cv.clientHeight || 220;
    if (cv.width !== w * dpr) { cv.width = w * dpr; cv.height = hh * dpr; }
    const x = cv.getContext("2d"); x.setTransform(dpr, 0, 0, dpr, 0, 0); x.clearRect(0, 0, w, hh);
    const bars = [];
    for (let k = 0; k < d.K; k++) bars.push({ k, mc: d.at("mc_chf_per_server_h", k, h), st: d.at("state", k, h), on: d.at("servers_on", k, h) });
    bars.sort((a, b) => a.mc - b.mc);
    const bid = d.fleet.paid_price_chf_per_server_h ? d.fleet.paid_price_chf_per_server_h[h] : null;
    const max = Math.max(0.0001, bid || 0, ...bars.map((b) => b.mc)) * 1.15, pad = 26, bw = (w - pad) / Math.max(1, bars.length);
    x.font = `10px ${MONO}`; x.fillStyle = C.mute; x.fillText(fmt(max, 2) + " CHF", 0, 10); x.fillText("0", 0, hh - 2);
    bars.forEach((b, i) => {
      const bh = (b.mc / max) * (hh - 16);
      x.fillStyle = STATE_C[b.st] || C.idle; x.globalAlpha = b.on > 0 ? 1 : 0.45;
      x.fillRect(pad + i * bw + (bw > 3 ? 0.5 : 0), hh - bh, Math.max(1, bw - (bw > 3 ? 1 : 0)), bh);
    });
    x.globalAlpha = 1;
    if (bid != null) { const y = hh - (bid / max) * (hh - 16); x.strokeStyle = C.ink; x.lineWidth = 1.5; x.beginPath(); x.moveTo(pad, y); x.lineTo(w, y); x.stroke(); x.fillStyle = C.ink; x.fillText("bid " + fmt(bid, 3), w - 70, y - 4); }
    const clear = bars.filter((b) => bid != null && b.mc <= bid).length;
    ui.merit._right.textContent = bid != null ? `${clear}/${d.K} houses clear the bid` : "";
  }

  function start(root) {
    const ui = mount(root);
    let d = null, hour = 0, policy = "ours", house = null, sel = null, ownClock = true, playing = true, lastLogHour = -1;
    const lines = [];

    function renderJobs() {
      const rows = [];
      for (const u of d.units) {
        const s = unitStateAt(u, hour);
        if (!s) continue;
        if (house != null && s.house !== house) continue;
        rows.push({ u, s });
      }
      const order = { running: 0, waiting: 1, paused: 2, done: 3, missed: 4, rejected: 5 };
      rows.sort((a, b) => order[a.s.s] - order[b.s.s] || a.u.job.arrival_h - b.u.job.arrival_h);
      ui.filt.innerHTML = house != null ? `filtered to house ${house} · <a href="#" data-clear style="color:${C.heat}">show all</a>` :
        `${rows.filter((r) => r.s.s === "running").length} running · ${rows.filter((r) => r.s.s === "waiting" || r.s.s === "paused").length} waiting · click a row to find it on the map`;
      const th = (t) => `<th style="text-align:left;font-weight:500;color:${C.mute};padding:6px 8px;border-bottom:1px solid ${C.line};position:sticky;top:0;background:${C.card}">${t}</th>`;
      let html = `<table style="width:100%;border-collapse:collapse;font-size:12px"><thead><tr>${["unit", "type", "class", "bid", "slack left", "state", "house"].map(th).join("")}</tr></thead><tbody>`;
      for (const { u, s } of rows.slice(0, 200)) {
        const on = sel === u.unit;
        html += `<tr data-unit="${esc(u.unit)}" style="cursor:pointer;background:${on ? "#fbe9df" : "transparent"}">` +
          `<td style="padding:5px 8px;border-bottom:1px solid #efeae2">${esc(u.unit)}</td>` +
          `<td style="padding:5px 8px;border-bottom:1px solid #efeae2">${esc(String(u.job.type).replace("_", " "))}</td>` +
          `<td style="padding:5px 8px;border-bottom:1px solid #efeae2">${esc(u.job.class)}</td>` +
          `<td style="padding:5px 8px;border-bottom:1px solid #efeae2">${fmt(u.job.bid, 2)}</td>` +
          `<td style="padding:5px 8px;border-bottom:1px solid #efeae2">${s.slack != null ? fmt(s.slack) + " h" : "–"}</td>` +
          `<td style="padding:5px 8px;border-bottom:1px solid #efeae2;color:${s.c};font-weight:600">${s.s}</td>` +
          `<td style="padding:5px 8px;border-bottom:1px solid #efeae2">${s.house != null ? "house " + s.house : "–"}</td></tr>`;
      }
      if (!rows.length) html += `<tr><td colspan="7" style="padding:10px 8px;color:${C.mute}">No tracked job is active this hour.</td></tr>`;
      ui.tbl.innerHTML = html + "</tbody></table>";
    }

    function render() {
      if (!d) return;
      const h = Math.max(0, Math.min(d.H - 1, hour | 0)), f = d.fleet, g = (k, dd) => fmt(f[k] ? f[k][h] : null, dd || 0);
      hour = h;
      ui.head._right.innerHTML = `<span style="color:${d.index.fixture ? C.held : C.ok}">● ${d.index.fixture ? "FIXTURE · not results" : "FLEET RUN · " + esc(String(d.index.provenance.key).slice(0, 10))}</span> · ${esc(hourLabel(d, h))}`;
      ui.tiles.innerHTML = tile("houses", fmt(d.K)) + tile("queue", g("queue")) + tile("arrived", g("arrivals")) +
        tile("assigned", g("assigned"), C.heat) + tile("deferred", g("deferred"), C.held) + tile("rejected", g("rejected"), C.dump) +
        tile("heat used kWh", g("heat_used_kwh", 1), C.heat) + tile("dumped kWh", g("dumped_kwh", 1), C.dump) +
        tile("backup kWh", g("unmet_kwh", 1), C.cold) + tile("net CHF so far", g("net_chf_cum", 0), C.ok);
      const a = d.index.assumed || {};
      ui.note.innerHTML = `ASSUMED fleet: ${esc(a.houses ?? d.K)} houses (${esc(a.placement || "on residential buildings")}); ${esc(a.servers || "")} ${esc(a.job_stream || "")}. REAL: Basel 2025 weather and our scheduler: one <code>decide()</code> over all houses every hour.`;
      drawMerit(ui, d, h);
      if (h !== lastLogHour) {
        lines.unshift({ h, t: decisionLine(d, h) });
        if (Math.abs(h - lastLogHour) > 1) lines.length = 1;
        lines.length = Math.min(lines.length, 24);
        lastLogHour = h;
        ui.logList.innerHTML = lines.map((l, i) => `<div style="padding:6px 0;border-bottom:1px solid #efeae2;opacity:${1 - i * 0.03}"><span style="color:${C.heat}">${esc(hourLabel(d, l.h))}</span> · ${esc(l.t)}</div>`).join("");
      }
      renderJobs();
    }

    function renderTotals() {
      const t = d.index.totals || {}, o = t.ours || {}, b = t.baseline || {};
      const r = (label, k, dd, unit) => `<span style="color:${C.mute}">${label}</span><span style="font-weight:600;color:${C.heat}">${fmt(o[k], dd)}${unit || ""}</span><span>${fmt(b[k], dd)}${unit || ""}</span>`;
      ui.totGrid.innerHTML = `<span></span><span style="color:${C.mute}">ours (merit)</span><span style="color:${C.mute}">thermostat</span>` +
        r("heat covered", "coverage_pct", 1, " %") + r("heat used kWh", "heat_used_kwh") + r("dumped kWh", "dumped_kwh") +
        r("backup heater kWh", "backup_kwh") + r("units done", "units_done") + r("units missed", "units_missed") +
        r("missed deadlines", "missed_pct", 1, " %") + r("utilisation", "utilisation_pct", 1, " %") + r("net CHF excl. hardware", "net_chf_excl_hardware");
    }

    ui.tbl.addEventListener("click", (e) => {
      const tr = e.target.closest("tr[data-unit]"); if (!tr) return;
      sel = sel === tr.dataset.unit ? null : tr.dataset.unit;
      window.dispatchEvent(new CustomEvent("dh:select-job", { detail: { unit_id: sel, source: "panel" } }));
      renderJobs();
    });
    ui.filt.addEventListener("click", (e) => { if (e.target.closest("[data-clear]")) { e.preventDefault(); house = null; renderJobs(); } });
    window.addEventListener("dh:tick", (e) => {
      const x = e.detail || {}; ownClock = false;
      if (typeof x.hour === "number") hour = x.hour;
      if (x.policy) policy = x.policy;
      playing = !!x.playing; render();
    });
    window.addEventListener("dh:select-job", (e) => { const x = e.detail || {}; if (x.source === "panel") return; sel = x.unit_id || null; if (d) renderJobs(); });
    window.addEventListener("dh:select-house", (e) => { const x = e.detail || {}; house = x.house == null ? null : x.house; if (d) renderJobs(); });

    load().then((data) => {
      d = data; renderTotals(); render();
      let t = 0;
      const step = (ts) => {           // own clock (6 h per second) until the page's dh:tick takes over
        if (ownClock && playing && document.visibilityState === "visible") {
          if (!t) t = ts;
          if (ts - t > 166) { t = ts; hour = (hour + 1) % d.H; render(); }
        }
        if (ownClock) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    }).catch((err) => {
      ui.head._right.innerHTML = `<span style="color:${C.held}">● NO FLEET DATA</span>`;
      ui.note.innerHTML = `Could not load the city-fleet run (${esc(err.message)}). Run <code>python -m simulate_year.fleetview --out runs/fleetview</code>, then reload. Nothing here is invented: without data it stays empty.`;
    });
  }

  function boot() { document.querySelectorAll("[data-dh-fleet-telemetry]").forEach((r) => { if (!r._dh) { r._dh = 1; start(r); } }); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
  new MutationObserver(boot).observe(document.documentElement, { childList: true, subtree: true });
})();
