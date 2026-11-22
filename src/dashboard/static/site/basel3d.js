// DigitalHeat · 07 Year · Basel 2025 in 3D (#109). three.js r170 vendored offline; map from OpenStreetMap (ODbL).
//
// The year played through our scheduler: every hour, each simulated house glows by the server heat it received,
// turns cold-blue by the demand its servers did not cover (backup heater), throws red sparks for heat dumped, and goes
// dark when the scheduler held its servers. The REFERENCE house carries the real yearview numbers (#95); the FLEET is
// illustrative: the reference year scaled by each house's footprint with a seeded variation (labelled on the page).
//
//   const v = await DHBasel3D.create(host, {map: "data/basel3d.json"})   // null without WebGL2
//   v.setRun(run); v.setPolicy("ours" | "thermostat"); v.setHour(h); v.focus("city" | "district" | "house"); v.info()
import * as THREE from "./vendor/three/three.module.js";
import { OrbitControls } from "./vendor/three/addons/controls/OrbitControls.js";
import { EffectComposer } from "./vendor/three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "./vendor/three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "./vendor/three/addons/postprocessing/UnrealBloomPass.js";
import { ShaderPass } from "./vendor/three/addons/postprocessing/ShaderPass.js";
import { OutputPass } from "./vendor/three/addons/postprocessing/OutputPass.js";

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const HOURS = 8760, MAXH = 64, PARTS = 14000, SPARKS = 2500, RACK_MAX = 8;
const C = { ink: 0x0e0d0c, cream: 0xf2efe9, orange: 0xc93c05, heat: 0xff8c1f, cold: 0x1d6bb3, dump: 0xd1173a };

function ringPts(arr, start, q) { // delta-encoded int ring (first pair absolute) -> [[x, y], ...] metres, y north
  const pts = []; let x = arr[start], y = arr[start + 1]; pts.push([x * q, y * q]);
  for (let i = start + 2; i + 1 < arr.length; i += 2) { x += arr[i]; y += arr[i + 1]; pts.push([x * q, y * q]); }
  return pts;
}

function sunDir(hour) { // Basel 47.56 N; hour of 2025 (local) -> unit vector to the sun, elevation in radians
  const doy = Math.floor(hour / 24), hh = hour % 24, lat = 47.56 * Math.PI / 180;
  const decl = 23.44 * Math.PI / 180 * Math.sin(2 * Math.PI * (284 + doy) / 365);
  const ha = (hh - 12.5) * 15 * Math.PI / 180;
  const el = Math.asin(Math.sin(lat) * Math.sin(decl) + Math.cos(lat) * Math.cos(decl) * Math.cos(ha));
  const az = Math.atan2(Math.sin(ha), Math.cos(ha) * Math.sin(lat) - Math.tan(decl) * Math.cos(lat));
  return { v: new THREE.Vector3(Math.sin(az) * Math.cos(el), Math.sin(el), Math.cos(az) * Math.cos(el)), el };
}

function buildCity(map, simIdx) {
  // merged walls + roofs; simulated houses go into their own geometry with a per-vertex house index
  const q = map.q, city = { p: [], n: [], c: [], bid: [] }, sim = { p: [], n: [], hid: [], bid: [] }, base = new THREE.Color();
  const centroids = [];
  map.buildings.forEach((b, i) => {
    const h = b[0] / 10, kind = b[1], pts = ringPts(b, 2, q);
    const hid = simIdx.get(i); const tgt = hid === undefined ? city : sim;
    let cx = 0, cy = 0; for (const p of pts) { cx += p[0]; cy += p[1]; } centroids[i] = [cx / pts.length, cy / pts.length, h];
    const shade = kind ? 0.16 : 0.13; base.setRGB(shade * 1.05, shade, shade * 0.95);
    const push = (x, y, z, nx, ny, nz) => {
      tgt.p.push(x, y, z); tgt.n.push(nx, ny, nz); tgt.bid.push(i);
      if (tgt === city) tgt.c.push(base.r * (0.75 + 0.25 * y / Math.max(h, 1)), base.g * (0.75 + 0.25 * y / Math.max(h, 1)), base.b * (0.8 + 0.2 * y / Math.max(h, 1)));
      else tgt.hid.push(hid, y / Math.max(h, 1));
    };
    for (let k = 0; k < pts.length; k++) { // walls (map y north -> three -z)
      const [x0, y0] = pts[k], [x1, y1] = pts[(k + 1) % pts.length];
      const dx = x1 - x0, dy = y1 - y0, L = Math.hypot(dx, dy) || 1, nx = dy / L, nz = dx / L;
      push(x0, 0, -y0, nx, 0, nz); push(x1, 0, -y1, nx, 0, nz); push(x1, h, -y1, nx, 0, nz);
      push(x0, 0, -y0, nx, 0, nz); push(x1, h, -y1, nx, 0, nz); push(x0, h, -y0, nx, 0, nz);
    }
    const contour = pts.map((p) => new THREE.Vector2(p[0], p[1]));
    let tris; try { tris = THREE.ShapeUtils.triangulateShape(contour, []); } catch (e) { tris = []; }
    for (const t of tris) for (const k of t) push(pts[k][0], h, -pts[k][1], 0, 1, 0);
  });
  const mk = (o, extra) => { const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(o.p, 3)); g.setAttribute("normal", new THREE.Float32BufferAttribute(o.n, 3));
    if (extra) extra(g); return g; };
  return {
    city: mk(city, (g) => { g.setAttribute("color", new THREE.Float32BufferAttribute(city.c, 3)); g.setAttribute("aBid", new THREE.Float32BufferAttribute(city.bid, 1)); }),
    sim: mk(sim, (g) => { g.setAttribute("aHouse", new THREE.Float32BufferAttribute(sim.hid, 2)); g.setAttribute("aBid", new THREE.Float32BufferAttribute(sim.bid, 1)); }),
    centroids,
  };
}

function polyMesh(rings, q, y, material) {
  const pos = [];
  for (const r of rings) {
    const pts = ringPts(r, 0, q); if (pts.length < 3) continue;
    let tris; try { tris = THREE.ShapeUtils.triangulateShape(pts.map((p) => new THREE.Vector2(p[0], p[1])), []); } catch (e) { continue; }
    for (const t of tris) for (const k of t) pos.push(pts[k][0], y, -pts[k][1]);
  }
  const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  return new THREE.Mesh(g, material);
}

const NOISE = `
  float hash(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
  float noise(vec2 p){ vec2 i = floor(p), f = fract(p); vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1, 0)), u.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), u.x), u.y); }
  float fbm(vec2 p){ float s = 0.0, a = 0.5; for (int i = 0; i < 5; i++) { s += a * noise(p); p *= 2.03; a *= 0.5; } return s; }`;

