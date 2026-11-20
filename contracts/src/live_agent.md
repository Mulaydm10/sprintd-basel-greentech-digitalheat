# contract: src/live_agent

FastAPI app per machine (`uvicorn live_agent.app:app --port 8710`), node id + site config from env `DH_SITE_ID`, `DH_ELIGIBLE` (comma list).
- `GET /status` → `{site_id, eligible, job: {id,type,state: running|paused|stopped, progress, pid}|null, power_w, heat_kwh}`
- `POST /jobs/{id}/start` body `{type, checkpoint_url?}`; `/pause` (SIGSTOP); `/resume` (SIGCONT); `/checkpoint` (SIGTERM → returns checkpoint file); `/migrate` body `{to: base_url}` = checkpoint + upload + remote start.
- Refuses (HTTP 403) a job whose access_class is not in `DH_ELIGIBLE`.
- A coordinator loop (`python -m live_agent.coordinator --nodes ...`) feeds a heat signal (replayed hour) into `scheduler.decide` and calls these endpoints.
Power: Linux RAPL / macOS powermetrics when available, else declared W.
