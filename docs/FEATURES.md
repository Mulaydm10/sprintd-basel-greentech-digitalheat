# DigitalHeat: feature inventory (what exists, where, and why)

Living list of everything built, kept for the pitch, the video and later work. Updated by the design session.
Live site: https://dhruvs-mac-mini.tailaf7ebe.ts.net:8443 · coordinator API: https://dhruvs-mac-mini.tailaf7ebe.ts.net
(token-gated). Numbers below come from runs named in the text; never quote one that isn't in a run file.

## 1. Core engine
| Feature | Where | Issue/PR |
|---|---|---|
| Merit-order scheduler `decide()`: heat price per site, job bids, slack holding, tank-band hysteresis, eligibility (public / swiss-only / certified), ballast filler | `src/scheduler/` | #6, contract v2–v2.3 |
| Admission control: a job is accepted only if it can finish in time | `scheduler.admit` | #54/#59 |
| Yearly simulation of the reference house (Basel 2025, 8,760 h) + thermostat / always-on baselines | `src/simulate_year/sim.py` | #7 |
| yearview: N = 1..8 servers, ours vs like-for-like thermostat, sizing rule (recommended N = 3, ≤ 10 % dumped, 0 % missed) | `simulate_year/yearview.py` | #95/#98 |
| fleetview: a whole-city fleet (ASSUMED: 100–200 houses on real OSM residential buildings, 8-unit jobs) run by ONE real `decide()` per hour over all sites; thermostat on the same fleet + jobs | `simulate_year/fleetview.py`, `fleetview_schema.py` | #119/#121/#124/#125 |
| Pitch numbers regenerated with provenance | `python -m tools.pitch` → `research/PITCH_NUMBERS.md` | #50 |

## 2. Live deployment (Tailscale: Mac = coordinator + node, Omen = node)
| Feature | Where | Issue/PR |
|---|---|---|
| Coordinator: leases (15 s, renew 5 s), heartbeats, checkpoints, exactly-once content-addressed completion, SQLite state, lease timers frozen across restart | `src/coordinator/` | #8, v1–v1.2 |
| Security: bearer tokens by role, rate limit, body limits, slow-loris guard, operator registry for certification (never self-reported) | `coordinator/auth.py`, `registry.py` | R1–R5 red team |
| Node agent: leases, stop file, checkpoint upload, orphan watchdog | `src/live_agent/` | #67 |
| Site heat signal simulator (coldest / July / year replay, loop, scenario switch) | `coordinator.sitesim` | #76 |
| Trust: AES-GCM/X25519 envelopes, mock attestation (stated), key broker, hash-chained audit log, tamper → key denied | `src/trust/` | |
| Portal API: client (submit/track/cancel/result/receipt), host (site, nodes, pause/resume), ops (overview, drain/kill/tamper, scenario, audit), SSE + poll events, CORS | `src/portal/`, `coordinator/portal_store.py`, contract `contracts/src/portal.md` | #83–#93 |
| Pull the plug = drain + kill → job moves to the other node, byte-identical result | `/api/live/kill` | #97/#99 |

## 3. Website (Dhruv's design, served as-is + our pages in the same theme)
| Page | What | Issue/PR |
|---|---|---|
| 01–06 Overview, Problem, Scheduler, Live demo, Economics, Simulator | Dhruv's frontend, offline-vendored, wired to the backend | #91/#94 |
| 07 Year | Basel 2025 hour by hour, 1×/2×/4×/8×, N slider, ours vs thermostat, sizing verdict; views Map / Helix / Chart | #96, #100, #104, #105 |
| 07 · 3D Basel map | 20,601 OSM buildings + Rhine + streets (ODbL credited), reference house + fleet houses, servers in basements lit by state, coordinator hub, seasonal sun/snow, navigation controls, clickable buildings, estimates overlay, live node-mac / node-omen2, district hex heat layer | #109/#111, #112/#114, #115/#120 |
| 07 · algorithm on the map | job packets hub → house, house cost rings, waiting jobs, holds, decision text | #118/#123 |
| 07 · job telemetry below the map | city tiles, merit-order chart per hour, plain-words decision log, job table (click → map), year totals ours vs thermostat | #118 (design) |
| 07 · job connections + traceability (simple, calm) | arcs between houses sharing a job (≤ 30), light A → B when a job moves, click job → path ribbon through the year, ghost thermostat, story chips (coldest hour, widest job, first summer hold, most dumped), **trace card** (hour → house → why, class, all eligible ✓, deadline, run key + commit), eligibility outlines / 🔒, URL hash for an exact shareable moment, source tag on every number | #125 |
| 08 Client | sign in, catalogue, submit with admission result, live chunk progress over SSE, cancel, result + receipt | #102/#113 |
| 09 GPU Server | site, tank, nodes, watts, heat today/month, CHF value, 24 h history, pause/resume | #102/#113 |
| 10 Coordinator | fleet overview, nodes (drain/kill/tamper for admin), jobs, scenario switch, live events, audit verify | #103/#107 |

