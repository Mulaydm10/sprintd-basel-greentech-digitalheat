"""python -m coordinator [--state runs/coordinator] [--host 127.0.0.1] [--port 8710] [--make-tokens node-a,node-b] [--make-site-tokens site-a]

Binds 127.0.0.1 by default (Tailscale Funnel forwards to it). For direct tailnet access pass the tailnet
address with --host. `--make-tokens` writes runs/coordinator/tokens.json (admin, observer, one per node, one `site:<id>` per
--make-site-tokens site, for coordinator.sitesim) if
it does not exist yet and prints where; tokens are never printed or committed.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import threading
import time
from pathlib import Path

from common.config import ROOT


def make_tokens(path: Path, nodes: list[str], sites: list[str] | None = None) -> bool:
    from .auth import ID_RE
    for i in [*nodes, *(sites or [])]:
        if not ID_RE.match(i):
            raise SystemExit(f"bad id {i!r}: must match {ID_RE.pattern}")
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    roles = ["admin", "observer"] + [f"node:{n}" for n in nodes] + [f"site:{s}" for s in sites or []]
    data = {secrets.token_urlsafe(32): r for r in roles}
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m coordinator")
    ap.add_argument("--state", type=Path, default=ROOT / "runs" / "coordinator")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8710)
    ap.add_argument("--make-tokens", default=None, help="comma-separated node ids; creates tokens.json once")
    ap.add_argument("--make-site-tokens", default=None,
                    help="comma-separated site ids (role site:<id>, for POST /v1/sites/<id>/signal)")
    ns = ap.parse_args(argv)
    if ns.make_tokens is not None or ns.make_site_tokens is not None:
        nodes = [n for n in (ns.make_tokens or "").split(",") if n]
        sites = [n for n in (ns.make_site_tokens or "").split(",") if n]
        made = make_tokens(ns.state / "tokens.json", nodes, sites)
        print(f"{'wrote' if made else 'kept existing'} {ns.state / 'tokens.json'} (mode 600; not printed)")
        return 0

    import uvicorn

    from .app import create_app
    app = create_app(ns.state)
    coord = app.state.coord
    stop = threading.Event()

    def ticker():  # keeps alive_at fresh and lapses expired leases even when no request arrives
        while not stop.wait(1.0):
            try:
                coord.tick()
            except Exception:  # noqa: BLE001 - never let the ticker die
                pass

    threading.Thread(target=ticker, daemon=True).start()
    try:
        uvicorn.run(app, host=ns.host, port=ns.port, log_level="info", proxy_headers=False,
                    limit_concurrency=64, timeout_keep_alive=5)
    finally:
        stop.set()
    return 0


if __name__ == "__main__":
    sys.exit(main())
