/* Hearthbeat · 07 Year · 3D heat helix (#101). Raw WebGL2, no dependencies, offline.
 *
 * The Basel 2025 year as a helix: one turn = one day (24 h around), 365 turns stacked bottom (1 Jan) to top (31 Dec).
 *  - radius   = the house's heat demand that hour   (cold days bulge outward)
 *  - colour   = outdoor temperature                 (ink-blue cold -> cream -> heat-orange warm)
 *  - glow     = server heat delivered into the house (brighter = more of the demand met by servers)
 *  - red      = heat dumped (hours where paid deadlines forced running with no heat wanted); sparks fly off
 *  - dark     = hours the site was paused (no heat wanted, no deadline)
 *  - particles stream from the core (the servers) into the helix at the playhead, one per ~0.05 kWh used
 * Everything is read from /api/year?n= (yearview-v1, #95): no number on this canvas is invented.
 *
 *   const v = DHYear3D.create(canvas, {onError})   // null if WebGL2 is unavailable (the page keeps its 2D view)
 *   v.setRun(run)            // yearview-v1 n<N>.json (morphs smoothly from the previous run)
 *   v.setPolicy("ours"|"thermostat")   // crossfade
 *   v.setHour(hf)            // fractional hour 0..8759 (the page's playhead)
 *   v.destroy()
 */
