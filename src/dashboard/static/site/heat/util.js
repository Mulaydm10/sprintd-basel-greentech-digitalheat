/*
 * Phone Heat Test - shared helpers.
 * Written in ES5 on purpose so it runs on old Android WebViews and older Safari.
 */
(function (root) {
  'use strict';

  var PHT = root.PHT = root.PHT || {};

  // ---- time & animation frame (with fallbacks) ----
  PHT.now = (root.performance && typeof root.performance.now === 'function')
    ? function () { return root.performance.now(); }
    : function () { return Date.now(); };

  PHT.raf = typeof root.requestAnimationFrame === 'function'
    ? function (cb) { return root.requestAnimationFrame(cb); }
    : function (cb) { return root.setTimeout(function () { cb(PHT.now()); }, 16); };

  PHT.caf = typeof root.cancelAnimationFrame === 'function'
    ? function (id) { root.cancelAnimationFrame(id); }
    : function (id) { root.clearTimeout(id); };

  PHT.clamp = function (v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v); };

  PHT.errMsg = function (e) {
    if (!e) return 'unknown error';
    if (e.message) return e.message;
    try { return String(e); } catch (_) { return 'unknown error'; }
  };

  // ---- on-screen error/warning log: never fail silently ----
  var MAX_LINES = 40;
  var box = null;
  var lines = [];
  var lastMsg = '';
  var repeat = 1;

  function render() {
    if (!box) return;
    if (!lines.length) { box.style.display = 'none'; return; }
    box.style.display = 'block';
    box.textContent = lines.join('\n');
    box.scrollTop = box.scrollHeight;
  }

  /** level: 'error' (default) | 'warn' | 'info' */
  PHT.report = function (msg, level) {
    level = level || 'error';
    var prefix = level === 'error' ? 'ERROR ' : (level === 'warn' ? 'WARN  ' : 'INFO  ');
    try { (level === 'error' ? console.error : console.warn).call(console, msg); } catch (_) {}
    if (msg === lastMsg && lines.length) {
      repeat++;
      lines[lines.length - 1] = prefix + msg + '  (x' + repeat + ')';
    } else {
      lastMsg = msg;
      repeat = 1;
      var t = new Date();
      var hh = ('0' + t.getHours()).slice(-2), mm = ('0' + t.getMinutes()).slice(-2), ss = ('0' + t.getSeconds()).slice(-2);
      lines.push(prefix + hh + ':' + mm + ':' + ss + '  ' + msg);
      if (lines.length > MAX_LINES) lines.shift();
    }
    render();
  };

  PHT.initErrors = function (el) { box = el; render(); };

  /** Wrap a function so any exception is shown on screen instead of vanishing. */
  PHT.guard = function (label, fn) {
    return function () {
      try { return fn.apply(this, arguments); }
      catch (e) { PHT.report(label + ': ' + PHT.errMsg(e)); }
    };
  };

  root.onerror = function (message, source, lineno, colno, error) {
    PHT.report('Uncaught: ' + message + (lineno ? ' (line ' + lineno + ':' + colno + ')' : '') +
      (error && error.stack ? '\n' + error.stack : ''));
    return false;
  };

  if (root.addEventListener) {
    root.addEventListener('unhandledrejection', function (e) {
      PHT.report('Unhandled promise rejection: ' + PHT.errMsg(e && e.reason));
    });
  }
})(this);
