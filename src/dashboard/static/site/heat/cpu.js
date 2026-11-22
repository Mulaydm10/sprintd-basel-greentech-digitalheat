/*
 * Phone Heat Test - CPU + memory load.
 *
 * One Web Worker per logical core (navigator.hardwareConcurrency), created from a Blob URL
 * so it works from file://, http(s):// and sandboxed hosts alike. Each worker allocates an
 * 8 MB Float64Array (falls back to smaller sizes on low-memory phones) and loops forever doing
 * LCG random-index reads/writes mixed with sqrt/sin/cos. Workers report "ready" and a 1 s
 * heartbeat so the UI shows how many are really running.
 *
 * If workers can't be created (no Worker/Blob support, CSP, crash) or none start within 4 s,
 * it falls back to main-thread busy loops (~10 ms of work every 16 ms).
 */
(function (root) {
  'use strict';

  var PHT = root.PHT;
  var MAX_THREADS = 32;
  var READY_TIMEOUT_MS = 4000;
  var BEAT_STALE_MS = 3500;

  /* This function is serialised with toString() and run inside each worker. Keep it self-contained. */
  function heatWorkerMain() {
    var N = 1 << 20;            // 1M doubles = 8 MB
    var a = null;
    while (!a && N >= (1 << 14)) {
      try { a = new Float64Array(N); } catch (e) { N = N >> 2; }
    }
    if (!a) { self.postMessage({ t: 'err', m: 'could not allocate memory' }); return; }
    var mask = N - 1;
    for (var i = 0; i < N; i++) a[i] = i * 0.5;   // touch every page so memory is really committed
    self.postMessage({ t: 'ready', bytes: N * 8 });

    var s = (Math.random() * 4294967296) >>> 0;
    var acc = 0;
    var last = Date.now();
    for (;;) {
      for (var k = 0; k < 200000; k++) {
        s = (Math.imul(s, 1664525) + 1013904223) >>> 0;   // LCG
        var idx = s & mask;
        var v = a[idx];
        var w = Math.sqrt(Math.abs(v) + k) + Math.sin(v) * Math.cos(acc);
        a[idx] = w;
        a[(idx ^ 0x5A5A5) & mask] += w * 1e-7;
        acc += w * 1e-9;
      }
      if (acc !== acc || acc > 1e12) acc = 0;     // keep NaN/overflow out
      var now = Date.now();
      if (now - last >= 1000) { last = now; self.postMessage({ t: 'beat', acc: acc }); }
    }
  }

  // Math.imul polyfill for very old engines (inlined into the worker source too).
  var IMUL_POLYFILL =
    'if(!Math.imul)Math.imul=function(a,b){var ah=(a>>>16)&0xffff,al=a&0xffff,bh=(b>>>16)&0xffff,bl=b&0xffff;' +
    'return((al*bl)+(((ah*bl+al*bh)<<16)>>>0)|0);};\n';

  function CpuLoad() {
    this.workers = [];
    this.beats = [];
    this.url = null;
    this.timers = [];
    this.readyTimer = null;
    this.mode = 'idle';
    this.requested = 0;
    this.ready = 0;
    this.failed = 0;
    this.bytes = 0;
    this.running = false;
  }

  CpuLoad.threadCount = function () {
    var n = parseInt(navigator.hardwareConcurrency, 10);
    if (!n || n < 1) n = 4;   // unknown (older Safari etc.): assume 4
    return PHT.clamp(n, 1, MAX_THREADS);
  };

  CpuLoad.prototype.start = function () {
    if (this.running) return;
    this.running = true;
    this.ready = 0;
    this.failed = 0;
    this.bytes = 0;
    this.requested = CpuLoad.threadCount();
    try {
      this._startWorkers();
    } catch (e) {
      PHT.report('Could not create Web Workers (' + PHT.errMsg(e) + '); using main-thread busy loops instead.', 'warn');
      this._terminateWorkers();
      this._startFallback();
    }
  };

  CpuLoad.prototype._startWorkers = function () {
    if (typeof root.Worker === 'undefined') throw new Error('Web Workers not supported');
    if (typeof root.Blob === 'undefined') throw new Error('Blob not supported');
    var URLc = root.URL || root.webkitURL;
    if (!URLc || !URLc.createObjectURL) throw new Error('Blob URLs not supported');

    var src = IMUL_POLYFILL + '(' + heatWorkerMain.toString() + ')();';
    this.url = URLc.createObjectURL(new root.Blob([src], { type: 'application/javascript' }));

    var self = this;
    for (var i = 0; i < this.requested; i++) {
      (function (idx) {
        var w = new root.Worker(self.url);
        self.beats[idx] = 0;
        w.onmessage = function (ev) {
          var d = ev.data || {};
          if (d.t === 'ready') { self.ready++; self.bytes += d.bytes || 0; self.beats[idx] = Date.now(); }
          else if (d.t === 'beat') { self.beats[idx] = Date.now(); }
          else if (d.t === 'err') { self.failed++; PHT.report('CPU worker ' + idx + ': ' + d.m, 'warn'); }
        };
        w.onerror = function (ev) {
          if (ev && ev.preventDefault) ev.preventDefault();
          self.failed++;
          PHT.report('CPU worker ' + idx + ' crashed: ' + ((ev && ev.message) || 'unknown error'), 'warn');
        };
        self.workers.push(w);
      })(i);
    }
    this.mode = 'workers';

    this.readyTimer = root.setTimeout(function () {
      self.readyTimer = null;
      if (!self.running || self.mode !== 'workers') return;
      if (self.ready === 0) {
        PHT.report('No CPU worker started within ' + (READY_TIMEOUT_MS / 1000) + ' s; switching to main-thread busy loops.', 'warn');
        self._terminateWorkers();
        self._startFallback();
      } else if (self.ready < self.requested) {
        PHT.report('Only ' + self.ready + ' of ' + self.requested + ' CPU workers started.', 'warn');
      }
    }, READY_TIMEOUT_MS);
  };

  CpuLoad.prototype._startFallback = function () {
    var arr = null, N = 1 << 20;
    while (!arr && N >= (1 << 14)) { try { arr = new Float64Array(N); } catch (_) { N >>= 2; } }
    if (!arr) arr = new Array(4096);
    var mask = arr.length - 1;
    var s = 12345, acc = 0;
    var imul = Math.imul || function (a, b) {
      var ah = (a >>> 16) & 0xffff, al = a & 0xffff, bh = (b >>> 16) & 0xffff, bl = b & 0xffff;
      return ((al * bl) + (((ah * bl + al * bh) << 16) >>> 0) | 0);
    };
    var t = root.setInterval(function () {
      var end = PHT.now() + 10;
      while (PHT.now() < end) {
        for (var k = 0; k < 2000; k++) {
          s = (imul(s, 1664525) + 1013904223) >>> 0;
          var idx = s & mask;
          var v = arr[idx] || 0;
          arr[idx] = Math.sqrt(Math.abs(v) + k) + Math.sin(v) * Math.cos(acc);
          acc += arr[idx] * 1e-9;
        }
        if (acc !== acc) acc = 0;
      }
    }, 16);
    this.timers.push(t);
    this.mode = 'main-thread fallback';
    this.bytes = arr.length * 8;
    this.ready = 1;
  };

  CpuLoad.prototype._terminateWorkers = function () {
    for (var i = 0; i < this.workers.length; i++) {
      try { this.workers[i].terminate(); } catch (_) {}
    }
    this.workers = [];
    this.beats = [];
    if (this.url) {
      try { (root.URL || root.webkitURL).revokeObjectURL(this.url); } catch (_) {}
      this.url = null;
    }
  };

  CpuLoad.prototype.stop = function () {
    this.running = false;
    if (this.readyTimer) { root.clearTimeout(this.readyTimer); this.readyTimer = null; }
    this._terminateWorkers();
    for (var i = 0; i < this.timers.length; i++) root.clearInterval(this.timers[i]);
    this.timers = [];
    this.mode = 'idle';
    this.ready = 0;
    this.bytes = 0;
  };

  CpuLoad.prototype.alive = function () {
    if (this.mode !== 'workers') return this.mode === 'idle' ? 0 : 1;
    var now = Date.now(), n = 0;
    for (var i = 0; i < this.beats.length; i++) if (this.beats[i] && now - this.beats[i] < BEAT_STALE_MS) n++;
    return n;
  };

  CpuLoad.prototype.statusText = function () {
    var mb = (this.bytes / 1048576).toFixed(0) + ' MB';
    if (this.mode === 'workers') {
      return this.alive() + '/' + this.requested + ' worker threads alive, ' + mb;
    }
    if (this.mode === 'main-thread fallback') return '1 thread (main-thread fallback), ' + mb;
    return '0 threads (idle)';
  };

  PHT.CpuLoad = CpuLoad;
})(this);
