# contract: src/dashboard

Read-only. Inputs: `runs/<id>/balance.json`, `hourly.parquet`, `sweep.csv`, and live nodes' `GET /status`.
Serve at `:8700` (FastAPI + static HTML/JS, no build step). Views: (1) key-figures header in the exact order of DEMO.md, (2) January day + July day replay, (3) live nodes with job state, power, heat and the "cost of the access rule". Must be understandable by a homeowner in one minute.
