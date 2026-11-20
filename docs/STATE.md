# STATE.md — current shape of the project (written by design only, via `claim/state`)

## Purpose
DigitalHeat case, sprintd Basel GreenTech (20–22 Nov 2026): a heat-aware scheduler that runs interruptible AI jobs on basement servers so their heat covers a home's demand over a full year, with a transparent yearly balance (heat covered, dumped, utilisation, missed deadlines, break-even CHF/server-hour) and a live demo that pauses/resumes/migrates a real process on the heat signal. Draft Sat 21 Nov 15:00 CET; final submission Sun 22 Nov 08:30 CET. Design = Claude Code on the Omen (owner Mulaydm10); no Devin. Only design writes `main`; see AGENTS-project.md.

mode: team
attention: active
merge: human
design: Mulaydm10
<!-- design: <login>   set by design on join, via claim/state; absent = repo not live, workers report "no design node" -->
<!-- mode: solo | team.  attention: active | paused (workers' cross-repo pick order skips paused repos; design sessions do not wake).
     merge: human | auto-lane (auto-lane = you give up human code review of lane PRs for throughput; design sets auto-merge on green + approved claim PRs; refused unless main requires lane+run; design/* always human).
     CI reads these from the live tip of the base branch and workers from `main`, never from a PR head: a PR must not relax the enforcement it is judged by. -->

## Lanes

| lane | directory | purpose | contract |
|------|-----------|---------|----------|
| `lane:canary` | `canary/` | two standing issues: post-merge canary (permanent claim, draft PR) and pre-merge canary (transient claim per workflow PR) | — |
| `lane:src/dashboard` | `src/dashboard/` | homeowner/utility view: key figures, January/July day replay, live nodes | `contracts/src/dashboard.md` |
| `lane:src/live_agent` | `src/live_agent/` | per-machine FastAPI agent: runs a real job, pauses/resumes/checkpoints/migrates on scheduler commands | `contracts/src/live_agent.md` |
| `lane:src/simulate_year` | `src/simulate_year/` | 8,760-hour simulation using scheduler; outputs the yearly balance + break-even and sensitivity | `contracts/src/simulate_year.md` |
| `lane:src/scheduler` | `src/scheduler/` | pure policy: given hour state (demand, tank, queue, sites) → run/pause/migrate/dump decisions; shared by sim and live | `contracts/src/scheduler.md` |
| `lane:src/jobs` | `src/jobs/` | job catalogue (runtime, energy, interruptible, deadline, access class), real local workloads with measurement + checkpointing | `contracts/src/jobs.md` |
| `lane:src/house_model` | `src/house_model/` | reference house: Basel 2025 hourly weather → heat demand + hot water + 35 kWh tank model | `contracts/src/house_model.md` |
<!-- bootstrap.sh appends one row per lane you pass it; design edits after that. A lane may be a nested path (`src/01_ingest`); no lane may be a prefix of another. -->

## Verify environment
`docs/setup.sh` (design-owned; CI runs the copy on `main`; changing it needs a canary like any workflow change). Default: `python3` + `requirements-dev.txt`. Workers run the same script once per worktree.
<!-- change both this line and requirements-dev.txt / docs/verify.txt if the project is not Python -->

## Decisions
- Lock = `claim/<n>` ref via git refs API (201/422). Labels advisory; refs beat labels.
- Lane + per-lane verify (`docs/verify.txt`) are CI jobs in one workflow (`checks.yml`: lane → resolve → run).
- Reclaim renames to `abandoned/…`; resume only on green CI + passing verify.
- Worker id = device/session; sessions hold claims, machines don't. Worktree per claim.
- Contracts in `contracts/<lane>.md`, design-owned.

## Known gaps
- Branch protection (`lane` + `run` required, PR-only `main`) needs a public repo or GitHub Pro/org. Without it checks are advisory — see docs/SETUP.md.
- One GitHub account for all workers (solo mode) = one API rate bucket; GitHub App with per-device tokens before ~20 nodes.
- Actions minutes are one pool per repo; check quota before a team event.

## Log
- 2026-11-20: repo created from agent-bus-template; bootstrap run (mode=team).
