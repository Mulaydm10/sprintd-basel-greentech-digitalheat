> **LOCKED governing file.** Do not edit in place. See `GOVERNANCE.md`.

# VISION

Event facts, rubric and deadlines: `COMPETITION.md` (not restated here).

## Thesis
Basement servers heat homes; if the compute they run is interruptible and scheduled by the home's heat
demand and hot-water tank, the waste heat is useful instead of dumped, and the compute is cheap enough
to sell. We build the scheduler, the yearly economics, and a real demo that proves the same scheduling
code can pause, resume and move a real process.

## For whom
- Homeowners / building owners hosting a server (must understand it in 1 minute).
- The utility / DigitalHeat as the operator and case judge.

## Why it is not already solved
Source: the case brief only. Prior-art check: `research/prior_art.md` (TODO(Dhruv): confirm the "not solved" claim with real sources before claiming it on stage).

## What "working" looks like at demo time
- Opening slide: key figures from one reproducible command (servers/house, % heat covered, heat dumped, utilisation, % missed deadlines, break-even CHF/server-h) and an honest "does NOT pay off when ..." line.
- Live: a January day, a July day, and one real process interrupted by the heat signal; then DEMO-0001 (checkpoint, migrate to another eligible "house", resume).
- Dashboard shows the cost of the sovereignty rule (public / swiss-only / certified).

## Non-goals
- District heating grid. Spreadsheet-only or slide-only answers. Training-scale AI workloads. Anything needing network/model downloads on stage.
- Stretch only (do not start before the core gates pass): solar + compute + storage "Prepper".
