"""User-scoped SQL tools for the agent.

Exposes two custom tools that wrap Agno's SQLTools introspection with
annotation context:

  list_my_sql_tables()   list sd_personal_* tables + stored annotations
  describe_table(name)   merge information_schema columns + annotations

The hardening pattern recommended by G-0003 (Postgres role `aide_readonly`
with SELECT-only grants on `sd_*` tables) is intentionally NOT wired in
this single-user demo. A real assistant exposing SQL to many users should
create the role and pass `grant_to="aide_readonly"` to
`create_dynamic_table`. The 5-second statement timeout is wired on the
SQL engine in bootstrap.py — that piece is cheap and demonstrates the
pattern.
"""

from __future__ import annotations

import json
from typing import Any

from agno.tools import tool
from sqlalchemy import text

from bootstrap import DOMAIN_ID, engine
from ingestion import annotations

_TABLE_PREFIX = f"sd_{DOMAIN_ID[:8]}_"

_PG_TYPE_MAP = {
    "integer": "BIGINT", "bigint": "BIGINT", "smallint": "BIGINT",
    "numeric": "NUMERIC", "real": "NUMERIC", "double precision": "NUMERIC",
    "text": "TEXT", "character varying": "TEXT", "character": "TEXT", "varchar": "TEXT",
    "date": "DATE",
    "timestamp with time zone": "TIMESTAMPTZ",
    "timestamp without time zone": "TIMESTAMPTZ",
    "boolean": "BOOLEAN",
}


def _label_from_table(table_name: str) -> str:
    return table_name[len(_TABLE_PREFIX):] if table_name.startswith(_TABLE_PREFIX) else table_name


def _stored_columns(table_name: str) -> dict[str, dict[str, str]]:
    stored = annotations.get(table_name) or {}
    cols = stored.get("columns")
    if isinstance(cols, list):
        return {c["name"]: {"description": c.get("description", ""),
                            "type": c.get("type", "")} for c in cols if "name" in c}
    return {}


@tool
def list_my_sql_tables() -> str:
    """List the SQL tables the user has ingested, with descriptions.

    Always call this first when you suspect the user is asking about
    structured/tabular data. Returns a JSON list with one entry per table:
    `{table_name, label, description, row_count}`. Use the `table_name`
    value verbatim in subsequent calls to `describe_table` and `run_sql_query`.
    """
    with engine().connect() as conn:
        rows = conn.execute(
            text("SELECT table_name FROM information_schema.tables "
                 "WHERE table_schema='public' AND table_name LIKE :p "
                 "ORDER BY table_name"),
            {"p": f"{_TABLE_PREFIX}%"},
        ).fetchall()

        result: list[dict[str, Any]] = []
        for (tname,) in rows:
            stored = annotations.get(tname) or {}
            try:
                row_count = conn.execute(text(f'SELECT COUNT(*) FROM "{tname}"')).scalar() or 0
            except Exception:
                row_count = 0
            result.append({
                "table_name": tname,
                "label": _label_from_table(tname),
                "description": stored.get("description", ""),
                "row_count": row_count,
            })

    return json.dumps({"tables": result})


@tool
def describe_table(table_name: str) -> str:
    """Describe a SQL table's columns. Returns column names, PostgreSQL types,
    and any user-authored descriptions.

    Call this before generating a SQL query so you know the column names,
    types, and intent. The returned JSON has `columns` as a dict keyed by
    column name with `{type, description}` values.
    """
    if not table_name.startswith(_TABLE_PREFIX):
        return json.dumps({"error": f"Unknown table: {table_name!r}"})

    stored_cols = _stored_columns(table_name)
    with engine().connect() as conn:
        rows = conn.execute(
            text("SELECT column_name, data_type FROM information_schema.columns "
                 "WHERE table_schema='public' AND table_name=:t "
                 "AND column_name != '_row_id' ORDER BY ordinal_position"),
            {"t": table_name},
        ).fetchall()
        try:
            row_count = conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar() or 0
        except Exception:
            row_count = 0

    if not rows:
        return json.dumps({"error": f"Table {table_name!r} not found"})

    columns: dict[str, dict[str, str]] = {}
    for col, dtype in rows:
        stored = stored_cols.get(col, {})
        columns[col] = {
            "type": stored.get("type") or _PG_TYPE_MAP.get(dtype.lower(), "TEXT"),
            "description": stored.get("description", ""),
        }

    stored_root = annotations.get(table_name) or {}
    return json.dumps({
        "table_name": table_name,
        "label": _label_from_table(table_name),
        "description": stored_root.get("description", ""),
        "row_count": row_count,
        "columns": columns,
    })
