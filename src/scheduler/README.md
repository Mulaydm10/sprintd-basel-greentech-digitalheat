> **LOCKED governing file.** Do not edit in place. See `GOVERNANCE.md`.

# src/scheduler

Policy: given heat signal, tank, queue, deadlines, access classes, decide run/pause/migrate. Pure functions, no I/O.

Conventions: type hints, no hard-coded assumptions (read `data/assumptions.yaml` via `common.config`), unit-test in `tests/`.
