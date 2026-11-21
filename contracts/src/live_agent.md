# contract: src/live_agent — v2 (2026-11-21)  (node agent; talks to src/coordinator v1)

`python -m live_agent --coordinator URL --node-id ID --token-file PATH [--site-id S] [--backend fake|mlx|faster-whisper|cpu-hash]`
Runs on each machine (Mac, Omen; Windows later). Pure client; no inbound ports.

Loop:
1. Register (with a mock attestation from `trust.attest`, evidence: node_id, region `CH-BS`, measurement, certified flag from config).
2. Heartbeat every 2 s in a background thread: measured watts (macOS `powermetrics` if a human-run sampler file is present, Linux RAPL/NVML if readable, else `null` with `watts_source: none`, never invented), current unit, progress.
3. Ask for a lease; on `{hold}` sleep the hinted seconds (backpressure, BOINC-style work-fetch stop).
4. On a unit: fetch the checkpoint if one exists; obtain the key only through `key_release` (denied → report and drop); run `jobs.runner` as a **subprocess** with `--checkpoint`; renew the lease every 5 s; upload the encrypted checkpoint after each chunk group (≤ every 10 s); on completion POST complete with chunk ids + result hash.
5. Pause = the coordinator stops renewing or returns hold → the agent requests a graceful stop (stop file, portable, #51), waits ≤ 5 s, then kills; uploads the final checkpoint if it got one.
6. A lapsed lease (410) → kill the subprocess immediately and discard local partial output (the other node owns it now).
7. Network errors: exponential backoff with jitter (cap 10 s); never busy-loop; never exit on a transient error.
Never runs anything except `jobs.runner`; never writes outside `runs/agent/<node_id>/`.

Tests: against an in-process coordinator (TestClient transport) with the `cpu-hash` backend: pause/resume, lease lapse → kill, checkpoint upload/resume on another agent instance, backoff on 5xx, key denied, Windows stop-file path (skip the signal parts on win32).
