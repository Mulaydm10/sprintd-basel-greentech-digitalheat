# STATE (live snapshot - OVERWRITE every session)

If this file and `workflow.md` disagree about what is true NOW, this file wins; the worklog explains how we got here.
Deadlines and rubric: `COMPETITION.md` (not restated here beyond the next gate).

**Next gate:** DRAFT submission, Sat 21 Nov 15:00-15:30 CET. See `COMPETITION.md` for all times.
**Clock warning:** when this scaffold was written the host clock read Fri 20 Nov 21:34 CET (host appears to be in
a non-CET timezone, files stamped 21 Nov 02:02 local). The brief says "today is Sat 21 Nov". Recompute time remaining from the CET clock: `TZ=Europe/Zurich date`.
**Time remaining to next gate:** TODO(Dhruv) - recompute at session start.

## Done
- Repo scaffold (comp-setup style) and hackathon layer (CLAUDE/AGENTS/STATE/COMPETITION/VISION/DEMO, judging map, ADRs).
- Basel 2025 heat-demand formula verified at 26,851 kWh / 206 heating days (value from the brief; not yet re-derived in code here).

## In flight
- Nothing claimed. All `src/` packages are stubs (a few lines each).

## Blocked / open
- `Q-0001` ... `Q-0006` in `research/open_questions.md` (price value, draft format, rules, stack details).
- Mismatches flagged for Main Human, see `ADR-0001` and `workflow.md` 2026-11-21 entry (dashboard extra in pyproject; locked onboarding prompt is stale; task READMEs duplicate the case text).

## Next intended step
`tasks/README.md` item G0-1 (fix price + load weather), then G0-2..G0-5 toward the draft gate.

## Latest experiment
None. First row goes into `runs/experiment_tracker.md` as `EXP-0001` (real job measurement).

## Work claims
| Lane | Unit of work | Agent / machine | Started (CET) | Bus ref |
|---|---|---|---|---|
| (none) | | | | |

Last updated: 2026-11-21 (scaffold layering) by hackathon-setup. Test baseline: tests exist but were NOT run by the scaffold (no installs allowed).
