repo: Mulaydm10/sprintd-basel-greentech-digitalheat
branch: main

## Last sync
date: 2026-11-21T09:04:15Z
### Updated in this project
- Rebuilt the dashboard as a 6-page presenting site (Overview → Simulator) with shared bottom nav + arrow-key paging
- Simulator and Live pages take an `apiBase` tweak to pull real runs / live nodes from the FastAPI dashboard

## Screen map
| Screen | Repo files |
|---|---|
| DigitalHeat 01 Overview | design/PITCH_DECK.md, research/deploy/E2E_TAILNET.md, data/assumptions.yaml |
| DigitalHeat 02 Problem | research/briefing/numbers.json, COMPETITION.md |
| DigitalHeat 03 Scheduler | data/assumptions.yaml, src/scheduler/*, DEMO.md |
| DigitalHeat 04 Live | research/deploy/E2E_TAILNET.md, src/dashboard/app.py (/api/nodes, /api/trust) |
| DigitalHeat 05 Economics | research/briefing/numbers.json, design/PITCH_DECK.md, runs/experiment_tracker.md |
| DigitalHeat 06 Simulator | src/dashboard/static/index.html, src/dashboard/app.py (/api/day, /api/balance), research/briefing/numbers.json |
