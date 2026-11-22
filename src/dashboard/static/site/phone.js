/* DigitalHeat phone pages (client + server), shared helpers. Vanilla, offline, website theme.
 * Token lives in sessionStorage only (this tab), never in the URL or persistent storage; "Sign out" clears it.
 * Talks directly to the coordinator (CORS allows this site's origin). */
(function () {
  "use strict";
  const DEF = "https://dhruvs-mac-mini.tailaf7ebe.ts.net";
  const K = { url: "dh.phone.url", tok: "dh.phone.tok" };
  const ss = { get: (k) => { try { return sessionStorage.getItem(k); } catch (e) { return null; } },
               set: (k, v) => { try { sessionStorage.setItem(k, v); } catch (e) {} },
               del: (k) => { try { sessionStorage.removeItem(k); } catch (e) {} } };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const NODE_C = ["#c93c05", "#1d6bb3", "#157a43", "#a86400", "#7b3fa0", "#d1173a"];
  const nodeColour = (() => { const m = {}; let i = 0; return (n) => (m[n] ??= NODE_C[i++ % NODE_C.length]); })();

  function cfg() { return { url: (ss.get(K.url) || DEF).replace(/\/$/, ""), tok: ss.get(K.tok) || "" }; }
  async function api(path, opt = {}) {
    const c = cfg();
    const h = Object.assign({ Authorization: "Bearer " + c.tok }, opt.headers || {});
    if (opt.json !== undefined) { h["Content-Type"] = "application/json"; opt.body = JSON.stringify(opt.json); }
    const r = await fetch(c.url + path, { method: opt.method || "GET", headers: h, body: opt.body });
    const ct = r.headers.get("content-type") || "";
    const data = ct.includes("json") ? await r.json().catch(() => ({})) : await r.text();
    if (!r.ok) { const e = new Error((data && data.detail) ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : r.status + ""); e.status = r.status; e.data = data; throw e; }
    return data;
  }

  /* sign-in card: fills `root`, calls onReady() once signed in */
  function signin(root, role, onReady) {
    const c = cfg();
    if (c.tok) { root.innerHTML = `<div class="row"><span class="mute">Signed in as ${esc(role)} · ${esc(c.url.replace(/^https?:\/\//, ""))}</span><button class="ghost" id="so">Sign out</button></div>`;
      root.querySelector("#so").onclick = () => { ss.del(K.tok); location.reload(); }; onReady(); return; }
    root.innerHTML = `<label class="lab">Coordinator</label><input id="u" value="${esc(c.url)}" autocomplete="off">
      <label class="lab">${esc(role)} token</label><input id="t" type="password" autocomplete="off" placeholder="paste token">
      <button class="primary" id="go">Sign in</button>
      <p class="mute small">The token stays in this browser tab only and is sent only to the coordinator above.</p>`;
    root.querySelector("#go").onclick = () => { ss.set(K.url, root.querySelector("#u").value.trim()); ss.set(K.tok, root.querySelector("#t").value.trim()); location.reload(); };
  }

  /* events: poll /v1/events/poll after the newest id; calls fn(event) */
  function events(fn, every = 1200) {
    let after = null, stop = false;
    (async function loop() {
      while (!stop) {
        try {
          if (after === null) { const r = await api("/v1/events/poll?after=0&limit=1"); after = Math.max(0, (r.last_id || 0)); }
          const r = await api(`/v1/events/poll?after=${after}&limit=200`);
          for (const e of r.events || []) { after = Math.max(after, e.id); fn(e); }
        } catch (e) { /* transient */ }
        await new Promise((r) => setTimeout(r, every));
      }
    })();
    return () => { stop = true; };
  }

  /* microphone -> 16 kHz mono PCM16 WAV segments of `segS` seconds with `ovS` s overlap prefix */
  async function mic(onSegment, segS = 4, ovS = 1.0) {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    const ac = new (window.AudioContext || window.webkitAudioContext)();
    const src = ac.createMediaStreamSource(stream);
    const proc = ac.createScriptProcessor(4096, 1, 1);
    const ratio = ac.sampleRate / 16000, SEG = 16000 * segS, OV = Math.round(16000 * ovS);
    let buf = new Float32Array(0), tail = new Float32Array(0), seq = 0, frac = 0;
    proc.onaudioprocess = (ev) => {
      const x = ev.inputBuffer.getChannelData(0), out = [];
      for (let i = frac; i < x.length; i += ratio) out.push(x[Math.floor(i)]);
      frac = (frac + Math.ceil((x.length - frac) / ratio) * ratio) - x.length;
      const nb = new Float32Array(buf.length + out.length); nb.set(buf); nb.set(out, buf.length); buf = nb;
      while (buf.length >= SEG) {
        const body = buf.subarray(0, SEG), seg = new Float32Array(tail.length + SEG);
        seg.set(tail); seg.set(body, tail.length);
        tail = body.slice(SEG - OV); buf = buf.slice(SEG);
        onSegment(seq++, wav(seg), level(body));
      }
    };
    src.connect(proc); proc.connect(ac.destination);
    return { stop: () => { proc.disconnect(); src.disconnect(); stream.getTracks().forEach((t) => t.stop()); ac.close(); } };
  }
  function level(a) { let s = 0; for (let i = 0; i < a.length; i += 32) s += a[i] * a[i]; return Math.sqrt(s / (a.length / 32)); }
  function wav(f) {
    const b = new ArrayBuffer(44 + f.length * 2), v = new DataView(b), w = (o, s) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
    w(0, "RIFF"); v.setUint32(4, 36 + f.length * 2, true); w(8, "WAVE"); w(12, "fmt "); v.setUint32(16, 16, true);
    v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, 16000, true); v.setUint32(28, 32000, true);
    v.setUint16(32, 2, true); v.setUint16(34, 16, true); w(36, "data"); v.setUint32(40, f.length * 2, true);
    for (let i = 0; i < f.length; i++) { const s = Math.max(-1, Math.min(1, f[i])); v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true); }
    return new Blob([b], { type: "audio/wav" });
  }

  window.DHPhone = { cfg, api, signin, events, mic, esc, nodeColour };
})();
