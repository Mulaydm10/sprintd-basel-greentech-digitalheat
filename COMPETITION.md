> **LOCKED governing file.** Do not edit in place. See `GOVERNANCE.md`.

# COMPETITION - event facts (single source of truth)

Every other doc LINKS here instead of restating a date, time or weight. A duplicate found elsewhere
is to be deleted and replaced by a link to the section below. A bare time with no timezone has caused
real missed submissions: every time in this repo is written with its timezone.

**Timezone for ALL event times: CET = UTC+1 = Europe/Zurich (Basel local time).** Dev machines may run
other timezones; convert before reading a clock.

## Event
| Field | Value |
|---|---|
| Name | sprintd Basel - GreenTech Edition |
| Host / venue | sprintd; FHNW Dreispitz, Basel |
| Dates | Fri 20 Nov - Sun 22 Nov 2026 |
| Event link | TODO(Dhruv) |
| Platform for submissions | the sprintd platform (URL/login: TODO(Dhruv)) |
| Case | DigitalHeat "Useful Load => Useful Heat" (DigitalHeat judges its own case) |
| Case slide theme | "Server heat and Sovereign AI": local Swiss data and ops; jobs slow down / pause and resume / move to another ELIGIBLE site, respecting access and deadlines |
| Team | solo (Dhruv, Main Human) + several AI agents on Omen + Mac |

## Timeline (all CET)
| When | What |
|---|---|
| Fri 20 Nov, evening | Mentors on site |
| Sat 21 Nov 09:00-20:00 | Mentors on site |
| **Sat 21 Nov 15:00-15:30** | **DRAFT submission window (first gate)** |
| **Sun 22 Nov 08:30** | **FINAL submission on the sprintd platform (hard)** |
| Sun 22 Nov 09:00-11:30 | Case pitches: 5 min incl. live demo + 3 min Q&A. Our exact slot: TODO(Dhruv) |
| Sun 22 Nov 12:00 | Finalists chosen |
| Sun 22 Nov 13:00-14:45 | Grand Finale |

Open: is the 08:30 final a cutoff or a start time, and what exactly must the draft contain? -> `Q-0003`.

## Submission format
TODO(Dhruv): what the platform accepts (repo link / zip / video / form fields). Until known, staging is
`submissions/README.md`. Validity rule from the brief: **a spreadsheet, slides, or a simulation alone is
NOT valid** - a real running process driven by the scheduler is required.

## Judging rubric (weights sum to 100)
| Criterion | Weight | Notes from brief |
|---|---|---|
| Transparency & reproducibility | 25 | all assumptions visible, numbers regenerate from one command |
| Feasibility | 25 | real measured workload, scaled to the 1 kW server |
| Scheduling quality & impact | 20 | order of importance: heat covered at least dumped, then utilisation, then missed deadlines |
| Creativity | 20 | |
| Design & usability | 10 | a homeowner or utility understands it in 1 minute |

Mapping rubric -> repo artifact lives in `notes/judging_alignment.md`.

## Pitch requirements (from brief)
- Pitch must OPEN with the key figures, then live demo: **one January day, one July day, one interrupted job on a real process**.
- Script: `DEMO.md`.

## Case requirements (must-haves)
1. >=2 job types with runtime, energy, interruptible?, deadline; >=1 really runs and is measured on the machine, scaled to 1 kW; jobs/day with a source.
2. Scheduler driven by heat demand + tank; the SAME code pauses/resumes (or checkpoint/restarts) a real process on the heat signal.
3. Yearly balance: servers/house, % heat covered, heat dumped, utilisation = run-h/(servers*8760), % missed deadlines, electricity cost, compute income, break-even CHF/server-h = (electricity cost - value of heat used) / server-h sold. All assumptions visible. Show when it does NOT pay off.

## Reference house (fixed for all teams)
Numbers are mirrored in `data/assumptions.yaml` (machine truth) and `docs/ASSUMPTIONS.md` (human view).
This section is the event-given definition; if they ever disagree, flag it in `STATE.md` Blocked and do not silently pick one.
- Weather: Open-Meteo Basel 2025 hourly.
- Heat demand = max(0, 10 kW*(20-T)/25.6) on heating days (daily mean T < 12 C): ~27,000 kWh over 206 days (verified 26,851).
- Hot water 12 kWh/day. Tank 35 kWh, lossless.
- Server 1 kW electric -> 0.8 kW recoverable heat (19.2 kWh/day).
- Electricity: ElCom 2026, IWB Basel, category H4, flat. Heat value = price / 2.5. (Price value itself: TODO, `Q-0002`.)

## Hard rules
- Pre-built code / allowed libraries / AI-generated-code rule / licensing: TODO(Dhruv) - never assume; ask a mentor (on site until Sat 20:00 CET). `Q-0004`.
- API keys / rate limits: none known. Real jobs run locally; no network model downloads during the demo.
- Scope: district-heating grid is OUT of scope.

## Stretch (non-binding)
Solar + compute + storage "Prepper" scenario.
