"""python -m coordinator [--state runs/coordinator] [--host 127.0.0.1] [--port 8710] [--make-tokens node-a,node-b] [--make-site-tokens site-a]
       python -m coordinator --register-node ID [--certified] [--classes public,swiss-only,certified] [--region CH-BS] [--site ID]

Binds 127.0.0.1 by default (Tailscale Funnel forwards to it). For direct tailnet access pass the tailnet
address with --host. `--make-tokens` writes runs/coordinator/tokens.json (admin, observer, one per node, one `site:<id>` per
--make-site-tokens site, for coordinator.sitesim) (adding any missing roles to an existing file
without changing its tokens) and prints where; tokens are never printed or committed.
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
    from .auth import ID_RE, load_tokens
    for i in [*nodes, *(sites or [])]:
        if not ID_RE.match(i):
            raise SystemExit(f"bad id {i!r}: must match {ID_RE.pattern}")
    roles = ["admin", "observer"] + [f"node:{n}" for n in nodes] + [f"site:{s}" for s in sites or []]
    data: dict[str, str] = {}
    if path.exists():
        data = dict(load_tokens(path))  # validates; refuses to rewrite a malformed file
    have = set(data.values())
    missing = [r for r in dict.fromkeys(roles) if r not in have]
    if not missing:
        return False
    data.update({secrets.token_urlsafe(32): r for r in missing})  # existing tokens untouched
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return True

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m coordinator")
    ap.add_argument("--state", type=Path, default=ROOT / "runs" / "coordinator")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8710)
    ap.add_argument("--make-tokens", default=None, help="comma-separated node ids; adds missing roles to tokens.json")
    ap.add_argument("--make-site-tokens", default=None,
                    help="comma-separated site ids (role site:<id>, for POST /v1/sites/<id>/signal)")
    ap.add_argument("--register-node", default=None, metavar="ID",
                    help="add/replace one node in the operator registry nodes.json (v1.2; mode 600)")
    ap.add_argument("--certified", action="store_true", help="with --register-node: the node is certified")
    ap.add_argument("--classes", default="public", help="with --register-node: max classes, comma-separated")
    ap.add_argument("--region", default="CH-BS", help="with --register-node: region")
    ap.add_argument("--site", default=None, help="with --register-node: the only site_id it may register (default: ID)")
    ns = ap.parse_args(argv)
    if ns.register_node is not None:
        from .registry import register_node
        classes = [c for c in ns.classes.split(",") if c]
        try:
            e = register_node(ns.state / "nodes.json", ns.register_node, ns.certified, classes, ns.region, ns.site)
        except ValueError as err:
            raise SystemExit(str(err))
        print(f"registered {ns.register_node} {e} in {ns.state / 'nodes.json'} (mode 600); restart the coordinator")
        return 0
    if ns.make_tokens is not None or ns.make_site_tokens is not None:
        nodes = [n for n in (ns.make_tokens or "").split(",") if n]
        sites = [n for n in (ns.make_site_tokens or "").split(",") if n]
        made = make_tokens(ns.state / "tokens.json", nodes, sites)
        print(f"{'updated' if made else 'nothing to add to'} {ns.state / 'tokens.json'} (mode 600; not printed)")
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
