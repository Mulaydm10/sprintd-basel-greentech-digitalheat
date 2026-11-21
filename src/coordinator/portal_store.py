"""Portal data layer (contracts/src/portal.md §P1). The ONLY place P2 (`portal/client.py`, `portal/host.py`) and
P3 (`portal/ops.py`, `portal/events.py`) touch coordinator state. Routers call these functions; they never run SQL.

Conventions (all functions):
- First argument `coord` is the running `coordinator.core.Coordinator` (routers get it as `request.app.state.coord`).
- Ownership is enforced INSIDE the query: a function scoped to `client_id` / `site_id` returns `None` for an unknown
  OR foreign id, and the router answers 404 (never 403, so ids cannot be probed).
- Pagination: `limit` 1..200, `cursor` = opaque string from the previous page's `next_cursor` (None = first page);
  lists are newest-first and return `{"items": [...], "next_cursor": str | None}`.
- Times are ISO-8601 UTC strings, energies kWh, money CHF.
- Business errors raise `coordinator.core.CoordError(status, detail)`; `detail` may be a dict (e.g. 422 rejected).
- Every state change runs in ONE `coord._tx()` and writes its events in the same transaction (restart-safe).

Event types (stored in the `events` table, ring of 10 000; `id` strictly increasing):
  node.state, lease.granted, lease.renewed, lease.lapsed, lease.released, unit.progress,
  unit.migrated {from, to, next_chunk}, job.state, site.signal, site.paused, audit.appended
Each event row: {id, ts, type, client_id|None, site_id|None, node_id|None, job_id|None, data:{...}}.
Visibility: client sees rows with its client_id; host sees rows with its site_id; admin/observer see all.
"""
from __future__ import annotations

from typing import Any

from .auth import Principal

# ------------------------------------------------------------------ client  (role client:<client_id>)


def client_summary(coord, client_id: str) -> dict[str, Any]:
    """{client_id, jobs_total, jobs_running, server_h_used, chf_spent}. server_h_used = completed units' kWh /
    server kW; chf_spent = server_h_used x the job type's price."""
    raise NotImplementedError


def catalogue(coord) -> list[dict[str, Any]]:
    """[{type, label, access_classes, est_unit_min, price_chf_server_h}] from the jobs catalogue."""
    raise NotImplementedError


def submit_client_job(coord, client_id: str, *, type: str, access_class: str, deadline_h: float,
                      idempotency_key: str, rounds: int | None = None, chunks: int | None = None) -> dict[str, Any]:
    """Admit via scheduler.admit (no `force`). Returns {job_id, status: "admitted", eta, created: bool}; the router
    answers 201 when created, 200 for an idempotent replay (same client_id + idempotency_key -> same job, never a
    duplicate). Rejected -> raises CoordError(422, {"status": "rejected", "reason": ...})."""
    raise NotImplementedError


