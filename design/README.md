> **LOCKED governing file.** Do not edit in place. See `GOVERNANCE.md`.

# design

Architecture in one view:

```
data/assumptions.yaml + weather CSV
        |
   house_model  (demand, tank, server heat)
        |                      jobs (catalogue, real workloads, checkpoint, measurement)
        v                          |
   scheduler  <-- pure policy, shared --+
     |                         |
 simulate_year            live_agent (per node, FastAPI: signal/pause/resume/migrate)
 (yearly balance)               |
        \                      /
              dashboard (FastAPI-served web UI: day replay, yearly table, cost of sovereignty rule)
```

Decisions are ADRs in `decisions/` (copy `ADR-0000-template.md`, next free number). ADRs are append-only:
supersede with a new ADR, never edit an accepted one. Open questions go to `research/open_questions.md` as `Q-####`.
