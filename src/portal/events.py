"""Live events (contract portal v1, P3): ``GET /v1/events`` (Server-Sent Events) and ``GET /v1/events/poll``.

- Every role may connect; the backend filters events **in SQL** by role (client: own jobs, host: own site,
  admin/observer: everything).
- Resume: ``Last-Event-ID`` header (what ``EventSource`` sends on reconnect) or ``?last_event_id=``; the stream
  continues after that id from the store's events table (ring of 10 000). Without one it starts at the head.
- A keep-alive comment every ``KEEPALIVE_S`` (15 s), so proxies and the Funnel keep the connection open.
- At most ``MAX_STREAMS`` (4) concurrent streams per token → 429.
- No unbounded buffering: each event is sent with a deadline (``SEND_TIMEOUT_S``); a consumer that cannot take it
  in time is **dropped**, not queued. The stream slot is released on disconnect, drop, error or cancel.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Annotated, Any, Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

MAX_STREAMS = 4
KEEPALIVE_S = 15.0
POLL_S = 0.5
SEND_TIMEOUT_S = 10.0
BATCH = 200


class Event(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: int
    type: str
    ts: str
    data: dict[str, Any] = {}


class PollOut(BaseModel):
    events: list[Event]
    last_id: int


class StreamSlots:
    """Per-token concurrent stream counter (thread-safe: TestClient and uvicorn may use threads)."""

    def __init__(self, limit: int = MAX_STREAMS) -> None:
        self.limit, self._n, self._lock = limit, {}, threading.Lock()

    def acquire(self, key: str) -> bool:
        with self._lock:
            if self._n.get(key, 0) >= self.limit:
                return False
            self._n[key] = self._n.get(key, 0) + 1
            return True

    def release(self, key: str) -> None:
        with self._lock:
            n = self._n.get(key, 0) - 1
            if n <= 0:
                self._n.pop(key, None)
            else:
                self._n[key] = n

    def count(self, key: str) -> int:
        with self._lock:
            return self._n.get(key, 0)


def format_event(e: dict[str, Any]) -> bytes:
    data = json.dumps({k: v for k, v in e.items() if k != "id"}, separators=(",", ":"), sort_keys=True)
    # data is one JSON line (json.dumps escapes newlines), so a single "data:" field is valid SSE
    return f"id: {int(e['id'])}\nevent: {e['type']}\ndata: {data}\n\n".encode()


class EventStream(Response):
    """A minimal ASGI SSE response: pulls from the backend, sends with a deadline, stops on disconnect."""

    media_type = "text/event-stream"

    def __init__(self, fetch: Callable[[int], list[dict[str, Any]]], start_id: int, on_close: Callable[[], None],
                 keepalive_s: float = KEEPALIVE_S, poll_s: float = POLL_S, send_timeout_s: float = SEND_TIMEOUT_S,
                 max_events: int | None = None) -> None:
        self.background = None  # Response API used by FastAPI; no Response.__init__ (we stream ourselves)
        self.status_code = 200
        self.fetch, self.last, self.on_close = fetch, start_id, on_close
        self.keepalive_s, self.poll_s, self.send_timeout_s = keepalive_s, poll_s, send_timeout_s
        self.max_events = max_events  # tests only: end the stream after N events
        self.dropped = False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        disconnected = asyncio.Event()

        async def watch() -> None:
            while True:
                msg = await receive()
                if msg["type"] == "http.disconnect":
                    disconnected.set()
                    return

        watcher = asyncio.create_task(watch())
        try:
            await send({"type": "http.response.start", "status": 200, "headers": [
                (b"content-type", b"text/event-stream; charset=utf-8"), (b"cache-control", b"no-cache"),
                (b"x-accel-buffering", b"no"), (b"connection", b"keep-alive")]})
            if not await self._send(send, b": stream open\n\n"):
                return
            sent, last_beat = 0, time.monotonic()
            while not disconnected.is_set():
                events = await run_in_threadpool(self.fetch, self.last)
                for e in events:
                    if not await self._send(send, format_event(e)):
                        return
                    self.last = int(e["id"])
                    sent += 1
                    if self.max_events is not None and sent >= self.max_events:
                        return
                if events:
                    last_beat = time.monotonic()
                    continue
                if time.monotonic() - last_beat >= self.keepalive_s:
                    if not await self._send(send, b": keep-alive\n\n"):
                        return
                    last_beat = time.monotonic()
                try:
                    await asyncio.wait_for(disconnected.wait(), timeout=self.poll_s)
                except asyncio.TimeoutError:
                    pass
        finally:
            watcher.cancel()
            try:
                await send({"type": "http.response.body", "body": b"", "more_body": False})
            except Exception:  # client already gone
                pass
            self.on_close()

    async def _send(self, send: Send, chunk: bytes) -> bool:
        try:
            await asyncio.wait_for(send({"type": "http.response.body", "body": chunk, "more_body": True}),
                                   timeout=self.send_timeout_s)
            return True
        except asyncio.TimeoutError:
            self.dropped = True  # slow consumer: drop it, never buffer
            return False
        except Exception:  # broken pipe / client gone
            return False


def make_router(principal: Callable[..., Any], backend: Callable[[], Any], slots: StreamSlots | None = None,
                **stream_kw: Any) -> APIRouter:
    r = APIRouter(prefix="/v1/events", tags=["events"])
    slots = slots or StreamSlots()

    def start_id(header: str | None, query: int | None) -> int:
        raw = header if header is not None else query
        if raw is None:
            return int(backend().events_head())
        try:
            v = int(str(raw).strip())
        except ValueError:
            raise HTTPException(422, "Last-Event-ID must be a non-negative integer") from None
        if v < 0:
            raise HTTPException(422, "Last-Event-ID must be a non-negative integer")
        return v

    @r.get("", responses={200: {"content": {"text/event-stream": {}},
                                                        "description": "Server-Sent Events"},
                                                   429: {"description": "too many concurrent streams"}})
    async def stream(request: Request, p=Depends(principal),
                     last_event_id: Annotated[str | None, Header(alias="Last-Event-ID", max_length=20)] = None,
                     last_event_id_q: Annotated[int | None, Query(alias="last_event_id", ge=0)] = None):
        start = start_id(last_event_id, last_event_id_q)
        key = p.token_id or p.role
        if not slots.acquire(key):
            raise HTTPException(429, f"at most {slots.limit} concurrent event streams per token")
        released = threading.Event()

        def close() -> None:
            if not released.is_set():
                released.set()
                slots.release(key)

        try:
            b = backend()
            return EventStream(lambda after: b.events_after(p, after, BATCH), start, close, **stream_kw)
        except BaseException:
            close()
            raise

    @r.get("/poll", response_model=PollOut)
    def poll(after: Annotated[int, Query(ge=0)] = 0, limit: Annotated[int, Query(ge=1, le=BATCH)] = BATCH,
             p=Depends(principal)):
        events = backend().events_after(p, after, limit)
        return {"events": events, "last_id": int(events[-1]["id"]) if events else after}

    r.slots = slots  # type: ignore[attr-defined]  # exposed for tests and status
    return r
