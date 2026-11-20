> **LOCKED governing file.** Do not edit in place. See `GOVERNANCE.md`.

# src/live_agent

Per-node FastAPI agent: heat signal in, SIGSTOP/SIGCONT or checkpoint/restart of the real process, migrate endpoint.

Conventions: type hints, no hard-coded assumptions (read `data/assumptions.yaml` via `common.config`), unit-test in `tests/`.
