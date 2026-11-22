/*
 * Phone Heat Test - keep the screen on + fullscreen.
 *
 * 1. Screen Wake Lock API (Chrome/Samsung Internet on Android 84+, Safari iOS 16.4+, Firefox 126+).
 *    Re-requested on visibilitychange and once after an unexpected release.
 * 2. Fallback for phones without it: a tiny muted, looping, inline video
 *    (playing media keeps the screen awake on Android browsers and older iOS).
 * 3. Fullscreen with vendor prefixes. iPhone Safari has no element fullscreen: reported as "n/a".
 * Every refusal is caught and shown; nothing here can stop the load from running.
 */
(function (root) {
  'use strict';

  var PHT = root.PHT;
  var MAX_AUTO_RETRIES = 3;

  function KeepAwake() {
    this.active = false;
    this.lock = null;
    this.video = null;
    this.state = 'off';
    this.retries = 0;
    this.fullscreen = 'off';
    var self = this;
    this._onVis = function () {
      if (self.active && document.visibilityState === 'visible') {
        self.retries = 0;
        self._request();
      }
    };
    this._onFsChange = function () {
      self.fullscreen = KeepAwake.fullscreenElement() ? 'on' : (self.fullscreen === 'on' ? 'exited' : self.fullscreen);
    };
    document.addEventListener('visibilitychange', this._onVis);
    document.addEventListener('fullscreenchange', this._onFsChange);
    document.addEventListener('webkitfullscreenchange', this._onFsChange);
  }

  KeepAwake.hasWakeLock = function () {
    return !!(navigator.wakeLock && typeof navigator.wakeLock.request === 'function');
  };

  KeepAwake.fullscreenElement = function () {
    return document.fullscreenElement || document.webkitFullscreenElement || null;
  };

  KeepAwake.canFullscreen = function () {
    var el = document.documentElement;
    return !!(el.requestFullscreen || el.webkitRequestFullscreen);
  };

  /** Must be called from inside a tap handler (user gesture) for video + fullscreen to be allowed. */
  KeepAwake.prototype.start = function () {
    this.active = true;
    this.retries = 0;
    this._enterFullscreen();
    if (KeepAwake.hasWakeLock()) this._request();
    else this._startVideo('Wake Lock API not supported');
  };

  KeepAwake.prototype.stop = function () {
    this.active = false;
    if (this.lock) {
      var l = this.lock;
      this.lock = null;
      try { var r = l.release(); if (r && r.catch) r.catch(function () {}); } catch (_) {}
    }
    this._stopVideo();
    this.state = 'off';
    this._exitFullscreen();
  };

  // ---------- wake lock ----------
  KeepAwake.prototype._request = function () {
    if (!this.active || this.lock) return;
    if (!KeepAwake.hasWakeLock()) return;
    if (document.visibilityState && document.visibilityState !== 'visible') return;
    var self = this;
    try {
      navigator.wakeLock.request('screen').then(function (lock) {
        if (!self.active) { try { lock.release(); } catch (_) {} return; }
        self.lock = lock;
        self.state = 'wake lock on';
        self._stopVideo();
        lock.addEventListener('release', function () {
          if (self.lock !== lock) return;
          self.lock = null;
          if (!self.active) return;
          self.state = 'wake lock released';
          if (document.visibilityState === 'visible' && self.retries < MAX_AUTO_RETRIES) {
            self.retries++;
            root.setTimeout(function () { self._request(); }, 1000);
          }
        });
      }).catch(function (e) {
        self._startVideo('wake lock refused: ' + PHT.errMsg(e));
      });
    } catch (e) {
      this._startVideo('wake lock error: ' + PHT.errMsg(e));
    }
  };

  // ---------- video fallback ----------
  KeepAwake.prototype._startVideo = function (why) {
    if (!this.active || this.video) return;
    var media = PHT.KEEPAWAKE_MEDIA;
    if (!media) { this.state = 'unavailable'; PHT.report('Keep-screen-on unavailable (' + why + '). Turn off auto-lock manually.', 'warn'); return; }
    var self = this;
    try {
      var v = document.createElement('video');
      v.setAttribute('playsinline', '');
      v.setAttribute('webkit-playsinline', '');
      v.setAttribute('muted', '');
      v.setAttribute('loop', '');
      v.setAttribute('aria-hidden', 'true');
      v.muted = true;
      v.loop = true;
      v.playsInline = true;
      v.style.cssText = 'position:fixed;left:0;bottom:0;width:2px;height:2px;opacity:0.01;pointer-events:none;z-index:-1;';
      var canWebm = v.canPlayType && v.canPlayType('video/webm; codecs="vp8"');
      var s1 = document.createElement('source');
      var s2 = document.createElement('source');
      if (canWebm) { s1.src = media.webm; s1.type = 'video/webm'; s2.src = media.mp4; s2.type = 'video/mp4'; }
      else { s1.src = media.mp4; s1.type = 'video/mp4'; s2.src = media.webm; s2.type = 'video/webm'; }
      v.appendChild(s1);
      v.appendChild(s2);
      document.body.appendChild(v);
      this.video = v;
      var p = v.play();
      this.state = 'video fallback';
      PHT.report('Using video keep-awake fallback (' + why + ').', 'info');
      if (p && p.catch) {
        p.catch(function (e) {
          self.state = 'unavailable';
          PHT.report('Keep-screen-on fallback refused (' + PHT.errMsg(e) + '). Turn off auto-lock manually.', 'warn');
        });
      }
    } catch (e) {
      this.state = 'unavailable';
      PHT.report('Keep-screen-on fallback failed (' + PHT.errMsg(e) + '). Turn off auto-lock manually.', 'warn');
    }
  };

  KeepAwake.prototype._stopVideo = function () {
    if (!this.video) return;
    try { this.video.pause(); } catch (_) {}
    try { this.video.removeAttribute('src'); while (this.video.firstChild) this.video.removeChild(this.video.firstChild); this.video.load(); } catch (_) {}
    try { if (this.video.parentNode) this.video.parentNode.removeChild(this.video); } catch (_) {}
    this.video = null;
  };

  // ---------- fullscreen ----------
  KeepAwake.prototype._enterFullscreen = function () {
    var self = this;
    try {
      var el = document.documentElement;
      var fn = el.requestFullscreen || el.webkitRequestFullscreen;
      if (!fn) { this.fullscreen = 'n/a on this browser'; return; }
      var r = fn.call(el, { navigationUI: 'hide' });
      if (r && r.then) {
        r.then(function () { self.fullscreen = 'on'; }, function (e) {
          self.fullscreen = 'refused';
          PHT.report('Fullscreen refused: ' + PHT.errMsg(e), 'warn');
        });
      } else {
        this.fullscreen = 'requested';
      }
    } catch (e) {
      this.fullscreen = 'refused';
      PHT.report('Fullscreen refused: ' + PHT.errMsg(e), 'warn');
    }
  };

  KeepAwake.prototype._exitFullscreen = function () {
    try {
      if (!KeepAwake.fullscreenElement()) { this.fullscreen = 'off'; return; }
      var fn = document.exitFullscreen || document.webkitExitFullscreen;
      var r = fn && fn.call(document);
      if (r && r.catch) r.catch(function () {});
      this.fullscreen = 'off';
    } catch (e) { PHT.report('Exit fullscreen: ' + PHT.errMsg(e), 'warn'); }
  };

  KeepAwake.prototype.statusText = function () {
    return this.state + ' | fullscreen ' + this.fullscreen;
  };

  PHT.KeepAwake = KeepAwake;
})(this);
