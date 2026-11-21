# Tank hysteresis band (#31)

**Proposal for design: `scheduler.tank_band_low_kwh: 33.0`, `scheduler.tank_band_high_kwh: 35.0`** (now 10/33).
Design owns `data/assumptions.yaml`. This file holds the evidence; nothing here changes a number by itself.

## How it was measured
`python -m simulate_year --band-sweep --out runs/<id>/` produces `band_sweep.csv`. Settings:
- real Basel 2025 weather, merit, N = 4, slack 24 h, load 0.6;
- heat-backed ballast on (#37), seed 0, `assumptions_hash` as written in the CSV's run;
- band_low ∈ {0, 5, 10, 15, 20, 25, 30, 33} × band_high ∈ {25, 30, 33, 35}, keeping low ≤ high ≤ tank (35 kWh), which gives 29 cells.

The #31 grid stopped at low = 20. Lows 25–33 were added because coverage kept rising with band_low.

**Rule** (`analysis.choose_band`): the highest coverage among bands with ≤ 2 on/off transitions per day (actuator wear). Ties go to less dump, then the wider band.

## Result (selected rows of band_sweep.csv)

| band low/high kWh | covered | dumped kWh | transitions/day | paid price to break even incl. hw (CHF/server-h) |
|---|---|---|---|---|
| 0/35 | 57.14% | 4,757 | 0.066 | 0.5524 |
| **10/33 (current)** | 57.32% | 4,757 | 0.071 | 0.5523 |
| 20/35 | 57.61% | 4,757 | 0.066 | 0.5522 |
| 25/35 | 57.71% | 4,757 | 0.071 | 0.5521 |
| 30/35 | 57.87% | 4,757 | 0.077 | 0.5521 |
| 33/33 | 57.92% | 4,757 | 0.395 | 0.5520 |
| **33/35 (chosen)** | **57.95%** | 4,757 | **0.115** | 0.5520 |

0 missed deadlines in every cell.

## What it means
- **The band barely matters for money and dump.** Dump varies by only ~30 kWh across all 29 cells: it comes from deadline-forced paid work in summer, not from the band. The break-even moves in the 4th decimal.
- **It does matter for coverage, through hysteresis.** A low `band_low` keeps the servers idle while the tank drains from band_high down to band_low, even when heat is wanted. The backup heater covers that gap.
  - Raising band_low to 33 recovers +0.63 pp at N = 4.
  - The cost is more switching: 0.115 vs 0.071 transitions/day, i.e. ~42 vs ~26 switches a year, far below the 2/day limit.
  - 35/35, i.e. no band at all (not in the grid; measured on #42), would switch 9.4 times a day.
- **Like-for-like A/B.** Here the paid stream equals what the thermostat runs (`--load thermostat`, load 0.6465), with N = 4, slack 24 and ballast on:

| band | merit + ballast covered | thermostat covered | gap | merit missed | thermostat missed |
|---|---|---|---|---|---|
| 10/33 | 57.35% | 58.03% | −0.68 pp | 0% | 30.96% |
| 20/35 | 57.62% | 58.03% | −0.40 pp | 0% | 30.96% |
| **33/35** | **57.95%** | 58.03% | **−0.07 pp** | 0% | 30.96% |

With 33/35, merit matches the thermostat's heat to within 0.1 pp and misses no paid deadline, while the thermostat misses 31%.

#44 (rule 5 wake-on-space-demand, contract v2.3) attacks the same hysteresis from the scheduler side. Re-run this sweep once #44 lands; after it, the band choice may matter even less.

## Reproduce
```
python -m simulate_year --band-sweep --out runs/band-seed0/
```
