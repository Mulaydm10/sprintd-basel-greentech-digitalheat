/*
 * Phone Heat Test - GPU load.
 *
 * Primary path: WebGL1 full-screen triangle with a heavy, adaptive fragment shader,
 * additive blending and several passes per frame (defeats tile-based overdraw skipping).
 *
 * Robustness for "any phone":
 *  - context creation ladder (webgl -> experimental-webgl), then a Canvas 2D fallback
 *  - shader ladder: highp/mediump x loop bounds 2048/1024/512/256 (old drivers reject big loops)
 *  - adapts iterations, passes AND render resolution toward a ~70 ms frame time,
 *    so weak phones are never stuck at multi-second frames (which trigger GPU watchdog resets)
 *  - stall guard: a single >1 s frame halves the load immediately
 *  - context lost/restored: halves the load, re-initialises; repeated losses lower resolution
 */
(function (root) {
  'use strict';

  var PHT = root.PHT;

  var CFG = PHT.GPU_CONFIG = {
    targetLowMs: 56,        // faster than this -> add load
    targetHighMs: 98,       // slower than this -> remove load
    iterMin: 64,
    iterStep: 32,
    passMin: 1,
    passMax: 8,
    supersample: 1.5,       // render at devicePixelRatio x 1.5
    minCssScale: 0.5,       // never render below 0.5 px per CSS px
    scaleStep: 0.8,
    scaleCooldownMs: 1500,
    stallMs: 1000,          // one frame slower than this -> emergency halve
    ignoreGapMs: 5000,      // gaps longer than this = tab was in background, ignore
    maxDim: 4096,
    loopBounds: [2048, 1024, 512, 256],
    shapesMin: 20,
    shapesMax: 5000
  };

  var CONTEXT_ATTRS = {
    alpha: false,
    antialias: false,
    depth: false,
    stencil: false,
    premultipliedAlpha: false,
    preserveDrawingBuffer: false,
    powerPreference: 'high-performance',
    failIfMajorPerformanceCaveat: false
  };

  var VERTEX_SRC =
    'attribute vec2 a_pos;\n' +
    'void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }';

  function fragmentSource(precision, bound) {
    return [
      'precision ' + precision + ' float;',
      'uniform vec2 u_res;',
      'uniform float u_time;',
      'uniform float u_pass;',
      'uniform float u_gain;',
      'uniform int u_n;',
      'void main() {',
      '  vec2 uv = gl_FragCoord.xy / u_res;',
      '  vec2 p = uv * 2.0 - 1.0 + vec2(u_pass * 0.0137, u_pass * -0.0091);',
      '  vec2 q = vec2(0.3 + fract(u_time * 0.011) * 10.0 + u_pass, 0.5 - fract(u_time * 0.007) * 10.0);',
      '  float acc = 0.0;',
      '  for (int i = 0; i < ' + bound + '; i++) {',
      '    if (i >= u_n) break;',
      '    float fi = float(i) * 0.001;',
      '    p = vec2(sin(p.x * 1.7 + q.y) + cos(p.y * 1.3 - q.x + fi),',
      '             cos(p.x * 0.9 - q.y) - sin(p.y * 1.1 + q.x));',
      '    q = vec2(atan(p.y, p.x + 2.5) + tan(clamp(q.x * 0.3, -1.2, 1.2)),',
      '             sqrt(abs(p.x * q.y) + 0.01) + exp(-abs(q.y)));',
      '    acc += pow(abs(p.x * p.y) + 0.001, 0.5) * 0.01 + q.y * 0.002;',
      '  }',
      '  float h = fract(acc + uv.x * 0.35 + uv.y * 0.2 + u_time * 0.05);',
      '  vec3 col = 0.62 + 0.38 * cos(6.2831853 * (h + vec3(0.0, 0.33, 0.67)));',
      '  col = clamp(col + 0.15 * sin(vec3(p, q.x) * 3.0), 0.0, 1.0);',
      '  gl_FragColor = vec4(col * u_gain, 1.0);',
      '}'
    ].join('\n');
  }

  function cssSize() {
    var de = document.documentElement;
    return {
      w: root.innerWidth || (de && de.clientWidth) || 360,
      h: root.innerHeight || (de && de.clientHeight) || 640
    };
  }

  function GpuLoad(canvas) {
    this.canvas = canvas;
    this.gl = null;
    this.ctx2d = null;
    this.mode = 'none';           // 'webgl' | '2d' | 'none'
    this.running = false;
    this.ready = false;
    this.lost = false;
    this.prog = null;
    this.buf = null;
    this.loc = {};
    this.precision = '';
    this.iterMax = CFG.loopBounds[0];
    this.iters = CFG.iterMin;
    this.passes = CFG.passMin;
    this.shapes = CFG.shapesMin;
    this.maxVP = [CFG.maxDim, CFG.maxDim];
    this.maxScale = 1;
    this.scale = 1;
    this.lastScaleChange = 0;
    this.renderer = '';
    this.note = 'idle';
    this.lossTimes = [];
    this.rafId = 0;
    this.t0 = 0;
    this.resetTiming();

    var self = this;
    this._onFrame = function (ts) { self._frame(ts); };
    this._onLost = function (e) { self._contextLost(e); };
    this._onRestored = function () { self._contextRestored(); };
    this._attachListeners(canvas);
  }

  GpuLoad.prototype._attachListeners = function (canvas) {
    canvas.addEventListener('webglcontextlost', this._onLost, false);
    canvas.addEventListener('webglcontextrestored', this._onRestored, false);
  };

  GpuLoad.prototype.resetTiming = function () {
    this.lastTs = 0;
    this.ema = 0;
    this.fps = 0;
    this._fpsN = 0;
    this._fpsT0 = 0;
  };

  // ---------- context ----------
  GpuLoad.prototype._getContext = function () {
    if (this.gl) return this.gl;
    var names = ['webgl', 'experimental-webgl'];
    var gl = null;
    for (var i = 0; i < names.length && !gl; i++) {
      try { gl = this.canvas.getContext(names[i], CONTEXT_ATTRS); } catch (_) { gl = null; }
    }
    if (!gl) return null;
    this.gl = gl;
    try {
      var ext = gl.getExtension('WEBGL_debug_renderer_info');
      this.renderer = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
    } catch (_) {
      try { this.renderer = gl.getParameter(gl.RENDERER); } catch (__) { this.renderer = 'unknown'; }
    }
    return gl;
  };

  /** Lightweight check used for the device summary before Start. */
  GpuLoad.prototype.probe = function () {
    var gl = null;
    try { gl = this._getContext(); } catch (_) {}
    return { webgl: !!gl, renderer: this.renderer || '' };
  };

  GpuLoad.prototype._computeMaxScale = function () {
    var s = cssSize();
    var dpr = root.devicePixelRatio || 1;
    var want = dpr * CFG.supersample;
    var cap = Math.min(this.maxVP[0] / s.w, this.maxVP[1] / s.h);
    this.maxScale = Math.max(CFG.minCssScale, Math.min(want, cap));
  };

  GpuLoad.prototype._resize = function () {
    var s = cssSize();
    var w = Math.max(1, Math.floor(s.w * this.scale));
    var h = Math.max(1, Math.floor(s.h * this.scale));
    w = Math.min(w, this.maxVP[0]);
    h = Math.min(h, this.maxVP[1]);
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w;
      this.canvas.height = h;
    }
    if (this.mode === 'webgl' && this.gl && !this.gl.isContextLost()) this.gl.viewport(0, 0, w, h);
  };

  GpuLoad.prototype.onResize = function () {
    if (!this.running) return;
    this._computeMaxScale();
    if (this.scale > this.maxScale) this.scale = this.maxScale;
    this._resize();
  };

  // ---------- WebGL setup ----------
  GpuLoad.prototype._compile = function (type, src) {
    var gl = this.gl;
    var s = gl.createShader(type);
    if (!s) throw new Error('createShader returned null (context lost?)');
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
      var log = gl.getShaderInfoLog(s) || 'no log';
      gl.deleteShader(s);
      throw new Error(log);
    }
    return s;
  };

  GpuLoad.prototype._buildProgram = function (precision, bound) {
    var gl = this.gl;
    var vs = this._compile(gl.VERTEX_SHADER, VERTEX_SRC);
    var fs;
    try { fs = this._compile(gl.FRAGMENT_SHADER, fragmentSource(precision, bound)); }
    catch (e) { gl.deleteShader(vs); throw e; }
    var prog = gl.createProgram();
    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.bindAttribLocation(prog, 0, 'a_pos');
    gl.linkProgram(prog);
    gl.deleteShader(vs);
    gl.deleteShader(fs);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
      var log = gl.getProgramInfoLog(prog) || 'no log';
      gl.deleteProgram(prog);
      throw new Error('link: ' + log);
    }
    return prog;
  };

  GpuLoad.prototype._initWebGL = function () {
    var gl = this.gl;
    this.ready = false;
    if (gl.isContextLost()) { this.lost = true; this.note = 'context lost, waiting'; return; }

    if (this.prog) { try { gl.deleteProgram(this.prog); } catch (_) {} this.prog = null; }
    if (this.buf) { try { gl.deleteBuffer(this.buf); } catch (_) {} this.buf = null; }

    var precisions = [];
    try {
      var hp = gl.getShaderPrecisionFormat(gl.FRAGMENT_SHADER, gl.HIGH_FLOAT);
      if (hp && hp.precision > 0) precisions.push('highp');
    } catch (_) {}
    precisions.push('mediump');

    var prog = null, lastErr = '';
    for (var pi = 0; pi < precisions.length && !prog; pi++) {
      for (var bi = 0; bi < CFG.loopBounds.length && !prog; bi++) {
        try {
          prog = this._buildProgram(precisions[pi], CFG.loopBounds[bi]);
          this.precision = precisions[pi];
          this.iterMax = CFG.loopBounds[bi];
        } catch (e) {
          if (gl.isContextLost()) { this.lost = true; this.note = 'context lost during compile'; return; }
          lastErr = precisions[pi] + '/' + CFG.loopBounds[bi] + ': ' + PHT.errMsg(e);
        }
      }
    }
    if (!prog) throw new Error('No shader variant compiled. Last error: ' + lastErr);
    if (this.iterMax < CFG.loopBounds[0] || this.precision !== 'highp') {
      PHT.report('GPU driver limits: using ' + this.precision + ' with max ' + this.iterMax + ' iterations.', 'info');
    }

    this.prog = prog;
    gl.useProgram(prog);

    this.buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);

    this.loc = {
      res: gl.getUniformLocation(prog, 'u_res'),
      time: gl.getUniformLocation(prog, 'u_time'),
      pass: gl.getUniformLocation(prog, 'u_pass'),
      gain: gl.getUniformLocation(prog, 'u_gain'),
      n: gl.getUniformLocation(prog, 'u_n')
    };

    var vp = null;
    try { vp = gl.getParameter(gl.MAX_VIEWPORT_DIMS); } catch (_) {}
    this.maxVP = [
      Math.min(CFG.maxDim, vp && vp[0] ? vp[0] : CFG.maxDim),
      Math.min(CFG.maxDim, vp && vp[1] ? vp[1] : CFG.maxDim)
    ];

    gl.disable(gl.DEPTH_TEST);
    gl.disable(gl.CULL_FACE);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE);   // additive: every pass must really be shaded
    gl.clearColor(0, 0, 0, 1);

    this.iters = PHT.clamp(this.iters, CFG.iterMin, this.iterMax);
    this._computeMaxScale();
    this.scale = Math.min(this.scale || this.maxScale, this.maxScale);
    this._resize();

    this.lost = false;
    this.ready = true;
    this.note = this.precision;
  };

  // ---------- Canvas 2D fallback ----------
  GpuLoad.prototype._init2D = function () {
    if (this.gl) {
      // A canvas that ever had a WebGL context can't give a 2D one: swap in a fresh element.
      var fresh = document.createElement('canvas');
      fresh.id = this.canvas.id;
      fresh.className = this.canvas.className;
      this.canvas.parentNode.replaceChild(fresh, this.canvas);
      this.canvas = fresh;
      this.gl = null;
    }
    var ctx = this.canvas.getContext('2d');
    if (!ctx) throw new Error('Canvas 2D is not available either.');
    this.ctx2d = ctx;
    this.mode = '2d';
    this.maxVP = [CFG.maxDim, CFG.maxDim];
    this._computeMaxScale();
    this.scale = this.maxScale;
    this._resize();
    this.ready = true;
    this.note = 'Canvas 2D fallback';
  };

  // ---------- start / stop ----------
  GpuLoad.prototype.start = function () {
    if (this.running) return this.mode;
    this.running = true;
    this.iters = CFG.iterMin;
    this.passes = CFG.passMin;
    this.shapes = CFG.shapesMin;
    this.scale = 0;           // = max scale once known
    this.lossTimes = [];
    this.resetTiming();
    this.t0 = PHT.now();

    var ok = false;
    if (this.mode !== '2d') {
      try {
        if (this._getContext()) {
          this.mode = 'webgl';
          this._initWebGL();
          ok = true;
        } else {
          PHT.report('WebGL is not available on this browser/phone; using the Canvas 2D fallback (less heat).', 'warn');
        }
      } catch (e) {
        PHT.report('WebGL setup failed (' + PHT.errMsg(e) + '); using the Canvas 2D fallback.', 'warn');
      }
    }
    if (!ok) {
      try { this._init2D(); ok = true; }
      catch (e2) { PHT.report('GPU load unavailable: ' + PHT.errMsg(e2)); this.mode = 'none'; this.note = 'unavailable'; }
    }
    if (ok) this.rafId = PHT.raf(this._onFrame);
    return this.mode;
  };

  GpuLoad.prototype.stop = function () {
    this.running = false;
    if (this.rafId) { try { PHT.caf(this.rafId); } catch (_) {} this.rafId = 0; }
    try {
      if (this.mode === 'webgl' && this.gl && !this.gl.isContextLost()) {
        this.gl.clearColor(0, 0, 0, 1);
        this.gl.clear(this.gl.COLOR_BUFFER_BIT);
      } else if (this.mode === '2d' && this.ctx2d) {
        this.ctx2d.globalCompositeOperation = 'source-over';
        this.ctx2d.fillStyle = '#000';
        this.ctx2d.fillRect(0, 0, this.canvas.width, this.canvas.height);
      }
    } catch (e) { PHT.report('Clearing canvas: ' + PHT.errMsg(e), 'warn'); }
    this.resetTiming();
    this.note = 'stopped';
  };

  // ---------- frame loop ----------
  GpuLoad.prototype._frame = function (ts) {
    if (!this.running) return;
    this.rafId = PHT.raf(this._onFrame);
    try {
      if (!this.ready || this.lost) return;
      if (typeof ts !== 'number') ts = PHT.now();

      if (this.lastTs) {
        var dt = ts - this.lastTs;
        if (dt > CFG.ignoreGapMs) {
          this.ema = 0;                      // came back from background
        } else if (dt > CFG.stallMs) {
          this._emergencyDrop(ts);           // one terrible frame: back off hard
        } else if (dt > 0) {
          this.ema = this.ema ? this.ema * 0.7 + dt * 0.3 : dt;
          this._adapt(this.ema, ts);
        }
      }
      this.lastTs = ts;

      this._fpsN++;
      if (!this._fpsT0) this._fpsT0 = ts;
      if (ts - this._fpsT0 >= 1000) {
        this.fps = this._fpsN * 1000 / (ts - this._fpsT0);
        this._fpsN = 0;
        this._fpsT0 = ts;
      }

      var t = (PHT.now() - this.t0) / 1000;
      if (this.mode === 'webgl') this._drawGL(t);
      else if (this.mode === '2d') this._draw2D(t);
    } catch (e) {
      PHT.report('GPU frame: ' + PHT.errMsg(e));
    }
  };

  GpuLoad.prototype._drawGL = function (t) {
    var gl = this.gl, loc = this.loc;
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.uniform2f(loc.res, this.canvas.width, this.canvas.height);
    gl.uniform1f(loc.time, t);
    gl.uniform1i(loc.n, this.iters);
    gl.uniform1f(loc.gain, 1 / this.passes);
    for (var p = 0; p < this.passes; p++) {
      gl.uniform1f(loc.pass, p);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    }
  };

  GpuLoad.prototype._draw2D = function (t) {
    var c = this.ctx2d, w = this.canvas.width, h = this.canvas.height;
    c.globalCompositeOperation = 'source-over';
    c.fillStyle = '#000';
    c.fillRect(0, 0, w, h);
    c.globalCompositeOperation = 'lighter';
    var r = Math.max(w, h) * 0.18;
    for (var i = 0; i < this.shapes; i++) {
      var x = (Math.sin(i * 12.9898 + t * 0.7) * 0.5 + 0.5) * w;
      var y = (Math.cos(i * 78.233 + t * 0.5) * 0.5 + 0.5) * h;
      var hue = Math.floor((i * 37 + t * 40) % 360);
      var g = c.createRadialGradient(x, y, 0, x, y, r);
      g.addColorStop(0, 'hsla(' + hue + ',100%,60%,0.35)');
      g.addColorStop(1, 'hsla(' + hue + ',100%,50%,0)');
      c.fillStyle = g;
      c.fillRect(x - r, y - r, r * 2, r * 2);
    }
  };

  // ---------- adaptation ----------
  GpuLoad.prototype._setScale = function (s, ts) {
    s = PHT.clamp(s, CFG.minCssScale, this.maxScale);
    if (Math.abs(s - this.scale) < 1e-3) return false;
    this.scale = s;
    this.lastScaleChange = ts;
    this._resize();
    this.ema = 0;
    return true;
  };

  GpuLoad.prototype._adapt = function (dt, ts) {
    var cooled = ts - this.lastScaleChange > CFG.scaleCooldownMs;
    if (this.mode === '2d') {
      if (dt < CFG.targetLowMs) {
        if (this.scale < this.maxScale) { if (cooled) this._setScale(this.scale / CFG.scaleStep, ts); }
        else this.shapes = Math.min(CFG.shapesMax, Math.ceil(this.shapes * 1.08) + 4);
      } else if (dt > CFG.targetHighMs) {
        if (this.shapes > CFG.shapesMin) this.shapes = Math.max(CFG.shapesMin, Math.floor(this.shapes * 0.85));
        else if (cooled) this._setScale(this.scale * CFG.scaleStep, ts);
      }
      return;
    }
    if (dt < CFG.targetLowMs) {
      // Restore full resolution first, then iterations, then passes.
      if (this.scale < this.maxScale) { if (cooled) this._setScale(this.scale / CFG.scaleStep, ts); }
      else if (this.iters < this.iterMax) this.iters = Math.min(this.iterMax, this.iters + CFG.iterStep);
      else if (this.passes < CFG.passMax) this.passes++;
    } else if (dt > CFG.targetHighMs) {
      // Passes first, then iterations, then (weak phones) resolution.
      if (this.passes > CFG.passMin) this.passes--;
      else if (this.iters > CFG.iterMin) this.iters = Math.max(CFG.iterMin, this.iters - CFG.iterStep);
      else if (cooled) this._setScale(this.scale * CFG.scaleStep, ts);
    }
  };

  GpuLoad.prototype._emergencyDrop = function (ts) {
    this.ema = 0;
    if (this.mode === '2d') { this.shapes = Math.max(CFG.shapesMin, Math.floor(this.shapes / 2)); return; }
    if (this.passes > 1 || this.iters > CFG.iterMin) {
      this.passes = CFG.passMin;
      this.iters = Math.max(CFG.iterMin, Math.floor(this.iters / 2));
    } else {
      this._setScale(this.scale * 0.7, ts);
    }
  };

  // ---------- context loss ----------
  GpuLoad.prototype._contextLost = function (e) {
    if (e && e.preventDefault) e.preventDefault();   // allow restoration
    this.lost = true;
    this.ready = false;
    this.iters = Math.max(CFG.iterMin, Math.floor(this.iters / 2));
    this.passes = Math.max(CFG.passMin, Math.floor(this.passes / 2));
    var now = PHT.now();
    this.lossTimes.push(now);
    this.lossTimes = this.lossTimes.filter(function (t) { return now - t < 60000; });
    if (this.lossTimes.length >= 2 && this.scale) {
      this.scale = Math.max(CFG.minCssScale, this.scale * 0.75);
    }
    this.resetTiming();
    this.note = 'context lost, load halved';
    if (this.running) {
      PHT.report('GPU context lost (the phone reset the GPU). Load halved to ' + this.iters + ' iter x ' +
        this.passes + ' pass; waiting for the browser to restore it.', 'warn');
    }
  };

  GpuLoad.prototype._contextRestored = function () {
    this.lost = false;
    if (!this.running) { this.note = 'restored'; return; }
    try {
      this._initWebGL();
      this.resetTiming();
      PHT.report('GPU context restored; resuming at ' + this.iters + ' iter x ' + this.passes + ' pass.', 'info');
    } catch (e) {
      PHT.report('Re-initialising WebGL failed: ' + PHT.errMsg(e));
    }
  };

  // ---------- status ----------
  GpuLoad.prototype.loadText = function () {
    if (this.mode === 'webgl') {
      if (!this.ready) return '- (' + this.note + ')';
      return this.iters + '/' + this.iterMax + ' iter x ' + this.passes + ' pass' +
        (this.passes === 1 ? '' : 'es') + ' [' + this.precision + ']';
    }
    if (this.mode === '2d') return this.shapes + ' gradient sprites [Canvas 2D fallback]';
    return '- (' + this.note + ')';
  };

  GpuLoad.prototype.canvasText = function () {
    if (this.mode === 'none') return '-';
    var dpr = root.devicePixelRatio || 1;
    return this.canvas.width + ' x ' + this.canvas.height +
      (this.scale ? '  (' + (this.scale / dpr).toFixed(2) + 'x DPR, max ' + (this.maxScale / dpr).toFixed(2) + ')' : '');
  };

  PHT.GpuLoad = GpuLoad;
})(this);
