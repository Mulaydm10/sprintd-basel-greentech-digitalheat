# ADR-0001 - Layer the hackathon scaffold onto the existing comp-setup repo

- Status: Accepted (by scaffold run; Main Human may overturn)
- Date / deciders: 2026-11-21, hackathon-setup, pending Mulaydm10 review
- Related: Q-0005, `GOVERNANCE.md` audit table

## Context
The repo already had a comp-setup-style layout (src lanes, tasks 01-04, runs tracker, workflow.md, locked notes).
Creating parallel hackathon files would duplicate state.

## Decision (merge map)
| Hackathon-layer need | Reused existing file | New file |
|---|---|---|
| worklog | `workflow.md` (kept name, now timestamped) | - |
| experiments | `runs/experiment_tracker.md` (rows use `EXP-####`) | - (no `experiments/` dir) |
| governance | `GOVERNANCE.md` extended (audit rows, not-locked list, ID scheme) | - |
| pitch script | `docs/PITCH.md` folded into `DEMO.md`; PITCH.md is a pointer | `DEMO.md` |
| event facts | `README.md` Event section and the copies in `tasks/*` now defer to it | `COMPETITION.md` |
| onboarding | locked `notes/ai_onboarding_prompt.md` left as is (stale) | `notes/2026-11-21_onboarding_addendum.md` |
| work order | `tasks/01-04` untouched | `tasks/README.md` |
| lanes | `src/README.md` lane list kept | `AGENTS.md` concurrency rules |
Omitted on purpose: `ideas/` (idea chosen), `data/` pipeline additions, `evals/` (the deterministic test + one-command
reproducibility serve as the eval; revisit if an LLM agent becomes part of the build), `hardware/` (no actuation).

## Mismatches found
1. `pyproject.toml` `dashboard` extra lists streamlit/plotly; the chosen dashboard is FastAPI-served web UI. Left as-is (optional extra, nothing installed); `httpx` added to `dev` for FastAPI TestClient.
2. `data/assumptions.yaml` `expected_checks` says 27000 kWh; brief says verified 26,851. Kept 27000 as the rounded check, added the verified value beside it; tests must use a tolerance.
3. `price.chf_per_kwh` is null: still open (`Q-0002`).
4. Locked task READMEs and `notes/ai_onboarding_prompt.md` duplicate event facts; cannot be edited without Main Agent approval.
5. README lists team "Mulaydm10, Dhruv"; brief says solo (Dhruv). Treated as one human; confirm.
6. Host clock vs brief date (see `STATE.md`).

## Consequences
One home per fact; the stale locked copies are explicitly marked superseded rather than silently drifting.
