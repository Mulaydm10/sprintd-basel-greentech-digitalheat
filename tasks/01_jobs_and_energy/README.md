> **LOCKED governing file.** Do not edit in place. See `GOVERNANCE.md`.

# Task 01_jobs_and_energy: Job catalogue + real measured workload

Define >=2 job types (embeddings, Whisper transcription) with runtime, energy, interruptible?, deadline, access class. At least one runs for real with measured runtime/energy and a stated scaling to the 1 kW server. Provide jobs/day with source (Alibaba trace, MLPerf, cloud prices). Code: `src/jobs/`.

## Context
## Event and case
- Event: sprintd Basel - GreenTech Edition, 20-22 Nov 2026, FHNW Dreispitz. 36 h sprint.
- Deadlines: draft submission Sat 21 Nov 15:00-15:30; FINAL submission Sun 22 Nov 08:30 CET; pitch 5 min live demo + 3 min Q&A.
- Case: DigitalHeat "Useful Load => Useful Heat". Servers in basements heat homes while running paid, interruptible AI jobs.

## Reference house (fixed for all teams)
- Weather: Basel 2025 hourly, Open-Meteo archive (lat 47.56, lon 7.59, Europe/Zurich, temperature_2m + shortwave_radiation).
- Heating demand per hour = max(0, 10 kW * (20 - T) / 25.6), only on heating days (local-day mean T < 12 C). Expect ~27,000 kWh/yr and 206 heating days.
- Hot water: 12 kWh/day all year. Tank: 35 kWh usable, lossless.
- Server: 1 kW electric -> 0.8 kW recoverable heat (19.2 kWh/day at full load).
- Electricity price: ElCom 2026, IWB Basel, category H4, flat CHF/kWh. Heat value = electricity price / 2.5.

## Must-haves
1. >=2 job types (e.g. embeddings, Whisper transcription) with runtime, energy, interruptible?, deadline. >=1 actually runs on the machine with measured runtime/energy and a stated scaling to the 1 kW server. Jobs/day with source.
2. Scheduler distributing/pausing/rescheduling jobs by heat demand + tank. The SAME scheduler code must pause/resume (or checkpoint/restart) a real running process on the heat signal.
3. Yearly balance per house: servers/house, % heat covered, heat dumped, utilisation = run-hours/(servers*8760), % missed deadlines, electricity cost, compute income, break-even CHF/server-hour = (elec cost - value of heat used)/server-hours sold. All assumptions visible. State when it does NOT pay off.

## Scoring
Transparency/reproducibility 25, feasibility 25, scheduling quality 20, creativity 20, design 10.

## Planned wow demo
Several machines act as houses. A real job (Whisper transcript / embedding batch) is checkpointed, migrated to another house and resumed mid-way. Sovereignty rule: jobs carry an access class (public / swiss-only / certified) and may only move to eligible sites; dashboard shows the cost of that rule.

## Resources
MLPerf Inference datacenter power results; Alibaba cluster-trace-gpu-v2020 (job durations/arrivals); cloud on-demand/spot prices; case PDF slides ("Sovereign AI", "slow down / pause & resume / distribute to eligible site, respect access and deadlines").

## Status
TODO: fill in acceptance criteria and owner.
