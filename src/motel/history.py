"""Run history: a SQLite record of every tool call, with provenance.

The history is Motel's memory. Each run stores the tool version and source
commit, the exact arguments, the result, output files, and timing, so a later
question can be answered from earlier work, and identical calls can be served
from cache.

Connections are short-lived and the database runs in WAL mode, so the CLI, the
MCP gateway, and background runs can use it concurrently.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from motel.models import RunRecord, RunStatus

_MIGRATIONS: list[str] = [
    # 1: initial schema
    """
    CREATE TABLE runs (
        id             TEXT PRIMARY KEY,
        tool           TEXT NOT NULL,
        function       TEXT NOT NULL,
        args           TEXT NOT NULL,
        status         TEXT NOT NULL,
        tool_version   TEXT,
        source_commit  TEXT,
        result         TEXT,
        error          TEXT,
        files          TEXT NOT NULL DEFAULT '[]',
        workdir        TEXT NOT NULL,
        run_dir        TEXT NOT NULL,
        pid            INTEGER,
        origin         TEXT NOT NULL,
        cache_key      TEXT,
        started_at     TEXT NOT NULL,
        finished_at    TEXT,
        duration       REAL
    );
    CREATE INDEX runs_tool_started ON runs (tool, started_at);
    CREATE INDEX runs_started ON runs (started_at);
    CREATE INDEX runs_cache_key ON runs (cache_key, status);
    """,
]

_JSON_COLUMNS = ("args", "result", "error", "files")


def new_run_id(now: datetime | None = None) -> str:
    """A sortable, readable id such as ``20261018-114501-3f9a2c``."""
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{secrets.token_hex(3)}"


class RunStore:
    """Persistent storage for :class:`RunRecord` objects."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._migrated = False

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            if not self._migrated:
                self._migrate(connection)
                self._migrated = True
            with connection:  # commit or roll back
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA journal_mode=WAL")
        if connection.execute("PRAGMA user_version").fetchone()[0] >= len(_MIGRATIONS):
            return
        previous_mode = connection.isolation_level
        connection.isolation_level = None  # manage the transaction explicitly
        try:
            # IMMEDIATE takes the write lock now, so concurrent processes migrate one at a time.
            connection.execute("BEGIN IMMEDIATE")
            try:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                for number, script in enumerate(_MIGRATIONS[version:], start=version + 1):
                    for statement in filter(str.strip, script.split(";")):
                        connection.execute(statement)
                    connection.execute(f"PRAGMA user_version = {number}")
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
        finally:
            connection.isolation_level = previous_mode

    # ----------------------------------------------------------------- write

    def insert(self, record: RunRecord) -> None:
        row = _to_row(record)
        columns = ", ".join(row)
        placeholders = ", ".join(f":{name}" for name in row)
        with self._connect() as db:
            db.execute(f"INSERT INTO runs ({columns}) VALUES ({placeholders})", row)  # noqa: S608

    def finish(
        self,
        run_id: str,
        *,
        status: RunStatus,
        result: Any = None,
        error: dict[str, Any] | None = None,
        files: list[str] | None = None,
        finished_at: datetime,
        duration: float | None,
    ) -> bool:
        """Record the outcome of a running run. Returns ``False`` if it was already finished."""
        with self._connect() as db:
            cursor = db.execute(
                """
                UPDATE runs
                   SET status = ?, result = ?, error = ?, files = ?, finished_at = ?, duration = ?
                 WHERE id = ? AND status = ?
                """,
                (
                    status.value,
                    _dump(result),
                    _dump(error),
                    json.dumps(files or []),
                    finished_at.isoformat(),
                    duration,
                    run_id,
                    RunStatus.RUNNING.value,
                ),
            )
            return cursor.rowcount == 1

    def delete_for_tool(self, tool: str) -> int:
        with self._connect() as db:
            return db.execute("DELETE FROM runs WHERE tool = ?", (tool,)).rowcount

    # ------------------------------------------------------------------ read

    def get(self, run_id: str) -> RunRecord | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return _from_row(row) if row else None

    def query(
        self,
        *,
        tool: str | None = None,
        status: RunStatus | None = None,
        query: str | None = None,
        limit: int = 20,
    ) -> list[RunRecord]:
        """Newest runs first, optionally filtered by tool, status, and free-text query.

        Every word of ``query`` must appear somewhere in the run's tool, function,
        arguments, result, or error.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if tool:
            clauses.append("tool = ?")
            params.append(tool)
        if status:
            clauses.append("status = ?")
            params.append(status.value)
        for word in (query or "").split():
            clauses.append(
                "(tool || ' ' || function || ' ' || args || ' ' || COALESCE(result, '') || ' ' "
                "|| COALESCE(error, '')) LIKE ? ESCAPE '\\'"
            )
            params.append(f"%{_escape_like(word)}%")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, limit))
        with self._connect() as db:
            rows = db.execute(
                f"SELECT * FROM runs {where} ORDER BY started_at DESC LIMIT ?",  # noqa: S608
                params,
            ).fetchall()
        return [_from_row(row) for row in rows]

    def find_cached(self, cache_key: str) -> RunRecord | None:
        """Most recent successful run with this cache key."""
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM runs WHERE cache_key = ? AND status = ? "
                "ORDER BY started_at DESC LIMIT 1",
                (cache_key, RunStatus.SUCCEEDED.value),
            ).fetchone()
        return _from_row(row) if row else None

    def running(self) -> list[RunRecord]:
        return self.query(status=RunStatus.RUNNING, limit=10_000)

    def count(self) -> int:
        with self._connect() as db:
            count: int = db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        return count


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _dump(value: Any) -> str | None:
    return None if value is None else json.dumps(value)


def _to_row(record: RunRecord) -> dict[str, Any]:
    data = record.model_dump(mode="json", exclude={"cached"})
    for column in _JSON_COLUMNS:
        data[column] = (
            json.dumps(data[column]) if column in ("args", "files") else _dump(data[column])
        )
    return data


def _from_row(row: sqlite3.Row) -> RunRecord:
    data = dict(row)
    for column in _JSON_COLUMNS:
        if data[column] is not None:
            data[column] = json.loads(data[column])
    data["files"] = data["files"] or []
    return RunRecord.model_validate(data)
