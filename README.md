# Hearthbeat: basement servers that heat the house

_Hearthbeat is our project for the DigitalHeat case (case partner: DigitalHeat). Earlier commits call the project DigitalHeat._

**sprintd Basel GreenTech 2026 · case "Useful Load ⇒ Useful Heat".** A heat-aware scheduler runs paid, interruptible AI jobs on servers in people's basements so that their waste heat covers the house's heat demand. The same `scheduler.decide()` drives a simulated Basel 2025 year (8,760 h) and real machines that pause, resume and move jobs between houses on the heat signal.

## Try it (live)
- **Website** (overview, problem, scheduler, live demo, economics, simulator, whole-year simulation, coordinator): https://dhruvs-mac-mini.tailaf7ebe.ts.net:8443
- **Coordinator API** (token required; `/healthz` is open): https://dhruvs-mac-mini.tailaf7ebe.ts.net

## Key results (reference house, Basel 2025; every number regenerates with `python -m tools.pitch` → `research/PITCH_NUMBERS.md`)
- With 4 servers our scheduler covers **57.9 %** of the house's heat and misses **0 %** of paid deadlines; a thermostat-led policy covers the same heat but misses **31 %**.
- Break-even incl. hardware: paid work must sell for **≥ 0.53 CHF/server-h** (thermostat: 0.74). At the assumed 0.50 it does **not** pay off yet; we say so.
- Recommended size (`python -m simulate_year.yearview`): **N = 3** servers (45 % coverage, ≤ 10 % of demand dumped, 0 % missed).
- Measured (EXP-0001): Whisper-small on an Apple M4 runs at 35× real time at 9.2 W.

## What is real and what is mocked
| Real | Mocked / simulated (stated on stage) |
|---|---|
| Scheduler, yearly simulation on real Open-Meteo Basel 2025 weather | Heat demand comes from the case's reference-house formula, not a real thermostat (`coordinator.sitesim`) |
| Coordinator with leases, checkpoints, exactly-once completion, SQLite state, auth, rate limits | Attestation is a **mock** (signed evidence); certification comes from the operator registry |
| Two real nodes (Mac mini M4, HP Omen) running jobs; a job migrates mid-run and finishes byte-identical | Fleet houses in the 3D view are illustrative; only the reference house is a graded number |
| AES-GCM envelopes, X25519 key wrap, hash-chained audit log, tamper → key denied | Prices for paid work and hardware capex are ASSUMED (`data/assumptions.yaml`) |

## Run it yourself (macOS or Linux, Python ≥ 3.11)
```bash
git clone https://github.com/Mulaydm10/sprintd-basel-greentech-digitalheat && cd sprintd-basel-greentech-digitalheat
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt     # or: uv sync --extra dev
PYTHONPATH=src .venv/bin/python -m pytest -q                               # ~1,190 tests
PYTHONPATH=src .venv/bin/python -m simulate_year --servers 4 --policy merit --slack-h 24   # one year → runs/
PYTHONPATH=src .venv/bin/python -m simulate_year.yearview --out runs/yearview             # N=1..8, ours vs thermostat (~7 s)
PYTHONPATH=src .venv/bin/python -m tools.pitch                             # regenerate every pitch number
PYTHONPATH=src .venv/bin/python -m dashboard                               # website on http://127.0.0.1:8700
```
Live system (one machine is enough; tokens are created locally, never committed):
```bash
PYTHONPATH=src .venv/bin/python -m coordinator --state runs/coordinator --make-tokens node-mac --make-site-tokens node-mac
python3 -c "import json,os;d=json.load(open('runs/coordinator/tokens.json'));os.makedirs('runs/coordinator/tok',exist_ok=True)
[open(f'runs/coordinator/tok/{r.replace(\":\",\"_\")}','w').write(t) for t,r in d.items()]"   # one file per role, e.g. tok/node_node-mac
PYTHONPATH=src .venv/bin/python -m coordinator --state runs/coordinator --register-node node-mac --certified --classes public,swiss-only,certified --site node-mac
PYTHONPATH=src .venv/bin/python -m coordinator --state runs/coordinator --port 8710
PYTHONPATH=src .venv/bin/python -m live_agent --coordinator http://127.0.0.1:8710 --node-id node-mac --token-file runs/coordinator/tok/node_node-mac
PYTHONPATH=src .venv/bin/python -m coordinator.sitesim --coordinator http://127.0.0.1:8710 --token-file runs/coordinator/tok/site_node-mac --site node-mac --replay coldest --loop
PYTHONPATH=src .venv/bin/python -m tools.e2e --help                        # one-command live end-to-end check (9 steps)
```

## Architecture
```
 customers ──(client API)──┐                    ┌── node agent (Mac)  ── jobs.runner (checkpointed)
 house owners ─(host API)──┼─► coordinator ◄────┼── node agent (Omen) ── jobs.runner
 operator ──(ops API, SSE)─┘   leases · scheduler.decide() · audit chain · key broker
 sitesim (heat signal per house) ──►│
 website (dashboard) ◄── yearview / balance / live status
```

