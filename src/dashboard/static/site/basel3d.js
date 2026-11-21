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
  const q = map.q, city = { p: [], n: [], c: [] }, sim = { p: [], n: [], hid: [] }, base = new THREE.Color();
  const centroids = [];
  map.buildings.forEach((b, i) => {
    const h = b[0] / 10, kind = b[1], pts = ringPts(b, 2, q);
    const hid = simIdx.get(i); const tgt = hid === undefined ? city : sim;
    let cx = 0, cy = 0; for (const p of pts) { cx += p[0]; cy += p[1]; } centroids[i] = [cx / pts.length, cy / pts.length, h];
    const shade = kind ? 0.16 : 0.13; base.setRGB(shade * 1.05, shade, shade * 0.95);
    const push = (x, y, z, nx, ny, nz) => {
      tgt.p.push(x, y, z); tgt.n.push(nx, ny, nz);
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
    city: mk(city, (g) => g.setAttribute("color", new THREE.Float32BufferAttribute(city.c, 3))),
    sim: mk(sim, (g) => g.setAttribute("aHouse", new THREE.Float32BufferAttribute(sim.hid, 2))),
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
  controls.enableDamping = true; controls.dampingFactor = 0.07; controls.maxPolarAngle = 1.42; controls.minDistance = 120; controls.maxDistance = 6000;
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
  cityMat.onBeforeCompile = (s) => { s.uniforms.uSnow = snowU;
    s.fragmentShader = s.fragmentShader.replace("#include <common>", "#include <common>\nuniform float uSnow;")
      .replace("#include <color_fragment>", "#include <color_fragment>\n if (vNormal.y > 0.5) diffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.78, 0.8, 0.84), uSnow * 0.8);"); };
  cityMat.emissive = new THREE.Color(0x2a1c10); cityMat.emissiveIntensity = 0.55;
  scene.add(new THREE.Mesh(geo.city, cityMat));
  const simU = { uState: { value: houseTex }, uTime: { value: 0 }, uSun: { value: new THREE.Vector3(0, 1, 0) }, uSunI: { value: 1 } };
  const simMesh = new THREE.Mesh(geo.sim, new THREE.ShaderMaterial({
    uniforms: simU,
    vertexShader: `attribute vec2 aHouse; varying vec2 vH; varying vec3 vN; void main(){ vH = aHouse; vN = normal; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: `uniform sampler2D uState; uniform float uTime, uSunI; uniform vec3 uSun; varying vec2 vH; varying vec3 vN;
      void main(){
        vec4 st = texture2D(uState, vec2((vH.x + 0.5) / ${MAXH}.0, 0.5));
        float lit = 0.25 + 0.75 * max(0.0, dot(normalize(vN), normalize(uSun))) * uSunI;
        vec3 base = vec3(0.30, 0.28, 0.26) * lit;
        float win = step(0.5, fract(vH.y * 9.0)) * 0.6 + 0.4;
        vec3 glow = vec3(1.0, 0.36, 0.04) * min(st.r, 1.0) * (0.55 + 0.35 * win) + vec3(0.12, 0.38, 1.0) * min(st.g, 1.0) * 0.6 + vec3(1.0, 0.06, 0.18) * min(st.b, 1.0) * 0.9;
        glow *= (1.0 - 0.85 * st.a);
        float ref = vH.x < 0.5 ? 0.35 + 0.25 * sin(uTime * 2.0) : 0.0;  // the reference house breathes
        gl_FragColor = vec4(base + glow + vec3(1.0, 0.8, 0.5) * ref * 0.25, 1.0);
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
  const tmpM = new THREE.Matrix4(), tmpC = new THREE.Color();

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
  const S = { run: null, pol: 0, polT: 0, hour: 0, dead: false, raf: 0, last: performance.now(), hover: -1, n: 0 };
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

  // hover card
  const card = document.createElement("div");
  card.style.cssText = "position:absolute;pointer-events:none;display:none;min-width:190px;padding:10px 12px;border-radius:12px;background:rgba(20,20,20,0.72);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);border:1px solid rgba(242,239,233,0.18);color:#f2efe9;font:12px/1.5 'Geist Mono',monospace;z-index:5";
  host.appendChild(card);
  const ray = new THREE.Raycaster(), mouse = new THREE.Vector2();
  cv.addEventListener("pointermove", (e) => {
    const r = cv.getBoundingClientRect(); mouse.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(mouse, camera); const hit = ray.intersectObject(simMesh, false)[0];
    if (!hit || !S.info) { card.style.display = "none"; return; }
    const hid = Math.round(geo.sim.getAttribute("aHouse").getX(hit.face.a)), hs = houses[hid], i = S.info, s = hs.scale;
    card.style.display = "block"; card.style.left = (e.clientX - r.left + 14) + "px"; card.style.top = (e.clientY - r.top + 14) + "px";
    card.innerHTML = `<div style="color:${hid ? "#c4bcae" : "#ff8c1f"};letter-spacing:.1em;text-transform:uppercase;font-size:10px">${hid ? "fleet house #" + hid + " · illustrative" : "reference house · simulated"}</div>`
      + `<div>heat used <b>${(i.used * s).toFixed(2)} kWh</b></div><div>demand ${(i.demand * s).toFixed(2)} kWh</div>`
      + `<div>backup heater ${(i.backup * s).toFixed(2)} kWh</div><div>dumped ${(i.dump * s).toFixed(2)} kWh</div>`
      + `<div>servers ${Math.round(i.on)}/${i.n} ${i.paused ? "· paused" : ""}</div>`;
  });
  cv.addEventListener("pointerleave", () => { card.style.display = "none"; });

  function resize() { const w = Math.max(1, host.clientWidth), h = Math.max(1, host.clientHeight);
    if (cv.width !== Math.round(w * renderer.getPixelRatio()) || cv.height !== Math.round(h * renderer.getPixelRatio())) {
      renderer.setSize(w, h, false); composer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix(); } }
  function frame(now) {
    if (S.dead) return; S.raf = requestAnimationFrame(frame);
    const dt = Math.min(0.05, (now - S.last) / 1000); S.last = now; resize();
    const t = now / 1000; for (const u of [groundU, simU, waterU, trailU, flowU, sparkU]) u.uTime.value = t; grain.uniforms.uTime.value = t;
    update(dt); controls.update(); composer.render();
  }
  S.raf = requestAnimationFrame(frame);
  const presets = { city: [[-1900, 1500, 1700], [0, 0, 0]], district: () => { const r = houses[0]; return [[r.x - 520, 420, r.z + 520], [r.x, 0, r.z]]; },
    house: () => { const r = houses[0]; return [[r.x - 120, 90, r.z + 140], [r.x, r.h * 0.5, r.z]]; } };
  return {
    setRun(run) { let m = 0; for (let i = 0; i < HOURS; i++) m = Math.max(m, run.weather.demand_kwh[i]); run._demMax = m; S.run = run; },
    setPolicy(p) { S.polT = p === "thermostat" || p === "baseline" ? 1 : 0; },
    setHour(h) { S.hour = Math.max(0, Math.min(HOURS - 1, +h || 0)); },
    focus(name) { const p = typeof presets[name] === "function" ? presets[name]() : presets[name]; if (!p) return;
      controls.autoRotate = false; camera.position.set(...p[0]); controls.target.set(...p[1]); },
    info() { return S.info || null; },
    stats() { return { buildings: map.buildings.length, houses: houses.length, tris: (geo.city.getAttribute("position").count + geo.sim.getAttribute("position").count) / 3 }; },
    attribution: map.attribution, fleetNote: map.fleet_note,
    destroy() { S.dead = true; cancelAnimationFrame(S.raf); renderer.dispose(); },
  };
}

window.DHBasel3D = { create };
