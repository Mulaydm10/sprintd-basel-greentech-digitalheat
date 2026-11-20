# sprintd Basel GreenTech 2026 - DigitalHeat

Scheduler + yearly economic model for heat-reuse AI servers (DigitalHeat case).
Team: Mulaydm10 / Dhruv (Main Agent and Main Human, solo) + AI agents on Omen and Mac. Compute: local machines (several act as "houses").

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

## Planned wow demo
Several machines act as houses. A real job (Whisper transcript / embedding batch) is checkpointed, migrated to another house and resumed mid-way. Sovereignty rule: jobs carry an access class (public / swiss-only / certified) and may only move to eligible sites; dashboard shows the cost of that rule.

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

## Quickstart
```bash
uv sync            # or: python3 -m venv .venv && pip install -e .[dev]
uv run pytest
uv run python -m simulate_year   # stub until implemented
```
Onboard any AI agent: paste `notes/2026-11-21_onboarding_addendum.md` (the older locked `notes/ai_onboarding_prompt.md` is stale).
