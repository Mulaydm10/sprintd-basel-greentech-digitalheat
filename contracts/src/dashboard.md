# contract: src/dashboard — v2 (2026-11-21)

Read-only. FastAPI + static HTML/JS, no build step, serve at `:8700`. Inputs: `runs/<id>/balance.json`, `hourly.parquet`, `sweep.csv` (schemas in contracts/src/simulate_year.md v2), and later live nodes' `GET /status` (#8; stub it now behind a flag).
Until #7 lands, develop against a fixture: `tests/src/dashboard/fixtures/` with a hand-made balance.json + 48-row hourly + small sweep, keys exactly per contract.

Views:
1. **Key figures** (homeowner-readable in one minute): heat covered %, backup heat %, heat dumped kWh, break-even CHF/server-h (case formula AND incl. hardware, labelled ASSUMED), pays_off + conditions.
2. **A/B**: thermostat vs always_on vs merit on the same year (from sweep.csv): coverage, dump, break-even, missed deadlines.
3. **Day replay**: January coldest day + a July day: demand, servers_on, routing stack (space/dhw/tank/dump/backup), tank level.
4. **Trust panel** (from #10 types, mock data now): audit log entries, a "denied" example, labelled MOCK.
5. **Decision card**: N chosen by coverage/hardware, and when it does NOT pay off.
Every number shown links to its key in balance.json (hover/title) — Transparency 25%.
Tests: the app starts, each endpoint returns 200 on the fixture, and no number is hard-coded in templates.
