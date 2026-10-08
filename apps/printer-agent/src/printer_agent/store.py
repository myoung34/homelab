"""Small SQLite store for state nothing else in the homelab keeps.

- config_events/config_blobs: which printer.cfg (on disk, and as loaded by
  Klipper) was active when. Klipper's own log only keeps ~5 days.
- jobs: Moonraker job outcomes joined to the config that was loaded when the
  job started; this is what "known good" and "known bad" mean.
- audit: every privileged action attempt.
- proposals: config change proposals awaiting approval/applied.
- diagnoses: past diagnostic results (failure classifications).

Operations are tiny, local and serialized by a lock; they are called inline.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS config_blobs (
    sha TEXT PRIMARY KEY,
    content TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS config_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    printer TEXT NOT NULL,
    kind TEXT NOT NULL,            -- 'file' (on disk) or 'loaded' (running)
    sha TEXT NOT NULL,
    ts REAL NOT NULL,              -- when this sha became current (best known)
    source TEXT NOT NULL           -- 'poll', 'klippy.log', 'apply', ...
);
CREATE INDEX IF NOT EXISTS config_events_idx ON config_events(printer, kind, ts);
CREATE TABLE IF NOT EXISTS jobs (
    printer TEXT NOT NULL,
    job_id TEXT NOT NULL,
    status TEXT NOT NULL,
    filename TEXT,
    start_time REAL,
    end_time REAL,
    loaded_sha TEXT,
    PRIMARY KEY (printer, job_id)
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    action TEXT NOT NULL,
    printer TEXT NOT NULL,
    risk TEXT NOT NULL,
    outcome TEXT NOT NULL,
    params TEXT NOT NULL,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY,
    printer TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    status TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS diagnoses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    printer TEXT NOT NULL,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    subject TEXT,
    top_class TEXT,
    body TEXT NOT NULL
);
"""


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Store:
    def __init__(self, path: Path | str) -> None:
        self._path = str(path)
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._tx() as c:
            c.executescript(SCHEMA)
            c.execute("PRAGMA journal_mode=WAL")

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            yield self._conn

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --------------------------------------------------------------- configs

    def record_config(
        self, printer: str, kind: str, content: str, *, ts: float | None = None, source: str
    ) -> tuple[str, bool]:
        """Record content as current. Returns (sha, changed?)."""
        digest = sha256(content)
        when = time.time() if ts is None else ts
        with self._tx() as c:
            c.execute("INSERT OR IGNORE INTO config_blobs(sha, content) VALUES (?, ?)", (digest, content))
            row = c.execute(
                "SELECT sha FROM config_events WHERE printer=? AND kind=? AND ts<=? ORDER BY ts DESC, id DESC LIMIT 1",
                (printer, kind, when),
            ).fetchone()
            if row is not None and row["sha"] == digest:
                return digest, False
            # Backfilled events can arrive out of order; avoid duplicates.
            dup = c.execute(
                "SELECT 1 FROM config_events WHERE printer=? AND kind=? AND sha=? AND ts=?",
                (printer, kind, digest, when),
            ).fetchone()
            if dup is None:
                c.execute(
                    "INSERT INTO config_events(printer, kind, sha, ts, source) VALUES (?,?,?,?,?)",
                    (printer, kind, digest, when, source),
                )
        return digest, True

    def config_at(self, printer: str, kind: str, ts: float) -> dict[str, Any] | None:
        with self._tx() as c:
            row = c.execute(
                "SELECT e.sha, e.ts, e.source, b.content FROM config_events e "
                "JOIN config_blobs b ON b.sha=e.sha "
                "WHERE e.printer=? AND e.kind=? AND e.ts<=? ORDER BY e.ts DESC, e.id DESC LIMIT 1",
                (printer, kind, ts),
            ).fetchone()
        return dict(row) if row else None

    def config_blob(self, sha_prefix: str) -> dict[str, Any] | None:
        if len(sha_prefix) < 7:
            return None
        with self._tx() as c:
            rows = c.execute("SELECT sha, content FROM config_blobs WHERE sha LIKE ?", (f"{sha_prefix}%",)).fetchall()
        return dict(rows[0]) if len(rows) == 1 else None

    def config_events(self, printer: str, kind: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._tx() as c:
            rows = c.execute(
                "SELECT sha, ts, source FROM config_events WHERE printer=? AND kind=? "
                "ORDER BY ts DESC, id DESC LIMIT ?",
                (printer, kind, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ jobs

    def record_job(self, printer: str, job: dict[str, Any]) -> None:
        start = job.get("start_time")
        loaded = self.config_at(printer, "loaded", float(start)) if start else None
        with self._tx() as c:
            c.execute(
                "INSERT INTO jobs(printer, job_id, status, filename, start_time, end_time, "
                "loaded_sha) VALUES (?,?,?,?,?,?,?) ON CONFLICT(printer, job_id) DO UPDATE SET "
                "status=excluded.status, end_time=excluded.end_time, "
                "loaded_sha=COALESCE(jobs.loaded_sha, excluded.loaded_sha)",
                (
                    printer,
                    str(job.get("job_id")),
                    str(job.get("status")),
                    job.get("filename"),
                    start,
                    job.get("end_time"),
                    loaded["sha"] if loaded else None,
                ),
            )

    def jobs(self, printer: str, limit: int = 200) -> list[dict[str, Any]]:
        with self._tx() as c:
            rows = c.execute(
                "SELECT * FROM jobs WHERE printer=? ORDER BY start_time DESC LIMIT ?",
                (printer, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ audit

    def record_audit(self, entry: dict[str, Any]) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT INTO audit(ts, action, printer, risk, outcome, params, detail) VALUES (?,?,?,?,?,?,?)",
                (
                    entry["ts"],
                    entry["action"],
                    entry["printer"],
                    entry["risk"],
                    entry["outcome"],
                    json.dumps(entry.get("params", {}), default=str),
                    entry.get("detail"),
                ),
            )

    def audit(self, printer: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        q = "SELECT * FROM audit"
        args: tuple[Any, ...] = ()
        if printer:
            q += " WHERE printer=?"
            args = (printer,)
        q += " ORDER BY ts DESC LIMIT ?"
        with self._tx() as c:
            rows = c.execute(q, (*args, limit)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["params"] = json.loads(d["params"])
            out.append(d)
        return out

    # -------------------------------------------------------------- proposals

    def save_proposal(self, proposal: dict[str, Any]) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT INTO proposals(id, printer, created_at, expires_at, status, body) "
                "VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status, "
                "body=excluded.body",
                (
                    proposal["id"],
                    proposal["printer"],
                    proposal["created_at"],
                    proposal["expires_at"],
                    proposal["status"],
                    json.dumps(proposal, default=str),
                ),
            )

    def get_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        with self._tx() as c:
            row = c.execute("SELECT body FROM proposals WHERE id=?", (proposal_id,)).fetchone()
        return json.loads(row["body"]) if row else None

    # -------------------------------------------------------------- diagnoses

    def record_diagnosis(
        self,
        printer: str,
        kind: str,
        subject: str | None,
        top_class: str | None,
        body: dict[str, Any],
    ) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT INTO diagnoses(printer, ts, kind, subject, top_class, body) VALUES (?,?,?,?,?,?)",
                (printer, time.time(), kind, subject, top_class, json.dumps(body, default=str)),
            )

    def diagnoses(self, printer: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._tx() as c:
            rows = c.execute(
                "SELECT id, ts, kind, subject, top_class FROM diagnoses WHERE printer=? ORDER BY ts DESC LIMIT ?",
                (printer, limit),
            ).fetchall()
        return [dict(r) for r in rows]
