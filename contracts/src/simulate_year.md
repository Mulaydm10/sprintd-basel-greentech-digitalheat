# contract: src/simulate_year — v2 (2026-11-21)

Depends on: `house_model` (#4), `jobs.catalogue` + `jobs.arrivals` (#5, the measurement part can land later), `scheduler.decide` (merged, v2).
Reference implementation of the loop, already validated against the briefing: `research/scheduler/year_replay.py`. Port it; don't fork the policy.

## CLI
`python -m simulate_year --servers N --policy {merit,thermostat,always_on} [--slack-h H] [--load F] [--seed S] [--out runs/<id>/]`
`python -m simulate_year --sweep` → grid servers 1..13 × policy × slack {0,24,168} × load {0.4,0.6,0.8} → `runs/<id>/sweep.csv` (one row per cell, same keys as balance.json).
All inputs from `data/assumptions.yaml`; `assumptions_hash` = sha256 of the file bytes. `--seed` fixes arrivals.

## Hour loop (order is part of the contract)
1. Arrivals for hour h → queue (units of `scheduler.unit_minutes`).
2. Build `SiteState` (heat value via `scheduler.types.heat_value_chf_kwh`, `mode_running` carried).
3. `decide()` → apply `SetPower`, `Assign`, `Route`.
4. Tank += route.tank; unmet = demand − space − dhw; draw from tank; the rest = **backup heater kWh**.
5. Remove assigned units; units with `deadline_hour ≤ h` still queued = **missed** (incl. forced units whose bid < MC).

## Outputs
`runs/<id>/hourly.parquet` (per hour: demand, servers_on, space, dhw, tank_in, tank_draw, dump, backup, tank_level, mode, queue_len, missed) and `runs/<id>/balance.json` with keys:
`servers_per_house, policy, slack_h, load, seed, heat_demand_kwh, server_heat_used_kwh, share_covered, backup_heat_kwh, heat_dumped_kwh, run_h, utilisation, jobs_total, units_done, missed_deadline_pct, transitions_per_day, electricity_cost_chf, heat_value_chf (=used_kwh*price/divisor), compute_income_chf, break_even_chf_per_server_h (=(elec_cost-heat_value)/server_h_sold), break_even_incl_hardware_chf_per_server_h (capex/life from hardware:, plus table for capex_range_chf × {3,5} y), assumptions_hash, pays_off: bool, pays_off_conditions: str`.
Every number in `pays_off_conditions` is computed, not typed.

## Robustness requirements (each is a test in tests/src/simulate_year/)
1. **Golden numbers:** thermostat N=1/4/8 → share_covered 0.195/0.580/0.929 (±0.002), utilisation 0.871/0.647/0.518, break-even 0.2261 (±0.0005). Merit N=4, load 0.6: dump(slack 24) < dump(slack 0) < always_on dump.
2. **Energy conservation each hour:** produced heat = space+dhw+tank_in+dump; demand = space+dhw+tank_draw+backup; 0 ≤ tank ≤ cap. Assert in the loop (cheap), not only in tests.
3. **Monotonicity:** share_covered non-decreasing in N for thermostat/always_on; dump non-increasing in slack for merit (sweep check).
4. **Determinism:** same seed → byte-identical balance.json; different seed changes only arrival-driven keys.
5. **Edge cases:** N=0 (backup = demand, no division by zero → break-even null), load 0 (merit runs nothing), load > 1 (missed > 0, no crash), a flat-weather synthetic year, a leap-free 8,760-row check.
6. **Speed:** one year < 15 s on the Mac (the reference loop runs ~5 s/yr); the full sweep runs in parallel processes.
7. Tests use a small synthetic profile or the committed CSV; no network.
