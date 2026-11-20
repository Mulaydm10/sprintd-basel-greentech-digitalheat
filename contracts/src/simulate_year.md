# contract: src/simulate_year

`python -m simulate_year --servers N [--sites config] [--price CHF/kWh] [--out runs/<id>/]` runs 8,760 h with `house_model` + `jobs` + `scheduler.decide`.
Writes `runs/<id>/hourly.parquet` and `runs/<id>/balance.json` with exactly these keys:
`servers_per_house, heat_demand_kwh, server_heat_used_kwh, share_covered, heat_dumped_kwh, utilisation (=run_h/(servers*8760)), jobs_total, missed_deadline_pct, electricity_cost_chf, heat_value_chf (=used_kwh*price/2.5), compute_income_chf, break_even_chf_per_server_h (=(elec_cost-heat_value)/server_h_sold), assumptions_hash, pays_off: bool, pays_off_conditions: str`.
Also `--sweep servers=1..13` → `runs/<id>/sweep.csv`. All inputs from `data/assumptions.yaml`.
