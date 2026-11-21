"""The store interface the portal routers call (P3 ops + events). Proposed to P1 on #83.

``StoreBackend`` binds it to ``coordinator.portal_store`` (P1, #83), imported lazily so this lane imports and tests
cleanly before P1 lands. Unit tests use an in-memory fake with the same methods.
"""
from __future__ import annotations

from typing import Any, Protocol


class Backend(Protocol):
    # events
    def events_after(self, principal: Any, after_id: int, limit: int = 200) -> list[dict[str, Any]]: ...
    def events_head(self) -> int: ...
    # ops reads
    def ops_overview(self) -> dict[str, Any]: ...
    def ops_nodes(self, limit: int, cursor: str | None) -> dict[str, Any]: ...
    def ops_jobs(self, limit: int, cursor: str | None) -> dict[str, Any]: ...
    def ops_sites(self, limit: int, cursor: str | None) -> dict[str, Any]: ...
    def ops_audit(self, limit: int, cursor: str | None) -> dict[str, Any]: ...
    # ops actions (idempotent, audited, emit their event)
    def drain_node(self, node_id: str, drained: bool) -> dict[str, Any]: ...
    def kill_node(self, node_id: str) -> dict[str, Any]: ...
    def tamper(self, node_id: str) -> dict[str, Any]: ...
    def set_site_scenario(self, site_id: str, replay: str) -> dict[str, Any]: ...


class StoreBackend:
    """Backend over a live ``coordinator.core.Coordinator`` and P1's ``coordinator.portal_store``."""

    def __init__(self, coord: Any) -> None:
        from coordinator import portal_store  # P1 (#83)
        self.coord, self.ps = coord, portal_store

    def events_after(self, principal, after_id, limit=200):
        return self.ps.events_after(self.coord, principal, after_id, limit)

    def events_head(self):
        return self.ps.events_head(self.coord)

    def ops_overview(self):
        return self.ps.ops_overview(self.coord)

    def ops_nodes(self, limit, cursor):
        return self.ps.ops_nodes(self.coord, limit, cursor)

    def ops_jobs(self, limit, cursor):
        return self.ps.ops_jobs(self.coord, limit, cursor)

    def ops_sites(self, limit, cursor):
        return self.ps.ops_sites(self.coord, limit, cursor)

    def ops_audit(self, limit, cursor):
        return self.ps.ops_audit(self.coord, limit, cursor)

    def drain_node(self, node_id, drained):
        return self.ps.drain_node(self.coord, node_id, drained)

    def kill_node(self, node_id):
        return self.ps.kill_node(self.coord, node_id)

    def tamper(self, node_id):
        r = self.coord.tamper(node_id)  # existing coordinator action (audited, leases revoked)
        return {"node_id": node_id, **(r if isinstance(r, dict) else {})}

    def set_site_scenario(self, site_id, replay):
        return self.ps.set_site_scenario(self.coord, site_id, replay)
