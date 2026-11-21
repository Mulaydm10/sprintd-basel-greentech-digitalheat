"""python -m live_agent --coordinator URL --node-id ID --token-file PATH [--site-id S] [--backend cpu-hash|fake]

Runs the node agent against a coordinator (contract live_agent v2). The bearer token is read from a file, never from
the command line (it would show in `ps`) and never logged. No inbound ports.
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
from pathlib import Path

import httpx

from .agent import BACKENDS, Agent, Config, Fatal


def read_token(path: Path) -> str:
    tok = path.read_text().strip()
    if not tok or any(c.isspace() for c in tok):
        raise SystemExit(f"{path}: expected one token without whitespace")
    return tok


def client(url: str, token: str) -> httpx.Client:
    return httpx.Client(base_url=url.rstrip("/"), headers={"Authorization": f"Bearer {token}"},
                        timeout=httpx.Timeout(10.0, connect=5.0))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m live_agent", description=__doc__.splitlines()[0])
    p.add_argument("--coordinator", required=True, help="e.g. https://<host>.ts.net")
    p.add_argument("--node-id", required=True)
    p.add_argument("--token-file", required=True, type=Path)
    p.add_argument("--site-id", default=None, help="default: the node id")
    p.add_argument("--backend", default="cpu-hash", choices=BACKENDS)
    p.add_argument("--eligible", default="public", help="comma-separated access classes this node may run")
    p.add_argument("--certified", action="store_true", help="evidence flag for the (mock) attestation")
    p.add_argument("--server-kw-el", type=float, default=1.0)
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Config(node_id=a.node_id, site_id=a.site_id or a.node_id, eligible_classes=a.eligible.split(","),
                 server_kw_el=a.server_kw_el, certified=a.certified, backend=a.backend)
    tok = read_token(a.token_file)
    stop = threading.Event()
    for s in (signal.SIGINT, signal.SIGTERM):
        signal.signal(s, lambda *_: stop.set())
    with client(a.coordinator, tok) as http, client(a.coordinator, tok) as hb:
        try:
            Agent(cfg, http, hb_http=hb).run_forever(stop)
        except Fatal as e:
            print(f"live_agent: {e}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
