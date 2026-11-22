# Phone Heat Test

A hackathon demo for volunteers who have agreed to take part. They open the page, tap **Start**, and their phone heats up from as much CPU, GPU and memory work as it can handle. It stops after 300 s, or straight away when they tap **Stop**. Phones throttle themselves as they warm up. The page never lowers those safety limits; it only gives the phone work to do.

Works on **Android** (Chrome, Samsung Internet, Firefox, Edge, Opera, older WebViews) and on **iPhone/iPad** (Safari, Chrome). Every feature is detected first and has a fallback, so the page still runs on old or low-end phones.

## Quick start

- **On a phone:** open `dist/phone-heat-test.html`, a single file with everything inlined. Host it anywhere (GitHub Pages, Netlify, any static server, a claude.ai artifact) and open the link.
- **During development:** serve `src/` with any static server, e.g. `npx serve src` or `python3 -m http.server -d src`. Opening `src/index.html` straight from disk (`file://`) also works, because it uses plain scripts and Blob-URL workers rather than ES modules.
- **Rebuild the single file** after you edit `src/`: run `node build.js` (no dependencies).

The Screen Wake Lock API only works over **HTTPS** (or localhost). On plain HTTP the page switches to the video fallback described below.

## Project layout

```
src/
  index.html             markup + intro text
  styles.css             mobile layout, safe-area insets, black background
  js/util.js             on-screen error log, window.onerror, rAF/performance fallbacks
  js/gpu.js              WebGL load, adaptive controller, context-loss handling, Canvas 2D fallback
  js/cpu.js              one worker per core (Blob URL), 8 MB memory churn, main-thread fallback
  js/keepawake.js        Wake Lock + video fallback, fullscreen
  js/keepawake-media.js  tiny silent MP4/WebM clips (data URIs) for the video fallback
  js/app.js              device check, platform tips, start/stop, status, auto-stop
build.js                 inlines everything into dist/phone-heat-test.html
dist/phone-heat-test.html
```

## What it does

### GPU (main heat source)
- WebGL1 full-screen triangle; `powerPreference: 'high-performance'`.
- Heavy fragment shader: a loop with a constant bound that `break`s at uniform `n` and runs sin/cos/tan/atan/exp/sqrt/pow math on two `vec2`s each iteration. The output colours are bright, because a bright OLED screen draws more power.
- Renders at `devicePixelRatio × 1.5` (supersampling), clamped to `MAX_VIEWPORT_DIMS` and 4096.
- Additive blending (`gl.ONE, gl.ONE`) with up to 8 passes per frame, so tile-based GPUs can't skip the overdraw.
- **Adaptive controller** aiming for a ~70 ms frame time (it smooths the frame time with a moving average):
  - faster than 56 ms: go back to full resolution first, then +32 iterations (up to the shader's maximum), then +1 pass (max 8)
  - slower than 98 ms: −1 pass first, then −32 iterations (min 64), then lower the resolution (min 0.5 px per CSS px). This lets weak phones reach the target instead of stalling.
  - a single frame over 1 s halves the load straight away, so the GPU watchdog doesn't reset the phone.
- **Shader fallback ladder:** `highp`, then `mediump`, each tried with loop bounds 2048, 1024, 512 and 256 (some older Android GPU drivers reject large loops).
- **Context loss:** halves the load, waits for `webglcontextrestored`, then re-initialises. Two losses within 60 s also lower the resolution.
- **No WebGL** (disabled, blocklisted or very old): a Canvas 2D fallback of additive radial-gradient sprites, adapted the same way.

### CPU + memory
- One Web Worker per `navigator.hardwareConcurrency` (assumes 4 if unknown, capped at 32), created from a Blob URL.
- Each worker allocates a `Float64Array` of `1<<20` doubles (8 MB) and drops to smaller arrays on low-memory phones. It touches every page, then loops forever doing LCG random-index reads/writes mixed with `Math.sqrt/sin/cos`.
- Workers send a "ready" message and a 1 s heartbeat, so the status line shows how many are really alive.
- If workers can't be created, or none start within 4 s, the page falls back to main-thread busy loops (~10 ms of work every 16 ms).

### Keeping the screen on
- Screen Wake Lock API, re-requested on `visibilitychange` and retried up to 3 times after an unexpected release.
- **Fallback** (older Android browsers, iOS before 16.4, plain HTTP): a hidden, muted, looping, inline 2-second video. Playing video keeps the screen awake on those browsers.
- Fullscreen on Start (with the webkit prefix); iPhone Safari doesn't support element fullscreen, so it shows "n/a".

### Errors
- `window.onerror`, `unhandledrejection` and try/catch around every subsystem. Every failure or fallback shows up in the red box on screen, and repeated messages are combined into one line.
- A subsystem that fails never stops the others: if WebGL dies, for example, the CPU load keeps running.

### Stop
Terminates the workers, clears the busy-loop timers, cancels `requestAnimationFrame`, releases the wake lock or video, exits fullscreen and clears the canvas. It also stops on `pagehide`, and a backup `setTimeout` makes sure the 300 s auto-stop happens even if intervals are throttled.

## Tips shown to volunteers (detected per phone)
- **Android:** turn off Battery Saver / Power saving mode, which caps CPU and GPU clocks. Chrome or Samsung Internet give the most load.
- **iPhone:** turn off Low Power Mode. If the Wake Lock API is missing (iOS < 16.4), set Auto-Lock to Never.
- **In-app browsers** (Instagram, WhatsApp, Facebook, TikTok…): open the page in the real browser instead.

## Tuning
All limits are in `PHT.GPU_CONFIG` at the top of `src/js/gpu.js` (target band, step sizes, pass and iteration limits, supersampling, minimum resolution). The duration is `DURATION_MS` in `src/js/app.js`.

## Safety notes
- Phones throttle and, in the worst case, shut down on their own when they get too hot. Nothing here overrides that.
- Volunteers should hold the phone by its edges or put it down on a table, and can stop at any time.
- It's best not to run the test while the phone is charging in a hot place or sitting in direct sun.