## 4. Verification
| Check | Command | Status |
|---|---|---|
| Full test suite | `PYTHONPATH=src .venv/bin/python -m pytest -q` | ~1,244 pass |
| Live end-to-end (9 steps: surface, roles, client, cancel, host, migrate, pause, certified, audit) | `python -m tools.e2e …` | 9/9 PASS on the public URLs |
| Browser E2E of pages 07–10 | `python -m tools.e2e --ui` | #117/#122 (opt-in) |
| Red team rounds R1–R5 (incl. live attack on the public URL) | `tests/redteam/` | all findings fixed |

## 5. Key results to quote (with source)
- Reference house, N = 4: 57.9 % heat covered, 0 % missed; thermostat 31 % missed; break-even ≥ 0.53 CHF/server-h incl. hardware (does not pay off at 0.50). `research/PITCH_NUMBERS.md`
- Recommended N = 3: 45.4 % covered, 9.8 % dumped, 0 % missed. `runs/yearview` (key dcac285…)
- City fleet, 100 houses (run c9ac768…, 1-unit jobs; superseded by the #125 rerun with 8-unit jobs): ours 0 % missed vs thermostat 25.8 %, 2.2× net CHF, same heat covered (~44 %), 9 % of demand dumped.
- EXP-0001: Whisper-small on the M4: 35× real time, 9.2 W.

## 5b. Wow moments (final pitch), runbook: docs/DEMO-RUNBOOK.md
| Feature | Where | Status |
|---|---|---|
| Wow #1 live transcription: phone client → Omen (Whisper) → STOP → Mac / Parth's HP (ElevenLabs, disclosed) continue, nothing lost | phone-client.html, phone-server.html, coordinator/transcribe.py, live_agent/transcriber.py | chain Omen→Mac→Parth→Mac→Omen passed live |
| E2E encryption, coordinator-blind (P-256 ECDH + HKDF + AES-GCM, phone WebCrypto ↔ node python) | phone-e2e.js, live_agent/e2e.py, contract live_transcribe.md v2 | live: server text empty, phone decrypts |
| Blockchain techniques: Ed25519-signed segments, hash-linked chain, Merkle receipt in the audit log, verified on the phone | contract v2.1 | live: links + sigs + root on every run |
| Wow #2 volunteer phone fleet: QR join (event code), cautions, 3 servers : 1 client, cap 20, server phones heat (phone-heat-test), STOP hands the job + progress to the next phone | dashboard/phones.py, phone-join.html, static/site/heat/ | real-browser flow + 6 live sim runs (up to 20 phones) passed; Mac red team: 4 bugs fixed |
| Big screen: 3D fleet forming around the coordinator, laptops live, QR, log | phone-fleet.js on 04 Live | live |
| One-command Mac stack | tools/demo/mac_stack.sh | done |

## 6. Open before the demo (must do)
- [ ] **Real phone test of live transcription**: phone-client.html on Dhruv's phone (client-demo token) → Start → speak → transcript appears from omen-gpu → STOP omen-gpu on phone-server.html (admin token) → laptop-2 (Parth's HP, ElevenLabs, disclosed as cloud) continues; no lost / doubled segment. Check the mic permission prompt.
- [x] Segment-boundary fix (#130, #136) merged; omen-gpu restarted on it.
- [x] laptop-2 running on Parth's HP (ElevenLabs).
- [ ] Wow #2 with real phones: 2-3 team phones join, one STOP, check heat + big screen.
- [ ] Reset the phone fleet right before the pitch (runbook step 4).
