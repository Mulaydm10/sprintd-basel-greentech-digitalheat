# Assumptions (visible, sourced)

Mirror of `data/assumptions.yaml`. Each row: value, unit, source, who confirmed.

| Assumption | Value | Source | Status |
|---|---|---|---|
| Heating demand | max(0,10*(20-T)/25.6) kW on heating days | Case brief | given |
| Hot water | 12 kWh/day | Case brief | given |
| Tank | 35 kWh, lossless | Case brief | given |
| Server | 1 kW -> 0.8 kW heat | Case brief | given |
| Elec price | ElCom 2026 IWB Basel H4 | ElCom | TODO |
| Job/day rates | - | Alibaba trace / MLPerf | TODO |

## Reconciliation notes (2026-11-21)
- Verified heating total from the brief: 26,851 kWh over 206 heating days. `data/assumptions.yaml` `expected_checks.annual_heating_kwh: 27000` is the rounded check; tests use a tolerance.
- Heat value = electricity price / 2.5 (`price.heat_value_divisor`). Electricity price value still unset: `Q-0002`.
- Event dates/times/rubric are NOT kept here: see `COMPETITION.md`.

## When it does NOT pay off
TODO (fill from simulation).
