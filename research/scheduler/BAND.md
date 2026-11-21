# Tank hysteresis band (#31)

**Proposal for design: `scheduler.tank_band_low_kwh: 20.0`, `scheduler.tank_band_high_kwh: 35.0`** (now 10/33).
This is a small change. After #46 (rule 5 wake-on-space-demand) the band barely matters; see below.
Design owns `data/assumptions.yaml`. This file holds the evidence; nothing here changes a number by itself.

## How it was measured
`python -m simulate_year --band-sweep --out runs/<id>/` produces `band_sweep.csv`. Settings:
- main a4080ab (includes #42 ballast and #46 wake rule);
- real Basel 2025 weather, merit, N = 4, slack 24 h, load 0.6;
- heat-backed ballast on, seed 0, assumptions sha256 cde8ebf6…;
- band_low ∈ {0, 5, 10, 15, 20, 25, 30, 33} × band_high ∈ {25, 30, 33, 35}, keeping low ≤ high ≤ tank (35 kWh), which gives 29 cells.

Lows 25–33 extend the #31 grid. Before #46, coverage rose with band_low; this sweep checks that.

**Rule** (`analysis.choose_band`):
1. Keep only bands with ≤ 2 on/off transitions per day (actuator wear).
2. Treat coverage within **0.1 pp** of the best as equal; that is below seed and weather noise.
3. Of those, pick the **fewest transitions**.
4. Then break ties by higher coverage, then less dump, then the higher band_low (a fuller tank is more buffer for a cold snap).

## Result (selected rows of band_sweep.csv, after #46)

| band low/high kWh | covered | dumped kWh | transitions/day | paid price to break even incl. hw (CHF/server-h) |
|---|---|---|---|---|
| 10/33 (current) | 57.88% | 4,757 | 0.071 | 0.5521 |
| 0/35 … 30/35 | 57.93% | 4,757 | 0.066–0.077 | 0.5520 |
| **20/35 (chosen)** | **57.93%** | 4,757 | **0.066** | 0.5520 |
| 33/33 | 57.92% | 4,757 | 0.395 | 0.5520 |
| 33/35 (max coverage) | 57.97% | 4,757 | 0.115 | 0.5520 |

0 missed deadlines in every cell. Across all 29 cells:
- coverage runs from 57.62% to 57.97%;
- dump runs from 4,727 to 4,757 kWh;
- the paid price to break even varies only in the 4th decimal.

## What it means
- **After #46 the band hardly matters.** The wake rule (idle → running when space heat is wanted and the tank is below band_high) removes most of the hysteresis loss. Before #46, 10/33 cost 0.6 pp of coverage against 33/35; now it costs 0.09 pp.
- **Dump and money don't depend on the band.** Dump comes from deadline-forced paid work in summer.
- **Why 20/35 and not the max-coverage 33/35.** 33/35 gains +0.04 pp over 20/35 but switches 75% more often: 0.115 vs 0.066 a day, i.e. ~42 vs ~24 switches a year. Under the tolerance rule that gain is noise. 20/35 is +0.05 pp over the current 10/33 with fewer switches, so it's a no-regret change. Keeping 10/33 is also defensible; the difference is < 0.1 pp.
- **Before #46**, for the record (same sweep, PR #50 at 3933874): 10/33 gave 57.32%, 20/35 57.61%, and 33/35 57.95% at 0.115 transitions/day. The old "max coverage" rule picked 33/35 then.

## Like-for-like A/B, after #46
Paid stream = what the thermostat runs (`--load thermostat`, load 0.6465); N = 4, slack 24, ballast on.

| band | merit + ballast covered | thermostat covered | gap | merit missed | thermostat missed |
|---|---|---|---|---|---|
| 10/33 | 57.88% | 58.03% | −0.14 pp | 0% | 30.96% |
| **20/35** | **57.93%** | 58.03% | **−0.09 pp** | 0% | 30.96% |
| 33/35 | 57.97% | 58.03% | −0.06 pp | 0% | 30.96% |

Merit + ballast matches the thermostat's heat to within 0.1 pp and misses no paid deadline; the thermostat misses 31%.

## Reproduce
```
python -m simulate_year --band-sweep --out runs/band-seed0/
```
