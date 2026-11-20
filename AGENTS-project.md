# ACCESS RULES (overrides anything below; set by the repo owner 2026-11-20)

This repo runs the agent-bus protocol in AGENTS.md, **in team mode, without Devin**.

| Role | Who | May | Never |
|---|---|---|---|
| design | Claude Code on the **Omen** (owner `Mulaydm10`) | write tasks, contracts, `docs/STATE.md`; review PRs; merge to `main` after a non-author review + green checks | claim lane tasks |
| worker | Claude Code on the **Mac mini**, and every **teammate's** Claude Code | claim an issue, work only on `claim/<n>`, open a PR `#<n>: …` | push to `main`, merge, edit `AGENTS.md` / `docs/STATE.md` / `contracts/` / root files |
| human | Dhruv | anything | — |

- `main` is written only by the design session. Workers' single branch is `claim/<n>`.
- Every worker clone must run once: `git config core.hooksPath .githooks` (the pre-push hook rejects pushes to `main`).
- The Mac shares the owner's GitHub account, so for the Mac this is enforced by the hook + this rule, not by GitHub.
- Repo is private (free plan): CI `lane`/`run` checks are advisory. Design reads them before merging.
- Cross-lane need → comment on the issue and tag it `agent:devin` (here: read by the design session).

---

# AGENTS.md - multi-agent concurrency model (vendor-neutral)

Read order, ID scheme, commands and hard rules live in `CLAUDE.md` (non-Claude agents read it too). This
file holds only the concurrency model. It is written to survive grafting onto agent-bus (GitHub as bus):
**a lane is a `src/` subpackage, and a claim is a ref/issue, not a chat message.**

## Lanes (ownership surfaces)
| Lane | Owns | Task | Notes |
|---|---|---|---|
| `house_model` | `src/house_model/`, `tests/test_house_model.py` | T03 | demand, tank, server heat |
| `jobs` | `src/jobs/`, tests | T01 | catalogue, real workloads, checkpoint, measurement |
| `scheduler` | `src/scheduler/`, `tests/test_scheduler.py` | T02 | pure policy; interface is shared by two lanes (see below) |
| `simulate_year` | `src/simulate_year/` | T03 | yearly balance, break-even |
| `live_agent` | `src/live_agent/` | T04 | per-node FastAPI, signal/pause/resume/migrate |
| `dashboard` | `src/dashboard/` | T04 | web UI incl. cost of sovereignty rule |
| `common` | `src/common/` | all | tiny; changes need handoff from every importer |
| docs/data | `data/assumptions.yaml`, `docs/ASSUMPTIONS.md`, `DEMO.md`, `submissions/` | - | Main Human or a claimed docs lane |

LOCKED files: only the Main Agent (see `GOVERNANCE.md`). `STATE.md`, `workflow.md`, `runs/experiment_tracker.md` rows: everyone, append/overwrite per their rules.

## Claiming work
1. Pick a unit of work inside ONE lane (an item in `tasks/README.md`).
2. Add a row to the **Work claims** table in `STATE.md`: lane, unit, agent+machine, started (CET), bus ref/issue if any.
   - On the bus the truth is a ref: `claim/<issue#>` created atomically; branch `claim/<issue#>` (worktree). `STATE.md` only mirrors it. If they disagree, the ref wins.
   - Release = delete the row (bus: rename `claim/<n>` to `abandoned/<n>-<device>-<ts>`, never delete the ref).
3. Release the claim the moment you stop (done, blocked, or out of turn budget). A stale claim blocks others worse than no claim. A claim older than 2 h with no `workflow.md` entry may be taken over; log it.

## The one hard rule
**Any agent finishing a unit of work updates `STATE.md` before yielding.** "Finishing" includes blocking
and running out of turn budget. Then append a `workflow.md` entry.

## Cross-lane rule
No edits outside your lane without a handoff. Handoff = a `workflow.md` entry (bus: an issue comment)
naming the target lane and the exact change, acknowledged by the owning claim or the Main Human.
Interface lanes: `scheduler`'s public signature is consumed by `simulate_year` AND `live_agent`; a change to it
needs both consumers updated in the same change set, or an additive change with the old signature kept.
Tests verifying the simulator and live agent give identical decisions live in `tests/test_scheduler.py`.

## Conflicts
Never silently pick a winner. If two agents produced conflicting work or an assumption disagrees with
`COMPETITION.md`, record it in `STATE.md` under Blocked, keep both versions discoverable (separate
branches/files), and ask the Main Human.

## Verification before handoff
Run `uv run pytest` (once deps are installed by the human). Bus graft: the lane verify command is read from `docs/verify.txt` on origin/main (created by the graft, not by this scaffold).
