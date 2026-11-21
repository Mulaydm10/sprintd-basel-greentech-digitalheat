# contract: src/coordinator — v1 (2026-11-21)  (deployment, #8 split; plan §2 + research #29 requirements)

One coordinator process (FastAPI, port **8710**) runs on the **Mac mini**. Nodes (Mac, Omen, later Windows PCs) talk to it over HTTP JSON. Tailnet URL: `http://dhruvs-mac-mini:8710` (Mac + Omen). Public red-team URL: Tailscale Funnel `https://dhruvs-mac-mini.tailaf7ebe.ts.net` → 127.0.0.1:8710 (design sets the funnel up; never expose anything else).

## State (durable)
SQLite at `runs/coordinator/state.db` (WAL). Tables: nodes, jobs, units, leases, checkpoints (metadata), audit (hash chain from `trust.AuditLog` semantics). A restart reloads everything; **lease timers freeze while the coordinator is down** (store `expires_at` as remaining seconds at shutdown, recompute on start; research #29).

## Auth (mandatory, the URL is public)
- Every request carries `Authorization: Bearer <token>`. Tokens live in `runs/coordinator/tokens.json` (never committed): roles `node:<node_id>` (node endpoints for its own id only), `admin` (submit jobs, tamper, inspect), `observer` (GET only). Token comparison is constant-time. Unknown or missing token → 401; a wrong role → 403.
- Rate limit per token (token bucket, e.g. 20 req/s, burst 40) → 429. Request body ≤ 1 MB, except checkpoint upload ≤ 32 MB → 413. All input validated with pydantic (extra fields forbidden) → 422.
- No endpoint may read or write a filesystem path taken from the request (ids are `[a-z0-9-]{1,64}` only).

## Node protocol
- `POST /v1/nodes/register {node_id, site_id, eligible_classes, server_kw_el, attestation}` → the broker checks the (mock) attestation; ok → 200; else 403 + audit.
- `POST /v1/nodes/{id}/heartbeat {watts, running_unit|null, progress, tank_level_kwh?, demand_kw?}` every **2 s**. Missing heartbeats for **6 s** → node `suspect`; at **lease expiry** its leases lapse.
- `POST /v1/nodes/{id}/lease` → the coordinator runs **one `scheduler.decide()` tick** over all live nodes and the queue (the real policy, imported, never forked) and returns `{unit, lease_id, expires_in_s: 15, checkpoint_url|null, key_release|denied}` or `{hold, reason}`.
- `POST /v1/leases/{lease_id}/renew` at ~1/3 of the lease (every 5 s). A renewal on a lapsed lease → 410 (the node must stop and discard).
- `POST /v1/leases/{lease_id}/checkpoint` (multipart: encrypted envelope bytes + `{next_chunk, out_bytes, sha256}`); stored under `runs/coordinator/ckpt/<unit_id>/<seq>` with an atomic rename; the sha256 is verified.
- `POST /v1/leases/{lease_id}/complete {result_sha256, chunk_ids}`: **idempotent and content-addressed**. A duplicate completion of the same unit counts once; a conflicting result → 409 + audit.
- `GET /v1/checkpoints/{unit_id}/latest` (the lease holder only) → envelope bytes.

## Admin / observer
`POST /v1/jobs` (admin): submit a job (type from the catalogue, access_class, deadline) → split into units via `jobs.arrivals.to_units`, admission via `scheduler.admit`. `POST /v1/nodes/{id}/tamper` (admin) → `KeyBroker.tamper`, leases revoked. `GET /v1/status` (observer): nodes, leases, queue, recent audit, all from state (this is what the dashboard live view reads). `GET /healthz` (no auth): `{ok, version}` only.

## Degraded mode (research #29)
If the heat/weather signal for a site is older than 2 ticks: use a persistence estimate, disable slack-holding (no deferral on stale data), never start dump-only work, and add `degraded` to the trace and status.

## Exactly-once (end to end)
Unit = ~15 min of work = N chunks. A chunk id is recorded once in `units.done_chunks`; the final output is assembled from chunk results in chunk order; the test kills nodes / the coordinator at random points and asserts that the output equals the uninterrupted run and every chunk id appears exactly once.

## Tests (tests/src/coordinator/)
TestClient + 2–3 in-process fake nodes: register/lease/renew/complete happy path; node death → lease lapse → reassign → resume from the latest checkpoint; coordinator restart mid-lease (timers frozen); auth 401/403/429/413/422; path-traversal ids rejected; duplicate/conflicting completion; tamper → key denied → reassigned; degraded mode; property test: random kill schedule → exactly-once.
