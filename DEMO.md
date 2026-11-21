# DEMO.md - judge-facing script (single source; replaces docs/PITCH.md)

NOT locked: must stay current. **Binding: once a path exists, this file stays runnable at all times;
fixing a broken demo outranks new features.** Retire scenarios by marking `superseded by DEMO-####`, never delete.
Pitch slot, length and event facts: `COMPETITION.md` (5 min incl. live demo + 3 min Q&A; case pitch Sun 22 Nov 09:00-11:30 CET).


## Critical path first
**#8 live_agent is still a stub** (`GET /status` only). DEMO-0003 (pause/resume a real process on the heat signal with the SAME `decide()`) is a case must-have and depends on it. The runner side is ready: `python -m jobs.runner` checkpoints, commits exactly once and exits cleanly on SIGTERM (#32). **I can take #8 now if you want**: a thin agent around `jobs.runner` plus a coordinator loop calling `decide()` on a 1-site state.

## Run-sheet (5 min, opens with key figures as COMPETITION.md requires)
| t | Segment | Scenario | Show | Status |
|---|---|---|---|---|
| 0:00–0:40 | Key figures | — | Dashboard "Key figures" + "Does it pay off?" from a real run (`python -m simulate_year --servers 4 --policy merit --slack-h 24 --load thermostat`). Say the computed `pays_off_conditions` line verbatim. | runnable (numbers move when #42/#37 lands, so re-run then) |
| 0:40–1:30 | January vs July | DEMO-0002 | Day replay: coldest January day (servers run, heat used, backup tops up) vs the July day with most dump (tank full). | runnable |
| 1:30–2:15 | Fair A/B | DEMO-0002b | Like-for-like table: thermostat vs always_on vs merit selling the same work. Point at coverage, dump, missed deadlines. | runnable; numbers wait for #42 |
| 2:15–3:30 | Real job paused & resumed | DEMO-0003 | One real process: heat signal "tank full" → `decide()` Holds → agent SIGTERMs runner (checkpoint) → signal "heat needed" → resumes at `next_chunk`, output log identical to an uninterrupted run. | **BLOCKED on #8** |
| 3:30–4:15 | Sovereignty + tamper | DEMO-0004 (new) | Dashboard trust panel: Frankfurt node asks with CH-BS → `region_mismatch`; tamper → `node_tampered`; chain verified against the signed head. Labelled MOCK. | runnable (dashboard) |
| 4:15–4:45 | Wow: migrate | DEMO-0001 | Job checkpoints on house A, resumes on eligible house B; ineligible house refused. | **BLOCKED on #8** (needs 2 agents) |
| 4:45–5:00 | Close | — | "One command reproduces every number": provenance panel (run id, assumptions hash, code commit). | runnable |

## Scenarios
**DEMO-0002 — January / July replay (runnable)**
- Pre: `python -m simulate_year --servers 4 --policy merit --slack-h 24 --load thermostat --ballast --force` (≈30 s on parth-hp). Then `PYTHONPATH=src python -m dashboard` (no DH_RUN_DIR: it uses the newest run) → http://127.0.0.1:8700
- Show: the "Day replay" cards (coldest January day by demand, July day with most dump). Hover any number: file:key · run · assumptions hash · commit.
- Reset: none (stateless). Fallback if the venue laptop is slow: pre-generate runs/ before the pitch.

**DEMO-0002b — like-for-like A/B (runnable)**
- Pre: also run `--policy thermostat` and `--policy always_on --load thermostat` at the same N.
- Show: the "Like-for-like" table. After #42: add paid vs ballast hours (I'll do that in the dashboard).

**DEMO-0003 — real process paused/resumed by decide() (BLOCKED on #8)**
- Pre: one machine; `python -m jobs.runner <type> --checkpoint ckpt.json --out out.log` (CPU stand-in by default, so no model download); the agent wraps it.
- Steps: 1) agent starts the runner, dashboard "Live nodes" shows running + chunk counter. 2) set signal tank_full → coordinator's `decide()` returns Hold → agent sends SIGTERM → runner commits the current chunk, exits 0, ckpt.json `next_chunk = k`. 3) set signal heat_needed → `decide()` Assigns → agent restarts the runner → continues at k. 4) after completion, `sha256 out.log` equals an uninterrupted reference run.
- Reset: delete ckpt.json/out.log, restart the agent. Target < 30 s.

**DEMO-0004 — sovereignty and tamper (runnable now in the dashboard; live once #8 calls `KeyBroker.release`)**
- Show: trust panel rows `release` (CH-BL), `deny region_mismatch` (DE-HE node claiming CH-BS), `tamper`, `deny node_tampered`; "Chain verified: yes".
- Say: "attestation here is a mock; the protocol is real crypto (X25519 + AES-GCM, signed audit head)".

**DEMO-0001 — migrate between houses (BLOCKED on #8)**: as in the current DEMO.md, with step 3 using the runner checkpoint (resume at `next_chunk`, not from zero).

## Honest-claims list for Q&A
- 50 ms/tick for 100k units holds on Omen (105 ms) / Mac, not on a 2017 i7 laptop (301 ms): say which machine.
- Admission uses a persistence forecast (repeat yesterday); in spring warming it can overstate capacity.
- Attestation is mock; physical attacks on CPU TEEs (TEE.Fail) are out of scope and stated.
- Merit vs thermostat numbers change after #42 (ballast fairness); never quote pre-#42 coverage.


## Previous draft
Superseded by the run-sheet above; see git history (DEMO.md before this commit).
