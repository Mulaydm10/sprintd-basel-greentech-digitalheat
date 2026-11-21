"""Bearer-token auth, roles, per-token rate limit and request-size limits (coordinator v1: the URL is public).

tokens.json (never committed, lives under runs/coordinator/): {"<token>": "admin" | "observer" | "node:<id>" | "site:<id>"}.
Every token is compared with hmac.compare_digest and the loop never exits early, so timing does not reveal
which prefix matched.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ID_RE = re.compile(r"^[a-z0-9-]{1,64}$")
ROLE_RE = re.compile(r"^(admin|observer|node:[a-z0-9-]{1,64}|site:[a-z0-9-]{1,64})$")


@dataclass(frozen=True)
class Principal:
    role: str  # admin | observer | node | site
    node_id: str | None = None
    token_id: str = ""  # stable, non-secret key for rate limiting (index in the token file)
    site_id: str | None = None


def load_tokens(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or not data:
        raise ValueError(f"{path}: expected a non-empty JSON object token -> role")
    for tok, role in data.items():
        if not isinstance(tok, str) or len(tok) < 24:
            raise ValueError(f"{path}: every token must be a string of >= 24 characters")
        if not isinstance(role, str) or not ROLE_RE.match(role):
            raise ValueError(f"{path}: bad role {role!r}")
    return data


def authenticate(header: str | None, tokens: dict[str, str]) -> Principal | None:
    if not header or not header.startswith("Bearer "):
        return None
    presented = header[len("Bearer "):].strip().encode()
    found: tuple[int, str] | None = None
    for i, (tok, role) in enumerate(tokens.items()):
        if hmac.compare_digest(presented, tok.encode()) and found is None:
            found = (i, role)
    if found is None:
        return None
    i, role = found
    if role.startswith("node:"):
        return Principal("node", role.split(":", 1)[1], f"t{i}")
    if role.startswith("site:"):
        return Principal("site", None, f"t{i}", role.split(":", 1)[1])
    return Principal(role, None, f"t{i}")


class RateLimiter:
    """Token bucket per principal: `rate` requests/s, bursts up to `burst`.

    Always a real monotonic clock (coordinator v1.1): never the coordinator's injected (possibly frozen or
    simulated) clock, which would 429 a token forever once its bucket is empty."""

    def __init__(self, rate: float, burst: float, clock: Callable[[], float] = time.monotonic):
        self.rate, self.burst, self.clock = rate, burst, clock
        self.state: dict[str, tuple[float, float]] = {}
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        with self.lock:
            now = self.clock()
            tokens, last = self.state.get(key, (self.burst, now))
            tokens = min(self.burst, tokens + max(0.0, now - last) * self.rate)
            if tokens < 1.0:
                self.state[key] = (tokens, now)
                return False
            self.state[key] = (tokens - 1.0, now)
            return True


class BodyLimit:
    """Pure-ASGI middleware: reject bodies over the limit with 413 before the app parses them, and slow bodies
    with 408 (red team F34, slow-loris).

    The limit is `large` for paths matching `large_path`, else `default`. A declared Content-Length over the
    limit is refused immediately; a streamed body is counted chunk by chunk. Reading the body must make
    progress: no bytes for `idle_s` -> 408, and the whole body must arrive within
    max(`min_total_s`, declared length / `min_rate_bps`) -> 408, so a held-open upload cannot pin a worker.
    """

    def __init__(self, app, default: int, large: int, large_path: re.Pattern, idle_s: float = 3.0,
                 min_total_s: float = 10.0, min_rate_bps: float = 256 * 1024):
        self.app, self.default, self.large, self.large_path = app, default, large, large_path
        self.idle_s, self.min_total_s, self.min_rate_bps = idle_s, min_total_s, min_rate_bps

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = self.large if self.large_path.match(scope.get("path", "")) else self.default
        declared = 0
        for k, v in scope.get("headers", []):
            if k == b"content-length":
                try:
                    declared = int(v)
                    if declared > limit:
                        return await _reject(send, limit)
                except ValueError:
                    return await _reject(send, limit, status=400, msg="bad content-length")
        seen = 0
        too_big = False
        too_slow = False
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(self.min_total_s, declared / self.min_rate_bps)
        done_reading = False

        async def counted():
            nonlocal seen, too_big, too_slow, done_reading
            if done_reading or too_slow or too_big:
                return await receive()  # after the body: disconnect notifications etc.
            wait = min(self.idle_s, deadline - loop.time())
            try:
                msg = await asyncio.wait_for(receive(), timeout=max(0.0, wait))
            except asyncio.TimeoutError:
                too_slow = True
                return {"type": "http.disconnect"}
            if msg["type"] == "http.request":
                if not msg.get("more_body", False):
                    done_reading = True
                seen += len(msg.get("body", b""))
                if seen > limit:
                    too_big = True
                    return {"type": "http.request", "body": b"", "more_body": False}
            return msg

        started = False

        async def guarded_send(msg):
            nonlocal started
            if (too_big or too_slow) and not started:
                started = True
                if too_slow:
                    return await _reject(send, limit, status=408, msg="request body too slow")
                return await _reject(send, limit)
            if too_big or too_slow:
                return None
            started = started or msg["type"] == "http.response.start"
            return await send(msg)

        try:
            await self.app(scope, counted, guarded_send)
        finally:
            if too_slow and not started:  # the app gave up without answering (client disconnect): answer 408
                started = True
                await _reject(send, limit, status=408, msg="request body too slow")


async def _reject(send, limit: int, status: int = 413, msg: str | None = None):
    body = json.dumps({"detail": msg or f"request body larger than {limit} bytes"}).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


class ConnCap:
    """Pure-ASGI middleware: at most `per_client` requests in flight per client, checked BEFORE auth (F34).

    Behind Tailscale Funnel every request arrives from 127.0.0.1, so the client key is the first
    X-Forwarded-For hop when (and only when) the peer is loopback; otherwise the peer address. Over the cap -> 503.
    """

    def __init__(self, app, per_client: int = 16):
        self.app, self.per_client = app, per_client
        self.inflight: dict[str, int] = {}

    def _key(self, scope) -> str:
        peer = (scope.get("client") or ("?", 0))[0]
        if peer in ("127.0.0.1", "::1"):
            for k, v in scope.get("headers", []):
                if k == b"x-forwarded-for":
                    return v.decode("latin-1").split(",")[0].strip() or peer
        return peer

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        key = self._key(scope)
        if self.inflight.get(key, 0) >= self.per_client:
            body = b'{"detail":"too many concurrent requests from this client"}'
            await send({"type": "http.response.start", "status": 503,
                        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                                    (b"retry-after", b"2")]})
            return await send({"type": "http.response.body", "body": body})
        self.inflight[key] = self.inflight.get(key, 0) + 1
        try:
            await self.app(scope, receive, send)
        finally:
            self.inflight[key] -= 1
            if self.inflight[key] <= 0:
                del self.inflight[key]
