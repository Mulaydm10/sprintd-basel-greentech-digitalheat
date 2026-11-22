"""Durable coordinator state: SQLite (WAL) under runs/coordinator/ (contracts/src/coordinator.md v1).

All access goes through `Store`, serialised by one re-entrant lock (FastAPI runs sync endpoints in a thread
pool). Every write commits before the request returns, so a crash loses nothing that was acknowledged.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS nodes (
  node_id TEXT PRIMARY KEY, site_id TEXT NOT NULL, eligible_classes TEXT NOT NULL, server_kw_el REAL NOT NULL,
  attestation TEXT NOT NULL, region TEXT NOT NULL, registered_at REAL NOT NULL,
  last_hb REAL NOT NULL, watts REAL, running_unit TEXT, progress REAL,
  tank_level_kwh REAL, demand_kw REAL, signal_at REAL, mode_running INTEGER NOT NULL DEFAULT 1,
  tampered INTEGER NOT NULL DEFAULT 0, last_error TEXT);
CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY, job_type TEXT NOT NULL, access_class TEXT NOT NULL, customer_id TEXT NOT NULL,
  deadline_hour INTEGER NOT NULL, priv_key BLOB, created_at REAL NOT NULL, admitted INTEGER NOT NULL,
  reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS units (
  unit_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, seq INTEGER NOT NULL, job_class TEXT NOT NULL,
  access_class TEXT NOT NULL, kwh_el REAL NOT NULL, bid REAL NOT NULL, deadline_hour INTEGER NOT NULL,
  slack_h REAL NOT NULL, checkpointable INTEGER NOT NULL, chunks INTEGER NOT NULL,
  state TEXT NOT NULL, result_sha256 TEXT, done_chunks TEXT, completed_at REAL, completed_by TEXT);
CREATE TABLE IF NOT EXISTS leases (
  lease_id TEXT PRIMARY KEY, unit_id TEXT NOT NULL, node_id TEXT NOT NULL, state TEXT NOT NULL,
  issued_at REAL NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS checkpoints (
  unit_id TEXT NOT NULL, seq INTEGER NOT NULL, next_chunk INTEGER NOT NULL, out_bytes INTEGER NOT NULL,
  sha256 TEXT NOT NULL, path TEXT NOT NULL, node_id TEXT NOT NULL, at REAL NOT NULL, PRIMARY KEY (unit_id, seq));
CREATE TABLE IF NOT EXISTS sites (
  site_id TEXT PRIMARY KEY, demand_kw REAL NOT NULL, tank_level_kwh REAL NOT NULL, ts REAL NOT NULL,
  received_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS audit (idx INTEGER PRIMARY KEY, event TEXT NOT NULL, prev_hash TEXT NOT NULL,
  hash TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS units_state ON units(state);
CREATE INDEX IF NOT EXISTS leases_state ON leases(state);
-- portal v1 (#83): live events (ring of 10 000; AUTOINCREMENT so an id is never reused after trimming)
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, type TEXT NOT NULL, client_id TEXT, site_id TEXT,
  node_id TEXT, job_id TEXT, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS events_client ON events(client_id, id);
CREATE INDEX IF NOT EXISTS events_site ON events(site_id, id);
CREATE TABLE IF NOT EXISTS site_override (site_id TEXT PRIMARY KEY, paused INTEGER NOT NULL, until_ts REAL,
  at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS site_hourly (site_id TEXT NOT NULL, hour_ts INTEGER NOT NULL, heat_kwh REAL NOT NULL,
  dumped_kwh REAL NOT NULL, demand_kwh REAL NOT NULL, PRIMARY KEY (site_id, hour_ts));
CREATE TABLE IF NOT EXISTS segments (job_id TEXT NOT NULL, seq INTEGER NOT NULL, path TEXT NOT NULL,
  sha256 TEXT NOT NULL, size INTEGER NOT NULL, received_at REAL NOT NULL, state TEXT NOT NULL, text TEXT, words TEXT,
  node TEXT, backend TEXT, ms REAL, accepted_at REAL, PRIMARY KEY (job_id, seq));  -- live transcription (#127)
CREATE TABLE IF NOT EXISTS results (unit_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, sha256 TEXT NOT NULL,
  path TEXT NOT NULL, bytes INTEGER NOT NULL);
"""

# forward migrations: (table, column, DDL) added to state.db files created before the column existed
MIGRATIONS = (
    ("nodes", "last_error", "ALTER TABLE nodes ADD COLUMN last_error TEXT"),  # #57 review
    ("units", "rounds", "ALTER TABLE units ADD COLUMN rounds INTEGER"),  # v1.1: per-unit runner rounds
    ("nodes", "drained", "ALTER TABLE nodes ADD COLUMN drained INTEGER NOT NULL DEFAULT 0"),  # portal v1
    ("jobs", "client_id", "ALTER TABLE jobs ADD COLUMN client_id TEXT"),  # portal v1: NULL = admin-submitted
    ("jobs", "idempotency_key", "ALTER TABLE jobs ADD COLUMN idempotency_key TEXT"),
    ("jobs", "cancelled_at", "ALTER TABLE jobs ADD COLUMN cancelled_at REAL"),
    ("jobs", "status", "ALTER TABLE jobs ADD COLUMN status TEXT"),  # last job.state emitted
    ("jobs", "ended_at", "ALTER TABLE jobs ADD COLUMN ended_at REAL"),  # #127 live transcription: client ended
    ("nodes", "backend", "ALTER TABLE nodes ADD COLUMN backend TEXT"),  # #127 transcriber backend from heartbeat
    ("segments", "flushed", "ALTER TABLE segments ADD COLUMN flushed TEXT"),  # #134 the final held-back tail
    ("jobs", "idem_params", "ALTER TABLE jobs ADD COLUMN idem_params TEXT"),  # F37: the request a key was used for
)


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)
        for table, col, ddl in MIGRATIONS:
            if col not in {r[1] for r in self.db.execute(f"PRAGMA table_info({table})")}:
                self.db.execute(ddl)
        self.db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS jobs_idem ON jobs(client_id, idempotency_key)
                           WHERE client_id IS NOT NULL AND idempotency_key IS NOT NULL""")
        self.db.execute("CREATE INDEX IF NOT EXISTS jobs_client ON jobs(client_id, created_at)")

    @contextmanager
    def tx(self, commit_on: tuple[type[BaseException], ...] = ()) -> Iterator[sqlite3.Connection]:
        """One serialised transaction: committed on success and on the expected business errors in
        `commit_on` (their audit rows and lease lapses must persist), rolled back on anything else."""
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield self.db
            except commit_on:
                self.db.execute("COMMIT")
                raise
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
            self.db.execute("COMMIT")

    def q(self, sql: str, *args: Any) -> list[sqlite3.Row]:
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def one(self, sql: str, *args: Any) -> sqlite3.Row | None:
        rows = self.q(sql, *args)
        return rows[0] if rows else None

    def meta_get(self, key: str) -> str | None:
        r = self.one("SELECT value FROM meta WHERE key=?", key)
        return None if r is None else r["value"]

    @staticmethod
    def meta_set(db: sqlite3.Connection, key: str, value: Any) -> None:
        db.execute("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (key, json.dumps(value) if not isinstance(value, str) else value))

    def close(self) -> None:
        with self.lock:
            self.db.close()
