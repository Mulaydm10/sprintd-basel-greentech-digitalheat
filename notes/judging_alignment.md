# Judging alignment (rubric criterion -> artifact -> status)

NOT locked (living). Weights are defined in `COMPETITION.md`; not restated here. A criterion with no row, or a
row with no artifact, is a gap to close BEFORE submission. Status: `gap` | `partial` | `proven`.

| Rubric criterion | What judges look for | Artifact that proves it | Task | Status |
|---|---|---|---|---|
| Transparency & reproducibility | all assumptions visible; one command regenerates numbers | `data/assumptions.yaml`, `docs/ASSUMPTIONS.md`, `uv run python -m simulate_year`, `runs/experiment_tracker.md` rows, assumptions page in dashboard, commit hash on submission | T03 (+ all) | gap: price unset (`Q-0002`), simulator is a stub |
| Feasibility | a real job really measured on real hardware, scaled to the 1 kW server | `EXP-0001` measurement, `src/jobs/` catalogue, DEMO-0003 on a real process | T01, T04 | gap |
| Scheduling quality & impact - heat covered vs dumped (primary) | yearly heat covered >= dumped | yearly balance table; January/July day replay (DEMO-0002) | T02, T03 | gap |
| Scheduling quality & impact - utilisation, missed deadlines (secondary) | utilisation and % missed deadlines reported | same table; scheduler tests | T02, T03 | gap |
| Must-have: same scheduler code controls a real process | pause/resume or checkpoint/restart on heat signal | `src/scheduler` imported by `simulate_year` and `live_agent`; test of identical decisions; DEMO-0003 | T02, T04 | gap |
| Must-have: honest "does NOT pay off" | condition stated with numbers | yearly table + break-even CHF/server-h; DEMO.md key-figures slide | T03 | gap |
| Creativity | beyond the brief | sovereignty rule with cost shown (DEMO-0001); migration across machines; optional live self-transcription; stretch "Prepper" | T04 | gap |
| Design & usability | homeowner/utility understands in 1 minute | dashboard first screen; key-figures opener in `DEMO.md`; test with a non-team person | T04 | gap |
| Pitch format (not scored, but required) | opens with key figures; Jan day, Jul day, interrupted job | `DEMO.md` run-sheet | - | partial (script drafted, nothing runnable) |