## AI tools and templates used
- Built with **Claude Code** (Anthropic): one design session plus several worker sessions coordinating through GitHub issues (agent-bus protocol, `AGENTS.md`); every PR cross-reviewed and merged only after the full test suite passed.
- The website was designed by the team in **Claude Design** (exported verbatim to `design/frontend/`, served unchanged).
- No other template; libraries are listed in `pyproject.toml`.

## Cold start (humans and agents)
**Read order:** `CLAUDE.md` (or `AGENTS.md` if not Claude Code) -> `STATE.md` -> `VISION.md` -> `COMPETITION.md` -> `GOVERNANCE.md` -> `AGENTS.md` -> tail of `workflow.md` -> `runs/experiment_tracker.md`. Work order: `tasks/README.md`. Pitch script: `DEMO.md`. Paste-ready prompt: `notes/2026-11-21_onboarding_addendum.md`.
**End of session:** overwrite `STATE.md` - append a dated+timestamped `workflow.md` entry - append any new `EXP-####` row - log any LOCKED-file edit in the `GOVERNANCE.md` audit table - release your work claim.
If a doc is still `TODO(<owner>)`, say so rather than invent.

## Event and case
- Event, dates, all deadlines (CET), rubric weights, rules: **`COMPETITION.md` only** (not restated here).
- Case: DigitalHeat "Useful Load => Useful Heat". Servers in basements heat homes while running paid, interruptible AI jobs.

## Reference house (fixed for all teams)
- Weather: Basel 2025 hourly, Open-Meteo archive (lat 47.56, lon 7.59, Europe/Zurich, temperature_2m + shortwave_radiation).
- Heating demand per hour = max(0, 10 kW * (20 - T) / 25.6), only on heating days (local-day mean T < 12 C). Expect ~27,000 kWh/yr and 206 heating days.
- Hot water: 12 kWh/day all year. Tank: 35 kWh usable, lossless.
- Server: 1 kW electric -> 0.8 kW recoverable heat (19.2 kWh/day at full load).
- Electricity price: ElCom 2026, IWB Basel, category H4, flat CHF/kWh. Heat value = electricity price / 2.5.

## Must-haves
1. >=2 job types (e.g. embeddings, Whisper transcription) with runtime, energy, interruptible?, deadline. >=1 actually runs on the machine with measured runtime/energy and a stated scaling to the 1 kW server. Jobs/day with source.
2. Scheduler distributing/pausing/rescheduling jobs by heat demand + tank. The SAME scheduler code must pause/resume (or checkpoint/restart) a real running process on the heat signal.
3. Yearly balance per house: servers/house, % heat covered, heat dumped, utilisation = run-hours/(servers*8760), % missed deadlines, electricity cost, compute income, break-even CHF/server-hour = (elec cost - value of heat used)/server-hours sold. All assumptions visible. State when it does NOT pay off.

## Scoring
Weights: `COMPETITION.md`. Rubric -> artifact map: `notes/judging_alignment.md`.

## Resources
MLPerf Inference datacenter power results; Alibaba cluster-trace-gpu-v2020 (job durations/arrivals); cloud on-demand/spot prices; case PDF slides ("Sovereign AI", "slow down / pause & resume / distribute to eligible site, respect access and deadlines").

## Repo map
| Path | Purpose |
|---|---|
| `COMPETITION.md` | LOCKED event facts: single source of truth |
| `VISION.md` | LOCKED thesis, demo-time definition of working, non-goals |
| `STATE.md` | Live snapshot + work claims (overwritten each session) |
| `CLAUDE.md`, `AGENTS.md` | Cold-start entry; multi-agent lanes and claim rules |
| `DEMO.md` | Judge-facing 5-min script + DEMO-#### scenarios with reset (replaces PITCH) |
| `GOVERNANCE.md` | Locked/append-only rules, Main Agent role, audit log |
| `workflow.md` | Append-only timestamped worklog |
| `tasks/` | Task descriptions (LOCKED); `tasks/README.md` = deadline-ordered list |
| `design/`, `research/` | ADRs; open questions `Q-####`, prior art |
| `notes/judging_alignment.md`, `notes/glossary.md` | Rubric map; naming |
| `data/` | Raw weather CSV, prices, `assumptions.yaml` (data itself gitignored except assumptions) |
| `src/house_model/` | Reference house heat demand, tank, server heat |
| `src/jobs/` | Real workloads + checkpointing, job catalogue |
| `src/scheduler/` | Policy shared by simulator and live runner |
| `src/simulate_year/` | Yearly balance and break-even |
| `src/live_agent/` | Per-node FastAPI agent: pause / resume / migrate |
| `src/dashboard/` | Dashboard incl. cost of sovereignty rule |
| `docs/ASSUMPTIONS.md` | Visible assumptions (`docs/PITCH.md` is a pointer to `DEMO.md`) |
| `runs/experiment_tracker.md` | Append-only experiment rows |
| `tests/` | pytest |

Onboard any AI agent: paste `notes/2026-11-21_onboarding_addendum.md`.
