# workflow.md (append-only)

Format: `## YYYY-MM-DD HH:MM CET - <who>` then bullets. Timestamped (hackathon history moves hourly). Never edit earlier entries. This is the worklog; `STATE.md` is the live snapshot and wins on what is true NOW.

## 2026-11-20 - comp-setup
- Scaffolded project from the comp-setup blueprint. Next: fill tasks/*/README.md, fetch weather, set electricity price in data/assumptions.yaml.

## 2026-11-21 HH:MM TODO(Dhruv) CET (host clock mismatch, see STATE.md) - hackathon-setup
- Layered the hackathon scaffold onto the comp-setup repo (merge map and mismatches: `design/decisions/ADR-0001-layering-hackathon-scaffold.md`).
- Added: CLAUDE.md, AGENTS.md, STATE.md, COMPETITION.md, VISION.md, DEMO.md (absorbs docs/PITCH.md), tasks/README.md, notes/judging_alignment.md, notes/glossary.md, notes/2026-11-21_onboarding_addendum.md, design/, research/.
- Modified: README.md, GOVERNANCE.md, docs/ASSUMPTIONS.md, docs/PITCH.md (now a pointer), data/assumptions.yaml (verified value), pyproject.toml (httpx in dev), submissions/README.md.
- PROPOSAL for Main Agent (not applied, files are LOCKED): replace `notes/ai_onboarding_prompt.md` with the addendum content; trim the duplicated "Context" blocks in `tasks/0*/README.md` to a link to `COMPETITION.md`.
- Not run: pytest (no installs or approvals; tests unverified).
