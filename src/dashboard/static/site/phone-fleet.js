/* DigitalHeat · 04 Live · wow #2: the volunteer phone fleet forming live around the coordinator (Mac).
 * Mounts into [data-dh-phone-fleet]. Data: /api/phones/state (volunteer phones, events) + /api/nodes (live laptops).
 * three.js r170 (vendored), bloom. Real data only: every node/edge/packet is a device or job from the fleet state. */
import * as THREE from "./vendor/three/three.module.js";
import { OrbitControls } from "./vendor/three/addons/controls/OrbitControls.js";
import { EffectComposer } from "./vendor/three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "./vendor/three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "./vendor/three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "./vendor/three/addons/postprocessing/OutputPass.js";

const C = { bg: 0x0b0a09, heat: 0xff6a1f, hot: 0xffb070, idle: 0xc9bfb0, stop: 0xd1173a, cold: 0x3d8fd8, ok: 0x2fbf71, laptop: 0xf2efe9 };
const MONO = "'Geist Mono', ui-monospace, monospace";
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const LAPTOPS = { "omen-gpu": "Omen · laptop", "laptop-2": "Parth's HP · laptop", "mac-live": "Mac · laptop" };

function ui(root) {
  root.innerHTML = `
  <div style="margin:10px 0 30px;font-family:${MONO};color:#141414">
    <div style="display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap;margin-bottom:12px">
      <div><div style="font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#a86400">Wow #2 · the room becomes a data centre</div>
      <div style="font-family:'Geist',system-ui;font-weight:760;font-size:clamp(32px,4.4vw,64px);letter-spacing:-.05em;line-height:.95">Your phones. <span style="color:#c93c05">Our fleet.</span></div></div>
      <div data-k="tiles" style="display:grid;grid-template-columns:repeat(4,minmax(92px,1fr));gap:1px;background:#dcd6cc;border:1px solid #dcd6cc;border-radius:14px;overflow:hidden"></div>
    </div>
    <div style="display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:14px" data-k="grid">
      <div style="position:relative;border-radius:20px;overflow:hidden;background:#0b0a09;border:1px solid #141414;min-height:560px">
        <div data-k="gl" style="position:absolute;inset:0"></div>
        <div data-k="labels" style="position:absolute;inset:0;pointer-events:none;overflow:hidden"></div>
        <div data-k="banner" style="position:absolute;left:18px;top:16px;right:18px;color:#f2efe9;font-size:12px;letter-spacing:.06em;text-transform:uppercase;display:flex;justify-content:space-between;gap:10px;pointer-events:none">
          <span>coordinator · Mac mini, Basel · live fleet</span><span data-k="clock"></span></div>
        <div data-k="flash" style="position:absolute;left:50%;bottom:22px;transform:translateX(-50%);padding:10px 16px;border-radius:999px;background:rgba(20,12,8,.78);border:1px solid rgba(255,160,90,.35);color:#ffd9bf;font-size:13px;opacity:0;transition:opacity .4s;pointer-events:none;white-space:nowrap"></div>
        <div style="position:absolute;left:18px;bottom:16px;color:#8a8278;font-size:10.5px;pointer-events:none">● orange = phone heating (running a job) · ● red = STOP · ◆ laptops · the core = coordinator · drag to orbit</div>
      </div>
      <div style="display:flex;flex-direction:column;gap:14px">
        <div style="border:1px solid #dcd6cc;border-radius:20px;background:#fff;padding:14px;text-align:center">
          <div style="font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#6e6a63;margin-bottom:6px">Scan to join</div>
          <img data-k="qr" alt="join QR" style="width:100%;max-width:240px;aspect-ratio:1;image-rendering:pixelated;border-radius:8px">
          <div data-k="qrnote" style="font-size:11px;color:#6e6a63;margin-top:6px">max 20 phones · 3 servers : 1 client</div>
        </div>
        <div style="border:1px solid #dcd6cc;border-radius:20px;background:#fff;padding:14px;flex:1;min-height:200px;display:flex;flex-direction:column">
          <div style="font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#6e6a63;margin-bottom:8px">Coordinator log</div>
          <div data-k="log" style="font-size:11.5px;line-height:1.45;display:flex;flex-direction:column;gap:5px;overflow:auto;max-height:330px"></div>
        </div>
      </div>
    </div>
  </div>`;
  const k = {}; root.querySelectorAll("[data-k]").forEach((e) => (k[e.dataset.k] = e));
  const mq = () => (k.grid.style.gridTemplateColumns = innerWidth < 900 ? "1fr" : "minmax(0,1fr) 300px");
  mq(); addEventListener("resize", mq);
  return k;
}

