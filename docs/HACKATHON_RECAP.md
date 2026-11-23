# Hearthbeat: hackathon recap

**Event:** sprintd Basel GreenTech 2026, case "Useful Load ⇒ Useful Heat" (case partner: DigitalHeat).
**Result:** 4th place. **Pitch:** Sun 22 Nov 2026, 5 minutes, driven from the website (script: `design/PITCH_SCRIPT_5MIN.md`).

## What we shipped
| Part | Where |
|---|---|
| A scheduler that puts a price on each house's heat every hour (`scheduler.decide()`); the same code drives the simulated year and the real machines | `src/scheduler`, `src/simulate_year` |
| A whole year of Basel 2025 weather (8,760 hours), for every fleet size, compared with a thermostat-led policy | `simulate_year.yearview`, `fleetview` |
| A coordinator that hands out work: leases, checkpoints, exactly-once completion, a hash-chained audit log, signed receipts | `src/coordinator` |
| Live transcription with end-to-end encryption: the phone encrypts its audio (P-256 + AES-GCM, using the browser's built-in crypto), each node signs its segment (Ed25519), segments are hash-linked, and a Merkle root goes into the audit log | `src/live_agent`, `static/site/phone-*.{html,js}` |
| Volunteer phone fleet: join by QR, 3 servers to 1 client, at most 20 phones online at once, 180 steps of work per job, STOP passes the job on | `src/dashboard/phones.py`, `phone-join.html`, `phone-fleet.js` |
| Website: 01–07 pages (including a 3D map of Basel and a whole-year view) | `src/dashboard/static/site`, `site_build.py` |

## Pitch day in numbers (from the server logs)
- The website and the coordinator ran through the pitch with no crash or restart (about 25,000 requests).
- 42 phones joined (27 servers, 15 clients); 22 jobs finished, 18 of them moved between phones mid-job. No progress was lost.
- The errors in the logs were all limits doing their job: "too many requests" on Submit (the 2-jobs-per-client cap), "you no longer hold this job" on progress after a hand-off, and the public page being refused the admin controls.

## Lessons
- **Rehearse on the presenting laptop, on the venue network.** The server side held up, but there was a problem on screen during the pitch, and the 3D pages were heavy on the 7 GB Omen.
- **Phones on venue Wi-Fi drop out**, so ask volunteers to use mobile data.
- Keep one demo path that needs nothing live: the recorded video and the Year page.

## Bringing it back
1. Mac: `tools/demo/mac_stack.sh start`.
2. Turn the Tailscale Funnel back on: the coordinator (port 8710) on `:443` and the website (port 8720) on `:8443`.
3. Omen: `~/digitalheat-omen-agent.sh start` and `~/digitalheat-omen-agent.sh gpu-start`.
4. Smoke test: `docs/DEMO-RUNBOOK.md`, step 5. It should report 9 passes.

Tokens are kept on the machines only and are never committed. **Before going live again, rotate every node token.** One (laptop-2's) was posted in a public issue comment.

## Team setup
We worked through an agent-bus: GitHub issues are the task board, and workers claim tasks by creating branches. Workers: the Mac mini (does the builds and hosts the system), the HP Omen (coordinates, design work, Whisper transcription node) and Parth's HP (`laptop-2`, an ElevenLabs transcription node).
