"""Database access: schema introspection and read-only query execution.

Everything here opens SQLite in read-only URI mode (``mode=ro``), so even a
query that slipped past every validation check could not modify data.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import get_settings


class QueryTimeoutError(RuntimeError):
    pass


@dataclass
class ForeignKey:
    column: str
    ref_table: str
    ref_column: str


@dataclass
class TableInfo:
    name: str
    columns: list[dict[str, Any]]           # {name, type, pk, notnull}
    foreign_keys: list[ForeignKey]
    indexes: list[dict[str, Any]]           # {name, columns, unique}
    row_count: int
    sample_rows: list[dict[str, Any]]
    ddl: str

    @property
    def column_names(self) -> list[str]:
        return [c["name"] for c in self.columns]


@dataclass
class SchemaInfo:
    tables: dict[str, TableInfo] = field(default_factory=dict)

    # -- lookups (case-insensitive, SQLite identifiers are case-insensitive) --
    def table(self, name: str) -> TableInfo | None:
        lname = name.lower()
        for t in self.tables.values():
            if t.name.lower() == lname:
                return t
        return None

    def as_sqlglot_schema(self) -> dict[str, dict[str, str]]:
        return {t.name: {c["name"]: c["type"] or "TEXT" for c in t.columns} for t in self.tables.values()}

    def fk_pairs(self) -> set[frozenset[tuple[str, str]]]:
        """Every declared FK as an unordered pair of (table, column), lower-cased."""
        pairs = set()
        for t in self.tables.values():
            for fk in t.foreign_keys:
                pairs.add(frozenset({(t.name.lower(), fk.column.lower()),
                                     (fk.ref_table.lower(), fk.ref_column.lower())}))
        return pairs

    def to_prompt(self, table_names: list[str] | None = None, sample_rows: int = 3) -> str:
        """Schema as CREATE TABLE DDL plus a few sample rows, for prompt injection."""
        chosen = [self.tables[n] for n in (table_names or self.tables.keys()) if n in self.tables]
        parts = []
        for t in chosen:
            parts.append(t.ddl.strip().rstrip(";") + ";")
            if t.sample_rows and sample_rows:
                cols = t.column_names
                rows = [" | ".join(_fmt(r.get(c)) for c in cols) for r in t.sample_rows[:sample_rows]]
                parts.append(f"/* {t.row_count} rows. Sample rows ({' | '.join(cols)}):\n"
                             + "\n".join(rows) + "\n*/")
        return "\n\n".join(parts)

    def to_api(self) -> list[dict[str, Any]]:
        return [
            {
                "name": t.name,
                "row_count": t.row_count,
                "columns": [
                    {
                        "name": c["name"],
                        "type": c["type"],
                        "pk": bool(c["pk"]),
                        "fk": next((f"{fk.ref_table}.{fk.ref_column}" for fk in t.foreign_keys
                                    if fk.column == c["name"]), None),
                    }
                    for c in t.columns
                ],
            }
            for t in self.tables.values()
        ]


def _fmt(value: Any) -> str:
    return "NULL" if value is None else str(value)


def connect_readonly(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path or get_settings().database_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Database not found at {path}. Run: python -m app.db.seed")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Belt and braces: refuse writes at the connection level too.
    conn.execute("PRAGMA query_only = ON")
    return conn


def load_schema(db_path: Path | str | None = None) -> SchemaInfo:
    conn = connect_readonly(db_path)
    try:
        schema = SchemaInfo()
        rows = conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        for row in rows:
            name, ddl = row["name"], row["sql"]
            cols = [
                {"name": c["name"], "type": c["type"], "pk": c["pk"], "notnull": c["notnull"]}
                for c in conn.execute(f'PRAGMA table_info("{name}")')
            ]
            fks = [
                ForeignKey(column=f["from"], ref_table=f["table"], ref_column=f["to"])
                for f in conn.execute(f'PRAGMA foreign_key_list("{name}")')
            ]
            indexes = []
            for idx in conn.execute(f'PRAGMA index_list("{name}")'):
                idx_cols = [i["name"] for i in conn.execute(f'PRAGMA index_info("{idx["name"]}")')]
                indexes.append({"name": idx["name"], "columns": idx_cols, "unique": bool(idx["unique"])})
            count = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            samples = [dict(r) for r in conn.execute(f'SELECT * FROM "{name}" LIMIT 3')]
            schema.tables[name] = TableInfo(name, cols, fks, indexes, count, samples, ddl)
        return schema
    finally:
        conn.close()


@lru_cache
def get_schema() -> SchemaInfo:
    """Schema is loaded once per process; the database is read-only so it never changes."""
    return load_schema()


def explain_query_plan(sql: str, db_path: Path | str | None = None) -> list[str]:
    """Compile the query without running it. Raises sqlite3.Error on invalid SQL."""
    conn = connect_readonly(db_path)
    try:
        return [r["detail"] for r in conn.execute(f"EXPLAIN QUERY PLAN {sql}")]
    finally:
        conn.close()


def execute_readonly(
    sql: str,
    db_path: Path | str | None = None,
    max_rows: int | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Run a validated SELECT on a read-only connection with a row cap and a timeout."""
    settings = get_settings()
    max_rows = max_rows or settings.max_result_rows
    timeout = timeout if timeout is not None else settings.query_timeout_seconds

    conn = connect_readonly(db_path)
    deadline = time.monotonic() + timeout
    # Called every N VM instructions; a non-zero return aborts the query.
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    started = time.monotonic()
    try:
        cur = conn.execute(sql)
        columns = [d[0] for d in cur.description or []]
        rows = cur.fetchmany(max_rows + 1)
    except sqlite3.OperationalError as exc:
        if "interrupted" in str(exc).lower():
            raise QueryTimeoutError(f"Query exceeded the {timeout:g}s time limit.") from exc
        raise
    finally:
        conn.close()

    truncated = len(rows) > max_rows
    rows = rows[:max_rows]
    return {
        "columns": columns,
        "rows": [list(r) for r in rows],
        "row_count": len(rows),
        "truncated": truncated,
        "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
    }