def list_client_jobs(coord, client_id: str, *, limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
    """{items: [job summary], next_cursor}; job summary as in get_client_job without units/events."""
    raise NotImplementedError


def get_client_job(coord, client_id: str, job_id: str) -> dict[str, Any] | None:
    """{job_id, type, access_class, status: queued|running|paused|done|failed|cancelled, progress 0..1,
    units: [{unit_id, status, node_id|None, done_chunks, total_chunks}], deadline, eta, missed_deadline,
    events: [last 50]} or None (unknown/foreign)."""
    raise NotImplementedError


def cancel_client_job(coord, client_id: str, job_id: str) -> dict[str, Any] | None:
    """Cancel (idempotent): pending units -> cancelled, active leases revoked (a renew after this -> 410).
    Returns the job (as get_client_job) or None."""
    raise NotImplementedError


def get_result(coord, client_id: str, job_id: str) -> tuple[bytes, str] | None:
    """(output bytes, sha256 hex) assembled from each unit's final checkpoint bundle (decrypted with the job key,
    each unit's output verified against its completed result_sha256, concatenated in unit order).
    None if unknown/foreign; CoordError(409) until every unit is done."""
    raise NotImplementedError


def get_receipt(coord, client_id: str, job_id: str) -> dict[str, Any] | None:
    """{result_sha256, chunk_ids, nodes_used, kwh, heat_used_kwh, audit_head} once done (409 before)."""
    raise NotImplementedError


# ------------------------------------------------------------------ host  (role host:<site_id>)


def host_site(coord, site_id: str) -> dict[str, Any] | None:
    """{site_id, demand_kw, tank_level_kwh, degraded, paused, paused_until, nodes: [node summary],
    heat_today_kwh, heat_month_kwh, dumped_today_kwh, chf_heat_value_today} or None if no such site."""
    raise NotImplementedError


def host_node(coord, site_id: str, node_id: str) -> dict[str, Any] | None:
    """Node summary + {watts, running_unit, progress, last_heartbeat_s,
    state: online|suspect|offline|paused|tampered}, or None if the node is not at this site."""
    raise NotImplementedError


def set_site_override(coord, site_id: str, *, paused: bool, until_ts: float | None = None) -> dict[str, Any]:
    """Owner override: paused -> the scheduler sees zero heat demand for the site (running units hold on their next
    renew). Idempotent, audited, emits site.paused. Returns host_site(...)."""
    raise NotImplementedError


def host_history(coord, site_id: str, *, hours: int = 24) -> list[dict[str, Any]]:
    """Hourly [{ts, heat_kwh, dumped_kwh, demand_kwh}] from the coordinator's own tick log (never invented); hours
    without data are omitted."""
    raise NotImplementedError


# ------------------------------------------------------------------ operator  (admin; observer = GETs)


def ops_overview(coord) -> dict[str, Any]:
    """{nodes: {online, suspect, offline}, jobs: {queued, running, done, failed}, leases_active,
    heat_used_kwh_today, dumped_kwh_today, missed_deadline_pct, degraded_sites, audit: {ok, head, length}}"""
    raise NotImplementedError


def ops_nodes(coord, *, limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
    raise NotImplementedError


def ops_jobs(coord, *, limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
    raise NotImplementedError


def ops_sites(coord, *, limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
    raise NotImplementedError


def drain_node(coord, node_id: str, *, drain: bool) -> dict[str, Any] | None:
    """drain=True: no new leases for the node; its running unit continues until it completes or checkpoints
    (renew returns hold so it moves). Idempotent. Returns the node row or None."""
    raise NotImplementedError


def kill_node(coord, node_id: str) -> dict[str, Any] | None:
    """Revoke the node's active lease NOW (demo 'pull the plug' without hardware): unit -> pending, the node's next
    renew/upload/complete -> 410. Idempotent. Returns {revoked: n} or None."""
    raise NotImplementedError


def set_scenario(coord, site_id: str, *, replay: str) -> dict[str, Any]:
    """Write the site's demo scenario (coldest|july) to runs/coordinator/scenario/<site_id> (atomic); sitesim polls
    it. No process is spawned from HTTP."""
    raise NotImplementedError


def audit_rows(coord, *, limit: int = 100, cursor: str | None = None) -> dict[str, Any]:
    """{items: audit rows newest-first, next_cursor, verify: bool, head, length}"""
    raise NotImplementedError


# ------------------------------------------------------------------ events (SSE + poll)


def emit(db, coord, type: str, data: dict[str, Any], *, client_id: str | None = None, site_id: str | None = None,
         node_id: str | None = None, job_id: str | None = None) -> int:
    """Append one event INSIDE the caller's transaction `db`; trims the ring to 10 000; returns its id."""
    raise NotImplementedError


def events_after(coord, principal: Principal, after_id: int = 0, *, limit: int = 200) -> list[dict[str, Any]]:
    """Events with id > after_id visible to `principal` (client: its jobs; host: its site; admin/observer: all),
    oldest-first, at most `limit`. A gap (after_id older than the ring) simply starts at the oldest kept."""
    raise NotImplementedError


def last_event_id(coord) -> int:
    raise NotImplementedError