export async function create(host, opts = {}) {
  const cv = document.createElement("canvas");
  cv.style.cssText = "width:100%;height:100%;display:block;cursor:grab;touch-action:none";
  if (!cv.getContext("webgl2")) return null;
  host.appendChild(cv);
  const map = await (await fetch(opts.map || "./data/basel3d.json")).json();
  const sims = [map.reference, ...map.fleet]; // house 0 = reference (real), 1.. = illustrative fleet
  const simIdx = new Map(sims.map((b, i) => [b, i]));
  const renderer = new THREE.WebGLRenderer({ canvas: cv, antialias: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(2, devicePixelRatio || 1));
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 0.95;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0b0b0d); scene.fog = new THREE.FogExp2(0x0d0e12, 0.00028);
  const camera = new THREE.PerspectiveCamera(38, 1, 5, 20000);
  camera.position.set(-1900, 1500, 1700);
  const controls = new OrbitControls(camera, cv);
  controls.enableDamping = true; controls.dampingFactor = 0.07; controls.maxPolarAngle = 1.42; controls.minDistance = 60; controls.maxDistance = 5200;
  controls.screenSpacePanning = false;  // right-drag / two-finger drag pans along the ground (#115)
  controls.target.set(0, 0, 0); controls.autoRotate = true; controls.autoRotateSpeed = 0.25;
  cv.addEventListener("pointerdown", () => { controls.autoRotate = false; });

  // lights: sun (season + hour), sky fill, warm city bounce
  const hemi = new THREE.HemisphereLight(0x9fb4d6, 0x2a1d12, 0.35); scene.add(hemi);
  const sun = new THREE.DirectionalLight(0xffe2b8, 1.4); scene.add(sun);
  const hubLight = new THREE.PointLight(C.heat, 0, 1400, 1.6); scene.add(hubLight);

  // ground with snow / green tint and the living heat field
  const H = new Float32Array(MAXH * 4), HP = new Float32Array(MAXH * 4);
  const houseTex = new THREE.DataTexture(H, MAXH, 1, THREE.RGBAFormat, THREE.FloatType); houseTex.needsUpdate = true;
  const groundU = { uTime: { value: 0 }, uSnow: { value: 0 }, uGreen: { value: 0 }, uHouses: { value: HP }, uN: { value: sims.length }, uState: { value: houseTex } };
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(9000, 9000, 1, 1), new THREE.ShaderMaterial({
    uniforms: groundU, transparent: false,
    vertexShader: `varying vec2 vXZ; void main(){ vec4 w = modelMatrix * vec4(position, 1.0); vXZ = w.xz; gl_Position = projectionMatrix * viewMatrix * w; }`,
    fragmentShader: `uniform float uTime, uSnow, uGreen, uN; uniform vec4 uHouses[${MAXH}]; uniform sampler2D uState; varying vec2 vXZ; ${NOISE}
      void main(){
        vec3 c = mix(vec3(0.035, 0.033, 0.031), vec3(0.03, 0.045, 0.03), uGreen * 0.6);
        c = mix(c, vec3(0.20, 0.22, 0.25), uSnow * 0.6 * (0.7 + 0.3 * fbm(vXZ * 0.01)));
        float g = smoothstep(0.96, 1.0, max(abs(fract(vXZ.x / 250.0) - 0.5), abs(fract(vXZ.y / 250.0) - 0.5)) * 2.0);
        c += vec3(0.05, 0.035, 0.02) * g * 0.35;
        vec3 heat = vec3(0.0); vec3 cold = vec3(0.0);
        for (int i = 0; i < ${MAXH}; i++) { if (float(i) >= uN) break;
          vec4 st = texture2D(uState, vec2((float(i) + 0.5) / ${MAXH}.0, 0.5));
          vec2 d = vXZ - uHouses[i].xy; float r2 = dot(d, d);
          float wob = fbm(vXZ * 0.006 + vec2(uTime * 0.05, -uTime * 0.03));
          heat += vec3(1.0, 0.40, 0.06) * st.r * exp(-r2 / (2.0 * pow(55.0 + 35.0 * wob, 2.0))) * (0.5 + 0.5 * wob);
          cold += vec3(0.10, 0.30, 0.75) * st.g * exp(-r2 / (2.0 * pow(45.0, 2.0)));
        }
        gl_FragColor = vec4(c + min(heat, vec3(1.2)) * 0.55 + min(cold, vec3(1.0)) * 0.30, 1.0);
      }`,
  }));
  ground.rotation.x = -Math.PI / 2; scene.add(ground);

  // city + simulated houses
  const geo = buildCity(map, simIdx);
  const cityMat = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.92, metalness: 0.0 });
  const snowU = { value: 0 };
  const selU = { value: -1 };
  cityMat.onBeforeCompile = (s) => { s.uniforms.uSnow = snowU; s.uniforms.uSel = selU;
    s.vertexShader = s.vertexShader.replace("#include <common>", "#include <common>\nattribute float aBid; uniform float uSel; varying float vSelHit;")
      .replace("#include <begin_vertex>", "#include <begin_vertex>\n vSelHit = abs(aBid - uSel) < 0.5 ? 1.0 : 0.0;");
    s.fragmentShader = s.fragmentShader.replace("#include <common>", "#include <common>\nuniform float uSnow; varying float vSelHit;")
      .replace("#include <emissivemap_fragment>", "#include <emissivemap_fragment>\n totalEmissiveRadiance += vec3(0.9, 0.55, 0.25) * vSelHit * 0.7;")
      .replace("#include <color_fragment>", "#include <color_fragment>\n if (vNormal.y > 0.5) diffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.78, 0.8, 0.84), uSnow * 0.8);"); };
  cityMat.emissive = new THREE.Color(0x2a1c10); cityMat.emissiveIntensity = 0.55;
  scene.add(new THREE.Mesh(geo.city, cityMat));
  const simU = { uState: { value: houseTex }, uTime: { value: 0 }, uSun: { value: new THREE.Vector3(0, 1, 0) }, uSunI: { value: 1 }, uSel: selU };
  const simMesh = new THREE.Mesh(geo.sim, new THREE.ShaderMaterial({
    uniforms: simU,
    vertexShader: `attribute vec2 aHouse; attribute float aBid; uniform float uSel; varying vec2 vH; varying vec3 vN; varying float vSelHit;
      void main(){ vH = aHouse; vN = normal; vSelHit = abs(aBid - uSel) < 0.5 ? 1.0 : 0.0; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: `uniform sampler2D uState; uniform float uTime, uSunI; uniform vec3 uSun; varying vec2 vH; varying vec3 vN; varying float vSelHit;
      void main(){
        vec4 st = texture2D(uState, vec2((vH.x + 0.5) / ${MAXH}.0, 0.5));
        float lit = 0.25 + 0.75 * max(0.0, dot(normalize(vN), normalize(uSun))) * uSunI;
        vec3 base = vec3(0.30, 0.28, 0.26) * lit;
        float win = step(0.5, fract(vH.y * 9.0)) * 0.6 + 0.4;
        vec3 glow = vec3(1.0, 0.36, 0.04) * min(st.r, 1.0) * (0.55 + 0.35 * win) + vec3(0.12, 0.38, 1.0) * min(st.g, 1.0) * 0.6 + vec3(1.0, 0.06, 0.18) * min(st.b, 1.0) * 0.9;
        glow *= (1.0 - 0.85 * st.a);
        float ref = vH.x < 0.5 ? 0.35 + 0.25 * sin(uTime * 2.0) : 0.0;  // the reference house breathes
        gl_FragColor = vec4(base + glow + vec3(1.0, 0.8, 0.5) * ref * 0.25 + vec3(0.55, 0.42, 0.28) * vSelHit * (0.25 + 0.15 * sin(uTime * 4.0)), 1.0);
      }`,
  }));
  scene.add(simMesh);

  // water (the Rhine) with a moving shimmer, and the main streets as faint warm lines
  const waterU = { uTime: { value: 0 }, uSunI: { value: 1 } };
  scene.add(polyMesh(map.water, map.q, 0.6, new THREE.ShaderMaterial({ uniforms: waterU, transparent: true,
    vertexShader: `varying vec2 vXZ; void main(){ vXZ = position.xz; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: `uniform float uTime, uSunI; varying vec2 vXZ; ${NOISE}
      void main(){ float n = fbm(vXZ * 0.02 + vec2(uTime * 0.12, uTime * 0.05)); float s = pow(n, 6.0) * 2.5;
        vec3 c = mix(vec3(0.02, 0.05, 0.09), vec3(0.10, 0.20, 0.30), uSunI * 0.6) + vec3(1.0, 0.75, 0.5) * s * (0.3 + 0.7 * uSunI);
        gl_FragColor = vec4(c, 0.96); }` })));
  const rp = [];
  for (const r of map.roads) { const pts = ringPts(r, 0, map.q); for (let k = 0; k + 1 < pts.length; k++) rp.push(pts[k][0], 1.2, -pts[k][1], pts[k + 1][0], 1.2, -pts[k + 1][1]); }
  const rg = new THREE.BufferGeometry(); rg.setAttribute("position", new THREE.Float32BufferAttribute(rp, 3));
  scene.add(new THREE.LineSegments(rg, new THREE.LineBasicMaterial({ color: 0x6b4a2a, transparent: true, opacity: 0.35 })));

  // houses: centroid, height, scale vs the reference (footprint) with seeded variation
  const refA = map.areas_m2[map.reference];
  let seed = 2025; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const houses = sims.map((b, i) => { const c = geo.centroids[b]; HP[i * 4] = c[0]; HP[i * 4 + 1] = -c[1];
    return { b, x: c[0], z: -c[1], h: c[2], rad: Math.sqrt(map.areas_m2[b] / Math.PI), scale: i === 0 ? 1 : Math.max(0.5, Math.min(3, map.areas_m2[b] / refA)) * (0.85 + 0.3 * rnd()) }; });
  const hub = new THREE.Vector3(map.hub[0] * map.q, 0, -map.hub[1] * map.q);

  // coordinator hub: a light column + core
  const hubCore = new THREE.Mesh(new THREE.CylinderGeometry(9, 14, 160, 24, 1, true), new THREE.MeshBasicMaterial({ color: 0xffb36b, transparent: true, opacity: 0.55, blending: THREE.AdditiveBlending, depthWrite: false }));
  hubCore.position.copy(hub).setY(80); scene.add(hubCore); hubLight.position.copy(hub).setY(140);
  // trails hub -> houses (animated dashes), one curve per house
  const TRAIL = 48, tp = new Float32Array(sims.length * TRAIL * 3), tt = new Float32Array(sims.length * TRAIL), th = new Float32Array(sims.length * TRAIL);
  houses.forEach((h, i) => { const a = new THREE.Vector3(hub.x, 170, hub.z), c = new THREE.Vector3(h.x, h.h + 6, h.z);
    const m = a.clone().lerp(c, 0.5).setY(260 + 0.15 * a.distanceTo(c)); const cur = new THREE.QuadraticBezierCurve3(a, m, c);
    for (let k = 0; k < TRAIL; k++) { const p = cur.getPoint(k / (TRAIL - 1)); const j = (i * TRAIL + k);
      tp[j * 3] = p.x; tp[j * 3 + 1] = p.y; tp[j * 3 + 2] = p.z; tt[j] = k / (TRAIL - 1); th[j] = i; } });
  const tg = new THREE.BufferGeometry(); tg.setAttribute("position", new THREE.BufferAttribute(tp, 3));
  tg.setAttribute("aT", new THREE.BufferAttribute(tt, 1)); tg.setAttribute("aH", new THREE.BufferAttribute(th, 1));
  const trailU = { uTime: { value: 0 }, uState: { value: houseTex }, uPx: { value: renderer.getPixelRatio() } };
  scene.add(new THREE.Points(tg, new THREE.ShaderMaterial({ uniforms: trailU, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    vertexShader: `attribute float aT, aH; uniform float uTime, uPx; uniform sampler2D uState; varying float vA;
      void main(){ vec4 st = texture2D(uState, vec2((aH + 0.5) / ${MAXH}.0, 0.5)); float on = st.r + st.b > 0.002 ? 1.0 : 0.0;
        float dash = pow(0.5 + 0.5 * sin((aT * 10.0 - uTime * 2.2) * 6.2831), 6.0);
        vA = on * (0.15 + 0.85 * dash) * (1.0 - st.a); vec4 mv = modelViewMatrix * vec4(position, 1.0);
        gl_PointSize = uPx * (2.0 + 5.0 * dash) * 300.0 / -mv.z; gl_Position = projectionMatrix * mv; }`,
    fragmentShader: `varying float vA; void main(){ vec2 c = gl_PointCoord * 2.0 - 1.0; float r = dot(c, c); if (r > 1.0) discard;
      gl_FragColor = vec4(vec3(1.0, 0.62, 0.25) * vA, vA * exp(-r * 3.0)); }` })));

  // heat particles: curl-ish rising flow from each house; dump sparks fly up and out
  function particles(count, sparks) {
    const g = new THREE.BufferGeometry(), seedA = new Float32Array(count * 4);
    for (let i = 0; i < count; i++) { seedA[i * 4] = Math.floor(Math.random() * sims.length); seedA[i * 4 + 1] = Math.random(); seedA[i * 4 + 2] = Math.random(); seedA[i * 4 + 3] = Math.random(); }
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(count * 3), 3)); g.setAttribute("aSeed", new THREE.BufferAttribute(seedA, 4));
    const hp = new Float32Array(MAXH * 4); houses.forEach((h, i) => { hp[i * 4] = h.x; hp[i * 4 + 1] = h.h; hp[i * 4 + 2] = h.z; });
    const u = { uTime: { value: 0 }, uState: { value: houseTex }, uH: { value: hp }, uPx: { value: renderer.getPixelRatio() } };
    const m = new THREE.ShaderMaterial({ uniforms: u, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      vertexShader: `attribute vec4 aSeed; uniform float uTime, uPx; uniform vec4 uH[${MAXH}]; uniform sampler2D uState; varying float vA; varying float vK;
        void main(){ int i = int(aSeed.x); vec4 h = uH[i]; vec4 st = texture2D(uState, vec2((aSeed.x + 0.5) / ${MAXH}.0, 0.5));
          float amt = ${sparks ? "st.b" : "st.r"}; float life = fract(aSeed.y + uTime * (${sparks ? "0.55" : "0.16"} + 0.1 * aSeed.z));
          float ang = aSeed.z * 6.2831 + life * ${sparks ? "1.5" : "4.0"} + sin(uTime * 0.7 + aSeed.w * 9.0);
          float rad = ${sparks ? "8.0 + life * 140.0" : "10.0 + 40.0 * life + 18.0 * sin(life * 7.0 + aSeed.w * 6.0)"};
          vec3 p = vec3(h.x + cos(ang) * rad, h.y + life * ${sparks ? "260.0" : "180.0"}, h.z + sin(ang) * rad);
          vA = step(aSeed.w, clamp(amt * ${sparks ? "3.0" : "2.2"}, 0.0, 1.0)) * smoothstep(0.0, 0.08, life) * (1.0 - life) * (1.0 - st.a); vK = life;
          vec4 mv = modelViewMatrix * vec4(p, 1.0); gl_PointSize = uPx * ${sparks ? "6.0" : "4.5"} * 420.0 / -mv.z; gl_Position = projectionMatrix * mv; }`,
      fragmentShader: `varying float vA; varying float vK; void main(){ vec2 c = gl_PointCoord * 2.0 - 1.0; float r = dot(c, c); if (r > 1.0) discard;
        vec3 col = ${sparks ? "mix(vec3(1.0, 0.25, 0.35), vec3(1.0, 0.75, 0.4), vK)" : "mix(vec3(1.0, 0.55, 0.15), vec3(1.0, 0.85, 0.6), vK)"};
        gl_FragColor = vec4(col * vA, vA * exp(-r * 2.5)); }` });
    const pts = new THREE.Points(g, m); pts.frustumCulled = false; scene.add(pts); return u;
  }
  const flowU = particles(PARTS, false), sparkU = particles(SPARKS, true);

  // servers in the basements: N racks per house, LED colour = state
  const racks = new THREE.InstancedMesh(new THREE.BoxGeometry(5, 9, 5), new THREE.MeshBasicMaterial({ color: 0xffffff, toneMapped: false }), sims.length * RACK_MAX);
  racks.instanceMatrix.setUsage(THREE.DynamicDrawUsage); scene.add(racks);
  const tmpM = new THREE.Matrix4(), tmpC = new THREE.Color(), tmpHex = new THREE.Matrix4();

  // districts (#112): hex heat layer (delivered vs unmet per Wohnviertel and hour), outlines, labels
  const D = map.districts || [], DMAX = 32, DS = new Float32Array(DMAX * 4);
  const distTex = new THREE.DataTexture(DS, DMAX, 1, THREE.RGBAFormat, THREE.FloatType); distTex.needsUpdate = true;
  const hexU = { uDist: { value: distTex }, uTime: { value: 0 } };
  const hexes = map.hexes || [];
  const hexMesh = new THREE.InstancedMesh(new THREE.CylinderGeometry((map.hex_m || 120) * 0.93, (map.hex_m || 120) * 0.93, 1.5, 6),
    new THREE.ShaderMaterial({ uniforms: hexU, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      vertexShader: `attribute float aDist; uniform sampler2D uDist; uniform float uTime; varying vec4 vS; varying float vEdge;
        void main(){ vS = texture2D(uDist, vec2((aDist + 0.5) / ${DMAX}.0, 0.5)); vEdge = length(position.xz) / ${((map.hex_m || 120) * 0.93).toFixed(1)};
          vec4 w = instanceMatrix * vec4(position, 1.0); w.y += 0.5 + 0.5 * sin(uTime * 0.8 + w.x * 0.01 + w.z * 0.013);
          gl_Position = projectionMatrix * modelViewMatrix * w; }`,
      fragmentShader: `varying vec4 vS; varying float vEdge;
        void main(){ float tot = vS.r + vS.g; if (tot < 0.002) discard;
          vec3 c = mix(vec3(0.15, 0.40, 0.95), vec3(1.0, 0.42, 0.06), vS.r / max(tot, 1e-4));
          float a = clamp(tot, 0.0, 1.0) * (0.16 + 0.14 * smoothstep(0.8, 1.0, vEdge)) * (1.0 - 0.8 * vS.a);
          gl_FragColor = vec4(c * a, a); }` }), Math.max(1, hexes.length));
  const hexDist = new Float32Array(Math.max(1, hexes.length));
  hexes.forEach((h, i) => { tmpHex.makeTranslation(h[0] * map.q, 1, -h[1] * map.q); hexMesh.setMatrixAt(i, tmpHex); hexDist[i] = h[2]; });
  hexMesh.geometry.setAttribute("aDist", new THREE.InstancedBufferAttribute(hexDist, 1));
  hexMesh.count = hexes.length; hexMesh.frustumCulled = false; scene.add(hexMesh);
  const dl = [];
  for (const d of D) { const pts = ringPts(d.ring, 0, map.q); for (let k = 0; k < pts.length; k++) { const a = pts[k], b = pts[(k + 1) % pts.length]; dl.push(a[0], 2.5, -a[1], b[0], 2.5, -b[1]); } }
  const dg = new THREE.BufferGeometry(); dg.setAttribute("position", new THREE.Float32BufferAttribute(dl, 3));
  scene.add(new THREE.LineSegments(dg, new THREE.LineBasicMaterial({ color: 0xf2efe9, transparent: true, opacity: 0.16 })));
  const labels = D.map((d) => { const pts = ringPts(d.ring, 0, map.q); let x = 0, y = 0; for (const p of pts) { x += p[0]; y += p[1]; }
    const el = document.createElement("div"); el.textContent = d.name;
    el.style.cssText = "position:absolute;pointer-events:none;transform:translate(-50%,-50%);font:10px 'Geist Mono',monospace;letter-spacing:.14em;text-transform:uppercase;color:rgba(242,239,233,0.42);white-space:nowrap;z-index:3";
    host.appendChild(el); return { el, p: new THREE.Vector3(x / pts.length, 30, -y / pts.length) }; });

  // live nodes (#112): node-mac / node-omen2 as named houses: beacon + always-on card; real state when the page feeds
  // /api/nodes, otherwise a clearly marked REPLAY of the reference house's simulated hour
  const live = Object.entries(map.live || {}).map(([id, b]) => { const c = geo.centroids[b];
    const beam = new THREE.Mesh(new THREE.CylinderGeometry(2.5, 6, 220, 16, 1, true), new THREE.MeshBasicMaterial({ color: 0x7fd18b, transparent: true, opacity: 0.5, blending: THREE.AdditiveBlending, depthWrite: false }));
    beam.position.set(c[0], c[2] + 110, -c[1]); scene.add(beam);
    const el = document.createElement("div");
    el.style.cssText = "position:absolute;pointer-events:none;transform:translate(-50%,-120%);padding:7px 10px;border-radius:10px;background:rgba(14,13,12,0.72);border:1px solid rgba(127,209,139,0.55);font:11px/1.45 'Geist Mono',monospace;color:#f2efe9;white-space:nowrap;z-index:4";
    host.appendChild(el);
    return { id, b, x: c[0], z: -c[1], h: c[2], beam, el, p: new THREE.Vector3(c[0], c[2] + 230, -c[1]), st: null }; });
  const liveTrail = new THREE.Group(); scene.add(liveTrail);
  let liveFeed = null;
  function liveState(L) {  // -> {mode, state, watts, unit, progress, lease}
    const n = liveFeed && liveFeed.ok ? (liveFeed.nodes || []).find((x) => x.node_id === L.id) : null;
    if (n) { const lease = (liveFeed.leases || []).find((x) => x.node_id === L.id);
      const state = n.tampered ? "tampered" : n.suspect ? "suspect" : n.running_unit ? "running" : "idle";
      return { mode: "LIVE", state, watts: n.watts, unit: n.running_unit, progress: n.progress, lease: !!lease }; }
    const i = S.info; if (!i) return { mode: "REPLAY", state: "–" };
    return { mode: "REPLAY", state: i.paused ? "held" : i.on > 0 ? "running" : "idle", watts: null, unit: null, progress: null, lease: i.on > 0 };
  }
  const STC = { running: 0xff8c1f, idle: 0x7fd18b, held: 0x8fa3bf, suspect: 0xf0a500, tampered: 0xd1173a, "–": 0x55524c };
  function updateLive() {
    while (liveTrail.children.length) { const o = liveTrail.children.pop(); o.geometry.dispose(); o.material.dispose(); }
    for (const L of live) {
      const st = liveState(L); L.st = st; const col = STC[st.state] ?? 0x7fd18b;
      L.beam.material.color.setHex(col); L.beam.material.opacity = 0.35 + 0.25 * Math.sin(performance.now() / 260);
      L.el.style.borderColor = "#" + col.toString(16).padStart(6, "0");
      L.el.innerHTML = `<span style="color:#${col.toString(16).padStart(6, "0")};font-weight:700">${L.id}</span> · ${st.mode === "LIVE" ? "<b style='color:#7fd18b'>LIVE</b>" : "<span style='color:#a8a298'>REPLAY</span>"} · ${st.state}`
        + (st.unit ? `<br>${esc(st.unit)}${st.progress != null ? " · " + Math.round(st.progress * 100) + " %" : ""}` : "")
        + (st.watts != null ? ` · ${Math.round(st.watts)} W` : "");
      if (st.lease) { const a = new THREE.Vector3(hub.x, 170, hub.z), c = new THREE.Vector3(L.x, L.h + 8, L.z);
        const m = a.clone().lerp(c, 0.5).setY(300 + 0.15 * a.distanceTo(c));
        const g = new THREE.BufferGeometry().setFromPoints(new THREE.QuadraticBezierCurve3(a, m, c).getPoints(48));
        liveTrail.add(new THREE.Line(g, new THREE.LineBasicMaterial({ color: col, transparent: true, opacity: 0.85, blending: THREE.AdditiveBlending }))); }
    }
  }
  const proj = new THREE.Vector3();
  function place(el, p) { proj.copy(p).project(camera); const vis = proj.z < 1 && Math.abs(proj.x) < 1.1 && Math.abs(proj.y) < 1.1;
    el.style.display = vis ? "block" : "none"; if (vis) { el.style.left = ((proj.x + 1) / 2 * host.clientWidth) + "px"; el.style.top = ((1 - proj.y) / 2 * host.clientHeight) + "px"; } }

  // post: bloom + grain/vignette in the site palette
  const composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));
  const bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.85, 0.55, 0.42); composer.addPass(bloom);
  const grain = new ShaderPass({ uniforms: { tDiffuse: { value: null }, uTime: { value: 0 } },
    vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: `uniform sampler2D tDiffuse; uniform float uTime; varying vec2 vUv;
      float h(vec2 p){ return fract(sin(dot(p, vec2(12.9898, 78.233)) + uTime) * 43758.5453); }
      void main(){ vec4 c = texture2D(tDiffuse, vUv); float v = smoothstep(1.15, 0.35, length(vUv - 0.5) * 1.6);
        c.rgb *= mix(0.55, 1.0, v); c.rgb += (h(vUv * 913.0) - 0.5) * 0.035; c.rgb = mix(c.rgb, c.rgb * vec3(1.03, 1.0, 0.95), 0.6); gl_FragColor = c; }` });
  composer.addPass(grain); composer.addPass(new OutputPass());

  // state
  // ---- #118 the algorithm on the map, driven by fleetview (#119): cost rings, job packets hub -> house, the waiting
  // orbit around the hub, held houses dimmed, floating decision tags. Fleet = ASSUMED houses; algorithm = real decide().
  const FL = { on: false, K: 0, H: 0, raw: null, fields: {}, fleet: null, jobs: [], ringMesh: null, packets: null, tags: [], sel: null };
  const ringGeo = new THREE.RingGeometry(9, 13, 28); ringGeo.rotateX(-Math.PI / 2);
  const ringMat = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.9, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false });
  const PK = 400, pkGeo = new THREE.BufferGeometry(), pkPos = new Float32Array(PK * 3), pkCol = new Float32Array(PK * 3);
  pkGeo.setAttribute("position", new THREE.BufferAttribute(pkPos, 3)); pkGeo.setAttribute("color", new THREE.BufferAttribute(pkCol, 3));
  const pkMat = new THREE.PointsMaterial({ size: 16, vertexColors: true, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true, toneMapped: false });
  const packets = new THREE.Points(pkGeo, pkMat); packets.frustumCulled = false; scene.add(packets);
  const orbitN = 120, orGeo = new THREE.BufferGeometry(), orPos = new Float32Array(orbitN * 3);
  orGeo.setAttribute("position", new THREE.BufferAttribute(orPos, 3));
  const orbit = new THREE.Points(orGeo, new THREE.PointsMaterial({ size: 10, color: 0xffd27a, transparent: true, opacity: 0.85, depthWrite: false, blending: THREE.AdditiveBlending, toneMapped: false }));
  orbit.frustumCulled = false; scene.add(orbit);
  const queueTag = document.createElement("div");
  queueTag.style.cssText = "position:absolute;pointer-events:none;transform:translate(-50%,-140%);padding:5px 9px;border-radius:9px;background:rgba(14,13,12,0.7);border:1px solid rgba(255,210,122,0.5);font:11px 'Geist Mono',monospace;color:#ffd27a;white-space:nowrap;z-index:4;display:none";
  host.appendChild(queueTag);
  const fv = (f, i, h) => FL.raw[(FL.fields[f].k * FL.K + i) * FL.H + h] * FL.fields[f].scale;
  function setFleet(d) {
    FL.K = d.index.houses.length; FL.H = d.index.hours; FL.raw = d.raw; FL.fleet = d.fleet; FL.jobs = d.jobs.tracked || [];
    FL.fields = Object.fromEntries(d.index.series.fields.map((f, k) => [f.name, { k, scale: f.scale }]));
    FL.houses = d.index.houses.map((h) => { const b = h.building, c = d.index.fixture ? null : geo.centroids[b];
      return { ...h, X: c ? c[0] : h.x, Z: c ? -c[1] : -h.y, Y: c ? c[2] : 12 }; });
    if (FL.ringMesh) scene.remove(FL.ringMesh);
    FL.ringMesh = new THREE.InstancedMesh(ringGeo, ringMat, FL.K); FL.ringMesh.frustumCulled = false; scene.add(FL.ringMesh);
    FL.on = true; FL.fixture = !!d.index.fixture;
    FL.rawBase = d.rawBase || null; FL.key = d.index.provenance && d.index.provenance.key; FL.commit = d.index.provenance && d.index.provenance.commit;
    FL.trackEvery = d.index.jobs && d.index.jobs.tracked_every; indexJobs();
  }
  const mcCol = new THREE.Color(), cheap = new THREE.Color(0xff8c1f), dear = new THREE.Color(0xff2d55), held = new THREE.Color(0x3a4250);
  function updateFleet(now) {
    if (!FL.on) return;
    const hf = Math.min(FL.H - 1 + 0.999, S.hour), h = Math.min(FL.H - 1, Math.floor(hf)), fr = hf - h;
    for (let i = 0; i < FL.K; i++) { const H0 = FL.houses[i], st = fv("state", i, h), mc = fv("mc_chf_per_server_h", i, h), on = fv("servers_on", i, h);
      const t = Math.max(0, Math.min(1, (mc - 0.20) / 0.14));  // 0.20 = heat wanted (cheap) .. 0.34 = would dump (dear)
      if (st === 3) mcCol.copy(held); else mcCol.copy(cheap).lerp(dear, st === 2 ? 1 : t);
      if (FL.ringSelClass && FL.ringSelClass !== "public") mcCol.copy((H0.classes || []).includes(FL.ringSelClass) ? new THREE.Color(0xf2efe9) : held);
      const sc = 0.6 + 0.25 * on;
      tmpM.makeScale(sc, 1, sc).setPosition(H0.X, 2 + (st === 3 ? 0 : 0.5 * Math.sin(now / 300 + i)), H0.Z);
      FL.ringMesh.setMatrixAt(i, tmpM); FL.ringMesh.setColorAt(i, mcCol); }
    FL.ringMesh.instanceMatrix.needsUpdate = true; if (FL.ringMesh.instanceColor) FL.ringMesh.instanceColor.needsUpdate = true;
    // packets: tracked units running this hour fly hub -> house during the hour; the selected job is white + larger
    let n = 0; const top = new THREE.Vector3();
    for (const j of FL.jobs) { for (const u of j.units) for (const [rh, house] of u.runs) {
      if (rh !== h || n >= PK) continue; const H0 = FL.houses[house]; if (!H0) continue;
      const e = Math.min(1, fr * 1.6), a = new THREE.Vector3(hub.x, 170, hub.z), c = new THREE.Vector3(H0.X, H0.Y + 10, H0.Z);
      top.copy(a).lerp(c, e).setY(a.y + (c.y - a.y) * e + Math.sin(e * Math.PI) * (120 + 0.12 * a.distanceTo(c)));
      pkPos.set([top.x, top.y, top.z], n * 3);
      const isSel = FL.sel && u.unit === FL.sel; pkCol.set(isSel ? [1, 1, 1] : j.class === "certified" ? [0.5, 0.9, 1] : [1, 0.6, 0.2], n * 3); n++; } }
    pkGeo.setDrawRange(0, n); pkGeo.attributes.position.needsUpdate = true; pkGeo.attributes.color.needsUpdate = true;
    // waiting orbit: deferred work circles the hub; ring density ~ queue size
    const q = FL.fleet.queue[h] || 0, m = Math.min(orbitN, Math.ceil(Math.sqrt(q) * 2));
    for (let i = 0; i < m; i++) { const ang = i / m * Math.PI * 2 + now / 2600, r = 70 + 18 * Math.sin(i * 1.7);
      orPos.set([hub.x + Math.cos(ang) * r, 150 + 20 * Math.sin(ang * 3 + i), hub.z + Math.sin(ang) * r], i * 3); }
    orGeo.setDrawRange(0, m); orGeo.attributes.position.needsUpdate = true;
    queueTag.style.display = "block";
    queueTag.textContent = `waiting ${Math.round(q).toLocaleString("en-CH")} units · deferred inside their slack · ${Math.round(FL.fleet.missed[h] || 0)} missed this hour`;
    place(queueTag, new THREE.Vector3(hub.x, 240, hub.z));
    updateTrace(now, h, fr);
    // floating decision tags: the first few tracked units landing this hour
    for (const t of FL.tags) t.remove(); FL.tags = [];
    let shown = 0;
    for (const j of FL.jobs) { if (shown >= 4) break; for (const u of j.units) for (const [rh, house] of u.runs) {
      if (rh !== h || shown >= 4) continue; const H0 = FL.houses[house]; const st = fv("state", house, h);
      const el = document.createElement("div"); el.textContent = `${u.unit} → house ${house} · ${st === 2 ? "deadline due: heat dumped" : "heat wanted"}`;
      el.style.cssText = "position:absolute;pointer-events:none;transform:translate(-50%,-160%);padding:4px 8px;border-radius:8px;background:rgba(14,13,12,0.7);font:10.5px 'Geist Mono',monospace;color:#f2efe9;white-space:nowrap;z-index:4;opacity:" + (1 - fr).toFixed(2);
      host.appendChild(el); FL.tags.push(el); place(el, new THREE.Vector3(H0.X, H0.Y + 30, H0.Z)); shown++; } }
  }
  // ---- #125 traceability on the map (fleetview): job arcs A -> B with travelling lights, the selected job's path
  // through the year + a trace card, eligibility outlines/locks, ghost thermostat, story chips. Calm: few colours.
  const PAL = [0xffb36b, 0x8fd3ff, 0xf2efe9, 0xff8c1f, 0xb8e986, 0xd9a6ff];
  const TR = { byHour: null, arcs: new THREE.Group(), lights: null, ribbon: null, locks: [], ghost: false, ghostMesh: null, ash: null, lastH: -1 };
  scene.add(TR.arcs);
  const LN = 30 * 10, lGeo = new THREE.BufferGeometry(), lPos = new Float32Array(LN * 3), lCol = new Float32Array(LN * 3);
  lGeo.setAttribute("position", new THREE.BufferAttribute(lPos, 3)); lGeo.setAttribute("color", new THREE.BufferAttribute(lCol, 3));
  TR.lights = new THREE.Points(lGeo, new THREE.PointsMaterial({ size: 14, vertexColors: true, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, toneMapped: false }));
  TR.lights.frustumCulled = false; scene.add(TR.lights);
  const AN = 300, aGeo = new THREE.BufferGeometry(), aPos = new Float32Array(AN * 3);
  aGeo.setAttribute("position", new THREE.BufferAttribute(aPos, 3));
  TR.ash = new THREE.Points(aGeo, new THREE.PointsMaterial({ size: 7, color: 0x9a9590, transparent: true, opacity: 0.55, depthWrite: false }));
  TR.ash.frustumCulled = false; TR.ash.visible = false; scene.add(TR.ash);
  const fvb = (f, i, h) => FL.rawBase ? FL.rawBase[(FL.fields[f].k * FL.K + i) * FL.H + h] * FL.fields[f].scale : 0;
  const hp = (i) => { const H0 = FL.houses[i]; return new THREE.Vector3(H0.X, H0.Y + 14, H0.Z); };
  const arcCurve = (a, b) => { const m = a.clone().lerp(b, 0.5); m.y += 60 + 0.25 * a.distanceTo(b); return new THREE.QuadraticBezierCurve3(a, m, b); };
  function indexJobs() {
    TR.byHour = new Map(); TR.unit = new Map(); TR.moves = new Map();
    FL.jobs.forEach((j, ji) => { for (const u of j.units) { TR.unit.set(u.unit, { j, u, ji }); let prev = null;
      for (const [h, house] of u.runs) { if (!TR.byHour.has(h)) TR.byHour.set(h, []); TR.byHour.get(h).push({ j, u, ji, house, prev });
        if (prev !== null && prev !== house) TR.moves.set(h, (TR.moves.get(h) || 0) + 1); prev = house; } } });
    TR.fan = new Map();  // hour -> the most houses one job ran on in that hour (its units placed by decide())
    for (const [h, list] of TR.byHour) { const by = new Map();
      for (const e of list) { const k = e.j.job; if (!by.has(k)) by.set(k, new Set()); by.get(k).add(e.house); }
      let best = 0; for (const v of by.values()) best = Math.max(best, v.size); TR.fan.set(h, best); }
  }
  function why(house, h) { const st = fv("state", house, h);
    return st === 2 ? "deadline due: ran although no heat was wanted (heat dumped)" : st === 1 ? "heat wanted: cheapest site in the merit order" : st === 3 ? "site held" : "ran"; }
  const when = (h) => new Date(Date.UTC(2024, 11, 31, 23) + h * 3600e3).toLocaleString("en-CH", { timeZone: "Europe/Zurich", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  const src = (file, h) => `fleetview ${(FL.key || "").slice(0, 10)} · ${file}${h != null ? " · hour " + h : ""}`;
  function eligible(cls, house) { return cls === "public" || (FL.houses[house].classes || []).includes(cls); }
  function jobCard(unit) {
    const t = TR.unit.get(unit); if (!t) return "";
    const { j, u } = t, runs = u.runs, used = [...new Set(runs.map((r) => r[1]))], allOk = used.every((hh) => eligible(j.class, hh));
    const rowsH = runs.slice(0, 14).map(([h, house]) => `<div title="${esc(src("jobs.json + houses.u16", h))}" style="display:grid;grid-template-columns:92px 70px 1fr;gap:8px;color:#d8d2c8"><span>${when(h)}</span><span style="color:#ffb36b">house ${house}</span><span style="color:#a8a298">${why(house, h)}</span></div>`).join("")
      + (runs.length > 14 ? `<div style="color:#6e6a63">… ${runs.length - 14} more hours</div>` : "");
    return `<div style="font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:#ffb36b;margin-bottom:6px">job trace · ${esc(j.job)} / ${esc(u.unit)}</div>`
      + row("class", esc(j.class), j.class === "public" ? null : "#8fd3ff") + row("bid", j.bid + " CHF/server-h") + row("arrived", when(j.arrival_h))
      + row("deadline", `${when(j.deadline_h)} · ${j.state === "done" ? "met" : esc(j.state)}`, j.state === "done" ? "#b8e986" : "#ff3355")
      + row("houses used", `${used.length} · ${allOk ? "all eligible ✓" : "INELIGIBLE HOUSE"}`, allOk ? "#b8e986" : "#ff3355")
      + `<div style="margin:8px 0 4px;padding-top:8px;border-top:1px solid rgba(242,239,233,0.14);color:#a8a298">hour → house → why</div>${rowsH}`
      + `<div style="margin-top:8px;color:#6e6a63;font-size:10.5px" title="${esc(src("index.json"))}">run ${esc(FL.key || "–")} · commit ${esc((FL.commit || "–").slice(0, 10))} · traced every ${FL.trackEvery}th unit · ASSUMED fleet, real decide()</div>`;
  }
  function selectJob(unit, source) {
    FL.sel = unit || null; if (TR.ribbon) { scene.remove(TR.ribbon); TR.ribbon.geometry.dispose(); TR.ribbon = null; }
    for (const l of TR.locks) l.el.remove(); TR.locks = [];
    if (!FL.sel || !TR.unit.has(FL.sel)) { if (S.jobCard) { panel.style.display = "none"; S.jobCard = false; } applyRings(); return; }
    const { j, u } = TR.unit.get(FL.sel), seq = []; for (const [, house] of u.runs) if (seq[seq.length - 1] !== house) seq.push(house);
    if (seq.length) { const pts = seq.map((i) => hp(i).setY(FL.houses[i].Y + 40));
      if (pts.length === 1) pts.push(pts[0].clone().setY(pts[0].y + 60));
      TR.ribbon = new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), Math.max(16, pts.length * 12), 2.2, 6, false),
        new THREE.MeshBasicMaterial({ color: 0xffb36b, transparent: true, opacity: 0.85, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false }));
      scene.add(TR.ribbon);
      const H0 = FL.houses[seq[seq.length - 1]]; flyTo(new THREE.Vector3(H0.X - 320, 300, H0.Z + 320), new THREE.Vector3(H0.X, 0, H0.Z)); }
    if (j.class !== "public") for (let i = 0; i < FL.K; i++) if (!eligible(j.class, i)) {
      const el = document.createElement("div"); el.textContent = "🔒"; el.title = `house ${i} is not ${j.class}: the scheduler never sends this job here`;
      el.style.cssText = "position:absolute;transform:translate(-50%,-50%);font-size:11px;opacity:0.45;pointer-events:auto;z-index:3"; host.appendChild(el); TR.locks.push({ el, i }); }
    panel.style.display = "block"; panel.innerHTML = jobCard(FL.sel); S.jobCard = true; applyRings();
    if (source !== "map-echo") dispatchEvent(new CustomEvent("dh:select-job", { detail: { unit_id: FL.sel, source: "map" } }));
  }
  function applyRings() { FL.ringSelClass = FL.sel && TR.unit.has(FL.sel) ? TR.unit.get(FL.sel).j.class : null; }
  function houseJobsHtml(house, h) {
    const list = (TR.byHour.get(h) || []).filter((e) => e.house === house).slice(0, 8);
    return `<div style="font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:#c4bcae;margin-bottom:6px">fleet house ${house} · ${esc(FL.houses[house].district || "")} · ASSUMED</div>`
      + row("servers on", fv("servers_on", house, h), null) + row("heat used", fv("heat_used_kwh", house, h).toFixed(2) + " kWh") + row("dumped", fv("dumped_kwh", house, h).toFixed(2) + " kWh")
      + row("site cost", fv("mc_chf_per_server_h", house, h).toFixed(3) + " CHF/server-h") + row("why", why(house, h))
      + `<div style="margin:8px 0 4px;color:#a8a298">traced jobs here this hour (click one)</div>`
      + (list.length ? list.map((e) => `<button data-job="${esc(e.u.unit)}" style="display:block;width:100%;text-align:left;margin:2px 0;padding:5px 8px;border-radius:8px;border:1px solid rgba(242,239,233,0.2);background:rgba(255,179,107,0.08);color:#f2efe9;font:11px 'Geist Mono',monospace;cursor:pointer">${esc(e.u.unit)} · ${esc(e.j.class)}</button>`).join("") : `<div style="color:#6e6a63">none in the traced sample</div>`)
      + `<div style="margin-top:8px;color:#6e6a63;font-size:10.5px">${esc(src("houses.u16", h))}</div>`;
  }
  function nearestFleetHouse(px, py) {  // css px -> fleet house within 26 px, else -1
    if (!FL.on) return -1; let best = -1, bd = 26; const v = new THREE.Vector3();
    for (let i = 0; i < FL.K; i++) { v.copy(hp(i)).project(camera); if (v.z > 1) continue;
      const x = (v.x + 1) / 2 * cv.clientWidth, y = (1 - v.y) / 2 * cv.clientHeight, d = Math.hypot(x - px, y - py); if (d < bd) { bd = d; best = i; } }
    return best;
  }
  function stories() {  // auto-detected moments in the run, for the timeline chips
    if (!FL.on || !S.run) return [];
    const temps = S.run.weather.temp_c; let cold = 0; for (let i = 1; i < temps.length; i++) if (temps[i] < temps[cold]) cold = i;
    let reroute = 0, rv = -1; for (const [h, n] of (TR.moves.size ? TR.moves : TR.fan)) if (n > rv) { rv = n; reroute = h; }
    let hold = -1; for (let h = 2160; h < FL.H && hold < 0; h++) { let c = 0; for (let i = 0; i < FL.K; i++) if (fv("state", i, h) === 3) c++; if (c >= FL.K * 0.5) hold = h; }
    let dumpH = 0, dv = -1; for (let h = 0; h < FL.H; h++) { const v = FL.fleet.dumped_kwh[h]; if (v > dv) { dv = v; dumpH = h; } }
    return [{ h: cold, label: `coldest hour · ${temps[cold].toFixed(1)} °C`, src: "yearview weather" },
      ...(rv > 0 ? [{ h: reroute, label: TR.moves.size ? `biggest re-route · ${rv} traced jobs moved` : `widest job · one job on ${rv} houses in 1 h`, src: src("jobs.json", reroute) }] : []),
      ...(hold >= 0 ? [{ h: hold, label: "first summer hold · half the fleet idle", src: src("houses.u16", hold) }] : []),
      { h: dumpH, label: `most heat dumped · ${dv.toFixed(0)} kWh in 1 h`, src: src("fleet.json", dumpH) }];
  }
  const tmpG = new THREE.Matrix4(), ghostCol = new THREE.Color();
  function updateTrace(now, h, fr) {
    if (!FL.on || !TR.byHour) return;
    if (h !== TR.lastH) { TR.lastH = h;  // rebuild the hour's arcs (max 30, one colour per job)
      while (TR.arcs.children.length) { const o = TR.arcs.children.pop(); o.geometry.dispose(); o.material.dispose(); }
      const list = TR.byHour.get(h) || [], moves = list.filter((e) => e.prev !== null && e.prev !== e.house);
      const by = new Map(); for (const e of list) { const k = e.j.job; if (!by.has(k)) by.set(k, []); by.get(k).push(e); }  // houses sharing a job this hour
      const links = [];
      for (const [, arr] of [...by].sort((a, b) => b[1].length - a[1].length)) {  // busiest batches first
        const seen = []; for (const e of arr) if (!seen.some((x) => x.house === e.house)) seen.push(e);
        for (let k = 1; k < seen.length; k++) links.push({ ...seen[k], prev: seen[k - 1].house, batch: true });
      }
      TR.cur = [...moves, ...links].slice(0, 30);
      for (const e of TR.cur) { const c = arcCurve(hp(e.prev), hp(e.house)); const isSel = FL.sel === e.u.unit;
        TR.arcs.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(c.getPoints(40)), new THREE.LineBasicMaterial({ color: isSel ? 0xffffff : PAL[e.ji % PAL.length], transparent: true, opacity: isSel ? 0.95 : 0.45, blending: THREE.AdditiveBlending, depthWrite: false })));
        e.curve = c; } }
    let n = 0; const p = new THREE.Vector3(), col = new THREE.Color();
    for (const e of TR.cur || []) for (let k = 0; k < 10 && n < LN; k++) {  // a light travelling A -> B with a short fading trail
      const t = Math.max(0, Math.min(1, fr * 1.4 - k * 0.025)); e.curve.getPoint(t, p); lPos.set([p.x, p.y, p.z], n * 3);
      col.setHex(FL.sel === e.u.unit ? 0xffffff : PAL[e.ji % PAL.length]).multiplyScalar(1 - k / 10); lCol.set([col.r, col.g, col.b], n * 3); n++; }
    lGeo.setDrawRange(0, n); lGeo.attributes.position.needsUpdate = true; lGeo.attributes.color.needsUpdate = true;
    // eligibility: outline eligible houses for a non-public selected job; locks show on ineligible ones
    for (const l of TR.locks) place(l.el, hp(l.i).setY(FL.houses[l.i].Y + 22));
    // ghost thermostat: translucent rings in the thermostat's state + its missed jobs falling as grey ash
    if (TR.ghost && FL.rawBase) {
      if (!TR.ghostMesh) { TR.ghostMesh = new THREE.InstancedMesh(ringGeo, new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.35, depthWrite: false, toneMapped: false }), FL.K); TR.ghostMesh.frustumCulled = false; scene.add(TR.ghostMesh); }
      for (let i = 0; i < FL.K; i++) { const H0 = FL.houses[i], st = fvb("state", i, h), on = fvb("servers_on", i, h);
        ghostCol.setHex(st === 0 || st === 3 ? 0x55606e : 0xc4bcae); const sc = 1.15 + 0.2 * on;
        tmpG.makeScale(sc, 1, sc).setPosition(H0.X, 26, H0.Z); TR.ghostMesh.setMatrixAt(i, tmpG); TR.ghostMesh.setColorAt(i, ghostCol); }
      TR.ghostMesh.visible = true; TR.ghostMesh.instanceMatrix.needsUpdate = true; if (TR.ghostMesh.instanceColor) TR.ghostMesh.instanceColor.needsUpdate = true;
      const missed = (FL.fleet.baseline_missed || [])[h] || 0, m = Math.min(AN, Math.ceil(Math.sqrt(missed) * 3));
      for (let i = 0; i < m; i++) { const ang = i * 2.399, r = 30 + (i % 17) * 9, y = 260 - ((now / 12 + i * 37) % 260);
        aPos.set([hub.x + Math.cos(ang) * r, y, hub.z + Math.sin(ang) * r], i * 3); }
      aGeo.setDrawRange(0, m); aGeo.attributes.position.needsUpdate = true; TR.ash.visible = true;
    } else { if (TR.ghostMesh) TR.ghostMesh.visible = false; TR.ash.visible = false; }
  }
  const onSelJob = (e) => { const d = e.detail || {}; if (d.source === "map") return; selectJob(d.unit_id || null, "map-echo"); };
  addEventListener("dh:select-job", onSelJob);

  const S = { sel: -1, run: null, pol: 0, polT: 0, hour: 0, dead: false, raf: 0, last: performance.now(), hover: -1, n: 0 };
  function sideVal(run, key, h, w) { const a = run.ours[key][h], b = run.baseline[key][h]; return a + (b - a) * w; }
  function update(dt) {
    const run = S.run; if (!run) return;
    S.pol += (S.polT - S.pol) * Math.min(1, dt * 4);
    const h = Math.max(0, Math.min(HOURS - 1, Math.floor(S.hour))), w = S.pol;
    const dem = run.weather.demand_kwh[h], used = sideVal(run, "heat_used_kwh", h, w), back = sideVal(run, "backup_kwh", h, w);
    const dump = sideVal(run, "dumped_kwh", h, w), paused = w < 0.5 ? run.ours.paused[h] : run.baseline.paused[h];
    const on = sideVal(run, "servers_on", h, w), N = run.n || 1, temp = run.weather.temp_c[h];
    const norm = Math.max(1, run._demMax || 1);
    houses.forEach((hs, i) => { const k = i * 4, s = hs.scale;
      H[k] = Math.min(1.5, used * s / norm * 1.6); H[k + 1] = Math.min(1.5, back * s / norm * 1.2);
      // dumped: any dumping hour sparks visibly; intensity grows with the dumped share of this hour's server heat
      H[k + 2] = dump > 1e-3 ? 0.35 + 0.65 * Math.min(1, dump / Math.max(1e-6, used + dump) + dump * s / (N * 0.8)) : 0;
      H[k + 3] = paused ? 1 : 0; });
    houseTex.needsUpdate = true;
    DS.fill(0);
    D.forEach((d, di) => { if (di >= DMAX || !d.houses.length) return; let del = 0, un = 0;
      for (const k of d.houses) { const sc = houses[k].scale; del += used * sc; un += back * sc; }
      const m = d.houses.length * norm; DS[di * 4] = Math.min(1, 1.4 * del / m); DS[di * 4 + 1] = Math.min(1, 1.4 * un / m); DS[di * 4 + 3] = paused ? 1 : 0; });
    distTex.needsUpdate = true;
    // racks: N per house, lit = running share
    let idx = 0;
    houses.forEach((hs, i) => { for (let r = 0; r < RACK_MAX; r++) {
      const vis = r < N; const ang = r / RACK_MAX * Math.PI * 2;
      const rr = hs.rad + 9; tmpM.makeTranslation(hs.x + Math.cos(ang) * rr, vis ? 4.5 : -50, hs.z + Math.sin(ang) * rr); racks.setMatrixAt(idx, tmpM);
      const running = r < on - 1e-6; tmpC.set(paused ? 0x1a1a1a : running ? (dump > 1e-3 ? C.dump : C.heat) : 0x2a3a4a); racks.setColorAt(idx, tmpC); idx++; } });
    racks.instanceMatrix.needsUpdate = true; if (racks.instanceColor) racks.instanceColor.needsUpdate = true;
    // sun, season, snow
    const sd = sunDir(h), day = Math.max(0, Math.sin(sd.el));
    sun.position.copy(sd.v).multiplyScalar(3000); sun.intensity = 0.15 + 1.6 * day;
    sun.color.setHSL(0.08, 0.6, 0.55 + 0.3 * day);
    hemi.intensity = 0.55 + 0.6 * day; simU.uSun.value.copy(sd.v); simU.uSunI.value = 0.2 + 0.8 * day; waterU.uSunI.value = 0.15 + 0.85 * day;
    const bg = new THREE.Color(0x07080b).lerp(new THREE.Color(0x3d4f66), day * 0.55); scene.background.copy(bg); scene.fog.color.copy(bg);
    const snow = Math.max(0, Math.min(1, (1 - temp) / 6)); groundU.uSnow.value = snow; snowU.value = snow;
    groundU.uGreen.value = Math.max(0, Math.min(1, (temp - 8) / 12));
    hubLight.intensity = on > 0 ? 3 + 2 * Math.sin(performance.now() / 300) : 0.6;
    hubCore.material.opacity = 0.25 + 0.4 * Math.min(1, on / N);
    S.info = { h, temp, demand: dem, used, backup: back, dump, paused: !!paused, on, n: N, policy: w < 0.5 ? "ours" : "thermostat" };
  }

  // ---- #115 clickable buildings: GPU id-buffer picking (rendered only on click / throttled hover), highlight, glass panel
  const pickScene = new THREE.Scene(), pickRT = new THREE.WebGLRenderTarget(1, 1);
  const pickMat = new THREE.ShaderMaterial({ vertexShader: `attribute float aBid; varying vec3 vId;
      void main(){ float id = aBid + 1.0; vId = vec3(floor(id / 65536.0), floor(mod(id, 65536.0) / 256.0), mod(id, 256.0)) / 255.0;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: `varying vec3 vId; void main(){ gl_FragColor = vec4(vId, 1.0); }` });
  pickScene.add(new THREE.Mesh(geo.city, pickMat), new THREE.Mesh(geo.sim, pickMat));
  const px = new Uint8Array(4);
  function pick(cx, cy) {  // css px inside the canvas -> building index, or -1 for ground / sky
    const w = cv.clientWidth, h = cv.clientHeight, dpr = renderer.getPixelRatio(), cc = new THREE.Color(), ca = renderer.getClearAlpha();
    renderer.getClearColor(cc);
    camera.setViewOffset(w * dpr, h * dpr, Math.round(cx * dpr), Math.round(cy * dpr), 1, 1);
    renderer.setRenderTarget(pickRT); renderer.setClearColor(0x000000, 1); renderer.clear(); renderer.render(pickScene, camera);
    renderer.readRenderTargetPixels(pickRT, 0, 0, 1, 1, px); renderer.setRenderTarget(null); camera.clearViewOffset();
    renderer.setClearColor(cc, ca);
    return px[0] * 65536 + px[1] * 256 + px[2] - 1;
  }
  const panel = document.createElement("div");
  panel.setAttribute("data-dh-panel", "");
  panel.style.cssText = "position:absolute;top:44px;right:156px;width:min(300px,42%);max-height:calc(100% - 260px);overflow:auto;display:none;padding:14px 16px;border-radius:16px;background:rgba(18,17,16,0.62);backdrop-filter:blur(14px) saturate(1.2);-webkit-backdrop-filter:blur(14px) saturate(1.2);border:1px solid rgba(242,239,233,0.2);box-shadow:0 20px 60px rgba(0,0,0,0.45);color:#f2efe9;font:12px/1.55 'Geist Mono',monospace;z-index:6";
  host.appendChild(panel);
  panel.addEventListener("click", (e) => { const b = e.target.closest && e.target.closest("[data-job]"); if (b) { e.stopPropagation(); selectJob(b.dataset.job, "map"); } });
  const liveByB = new Map(live.map((L) => [L.b, L]));
  const row = (k, v, c) => `<div style="display:flex;justify-content:space-between;gap:12px"><span style="color:#a8a298">${k}</span><span style="color:${c || "#f2efe9"};text-align:right">${v}</span></div>`;
  function reason(sd, h, n) {  // the scheduler's outcome this hour, from the yearview run (same wording as the HUD)
    const on = Math.round(sd.servers_on[h]), dump = sd.dumped_kwh[h], fill = sd.ballast_units ? sd.ballast_units[h] : 0;
    if (sd.paused[h] && on === 0) return "HOLD · no heat wanted, no paid deadline due";
    if (on === 0) return "IDLE · nothing worth running";
    if (dump > 1e-3) return `RUN ${on}/${n} · paid deadline due, heat dumped`;
    if (fill > 0) return `RUN ${on}/${n} · heat wanted, filler tops up`;
    return `RUN ${on}/${n} · paid work, heat used`;
  }
  function panelHtml(b) {
    const name = (map.names || {})[b], type = map.btypes ? map.btypes[map.bt[b]] : "building", hgt = map.buildings[b][0] / 10;
    let t2 = null;
    const head = (t, c) => `<div style="font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:${c};margin-bottom:6px">${t}</div>`
      + `<div style="font:600 15px/1.25 'Geist',system-ui,sans-serif;margin-bottom:8px">${esc(t2 || (name || type).replace(/_/g, " "))}</div>`;
    const close = `<div style="margin-top:10px;color:#6e6a63;font-size:10.5px">click empty space or Esc to close</div>`;
    const L = liveByB.get(b);
    if (L) { const st = L.st || {}; t2 = `${L.id} (illustrative placement)`;
      return head(`${L.id} · ${st.mode === "LIVE" ? "live node" : "live node · replay"}`, "#7fd18b") + row("state", st.state || "–", "#ff8c1f")
        + row("running unit", esc(st.unit || "–")) + row("progress", st.progress != null ? Math.round(st.progress * 100) + " %" : "–")
        + row("power", st.watts != null ? Math.round(st.watts) + " W" : "–") + row("lease", st.lease ? "held (trail from the hub)" : "none")
        + `<div style="margin-top:8px;color:#a8a298">placed on this building for illustration; the state is the real machine's.</div>` + close; }
    const k = simIdx.get(b), run = S.run, i = S.info;
    if (k !== undefined && run && i) {
      const hs = houses[k], sc = hs.scale, h = i.h, sd = i.policy === "ours" ? run.ours : run.baseline;
      t2 = k === 0 ? "the reference house" : `fleet house #${k}`;
      return head(k === 0 ? "reference house · simulated (graded)" : `fleet house #${k} · illustrative`, k === 0 ? "#ff8c1f" : "#c4bcae")
        + row("heat delivered", (i.used * sc).toFixed(2) + " kWh", "#ff8c1f") + row("demand", (i.demand * sc).toFixed(2) + " kWh")
        + row("backup heater", (i.backup * sc).toFixed(2) + " kWh", "#7fa6e0") + row("dumped", (i.dump * sc).toFixed(2) + " kWh", i.dump > 1e-3 ? "#ff3355" : null)
        + row("tank", (sd.tank_kwh[h] * sc).toFixed(1) + " kWh") + row("servers", `${Math.round(i.on)}/${i.n}${i.paused ? " · held" : ""}`)
        + row("net CHF so far", Math.round(sd.net_chf_cum[h] * sc).toLocaleString("en-CH") + " CHF")
        + `<div style="margin-top:8px;padding-top:8px;border-top:1px solid rgba(242,239,233,0.14)">${reason(sd, h, i.n)}</div>`
        + (k ? `<div style="margin-top:6px;color:#a8a298">= the reference year × ${sc.toFixed(2)} (footprint, seeded variation)</div>` : "") + close;
    }
    return head("building · OpenStreetMap", "#a8a298") + row("type", esc(type.replace(/_/g, " "))) + row("height", hgt.toFixed(1) + " m")
      + row("footprint", map.areas_m2[b] + " m²") + `<div style="margin-top:8px;color:#a8a298">no DigitalHeat server</div>` + close;
  }
  function select(b) {
    selU.value = b; S.sel = b;
    if (b < 0) { panel.style.display = "none"; return; }
    panel.style.display = "block"; panel.innerHTML = panelHtml(b);
    const c = geo.centroids[b], r = Math.max(70, Math.sqrt(map.areas_m2[b]) * 3 + c[2] * 2.2);
    const dir = camera.position.clone().sub(controls.target).setY(0).normalize();
    flyTo(new THREE.Vector3(c[0] + dir.x * r, c[2] + r * 0.8, -c[1] + dir.z * r), new THREE.Vector3(c[0], c[2] * 0.5, -c[1]));
  }
  let down = null;
  cv.addEventListener("pointerdown", (e) => { down = [e.clientX, e.clientY]; });
  cv.addEventListener("pointerup", (e) => {
    if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) { down = null; return; }
    down = null; const r = cv.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    const fh = nearestFleetHouse(x, y);
    if (fh >= 0) { S.sel = -1; selU.value = -1; S.jobCard = false; panel.style.display = "block"; panel.innerHTML = houseJobsHtml(fh, Math.floor(S.hour)); S.fleetHouse = fh;
      dispatchEvent(new CustomEvent("dh:select-house", { detail: { house: fh, source: "map" } })); return; }
    S.fleetHouse = -1; if (S.jobCard) selectJob(null, "map"); select(pick(x, y));
  });
  cv.addEventListener("pointermove", (e) => { if (e.buttons || e.pointerType === "touch") return; const now = performance.now();
    if ((S.hoverAt || 0) + 150 > now) return; S.hoverAt = now; const r = cv.getBoundingClientRect();
    cv.style.cursor = pick(e.clientX - r.left, e.clientY - r.top) >= 0 ? "pointer" : "grab"; });
  const onKey = (e) => {
    if (e.key === "Escape") { select(-1); selectJob(null, "map"); panel.style.display = "none"; return; }
    if (!S.inside || /input|textarea|select/i.test((e.target && e.target.tagName) || "")) return;
    const k = e.key.toLowerCase(), step = Math.max(30, camera.position.distanceTo(controls.target) * 0.08);
    const fwd = controls.target.clone().sub(camera.position).setY(0).normalize(), right = new THREE.Vector3(-fwd.z, 0, fwd.x);
    const mv = { w: fwd, arrowup: fwd, s: fwd.clone().negate(), arrowdown: fwd.clone().negate(), d: right, arrowright: right,
      a: right.clone().negate(), arrowleft: right.clone().negate() }[k];
    if (mv) { e.preventDefault(); const d = mv.clone().multiplyScalar(step); camera.position.add(d); controls.target.add(d); controls.autoRotate = false; }
    else if (k === "+" || k === "=") nav("in"); else if (k === "-" || k === "_") nav("out");
    else if (k === "q") nav("left"); else if (k === "e") nav("right");
  };
  addEventListener("keydown", onKey);
  host.addEventListener("pointerenter", () => { S.inside = true; }); host.addEventListener("pointerleave", () => { S.inside = false; });

  // ---- #115 navigation: smooth fly-to, on-screen controls, mini-map with compass + view cone, bounded camera
  function flyTo(pos, tgt, ms = 1100) { controls.autoRotate = false;
    S.fly = { p0: camera.position.clone(), t0: controls.target.clone(), p1: pos, t1: tgt, start: performance.now(), ms }; }
  function nav(cmd) {
    if (cmd === "reset") { flyTo(new THREE.Vector3(-1900, 1500, 1700), new THREE.Vector3(0, 0, 0)); return; }
    const off = camera.position.clone().sub(controls.target), sph = new THREE.Spherical().setFromVector3(off);
    if (cmd === "in") sph.radius *= 0.7; else if (cmd === "out") sph.radius *= 1.4;
    else if (cmd === "left") sph.theta += 0.45; else if (cmd === "right") sph.theta -= 0.45;
    else if (cmd === "up") sph.phi = Math.max(0.15, sph.phi - 0.2); else if (cmd === "down") sph.phi = Math.min(controls.maxPolarAngle, sph.phi + 0.2);
    sph.radius = Math.max(controls.minDistance, Math.min(controls.maxDistance, sph.radius));
    flyTo(new THREE.Vector3().setFromSpherical(sph).add(controls.target), controls.target.clone(), 450);
  }
  const navEl = document.createElement("div");
  navEl.setAttribute("data-dh-mapnav", "");
  navEl.style.cssText = "position:absolute;right:18px;bottom:70px;display:grid;grid-template-columns:repeat(3,34px);gap:5px;z-index:6";
  [["⟲", "left", "rotate left (Q)"], ["▲", "up", "tilt up"], ["⟳", "right", "rotate right (E)"], ["+", "in", "zoom in (+)"], ["⌂", "reset", "reset view"],
    ["−", "out", "zoom out (−)"], ["", "", ""], ["▼", "down", "tilt down"], ["", "", ""]].forEach(([t, cmd, tip]) => {
    const b = document.createElement(cmd ? "button" : "span"); b.textContent = t;
    if (cmd) { b.title = tip; b.setAttribute("aria-label", tip); b.dataset.nav = cmd;
      b.style.cssText = "width:34px;height:34px;border-radius:10px;border:1px solid rgba(242,239,233,0.25);background:rgba(14,13,12,0.6);color:#f2efe9;font:15px 'Geist Mono',monospace;cursor:pointer";
      b.addEventListener("click", (e) => { e.stopPropagation(); nav(cmd); }); }
    navEl.appendChild(b); });
  host.appendChild(navEl);
  const MM = 150, EXT = 2800, mm = document.createElement("canvas"); mm.width = mm.height = MM * 2;
  mm.setAttribute("data-dh-minimap", ""); mm.title = "mini-map: click to fly there";
  mm.style.cssText = `position:absolute;right:136px;bottom:70px;width:${MM}px;height:${MM}px;border-radius:12px;border:1px solid rgba(242,239,233,0.25);background:rgba(14,13,12,0.7);cursor:crosshair;z-index:6`;
  host.appendChild(mm);
  const mmBase = document.createElement("canvas"); mmBase.width = mmBase.height = MM * 2;
  { const g = mmBase.getContext("2d"), sc = (MM * 2) / (EXT * 2), X = (x) => (x + EXT) * sc, Y = (y) => (EXT - y) * sc;
    const poly = (r, fill) => { const pts = ringPts(r, 0, map.q); g.beginPath(); pts.forEach((p, k) => (k ? g.lineTo(X(p[0]), Y(p[1])) : g.moveTo(X(p[0]), Y(p[1])))); g.closePath(); fill ? g.fill() : g.stroke(); };
    g.fillStyle = "#3d6a96"; for (const w of map.water) poly(w, true);
    g.strokeStyle = "rgba(242,239,233,0.35)"; g.lineWidth = 1; for (const d of D) poly(d.ring, false);
    g.fillStyle = "#ff8c1f"; for (const hs of houses) g.fillRect(X(hs.x) - 2, Y(-hs.z) - 2, 4, 4);
    g.fillStyle = "#7fd18b"; for (const L of live) g.fillRect(X(L.x) - 3, Y(-L.z) - 3, 6, 6); }
  function drawMini() {
    const g = mm.getContext("2d"), sc = (MM * 2) / (EXT * 2), X = (x) => (x + EXT) * sc, Y = (z) => (EXT + z) * sc;
    g.clearRect(0, 0, MM * 2, MM * 2); g.drawImage(mmBase, 0, 0);
    const t = controls.target, cp = camera.position, ang = Math.atan2(t.z - cp.z, t.x - cp.x), L = cp.distanceTo(t) * 1.6;
    g.fillStyle = "rgba(255,179,107,0.22)"; g.beginPath(); g.moveTo(X(cp.x), Y(cp.z));
    g.lineTo(X(cp.x + Math.cos(ang - 0.35) * L), Y(cp.z + Math.sin(ang - 0.35) * L)); g.lineTo(X(cp.x + Math.cos(ang + 0.35) * L), Y(cp.z + Math.sin(ang + 0.35) * L)); g.fill();
    g.fillStyle = "#f2efe9"; g.beginPath(); g.arc(X(t.x), Y(t.z), 4, 0, 7); g.fill();
    g.font = "bold 20px 'Geist Mono', monospace"; g.fillText("N", MM * 2 - 26, 24);
    g.beginPath(); g.moveTo(MM * 2 - 19, 30); g.lineTo(MM * 2 - 25, 46); g.lineTo(MM * 2 - 13, 46); g.fill();
  }
  mm.addEventListener("click", (e) => { const r = mm.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width * 2 * EXT - EXT, z = (e.clientY - r.top) / r.height * 2 * EXT - EXT;
    const off = camera.position.clone().sub(controls.target), t1 = new THREE.Vector3(x, 0, z); flyTo(t1.clone().add(off), t1); });


  function resize() { const w = Math.max(1, host.clientWidth), h = Math.max(1, host.clientHeight);
    if (cv.width !== Math.round(w * renderer.getPixelRatio()) || cv.height !== Math.round(h * renderer.getPixelRatio())) {
      renderer.setSize(w, h, false); composer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix(); } }
  function frame(now) {
    if (S.dead) return; S.raf = requestAnimationFrame(frame);
    const dt = Math.min(0.05, (now - S.last) / 1000); S.last = now; resize();
    const t = now / 1000; for (const u of [groundU, simU, waterU, trailU, flowU, sparkU, hexU]) u.uTime.value = t; grain.uniforms.uTime.value = t;
    update(dt);
    if (S.fly) { const f = S.fly, k = Math.min(1, (now - f.start) / f.ms), e = k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
      camera.position.lerpVectors(f.p0, f.p1, e); controls.target.lerpVectors(f.t0, f.t1, e); if (k >= 1) S.fly = null; }
    controls.target.x = Math.max(-2600, Math.min(2600, controls.target.x)); controls.target.z = Math.max(-2600, Math.min(2600, controls.target.z));
    controls.target.y = Math.max(0, Math.min(200, controls.target.y));
    controls.update();
    if (now - (S.mmAt || 0) > 100) { S.mmAt = now; drawMini(); }
    if (S.sel >= 0 && !S.jobCard && now - (S.panelAt || 0) > 500) { S.panelAt = now; panel.innerHTML = panelHtml(S.sel); }
    if (now - (S.liveAt || 0) > 500) { S.liveAt = now; updateLive(); }
    updateFleet(now);
    for (const l of labels) place(l.el, l.p);
    for (const L of live) place(L.el, L.p);
    composer.render();
  }
  S.raf = requestAnimationFrame(frame);
  const presets = { city: [[-1900, 1500, 1700], [0, 0, 0]], district: () => { const r = houses[0]; return [[r.x - 520, 420, r.z + 520], [r.x, 0, r.z]]; },
    house: () => { const r = houses[0]; return [[r.x - 120, 90, r.z + 140], [r.x, r.h * 0.5, r.z]]; } };
  return {
    setRun(run) { let m = 0; for (let i = 0; i < HOURS; i++) m = Math.max(m, run.weather.demand_kwh[i]); run._demMax = m; S.run = run; },
    setPolicy(p) { S.polT = p === "thermostat" || p === "baseline" ? 1 : 0; },
    setHour(h) { S.hour = Math.max(0, Math.min(HOURS - 1, +h || 0)); },
    focus(name) { const p = typeof presets[name] === "function" ? presets[name]() : presets[name]; if (!p) return;
      if (name === "house") { select(map.reference); return; }
      flyTo(new THREE.Vector3(...p[0]), new THREE.Vector3(...p[1])); },
    select(b) { select(b); }, selected() { return S.sel; }, pick(x, y) { return pick(x, y); }, nav(cmd) { nav(cmd); },
    info() { return S.info || null; },
    setLive(feed) { liveFeed = feed; },
    setFleet(d) { setFleet(d); }, selectJob(u) { selectJob(u, "api"); }, setGhost(on) { TR.ghost = !!on; }, stories() { return stories(); },
    camera() { const p = camera.position, t = controls.target; return [p.x, p.y, p.z, t.x, t.y, t.z].map((v) => Math.round(v)); },
    setCamera(a) { if (Array.isArray(a) && a.length === 6 && a.every(Number.isFinite)) flyTo(new THREE.Vector3(a[0], a[1], a[2]), new THREE.Vector3(a[3], a[4], a[5]), 10); }, fleetOn() { return FL.on ? { K: FL.K, H: FL.H, fixture: FL.fixture } : null; },  // the dashboard's /api/nodes payload (#78); null/not ok -> REPLAY
    live() { return live.map((L) => ({ id: L.id, ...(L.st || {}) })); },
    stats() { return { buildings: map.buildings.length, houses: houses.length, districts: D.length, hexes: hexes.length, live: live.length, tris: (geo.city.getAttribute("position").count + geo.sim.getAttribute("position").count) / 3 }; },
    attribution: map.attribution, fleetNote: map.fleet_note,
    destroy() { S.dead = true; cancelAnimationFrame(S.raf); removeEventListener("keydown", onKey);
      removeEventListener("dh:select-job", onSelJob); for (const t of FL.tags) t.remove(); for (const l of TR.locks) l.el.remove();
      for (const el of [cv, panel, navEl, mm, queueTag, ...labels.map((l) => l.el), ...live.map((L) => L.el)]) el.remove();
      pickRT.dispose(); renderer.dispose(); },
  };
}

window.DHBasel3D = { create };
