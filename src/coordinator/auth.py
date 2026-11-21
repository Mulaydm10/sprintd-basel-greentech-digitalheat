"""Bearer-token auth, roles, per-token rate limit and request-size limits (coordinator v1: the URL is public).

tokens.json (never committed, lives under runs/coordinator/): {"<token>": "admin" | "observer" | "node:<id>" | "site:<id>"}.
Every token is compared with hmac.compare_digest and the loop never exits early, so timing does not reveal
which prefix matched.
"""
from __future__ import annotations

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
    """Pure-ASGI middleware: reject bodies over the limit with 413 before the app parses them.

    The limit is `large` for paths matching `large_path`, else `default`. A declared Content-Length over the
    limit is refused immediately; a streamed body is counted chunk by chunk.
    """

    def __init__(self, app, default: int, large: int, large_path: re.Pattern):
        self.app, self.default, self.large, self.large_path = app, default, large, large_path

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = self.large if self.large_path.match(scope.get("path", "")) else self.default
        for k, v in scope.get("headers", []):
            if k == b"content-length":
                try:
                    if int(v) > limit:
                        return await _reject(send, limit)
                except ValueError:
                    return await _reject(send, limit, status=400, msg="bad content-length")
        seen = 0
        too_big = False

        async def counted():
            nonlocal seen, too_big
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > limit:
                    too_big = True
                    return {"type": "http.request", "body": b"", "more_body": False}
            return msg

        started = False

        async def guarded_send(msg):
            nonlocal started
            if too_big and not started:
                started = True
                return await _reject(send, limit)
            if too_big:
                return None
            started = started or msg["type"] == "http.response.start"
            return await send(msg)

        await self.app(scope, counted, guarded_send)


async def _reject(send, limit: int, status: int = 413, msg: str | None = None):
    body = json.dumps({"detail": msg or f"request body larger than {limit} bytes"}).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
