# contract: portal API — v1 (2026-11-21)  (backend for the demo frontend: client / host / operator)

One backend, three audiences, all served by the **existing coordinator process** (port 8710, same auth,
rate limits, body limits, SQLite store). The frontend (supplied by Dhruv, not in this repo yet) talks
only to these endpoints. Everything is JSON; every list is newest-first and paginated
(`?limit≤200&cursor=`), every timestamp is ISO-8601 UTC, every energy is kWh, every price CHF.
OpenAPI at `/openapi.json` must describe every route below with response models (the frontend codegens from it).

## Roles (tokens.json, as today, plus one new role)
- `client:<client_id>` — a compute customer. NEW.
- `host:<site_id>` — the house owner where a node sits. NEW (distinct from `site:<id>`, which only posts signals).
- `admin`, `observer`, `node:<id>`, `site:<id>` — unchanged.
`--make-client-token ID` / `--make-host-token SITE` on `python -m coordinator` (additive, mode 600, printed once to a file, never stdout).

## CORS
`DH_CORS_ORIGINS` (comma list, default empty = no CORS). Exact origins only, never `*` with credentials. Methods GET/POST/DELETE, header Authorization + Content-Type.

## Client API  (`/v1/client/...`, role `client:<id>`, sees ONLY its own jobs → otherwise 404, not 403)
- `GET  /v1/client/me` → `{client_id, jobs_total, jobs_running, server_h_used, chf_spent}`
- `GET  /v1/client/catalogue` → job types from `jobs` catalogue: `{type, label, access_classes, est_unit_min, price_chf_server_h}`
- `POST /v1/client/jobs {type, access_class, deadline_h, rounds?, chunks?, idempotency_key}` → admission via `scheduler.admit`; `201 {job_id, status:"admitted", eta}` or `422 {status:"rejected", reason}`. Same `idempotency_key` → same job (no duplicate).
- `GET  /v1/client/jobs` / `GET /v1/client/jobs/{job_id}` → `{job_id, type, access_class, status: queued|running|paused|done|failed|cancelled, progress 0..1, units:[{unit_id, status, node_id|null, done_chunks, total_chunks}], deadline, eta, missed_deadline: bool, events:[…last 50]}`
- `DELETE /v1/client/jobs/{job_id}` → cancel; running leases revoked; idempotent.
- `GET  /v1/client/jobs/{job_id}/result` → the assembled output bytes + `X-Result-SHA256`; 409 until done.
- `GET  /v1/client/jobs/{job_id}/receipt` → `{result_sha256, chunk_ids, nodes_used, kwh, heat_used_kwh, audit_head}` (the "proof of where it ran"; certified jobs list only certified nodes).

## Host API  (`/v1/host/...`, role `host:<site_id>`, sees only nodes at its site)
- `GET  /v1/host/site` → `{site_id, demand_kw, tank_level_kwh, degraded, nodes:[node summary], heat_today_kwh, heat_month_kwh, dumped_today_kwh, chf_heat_value_today}`
- `GET  /v1/host/nodes/{node_id}` → node summary + `{watts, running_unit, progress, last_heartbeat_s, state: online|suspect|offline|paused|tampered}`
- `POST /v1/host/site/pause {until?}` / `POST /v1/host/site/resume` → owner override ("I'm away / too warm"): the scheduler treats the site as zero heat demand → running units pause via the existing hold path within one tick. Audited.
- `GET  /v1/host/history?hours=24` → hourly `{ts, heat_kwh, dumped_kwh, demand_kwh}` (from the coordinator's own tick log, never invented).

## Operator API  (`/v1/ops/...`, role `admin`; `observer` gets the GETs)
- `GET  /v1/ops/overview` → `{nodes:{online,suspect,offline}, jobs:{queued,running,done,failed}, leases_active, heat_used_kwh_today, dumped_kwh_today, missed_deadline_pct, degraded_sites:[…], audit:{ok, head, length}}`
- `GET  /v1/ops/nodes`, `GET /v1/ops/jobs`, `GET /v1/ops/sites` — full tables.
- `POST /v1/ops/nodes/{id}/drain` → no new leases; running unit finishes or checkpoints then moves. `POST …/undrain`.
- `POST /v1/ops/nodes/{id}/tamper` (alias of existing), `POST /v1/ops/nodes/{id}/kill` → revoke its lease NOW (demo "pull the plug" without touching hardware).
- `POST /v1/ops/sites/{id}/scenario {replay: coldest|july}` → switches the sitesim scenario for the demo (via a file/flag sitesim polls; no process spawn from HTTP).
- `GET  /v1/ops/audit?limit=` → audit rows + `verify()` result.

## Live events  (all roles, filtered by role)
`GET /v1/events` — Server-Sent Events. Event types: `node.state`, `lease.granted|renewed|lapsed|released`, `unit.progress`, `unit.migrated {from,to,next_chunk}`, `job.state`, `site.signal`, `site.paused`, `audit.appended`. Each event has a monotonically increasing `id`; `Last-Event-ID` resumes from the store (events table, ring of 10 000). Heartbeat comment every 15 s. Client sees only its jobs' events, host only its site's, admin/observer everything. Max 4 concurrent streams per token (429).
`GET /v1/events/poll?after=<id>` — the same as JSON for frontends that can't do SSE.

## Robustness rules (red team will attack each)
- Ownership checks in the SQL query, not after fetching (no IDOR; unknown or foreign id → 404).
- All new state transitions inside one `Store.tx`; restart-safe; events written in the same transaction as the change.
- Cancel/drain/kill/pause are idempotent and race-safe with lease renewals (renew after revoke → 410).
- Inputs: pydantic, extra=forbid, ids `[a-z0-9-]{1,64}`, deadline_h 0.25..720, rounds/chunks bounded as in jobs.
- Never `subprocess` or file paths from requests. Result bytes served from the coordinator's own store only.
- SSE must not leak memory on disconnect; slow consumers are dropped, not buffered unboundedly.

## Lanes / split
- **P1 `src/coordinator`**: roles client/host + token CLI, schema (jobs.client_id, idempotency_key, results, events, site_override, node drain), event emission at every transition, result assembly + storage, CORS. Exposes `coordinator.portal_store` functions used by P2/P3 (signatures in that module's docstring, written FIRST and pushed in the PR within 30 min so P2/P3 can code against it).
- **P2 `src/portal`**: `portal/client.py`, `portal/host.py` routers (FastAPI `APIRouter`), mounted by the coordinator app.
- **P3 `src/portal`**: `portal/ops.py`, `portal/events.py` (SSE + poll).
- **P4 `tests/redteam`**: R5 attack suite against the portal (IDOR, cross-role, SSE exhaustion, cancel/renew races, idempotency, CORS) as xfail(strict) first, then live against the funnel once merged.
Tests per lane under `tests/src/<lane>/`; P2/P3 test with an in-process coordinator (TestClient).
