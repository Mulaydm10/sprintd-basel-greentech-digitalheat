# CLAUDE.md - cold-start entry point

> **Workers (Mac, teammates):** you never push to `main`. Run `git config core.hooksPath .githooks`, then `/bus:claim`. See `AGENTS-project.md`.


DigitalHeat (sprintd Basel GreenTech 2026): heat-aware scheduler + yearly economics for basement
servers, proven by a real process that pauses/resumes/migrates on a heat signal. Deadline-driven:
**event facts, times and rubric live ONLY in `COMPETITION.md`.** Do not restate them anywhere.

## Three-piece state pattern (do not conflate)
- `CLAUDE.md` / `AGENTS.md` / `AGENTS-project.md`: stable instructions. `AGENTS.md` = agent-bus protocol; `AGENTS-project.md` = **access rules (read first)** + project concurrency notes.
- `STATE.md`: live snapshot, **overwritten** every session. If STATE and the worklog disagree about NOW, STATE wins.
- `workflow.md`: append-only worklog (this repo's name for it). Dated AND timestamped entries (`## YYYY-MM-DD HH:MM CET - who`).

## Read order (cold agent)
`CLAUDE.md` -> `STATE.md` -> `VISION.md` -> `COMPETITION.md` -> `GOVERNANCE.md` -> `AGENTS-project.md` (ACCESS RULES) -> `AGENTS.md` -> tail of `workflow.md` -> `runs/experiment_tracker.md`.
Then your lane's `src/<pkg>/README.md` and the matching `tasks/0X_*/README.md`. Work order: `tasks/README.md`.
**New teammate Claude? Start with `ONBOARDING.md`** (setup → handshake issue → claim). Older notes in `notes/` are superseded by it.
If a doc is still `TODO(<owner>)`, say so; never invent a fact, price, rule or number.

## Governance in one paragraph
Main Agent / Main Human = Mulaydm10 (Dhruv) holds sole authority over LOCKED files (header
`> **LOCKED governing file.**`). Others propose via `workflow.md`. Every LOCKED edit is a row in
the `GOVERNANCE.md` audit table. `CLAUDE.md`, `AGENTS.md`, `STATE.md`, `DEMO.md` are deliberately NOT locked: their value is staying current.

## IDs (grep `-rn '<ID>' .` recovers the trace)
`ADR-####` decisions (`design/decisions/`) - `Q-####` open questions (`research/open_questions.md`) -
`EXP-####` experiments/measurements (`runs/experiment_tracker.md`) - `DEMO-####` demo scenarios (`DEMO.md`).
Task folders `tasks/01..04` keep their names; they are the work packages, referenced as `T01..T04`.

## Canonical commands (stack: Python, uv, FastAPI; deps declared in `pyproject.toml`)
```
uv sync --extra dev                  # once, human-approved (agents: do not install unprompted)
uv run pytest                        # must be green before any handoff
uv run python -m simulate_year       # yearly balance (stub until T03 lands)
uv run uvicorn live_agent.app:app --port 8710   # per-node agent (package installed by uv sync)
```
Whoever changes a command updates this block in the same change.

## Hard rules
1. Every pitch number traces to `data/assumptions.yaml` + a commit + an `EXP-####` row. No hard-coded assumptions in code.
2. `src/scheduler` is pure policy (no I/O); the simulator and live agent MUST both import it. Never fork the logic.
3. Stay in your lane (`src/<pkg>`) unless you hold a handoff; see `AGENTS.md`.
4. `DEMO.md` must stay runnable. A broken demo path outranks new features.
5. No data/weights/logs/secrets committed. Workers commit and push **only** to their `claim/<n>` branch and open a PR; only the design session (Omen) writes `main`.
6. Installing `requirements-dev.txt` / `uv sync --extra dev` is approved for setup. Anything else (models, large data) needs your human's OK.
7. Times: always CET with explicit zone; the host may run in another timezone.

## End-of-session checklist
1. Overwrite `STATE.md`. 2. Append a dated+timestamped `workflow.md` entry. 3. Append new `EXP-####` rows.
4. Log any LOCKED-file edit in the `GOVERNANCE.md` audit table. 5. Release your work claim.
