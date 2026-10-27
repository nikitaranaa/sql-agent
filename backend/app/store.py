"""Writable application state: accounts, synced conversations and answer feedback.

Postgres when DATABASE_URL is set (persistent on a free host such as Neon), otherwise a
local SQLite file. This is separate from the sample database, which stays read-only.
Queries are written with ``?`` placeholders and converted for Postgres.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Iterator

from app.config import get_settings

_SQLITE_DDL = [
    """CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS conversations (
        user_id INTEGER NOT NULL,
        id TEXT NOT NULL,
        title TEXT NOT NULL,
        messages TEXT NOT NULL,
        updated_at REAL NOT NULL,
        PRIMARY KEY (user_id, id))""",
    """CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        user_id INTEGER,
        question TEXT NOT NULL,
        sql TEXT NOT NULL,
        rating TEXT NOT NULL,
        comment TEXT NOT NULL,
        created_at REAL NOT NULL)""",
]
_POSTGRES_DDL = [d.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
                  .replace("REAL NOT NULL", "DOUBLE PRECISION NOT NULL") for d in _SQLITE_DDL]


class Store:
    def __init__(self) -> None:
        settings = get_settings()
        self.postgres = bool(settings.database_url)
        if self.postgres:
            from psycopg_pool import ConnectionPool

            self._pool = ConnectionPool(settings.database_url, min_size=1, max_size=5,
                                        kwargs={"autocommit": True}, open=True)
        else:
            settings.state_db.parent.mkdir(parents=True, exist_ok=True)
            self._path = settings.state_db
        with self._conn() as conn:
            for ddl in _POSTGRES_DDL if self.postgres else _SQLITE_DDL:
                conn.execute(ddl)

    @contextmanager
    def _conn(self) -> Iterator[Any]:
        if self.postgres:
            with self._pool.connection() as conn:
                yield conn
        else:
            conn = sqlite3.connect(self._path)
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def _run(self, sql: str, params: tuple = ()) -> list[tuple]:
        if self.postgres:
            sql = sql.replace("?", "%s")
        with self._conn() as conn:
            cur = conn.execute(sql, params)
            return cur.fetchall() if cur.description else []

    # --- users ------------------------------------------------------------------------
    def create_user(self, username: str, password_hash: str) -> int | None:
        """Returns the new id, or None when the username is taken."""
        if self.get_user(username):
            return None
        self._run("INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                  (username, password_hash, time.time()))
        user = self.get_user(username)
        return user["id"] if user else None

    def get_user(self, username: str) -> dict[str, Any] | None:
        rows = self._run("SELECT id, username, password_hash FROM users WHERE lower(username) = lower(?)",
                         (username,))
        return {"id": rows[0][0], "username": rows[0][1], "password_hash": rows[0][2]} if rows else None

    # --- conversations ----------------------------------------------------------------
    def list_conversations(self, user_id: int) -> list[dict[str, Any]]:
        rows = self._run("SELECT id, title, messages, updated_at FROM conversations "
                         "WHERE user_id = ? ORDER BY updated_at DESC", (user_id,))
        return [{"id": r[0], "title": r[1], "messages": json.loads(r[2]), "updated_at": r[3]} for r in rows]

    def save_conversation(self, user_id: int, conv_id: str, title: str, messages: list[Any]) -> None:
        payload = json.dumps(messages, default=str)
        self._run("DELETE FROM conversations WHERE user_id = ? AND id = ?", (user_id, conv_id))
        self._run("INSERT INTO conversations (user_id, id, title, messages, updated_at) VALUES (?, ?, ?, ?, ?)",
                  (user_id, conv_id, title, payload, time.time()))

    def delete_conversation(self, user_id: int, conv_id: str) -> None:
        self._run("DELETE FROM conversations WHERE user_id = ? AND id = ?", (user_id, conv_id))

    # --- feedback ---------------------------------------------------------------------
    def add_feedback(self, session_id: str, user_id: int | None, question: str, sql: str,
                     rating: str, comment: str) -> None:
        self._run("INSERT INTO feedback (session_id, user_id, question, sql, rating, comment, created_at) "
                  "VALUES (?, ?, ?, ?, ?, ?, ?)", (session_id, user_id, question, sql, rating, comment, time.time()))

    def list_feedback(self) -> list[dict[str, Any]]:
        rows = self._run("SELECT question, sql, rating, comment FROM feedback ORDER BY created_at")
        return [{"question": r[0], "sql": r[1], "rating": r[2], "comment": r[3]} for r in rows]


@lru_cache
def get_store() -> Store:
    return Store()
