> **LOCKED governing file.** Do not edit in place. See `GOVERNANCE.md`.

# AI onboarding prompt (paste-ready)

```
You are joining the project "sprintd Basel GreenTech 2026 - DigitalHeat" (sprintd Basel GreenTech Edition, 20-22 Nov 2026, 36 h hackathon).
Final submission Sun 22 Nov 08:30 CET; draft Sat 15:00-15:30; pitch 5 min live demo + 3 min Q&A.

FIRST read, in order: README.md, GOVERNANCE.md, workflow.md, tasks/*/README.md, src/README.md, docs/ASSUMPTIONS.md.
Rules:
- Any file starting with "> **LOCKED governing file.**" is read-only. Never edit it. Propose changes in workflow.md.
- workflow.md and runs/experiment_tracker.md are append-only. Log every meaningful step and experiment.
- No hard-coded assumptions: all numbers live in data/assumptions.yaml and are mirrored in docs/ASSUMPTIONS.md.
- Never commit data/weights/logs. Never git push unless the Main Human (Mulaydm10) says so.
- The scheduler in src/scheduler is pure policy and is shared by the year simulator and the live agent.

Case: DigitalHeat "Useful Load => Useful Heat". Reference house: Basel 2025 hourly weather (Open-Meteo, 47.56N 7.59E),
demand = max(0, 10 kW*(20-T)/25.6) on heating days (daily mean T < 12 C), hot water 12 kWh/day, tank 35 kWh lossless,
server 1 kW electric -> 0.8 kW heat, heat value = electricity price / 2.5 (ElCom 2026, IWB Basel, H4).
Deliverables: (1) >=2 job types, >=1 really measured; (2) scheduler that also pauses/resumes a real process;
(3) yearly balance incl. break-even CHF/server-hour and honest "does NOT pay off when ..." statement.
Scoring: transparency/reproducibility 25, feasibility 25, scheduling 20, creativity 20, design 10.
Demo: checkpoint + migrate a real job between "houses" under a sovereignty rule (public / swiss-only / certified).
```
