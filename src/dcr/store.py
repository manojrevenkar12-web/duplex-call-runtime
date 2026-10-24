"""Call records in SQLite: every call's options, full event log and summary. One writer (the
server process); readers are the API and the evaluation."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
  id TEXT PRIMARY KEY,
  started_at TEXT NOT NULL,
  lang TEXT NOT NULL,
  scenario TEXT,
  options TEXT NOT NULL,
  events TEXT NOT NULL,
  summary TEXT NOT NULL,
  outcome TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS calls_started ON calls (started_at);
"""


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def save(self, call: dict[str, Any]) -> None:
        with self.lock, self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO calls (id, started_at, lang, scenario, options, events, summary, outcome) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    call["id"],
                    call["started_at"],
                    call["lang"],
                    call.get("scenario"),
                    json.dumps(call["options"]),
                    json.dumps(call["events"]),
                    json.dumps(call["summary"]),
                    json.dumps(call["outcome"]),
                ),
            )

    def list(self, limit: int = 100, scenario_prefix: str | None = None) -> list[dict[str, Any]]:
        q = "SELECT id, started_at, lang, scenario, options, summary, outcome FROM calls"
        args: list[Any] = []
        if scenario_prefix:
            q += " WHERE scenario LIKE ?"
            args.append(scenario_prefix + "%")
        q += " ORDER BY started_at DESC LIMIT ?"
        args.append(limit)
        with self._conn() as c:
            rows = c.execute(q, args).fetchall()
        return [_row(r) for r in rows]

    def get(self, call_id: str) -> dict[str, Any] | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()
        return _row(r) if r else None


def _row(r: sqlite3.Row) -> dict[str, Any]:
    d = dict(r)
    for k in ("options", "events", "summary", "outcome"):
        if k in d and d[k] is not None:
            d[k] = json.loads(d[k])
    return d
