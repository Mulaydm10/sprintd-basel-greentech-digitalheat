# contract: src/scheduler  (pure: no I/O, no clocks, no process control)

`scheduler.policy.decide(state: SiteState, sites: list[SiteInfo], queue: list[Job], hour) -> list[Action]`
- `SiteState`: `site_id, demand_kw, tank_level_kwh, tank_cap_kwh, servers: int, eligible_classes: set[str]`
- `Action`: one of `Run(job_id, site_id)`, `Pause(job_id)`, `Migrate(job_id, to_site)`, `Dump(site_id, kwh)` (servers run though heat unused) , `Idle(site_id, servers)`.
- Rules: never place a job on a site whose `eligible_classes` lacks its `access_class`; prefer covering demand, then tank charging, then deadlines; a job past `deadline` counts missed.
- Deterministic for a given input (seeded tie-break). The SAME function is called by `simulate_year` and by `live_agent` — no forks of the policy.