(function () {
  "use strict";
  const HOURS = 8760, DAYS = 365, POOL = 3500;
  const INK = [0.078, 0.078, 0.078], BG = [0.055, 0.052, 0.048];

  const VS_HELIX = `#version 300 es
  precision highp float;
  layout(location=0) in float aHour;
  layout(location=1) in vec4 aA0;   // run A: demand, used(ours), dump(ours), paused(ours)
  layout(location=2) in vec4 aA1;   // run A: used(base), dump(base), paused(base), temp
  layout(location=3) in vec4 aB0;   // run B (morph target), same layout
  layout(location=4) in vec4 aB1;
  uniform mat4 uVP; uniform float uMorph, uPol, uHour, uPoint, uTMin, uTMax, uDemMax, uTime, uLine;
  out vec4 vCol; out float vGlow;
  vec3 tempCol(float t) {
    float f = clamp((t - uTMin) / max(1e-3, uTMax - uTMin), 0.0, 1.0);
    vec3 cold = vec3(0.114, 0.420, 0.702), mid = vec3(0.949, 0.937, 0.914), hot = vec3(0.788, 0.235, 0.020);
    return f < 0.5 ? mix(cold, mid, f * 2.0) : mix(mid, hot, (f - 0.5) * 2.0);
  }
  void main() {
    vec4 a0 = mix(aA0, aB0, uMorph), a1 = mix(aA1, aB1, uMorph);
    float demand = a0.x;
    float used = mix(a0.y, a1.x, uPol), dump = mix(a0.z, a1.y, uPol), paused = mix(a0.w, a1.z, uPol);
    float day = floor(aHour / 24.0), hh = mod(aHour, 24.0);
    float ang = 6.2831853 * hh / 24.0 + day * 0.0172;
    float r = 1.6 + 2.6 * demand / max(1e-3, uDemMax);
    float y = (day / 365.0) * 12.0 - 6.0 + hh / 24.0 * (12.0 / 365.0);
    vec3 p = vec3(cos(ang) * r, y, sin(ang) * r);
    gl_Position = uVP * vec4(p, 1.0);
    float past = step(aHour, uHour);
    float near = exp(-max(0.0, uHour - aHour) / 30.0) * past;
    float cover = demand > 1e-4 ? clamp(used / demand, 0.0, 1.0) : 0.0;
    vec3 base = tempCol(a1.w);
    vec3 heat = vec3(1.0, 0.55, 0.12);
    vec3 col = mix(base * 0.55, heat, cover * 0.85);
    float d = clamp(dump / max(0.05, demand + dump), 0.0, 1.0);  // share of this hour's heat that was dumped
    col = mix(col, vec3(0.82, 0.09, 0.23), d * 0.85);
    col *= mix(1.0, 0.18, paused);
    float alpha = mix(0.20, 0.85, past) + near * 0.6;
    vGlow = (cover * 0.6 + d * 0.45) * past + near;
    vCol = vec4(col * (0.55 + 0.9 * vGlow), alpha * (uLine > 0.5 ? 0.35 : 1.0));
    gl_PointSize = uPoint * (0.7 + 1.1 * cover * past + 2.2 * near + 1.6 * d * past) / max(0.35, gl_Position.w * 0.16);
  }`;
  const FS_HELIX = `#version 300 es
  precision highp float;
  in vec4 vCol; in float vGlow; uniform float uLine; out vec4 o;
  void main() {
    if (uLine > 0.5) { o = vCol; return; }
    vec2 c = gl_PointCoord * 2.0 - 1.0; float r2 = dot(c, c);
    if (r2 > 1.0) discard;
    float core = exp(-r2 * 3.0);
    o = vec4(vCol.rgb * (0.6 + core), vCol.a * core);
  }`;
  const VS_P = `#version 300 es
  precision highp float;
  layout(location=0) in vec4 aP;   // xyz, life 0..1
  layout(location=1) in vec4 aC;   // rgb, size
  uniform mat4 uVP; out vec4 vC;
  void main() {
    gl_Position = uVP * vec4(aP.xyz, 1.0);
    float l = aP.w;
    vC = vec4(aC.rgb, smoothstep(0.0, 0.15, l) * smoothstep(1.0, 0.6, l));
    gl_PointSize = aC.w / max(0.35, gl_Position.w * 0.16);
  }`;
  const FS_P = `#version 300 es
  precision highp float;
  in vec4 vC; out vec4 o;
  void main() { vec2 c = gl_PointCoord * 2.0 - 1.0; float r2 = dot(c, c); if (r2 > 1.0) discard;
    float k = exp(-r2 * 4.0); o = vec4(vC.rgb * (0.7 + k), vC.a * k); }`;

  function sh(gl, type, src) {
    const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
    return s;
  }
  function prog(gl, vs, fs) {
    const p = gl.createProgram();
    gl.attachShader(p, sh(gl, gl.VERTEX_SHADER, vs)); gl.attachShader(p, sh(gl, gl.FRAGMENT_SHADER, fs));
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
    const u = {}; const n = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS);
    for (let i = 0; i < n; i++) { const name = gl.getActiveUniform(p, i).name; u[name] = gl.getUniformLocation(p, name); }
    return { p, u };
  }
  // column-major 4x4 helpers
  function persp(fov, asp, n, f) { const t = 1 / Math.tan(fov / 2), d = 1 / (n - f);
    return [t / asp, 0, 0, 0, 0, t, 0, 0, 0, 0, (f + n) * d, -1, 0, 0, 2 * f * n * d, 0]; }
  function lookAt(e, c) {
    let zx = e[0] - c[0], zy = e[1] - c[1], zz = e[2] - c[2]; let l = Math.hypot(zx, zy, zz); zx /= l; zy /= l; zz /= l;
    let xx = zz, xy = 0, xz = -zx; l = Math.hypot(xx, xy, xz) || 1; xx /= l; xz /= l;
    const yx = zy * xz - zz * xy, yy = zz * xx - zx * xz, yz = zx * xy - zy * xx;
    return [xx, yx, zx, 0, xy, yy, zy, 0, xz, yz, zz, 0,
      -(xx * e[0] + xy * e[1] + xz * e[2]), -(yx * e[0] + yy * e[1] + yz * e[2]), -(zx * e[0] + zy * e[1] + zz * e[2]), 1];
  }
  function mul(a, b) { const o = new Array(16);
    for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) { let s = 0; for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k]; o[c * 4 + r] = s; }
    return o; }

  function pack(run) {
    // -> Float32Array HOURS x 8: [demand, used_o, dump_o, paused_o, used_b, dump_b, paused_b, temp]
    const o = run.ours, b = run.baseline, w = run.weather, n = Math.min(HOURS, run.hours || HOURS);
    const f = new Float32Array(HOURS * 8);
    for (let i = 0; i < n; i++) {
      const k = i * 8;
      f[k] = w.demand_kwh[i]; f[k + 1] = o.heat_used_kwh[i]; f[k + 2] = o.dumped_kwh[i]; f[k + 3] = o.paused[i];
      f[k + 4] = b.heat_used_kwh[i]; f[k + 5] = b.dumped_kwh[i]; f[k + 6] = b.paused[i]; f[k + 7] = w.temp_c[i];
    }
    return f;
  }

  function create(canvas, opts) {
    opts = opts || {};
    const gl = canvas.getContext("webgl2", { antialias: true, premultipliedAlpha: false, alpha: false });
    if (!gl) return null;
    let helix, parts;
    try { helix = prog(gl, VS_HELIX, FS_HELIX); parts = prog(gl, VS_P, FS_P); }
    catch (e) { if (opts.onError) opts.onError(e); return null; }

    // static hour index
    const hourBuf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, hourBuf);
    gl.bufferData(gl.ARRAY_BUFFER, Float32Array.from({ length: HOURS }, (_, i) => i), gl.STATIC_DRAW);
    const bufA = gl.createBuffer(), bufB = gl.createBuffer();
    const vao = gl.createVertexArray();
    function bindRuns() {
      gl.bindVertexArray(vao);
      gl.bindBuffer(gl.ARRAY_BUFFER, hourBuf); gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 1, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ARRAY_BUFFER, bufA);
      gl.enableVertexAttribArray(1); gl.vertexAttribPointer(1, 4, gl.FLOAT, false, 32, 0);
      gl.enableVertexAttribArray(2); gl.vertexAttribPointer(2, 4, gl.FLOAT, false, 32, 16);
      gl.bindBuffer(gl.ARRAY_BUFFER, bufB);
      gl.enableVertexAttribArray(3); gl.vertexAttribPointer(3, 4, gl.FLOAT, false, 32, 0);
      gl.enableVertexAttribArray(4); gl.vertexAttribPointer(4, 4, gl.FLOAT, false, 32, 16);
      gl.bindVertexArray(null);
    }
    // particles (CPU-simulated, GPU-drawn)
    const pData = new Float32Array(POOL * 8), pVel = new Float32Array(POOL * 3), pTgt = new Float32Array(POOL * 3);
    const pKind = new Uint8Array(POOL); let pNext = 0;
    const pBuf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, pBuf); gl.bufferData(gl.ARRAY_BUFFER, pData.byteLength, gl.DYNAMIC_DRAW);
    const pVao = gl.createVertexArray(); gl.bindVertexArray(pVao);
    gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 4, gl.FLOAT, false, 32, 0);
    gl.enableVertexAttribArray(1); gl.vertexAttribPointer(1, 4, gl.FLOAT, false, 32, 16);
    gl.bindVertexArray(null);

    const S = { cur: null, prev: null, morph: 1, pol: 0, polT: 0, hour: 0, yaw: 0.6, pitch: 0.22, dist: 13,
      drag: null, auto: true, lastInput: -1e9, tmin: -6, tmax: 36, demMax: 11, camY: -3.5, raf: 0, last: performance.now(),
      spawnAcc: 0, dead: false };

    function helixPos(i, d) {
      const day = Math.floor(i / 24), hh = i % 24, ang = 2 * Math.PI * hh / 24 + day * 0.0172;
      const r = 1.6 + 2.6 * d / Math.max(1e-3, S.demMax), y = (day / 365) * 12 - 6 + hh / 24 * (12 / 365);
      return [Math.cos(ang) * r, y, Math.sin(ang) * r];
    }
    function spawn(kind, from, to, col, size, vel) {
      const i = pNext; pNext = (pNext + 1) % POOL; const k = i * 8;
      pData[k] = from[0]; pData[k + 1] = from[1]; pData[k + 2] = from[2]; pData[k + 3] = 0.0001;
      pData[k + 4] = col[0]; pData[k + 5] = col[1]; pData[k + 6] = col[2]; pData[k + 7] = size;
      pKind[i] = kind; pTgt[i * 3] = to[0]; pTgt[i * 3 + 1] = to[1]; pTgt[i * 3 + 2] = to[2];
      pVel[i * 3] = vel[0]; pVel[i * 3 + 1] = vel[1]; pVel[i * 3 + 2] = vel[2];
    }
    function stepParticles(dt, playing) {
      const run = S.cur; if (!run) return;
      const h = Math.max(0, Math.min(HOURS - 1, Math.floor(S.hour))), w = run.weather;
      const side = S.pol > 0.5 ? run.baseline : run.ours;
      const used = side.heat_used_kwh[h], dump = side.dumped_kwh[h];
      // emission: ~ particles per second scale with this hour's kWh (more heat -> denser stream)
      S.spawnAcc += dt * (used * 55 + dump * 90) * (playing ? 1 : 0.6);
      let guard = 0;
      while (S.spawnAcc >= 1 && guard++ < 400) {
        S.spawnAcc -= 1;
        const jitter = Math.floor(Math.random() * 6) - 3, hj = Math.max(0, Math.min(HOURS - 1, h + jitter));
        const to = helixPos(hj, w.demand_kwh[hj]);
        const coreY = to[1] + (Math.random() - 0.5) * 0.05;
        if (Math.random() * (used + dump) < used) {
          spawn(0, [(Math.random() - .5) * .12, coreY, (Math.random() - .5) * .12], to, [1.0, 0.52, 0.12], 7 + Math.random() * 6, [0, 0, 0]);
        } else {
          const out = [to[0] * 0.35, 0.25 + Math.random() * 0.5, to[2] * 0.35];
          spawn(1, to, to, [0.95, 0.16, 0.24], 6 + Math.random() * 6, [out[0] + (Math.random() - .5) * .3, out[1], out[2] + (Math.random() - .5) * .3]);
        }
      }
      for (let i = 0; i < POOL; i++) {
        const k = i * 8; let l = pData[k + 3]; if (l <= 0) continue;
        l += dt * (pKind[i] === 0 ? 0.9 : 0.55);
        if (l >= 1) { pData[k + 3] = 0; continue; }
        pData[k + 3] = l;
        if (pKind[i] === 0) { // flow: ease from core to its helix hour along a slight arc
          const e = 1 - Math.pow(1 - l, 3), sx = pData[k], sz = pData[k + 2];
          pData[k] = sx + (pTgt[i * 3] - sx) * Math.min(1, e * dt * 9);
          pData[k + 2] = sz + (pTgt[i * 3 + 2] - sz) * Math.min(1, e * dt * 9);
          pData[k + 1] += (pTgt[i * 3 + 1] - pData[k + 1]) * Math.min(1, dt * 6) + Math.sin(l * Math.PI) * dt * 0.15;
        } else { // spark: fly outward and up, slowing
          pData[k] += pVel[i * 3] * dt; pData[k + 1] += pVel[i * 3 + 1] * dt; pData[k + 2] += pVel[i * 3 + 2] * dt;
          pVel[i * 3] *= 0.985; pVel[i * 3 + 1] *= 0.985; pVel[i * 3 + 2] *= 0.985;
        }
      }
    }

    // input: orbit (drag), zoom (wheel), auto-rotate resumes after 4 s idle
    const onDown = (e) => { S.drag = [e.clientX, e.clientY, S.yaw, S.pitch]; S.lastInput = performance.now(); canvas.setPointerCapture && canvas.setPointerCapture(e.pointerId); };
    const onMove = (e) => { if (!S.drag) return; S.yaw = S.drag[2] + (e.clientX - S.drag[0]) * 0.006;
      S.pitch = Math.max(-1.2, Math.min(1.35, S.drag[3] + (e.clientY - S.drag[1]) * 0.005)); S.lastInput = performance.now(); };
    const onUp = () => { S.drag = null; };
    const onWheel = (e) => { e.preventDefault(); S.dist = Math.max(4, Math.min(30, S.dist * Math.exp(e.deltaY * 0.001))); S.lastInput = performance.now(); };
    canvas.addEventListener("pointerdown", onDown); addEventListener("pointermove", onMove); addEventListener("pointerup", onUp);
    canvas.addEventListener("wheel", onWheel, { passive: false });

    function frame(now) {
      if (S.dead) return;
      S.raf = requestAnimationFrame(frame);
      const dt = Math.min(0.05, (now - S.last) / 1000); S.last = now;
      const dpr = Math.min(2, devicePixelRatio || 1);
      const W = Math.max(1, Math.round(canvas.clientWidth * dpr)), H = Math.max(1, Math.round(canvas.clientHeight * dpr));
      if (canvas.width !== W || canvas.height !== H) { canvas.width = W; canvas.height = H; }
      gl.viewport(0, 0, W, H);
      gl.clearColor(BG[0], BG[1], BG[2], 1); gl.clear(gl.COLOR_BUFFER_BIT);
      if (!S.cur) return;
      S.morph = Math.min(1, S.morph + dt * 1.6);
      S.pol += (S.polT - S.pol) * Math.min(1, dt * 4);
      if (!S.drag && now - S.lastInput > 4000) S.yaw += dt * 0.12;
      const tgtY = ((S.hour / HOURS) * 12 - 6) * 0.2;  // lean towards the playhead, keep the whole year in frame
      S.camY += (tgtY - S.camY) * Math.min(1, dt * 2.5);
      const c = [0, S.camY, 0], e = [Math.cos(S.yaw) * Math.cos(S.pitch) * S.dist, S.camY + Math.sin(S.pitch) * S.dist, Math.sin(S.yaw) * Math.cos(S.pitch) * S.dist];
      const vp = mul(persp(0.8, W / H, 0.1, 100), lookAt(e, c));
      const morph = 1 - Math.pow(1 - S.morph, 3);

      gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE); gl.disable(gl.DEPTH_TEST);
      gl.useProgram(helix.p); const u = helix.u;
      gl.uniformMatrix4fv(u.uVP, false, vp);
      gl.uniform1f(u.uMorph, morph); gl.uniform1f(u.uPol, S.pol); gl.uniform1f(u.uHour, S.hour);
      gl.uniform1f(u.uTMin, S.tmin); gl.uniform1f(u.uTMax, S.tmax); gl.uniform1f(u.uDemMax, S.demMax);
      gl.uniform1f(u.uTime, now / 1000); gl.uniform1f(u.uPoint, 7 * dpr);
      gl.bindVertexArray(vao);
      gl.uniform1f(u.uLine, 1); gl.drawArrays(gl.LINE_STRIP, 0, HOURS);
      gl.uniform1f(u.uLine, 0); gl.drawArrays(gl.POINTS, 0, HOURS);
      gl.bindVertexArray(null);

      // the servers: a column of embers on the axis; its glow at the playhead = servers on / N this hour
      const run = S.cur, side = S.pol > 0.5 ? run.baseline : run.ours, hi = Math.floor(S.hour);
      const on = run.n > 0 ? side.servers_on[hi] / run.n : 0, coreY = (hi / HOURS) * 12 - 6;
      for (let j = 0; j < 6; j++) {
        if (Math.random() > 0.25 + 0.75 * on) continue;
        const i = pNext; pNext = (pNext + 1) % POOL; const k = i * 8;
        pData[k] = (Math.random() - .5) * .1; pData[k + 1] = coreY + (Math.random() - .5) * 0.4; pData[k + 2] = (Math.random() - .5) * .1;
        pData[k + 3] = 0.02; pData[k + 4] = 1.0; pData[k + 5] = 0.42 + 0.25 * on; pData[k + 6] = 0.1;
        pData[k + 7] = 4 + 10 * on * Math.random(); pKind[i] = 1; pVel[i * 3] = (Math.random() - .5) * .05;
        pVel[i * 3 + 1] = 0.08 + 0.3 * on * Math.random(); pVel[i * 3 + 2] = (Math.random() - .5) * .05;
      }
      stepParticles(dt, true);
      gl.useProgram(parts.p); gl.uniformMatrix4fv(parts.u.uVP, false, vp);
      gl.bindBuffer(gl.ARRAY_BUFFER, pBuf); gl.bufferSubData(gl.ARRAY_BUFFER, 0, pData);
      gl.bindVertexArray(pVao); gl.drawArrays(gl.POINTS, 0, POOL); gl.bindVertexArray(null);
    }
    S.raf = requestAnimationFrame(frame);

    return {
      setRun(run) {
        const f = pack(run);
        let tmin = Infinity, tmax = -Infinity, dmax = 0;
        for (let i = 0; i < HOURS; i++) { const t = f[i * 8 + 7]; if (t < tmin) tmin = t; if (t > tmax) tmax = t; if (f[i * 8] > dmax) dmax = f[i * 8]; }
        S.tmin = tmin; S.tmax = tmax; S.demMax = Math.max(1e-3, dmax);
        gl.bindBuffer(gl.ARRAY_BUFFER, bufA); gl.bufferData(gl.ARRAY_BUFFER, S.curF || f, gl.STATIC_DRAW);
        gl.bindBuffer(gl.ARRAY_BUFFER, bufB); gl.bufferData(gl.ARRAY_BUFFER, f, gl.STATIC_DRAW);
        S.curF = f; S.cur = run; S.morph = S.prevSet ? 0 : 1; S.prevSet = true;
        bindRuns();
      },
      setPolicy(p) { S.polT = p === "thermostat" || p === "baseline" ? 1 : 0; },
      setHour(h) { S.hour = Math.max(0, Math.min(HOURS - 1, +h || 0)); },
      state() { return { hour: S.hour, morph: S.morph, pol: S.pol, n: S.cur && S.cur.n }; },
      destroy() { S.dead = true; cancelAnimationFrame(S.raf); removeEventListener("pointermove", onMove); removeEventListener("pointerup", onUp); },
    };
  }

  window.DHYear3D = { create, pack, HOURS };
})();
