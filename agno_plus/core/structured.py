"""DDL utilities for dynamic PostgreSQL tables (structured domain ingestion).

These helpers are framework-agnostic — they only depend on SQLAlchemy and
standard library modules. Applications import an engine and pass it in.

Naming convention: tables are named by the caller; safe_col_name() converts
raw spreadsheet/PDF column headers to valid, lowercase SQL identifiers.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

_SAFE = re.compile(r"[^a-z0-9_]")

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?$")

_TYPE_SAMPLE_ROWS = 100

ALLOWED_PG_TYPES: frozenset[str] = frozenset(
    {"TEXT", "BIGINT", "NUMERIC", "DATE", "TIMESTAMPTZ", "BOOLEAN"}
)


def safe_col_name(s: str) -> str:
    """Convert a raw column header to a lowercase SQL-safe identifier."""
    return _SAFE.sub("_", s.lower())[:40].strip("_") or "col"


def infer_pg_type(values: list[str]) -> str:
    """Return the tightest PostgreSQL type that fits all non-empty sample values."""
    samples = [v for v in values if v]
    if not samples:
        return "TEXT"
    try:
        for v in samples:
            int(v)
        return "BIGINT"
    except ValueError:
        pass
    try:
        for v in samples:
            float(v)
        return "NUMERIC"
    except ValueError:
        pass
    if all(_ISO_DATETIME_RE.match(v) for v in samples):
        return "TIMESTAMPTZ"
    if all(_ISO_DATE_RE.match(v) for v in samples):
        return "DATE"
    return "TEXT"


def infer_column_types(headers: list[str], rows: list[dict]) -> dict[str, str]:
    """Return {safe_col_name: pg_type} inferred from up to _TYPE_SAMPLE_ROWS rows."""
    sample = rows[:_TYPE_SAMPLE_ROWS]
    return {
        safe_col_name(h): infer_pg_type([str(row.get(h, "") or "") for row in sample])
        for h in headers
    }


def create_dynamic_table(
    engine: Engine,
    table_name: str,
    headers: list[str],
    col_types: dict[str, str],
    *,
    grant_to: str | None = None,
) -> None:
    """DROP + CREATE a dynamic table with inferred column types.

    Args:
        engine: SQLAlchemy engine.
        table_name: Fully-qualified or unqualified table name (no injection check —
            callers must ensure the name is safe, e.g. produced by a naming function).
        headers: Original column headers (will be passed through safe_col_name).
        col_types: {safe_col_name: pg_type} map from infer_column_types().
        grant_to: Optional role to GRANT SELECT to (e.g. a read-only query role).
    """
    col_defs = ", ".join(
        f'"{safe_col_name(h)}" {col_types.get(safe_col_name(h), "TEXT")}' for h in headers
    )
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
        conn.execute(
            text(
                f"""
                CREATE TABLE {table_name} (
                    _row_id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
                    {col_defs}
                )
                """
            )
        )
        if grant_to:
            conn.execute(text(f"GRANT SELECT ON TABLE {table_name} TO {grant_to}"))


def bulk_insert(
    engine: Engine,
    table_name: str,
    headers: list[str],
    rows: list[dict[str, Any]],
) -> None:
    """Insert rows into a dynamic table created by create_dynamic_table()."""
    if not rows:
        return
    safe_cols = [safe_col_name(h) for h in headers]
    col_list = ", ".join(f'"{c}"' for c in safe_cols)
    placeholders = ", ".join(f":{c}" for c in safe_cols)
    sql = text(f"INSERT INTO {table_name} ({col_list}) VALUES ({placeholders})")
    with engine.begin() as conn:
        for row in rows:
            params = {
                safe_col_name(k): (None if str(v).strip() == "" else str(v))
                for k, v in row.items()
                if safe_col_name(k) in safe_cols
            }
            conn.execute(sql, params)


def fetch_sample_rows(
    engine: Engine,
    table_name: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return first N rows from a dynamic table (excluding _row_id)."""
    try:
        with engine.begin() as conn:
            rows = conn.execute(
                text(f"SELECT * FROM {table_name} LIMIT :n"),
                {"n": limit},
            ).fetchall()
        if not rows:
            return []
        keys = [k for k in rows[0]._mapping.keys() if k != "_row_id"]
        return [
            {k: (str(r._mapping[k]) if r._mapping[k] is not None else "") for k in keys}
            for r in rows
        ]
    except Exception:
        return []


def drop_table(engine: Engine, table_name: str) -> None:
    """DROP TABLE IF EXISTS for a dynamic table."""
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
