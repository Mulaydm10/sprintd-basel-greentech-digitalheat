# GOVERNANCE

## Roles
- **Main Agent / Main Human: Mulaydm10 (Dhruv).** Sole authority to edit LOCKED files. Others propose changes via `workflow.md`.
- Team: solo human + several AI agents (Omen, Mac). Concurrency rules: `AGENTS.md`.

## File classes
- **LOCKED**: opens with `> **LOCKED governing file.** Do not edit in place. See GOVERNANCE.md.` (backticks around the filename are an accepted variant; detect with `grep -rl "LOCKED governing file"`). Read, never edit. Changes = new dated addendum file, or Main Agent approval logged in the audit table. Locked set: `COMPETITION.md`, `VISION.md`, `design/README.md`, `tasks/*`, `notes/*` (except the files below), `src/**/README.md`, `tests/README.md`, `runs/README.md`.
- **Deliberately NOT locked** (their value is staying current; locking would defeat them): `CLAUDE.md`, `AGENTS.md`, `STATE.md`, `DEMO.md`, `README.md`, `notes/judging_alignment.md`, `notes/glossary.md`, `docs/`, `data/assumptions.yaml` (changes mirrored in `docs/ASSUMPTIONS.md` and logged in `workflow.md`).
- **Append-only**: `workflow.md`, `runs/experiment_tracker.md` rows, `research/*`, `design/decisions/` (supersede, never edit accepted), the audit log below. Never rewrite or delete earlier entries.
- **Free**: code under `src/` (inside your lane), `tests/`, `notebooks/`.
- Never commit data, weights, logs, secrets. Never `git push`, add remotes or commit without explicit Main Human instruction.

## Stable IDs
`ADR-####`, `Q-####`, `EXP-####`, `DEMO-####`. Defined once in `CLAUDE.md`; used in every log and table so `grep -rn '<ID>' .` finds the trace.

## Single source of truth
Event facts (dates, CET times, rubric weights, rules): `COMPETITION.md` only. Numbers: `data/assumptions.yaml`. A duplicate elsewhere is deleted and replaced by a link.

## Reproducibility rules (25 pts of scoring)
- Every number in the pitch traces to `data/assumptions.yaml` + a git commit + an `EXP-####` tracker row.
- Fixed seeds; assumptions are never hard-coded in code.

## Audit log (append-only)
| Date | Who | Change | Approved by |
|---|---|---|---|
| 2026-11-20 | comp-setup | Initial scaffold | Mulaydm10 |
| 2026-11-21 | hackathon-setup | Initial authorship of LOCKED `COMPETITION.md`, `VISION.md`, `design/README.md`, `tasks/README.md`, `notes/2026-11-21_onboarding_addendum.md` | pending Mulaydm10 review |
| 2026-11-21 | hackathon-setup | Edited (not locked) `GOVERNANCE.md` (added locked/unlocked lists, IDs, SSOT); no LOCKED file edited in place | pending Mulaydm10 review |
