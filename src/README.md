> **LOCKED governing file.** Do not edit in place. See `GOVERNANCE.md`.

# src layout

Packages (import by top-level name, `pythonpath = src`): `house_model`, `jobs`, `scheduler`, `simulate_year`, `live_agent`, `dashboard`, `common`.
Rule: `scheduler` is pure policy (no I/O, no process control) and is imported by BOTH `simulate_year` and `live_agent`.
Task mapping: 01 -> jobs, 02 -> scheduler, 03 -> house_model + simulate_year, 04 -> live_agent + dashboard.