function tile(label, v, c) {
  return `<div style="background:#f8f6f1;padding:8px 12px"><div style="font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:#6e6a63">${label}</div><div style="font-family:'Geist',system-ui;font-size:24px;font-weight:650;color:${c || "#141414"}">${v}</div></div>`;
}

function start(root) {
  const k = ui(root);
  // ---------- three ----------
  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(2, devicePixelRatio || 1));
  renderer.setClearColor(C.bg, 1);
  k.gl.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(C.bg, 0.012);
  const cam = new THREE.PerspectiveCamera(48, 1, 0.1, 500);
  cam.position.set(0, 26, 62);
  const ctl = new OrbitControls(cam, renderer.domElement);
  ctl.enableDamping = true; ctl.autoRotate = true; ctl.autoRotateSpeed = 0.15; ctl.minDistance = 25; ctl.maxDistance = 120;
  const comp = new EffectComposer(renderer);
  comp.addPass(new RenderPass(scene, cam));
  const bloom = new UnrealBloomPass(new THREE.Vector2(512, 512), 0.4, 0.45, 0.4);
  comp.addPass(bloom); comp.addPass(new OutputPass());
  scene.add(new THREE.AmbientLight(0xffffff, 0.35));
  const key = new THREE.PointLight(0xffb070, 60, 120); key.position.set(0, 10, 0); scene.add(key);

  // floor grid + star dust
  const grid = new THREE.PolarGridHelper(46, 16, 6, 96, 0x2a2420, 0x1a1512); grid.position.y = -9; scene.add(grid);
  { const g = new THREE.BufferGeometry(), n = 900, p = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) { const r = 60 + Math.random() * 90, a = Math.random() * 6.283, y = (Math.random() - 0.5) * 80; p.set([Math.cos(a) * r, y, Math.sin(a) * r], i * 3); }
    g.setAttribute("position", new THREE.BufferAttribute(p, 3));
    scene.add(new THREE.Points(g, new THREE.PointsMaterial({ color: 0x6b5a4a, size: 0.25, transparent: true, opacity: 0.25 }))); }

  // coordinator core
  const core = new THREE.Group(); scene.add(core);
  const coreMesh = new THREE.Mesh(new THREE.IcosahedronGeometry(3.2, 1), new THREE.MeshStandardMaterial({ color: 0x1a1210, emissive: C.heat, emissiveIntensity: 0.8, flatShading: true, metalness: 0.3, roughness: 0.4 }));
  core.add(coreMesh);
  const coreWire = new THREE.Mesh(new THREE.IcosahedronGeometry(4.4, 1), new THREE.MeshBasicMaterial({ color: C.hot, wireframe: true, transparent: true, opacity: 0.1 }));
  core.add(coreWire);
  const rings = [5.5, 7.2].map((r, i) => { const m = new THREE.Mesh(new THREE.TorusGeometry(r, 0.05, 8, 128), new THREE.MeshBasicMaterial({ color: i ? C.cold : C.hot, transparent: true, opacity: 0.25 })); m.rotation.x = Math.PI / 2 + i * 0.4; core.add(m); return m; });

  // nodes
  const nodes = new Map();    // id -> {g, mesh, glow, line, pos, kind, label, state, born, heat}
  const phoneGeo = new THREE.BoxGeometry(1.5, 2.8, 0.22), lapGeo = new THREE.BoxGeometry(3.6, 0.28, 2.4), lapLid = new THREE.BoxGeometry(3.6, 2.3, 0.12);
  const heatTex = (() => { const c = document.createElement("canvas"); c.width = c.height = 64; const x = c.getContext("2d"); const g = x.createRadialGradient(32, 32, 0, 32, 32, 32); g.addColorStop(0, "rgba(255,190,120,1)"); g.addColorStop(0.4, "rgba(255,106,31,.5)"); g.addColorStop(1, "rgba(255,106,31,0)"); x.fillStyle = g; x.fillRect(0, 0, 64, 64); return new THREE.CanvasTexture(c); })();

  function slotFor(kind, n) {
    if (kind === "laptop") { const a = n * 2.094 + 0.5; return new THREE.Vector3(Math.cos(a) * 15, -2, Math.sin(a) * 15); }
    // phones: golden-angle spiral on a shell, rising with the join order
    const ga = 2.39996, a = n * ga, r = 24 + (n % 3) * 4, y = -4 + ((n * 7) % 13) - 2;
    return new THREE.Vector3(Math.cos(a) * r, y, Math.sin(a) * r);
  }
  function addNode(id, kind, label, n) {
    const g = new THREE.Group();
    const mat = new THREE.MeshStandardMaterial({ color: 0x1b1714, emissive: kind === "laptop" ? C.laptop : C.idle, emissiveIntensity: 0.35, metalness: 0.4, roughness: 0.35 });
    let mesh;
    if (kind === "laptop") { mesh = new THREE.Group(); const base = new THREE.Mesh(lapGeo, mat); const lid = new THREE.Mesh(lapLid, mat); lid.position.set(0, 1.15, -1.2); lid.rotation.x = -0.25; mesh.add(base, lid); }
    else mesh = new THREE.Mesh(phoneGeo, mat);
    g.add(mesh);
    const glow = new THREE.Sprite(new THREE.SpriteMaterial({ map: heatTex, color: C.heat, transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending }));
    glow.scale.set(9, 9, 1); g.add(glow);
    const pos = slotFor(kind, n);
    g.position.copy(kind === "laptop" ? pos : pos.clone().multiplyScalar(4.5).setY(pos.y + 40));   // phones fly in
    scene.add(g);
    const lg = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), g.position.clone()]);
    const line = new THREE.Line(lg, new THREE.LineBasicMaterial({ color: kind === "laptop" ? 0x8a8278 : 0x5a4a3c, transparent: true, opacity: 0.35 }));
    scene.add(line);
    const el = document.createElement("div");
    el.style.cssText = `position:absolute;transform:translate(-50%,-140%);font:10px ${MONO};color:#cfc6b8;white-space:nowrap;text-shadow:0 0 4px #000;opacity:.7`;
    k.labels.appendChild(el);
    const nd = { id, g, mesh, mat, glow, line, pos, kind, label, state: "idle", born: performance.now(), el, heat: 0 };
    nodes.set(id, nd); return nd;
  }

  // packets (job moving between nodes) + rising heat particles
  const packets = [];
  function packet(from, to, color, ms = 1400, arc = 8) {
    const s = new THREE.Mesh(new THREE.SphereGeometry(0.35, 10, 10), new THREE.MeshBasicMaterial({ color }));
    scene.add(s);
    const trail = []; packets.push({ s, from: from.clone(), to: to.clone(), t0: performance.now(), ms, arc, trail, color });
  }
  const sparks = [];
  function spark(p) {
    const m = new THREE.Sprite(new THREE.SpriteMaterial({ map: heatTex, color: C.hot, transparent: true, opacity: 0.9, depthWrite: false, blending: THREE.AdditiveBlending }));
    m.position.copy(p).add(new THREE.Vector3((Math.random() - 0.5) * 1.5, 1.2, (Math.random() - 0.5) * 1.5)); m.scale.setScalar(1.2);
    scene.add(m); sparks.push({ m, v: 0.04 + Math.random() * 0.05, life: 1 });
  }

  // ---------- data ----------
  let after = 0, st = null, lapN = 0, flashT = null;
  const logLines = [];
  function logAt(t, c, at) {
    logLines.unshift(`<div><span style="color:#8a8278">${new Date(at ? at * 1000 : Date.now()).toLocaleTimeString("de-CH")}</span> <span style="color:${c || "#141414"}">${t}</span></div>`);
    logLines.length = Math.min(logLines.length, 60); k.log.innerHTML = logLines.join("");
  }
  const log = (t, c) => logAt(t, c);
  function flash(t) { k.flash.innerHTML = t; k.flash.style.opacity = 1; clearTimeout(flashT); flashT = setTimeout(() => (k.flash.style.opacity = 0), 3800); }
  const lbl = (id) => (nodes.get(id) || {}).label || id;

  async function poll() {
    try {
      const r = await fetch(`./api/phones/state?after=${after}`); if (!r.ok) throw new Error(r.status);
      st = await r.json(); after = st.last_id || after;
      for (const d of st.devices) {
        let nd = nodes.get(d.id);
        if (!nd) { nd = addNode(d.id, "phone", `${d.label} · ${d.role}`, d.n); if (d.role === "client") nd.mat.emissive.setHex(C.cold); }
        nd.state = d.online ? d.state : "gone"; nd.role = d.role;
      }
      for (const e of st.events || []) onEvent(e);
      const ph = st.devices.filter((d) => d.state !== "left");
      const heating = st.devices.filter((d) => d.state === "busy").length;
      const done = st.jobs.filter((j) => j.state === "done").length;
      const hand = st.jobs.reduce((a, j) => a + Math.max(0, j.hops.length - 1), 0);
      k.tiles.innerHTML = tile("phones", `${ph.length}/${st.cap}`) + tile("heating", heating, "#c93c05") + tile("jobs done", done, "#157a43") + tile("handovers", hand, "#1d6bb3");
    } catch (e) { /* keep animating */ }
    try {   // live laptops from the coordinator (read-only via the dashboard)
      const r = await fetch("./api/nodes"); if (r.ok) {
        const j = await r.json();
        for (const n of j.nodes || j.items || []) {
          if (!LAPTOPS[n.node_id]) continue;
          let nd = nodes.get(n.node_id); if (!nd) nd = addNode(n.node_id, "laptop", LAPTOPS[n.node_id], lapN++);
          nd.state = n.suspect ? "gone" : n.running_unit ? "busy" : "idle";
        }
      }
    } catch (e) {}
  }
  function onEvent(e) {
    const d = nodes.get(e.device);
    const log = (t, c) => logAt(t, c, e.t);
    if (e.type === "device.joined") { log(`${esc(e.label)} joined as <b>${e.role}</b>`, e.role === "server" ? "#c93c05" : "#1d6bb3"); flash(`＋ ${esc(e.label)} joined the fleet as a ${e.role}`); }
    if (e.type === "job.submitted") log(`job ${e.job} submitted by ${esc(lbl(e.client))}`, "#1d6bb3");
    if (e.type === "job.assigned" && d) { packet(new THREE.Vector3(), d.g.position, C.hot); log(`${e.job} → ${esc(d.label)}${e.moved ? ` · resumes at step ${e.step}` : ""}`, "#c93c05"); if (e.moved) flash(`↪ ${e.job} moved to ${esc(d.label)} · continues at step ${e.step} · nothing lost`); }
    if (e.type === "device.stopped" && d) { log(`■ STOP on ${esc(d.label)}${e.job ? ` · ${e.job} handed on at step ${e.step}` : ""}`, "#d1173a"); flash(`■ ${esc(d.label)} pressed STOP · heat need met`); }
    if (e.type === "job.moved" && d) { packet(d.g.position, new THREE.Vector3(), C.stop, 900, 4); }
    if (e.type === "job.done") { log(`✓ ${e.job} completed on ${esc(lbl(e.device))} · ${e.hops} phone${e.hops > 1 ? "s" : ""}`, "#157a43"); if (d) packet(d.g.position, new THREE.Vector3(), C.ok, 1100, 6); }
    if (e.type === "device.gone" && d) log(`${esc(d.label)} went silent · its job moves on`, "#a86400");
  }

  // join QR
  k.qr.src = "./api/phones/qr.svg?" + Date.now();
  k.qr.onerror = () => { k.qr.replaceWith(Object.assign(document.createElement("div"), { textContent: "joining closed (no event code set)", style: "font-size:12px;color:#a86400;padding:40px 0" })); };

  // ---------- loop ----------
  const v = new THREE.Vector3();
  function resize() { const w = k.gl.clientWidth, h = k.gl.clientHeight; renderer.setSize(w, h, false); comp.setSize(w, h); cam.aspect = w / h; cam.updateProjectionMatrix(); }
  new ResizeObserver(resize).observe(k.gl); resize();
  let last = performance.now();
  function frame(now) {
    const dt = Math.min(0.05, (now - last) / 1000); last = now;
    coreMesh.rotation.y += dt * 0.4; coreWire.rotation.y -= dt * 0.25; rings.forEach((r, i) => (r.rotation.z += dt * (i ? -0.3 : 0.5)));
    const busy = [...nodes.values()].filter((n) => n.state === "busy").length;
    coreMesh.material.emissiveIntensity = 0.7 + 0.12 * Math.sin(now / 600) + busy * 0.02;
    for (const n of nodes.values()) {
      if (n.kind === "phone") n.g.position.lerp(n.pos, 0.035);                       // fly in
      n.g.lookAt(cam.position.x, n.g.position.y, cam.position.z);
      const target = n.state === "busy" ? 1 : 0; n.heat += (target - n.heat) * 0.04;
      const col = n.state === "stopped" ? C.stop : n.state === "gone" ? 0x3a3430 : n.role === "client" ? C.cold : n.kind === "laptop" ? C.laptop : C.idle;
      n.mat.emissive.setHex(n.heat > 0.05 ? C.heat : col);
      n.mat.emissiveIntensity = n.state === "gone" ? 0.08 : 0.3 + n.heat * (0.7 + 0.15 * Math.sin(now / 400 + n.g.position.x));
      n.glow.material.opacity = n.heat * 0.35; n.glow.scale.setScalar(5 + 1.5 * n.heat);
      if (n.heat > 0.5 && Math.random() < 0.03) spark(n.g.position);
      const pa = n.line.geometry.attributes.position; pa.setXYZ(1, n.g.position.x, n.g.position.y, n.g.position.z); pa.needsUpdate = true;
      n.line.material.opacity = 0.12 + n.heat * 0.35; n.line.material.color.setHex(n.heat > 0.3 ? C.heat : 0x5a4a3c);
      v.copy(n.g.position); v.y += n.kind === "laptop" ? 2.6 : 2.2; v.project(cam);
      const vis = v.z < 1; n.el.style.display = vis ? "block" : "none";
      if (vis) { n.el.style.left = ((v.x + 1) / 2 * k.gl.clientWidth) + "px"; n.el.style.top = ((1 - v.y) / 2 * k.gl.clientHeight) + "px";
        n.el.innerHTML = `${esc(n.label)}${n.state === "busy" ? ' <span style="color:#ff9a5a">● heating</span>' : n.state === "stopped" ? ' <span style="color:#ff6b80">■ stopped</span>' : ""}`; }
    }
    for (let i = packets.length - 1; i >= 0; i--) {
      const p = packets[i], t = Math.min(1, (now - p.t0) / p.ms), e = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
      p.s.position.lerpVectors(p.from, p.to, e); p.s.position.y += Math.sin(Math.PI * e) * p.arc;
      if (Math.random() < 0.12) spark(p.s.position);
      if (t >= 1) { scene.remove(p.s); packets.splice(i, 1); }
    }
    for (let i = sparks.length - 1; i >= 0; i--) { const s = sparks[i]; s.m.position.y += s.v; s.life -= 0.02; s.m.material.opacity = s.life * 0.8; if (s.life <= 0) { scene.remove(s.m); sparks.splice(i, 1); } }
    k.clock.textContent = new Date().toLocaleTimeString("de-CH");
    ctl.update(); comp.render(); requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
  poll(); setInterval(poll, 1000);
}

function boot() { document.querySelectorAll("[data-dh-phone-fleet]").forEach((r) => { if (!r._dh) { r._dh = 1; try { start(r); } catch (e) { r.textContent = "fleet view: " + e.message; } } }); }
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
new MutationObserver(boot).observe(document.documentElement, { childList: true, subtree: true });
