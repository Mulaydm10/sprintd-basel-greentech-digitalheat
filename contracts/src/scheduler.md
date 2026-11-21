# contract: src/scheduler  — v2 (2026-11-21)  (pure: no I/O, no clocks, no process control, no randomness except a passed seed)

Plan: `design/PLAN-scheduler-deploy.md` §1. One policy, price-driven; heat-led vs compute-led is a *parameter outcome*, not a code fork.

## Types (`scheduler.types`, frozen dataclasses)
- `SiteState(site_id, hour_index, demand_kw, tank_level_kwh, tank_cap_kwh, servers: int, server_kw_el, heat_recovery, p_el_chf_kwh, heat_value_chf_kwh, eligible_classes: frozenset[str], night_cap_kw: float|None, has_dump: bool, band_low_kwh, band_high_kwh, mode_running: bool)`
  - `heat_value_chf_kwh` = `p_el / heat_value_divisor` (assumptions.yaml) when heat is wanted (demand or tank below band_high), else 0.
  - `mode_running` = the hysteresis state from the previous tick (caller carries it).
- `Unit(unit_id, job_id, job_class, access_class, kwh_el, bid_chf_per_server_h, deadline_hour, slack_h, checkpointable: bool)` — ~15 min of work on the 1 kW ref server.
- Actions (`scheduler.actions`): `SetPower(site_id, servers_on: float)`, `Assign(unit_id, site_id)`, `Hold(unit_id, reason)` (paused/deferred), `Route(site_id, space_kwh, dhw_kwh, tank_kwh, dump_kwh)`, `Refuse(unit_id, site_id, reason)` (eligibility).

## Function
`scheduler.policy.decide(sites: list[SiteState], queue: list[Unit], hour: int, params: Params, seed: int = 0) -> Decision`
- `Decision(actions: list[Action], next_mode: dict[site_id, bool], trace: list[str])` — `trace` = one human-readable line per non-trivial choice (Transparency 25%).
- `Params(policy: "merit" | "thermostat" | "always_on", eta_heat_used, slack_enabled: bool, migration_margin_chf)` — the two baselines are implemented in the SAME module as policies, sharing all types, so A/B uses one job stream.

## Rules (merit policy; each has a test)
1. **Eligibility first (hard filter):** a unit is never assigned to a site whose `eligible_classes` lacks its `access_class`; emit `Refuse` once per (unit, site) considered.
2. **Marginal cost per server-h at site s:** `MC_used = p_el·kw_el − heat_recovery·kw_el·heat_value` if its heat would be used (demand or tank room), else `MC_dump = p_el·kw_el`.
3. **Merit order:** sort site capacity blocks by MC ascending; sort units by (deadline_hour, -bid, unit_id); assign a unit to the cheapest eligible block where `bid ≥ MC`.
4. **Slack as storage:** a unit with `slack_h>0` whose cheapest eligible block is `MC_dump` is `Hold`-ed (reason "waiting for heat demand") unless `hour + remaining run time ≥ deadline_hour − safety`; then it runs anyway (deadline beats dump).
5. **Hysteresis:** a site switches from running to idle only when tank ≥ `band_high` and to running only when tank ≤ `band_low` (unless rule 4 forces deadline work). No more than one on/off transition per site per hour.
6. **Routing:** heat goes space → hot water → tank (up to cap) → dump; `Route` energies sum to produced heat exactly.
7. **Night cap:** `servers_on ≤ night_cap_kw/server_kw_el` when set.
8. **Determinism:** same inputs + seed → identical `Decision` (tie-break by id, then seeded).
- Thermostat baseline: run only while demand+tank room > 0 (the old `follow`). Always-on: all servers every hour.

## Tests required (tests/src/scheduler/)
- One test per rule above; plus: refusal of a `certified` unit on a `public`-only site; July day with merit+slack holds deferrable units instead of dumping; deadline forces run; ≤1 transition/hour under hysteresis; Route energy conservation; determinism.
- No file/network access in tests. Numbers come from a `Params`/fixture built from `data/assumptions.yaml` values passed in, never hard-coded constants in `src/`.

## Out of scope for #6
Leases, WebSocket, real processes (→ #8), yearly balance (→ #7). `Migrate` is gone: moving work = lease lapse + reassign in #8.
