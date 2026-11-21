# Tailnet end-to-end results (design, 2026-11-21 06:24–06:31 CET+1, main a95483d)

Setup: coordinator on the Mac mini (127.0.0.1:8710 behind `tailscale serve` HTTPS, tailnet only), node agents on Mac (`node-mac`, certified) and Omen (`node-omen`, public + swiss-only), `coordinator.sitesim` feeding both sites' heat signals (coldest day / July, speed 60). Workload: cpu-hash runner (stand-in for Whisper; same checkpoint path).

| # | Test | Result |
|---|---|---|
| 1 | Job submitted → admitted → leased → key released → completed | ✅ |
| 2 | **Migration:** job runs on Omen; at 30% the Omen agent is `kill -9`'d; the Mac picks up from the last uploaded checkpoint (25%) and finishes | ✅ result sha256 `486eb640…bc88d` **byte-identical** to an uninterrupted local run; `done_chunks` 0–19 each once; `completed_by=node-mac` |
| 3 | **Coordinator `kill -9` mid-lease, 8 s down**, restarted | ✅ lease survived with a frozen timer (11.7 s → 8.8 s left); the node kept going; job completed; the Omen agent reconnected by itself via backoff |
| 4 | **Heat pause:** a running job, the site switches to July (demand 0.5 kW, tank 35) | ✅ paused with a final checkpoint within ~4 s, held while warm; January again → resumed from the checkpoint (25%) and completed |
| 5 | Certified job with only the non-certified Omen alive | ✅ refused at admission ("no eligible site") |
| 6 | Tamper `node-omen` | ✅ key denied: node_tampered; no work runs there; `audit_verifies: true` |

Findings: (a) runner orphan survives an agent crash (issue filed, correctness unaffected); (b) the Mac can't resolve its own MagicDNS name (local agent uses 127.0.0.1); (c) `--make-site-tokens` is a no-op when tokens.json already exists (sitesim uses the admin token for now).
