"""Schema setup for the personal-aide-minimal demo.

`aide_files` is the application's record of ingested files (one row per upload).
agno-plus does not own this table — it is the consumer-side persistence
described in agentic-aide ADR-0005 and agno-plus guidance G-0002.
"""

from __future__ import annotations

from sqlalchemy import text

from bootstrap import engine


def init_schema() -> None:
    with engine().begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS ai"))
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS aide_files (
                id                  TEXT PRIMARY KEY,
                filename            TEXT NOT NULL,
                source_type         TEXT NOT NULL,
                chunks_count        INT DEFAULT 0,
                storage_key         TEXT,
                tables_created      TEXT[],
                extraction_preview  JSONB,
                created_at          TIMESTAMPTZ DEFAULT now()
            )
            """
        ))
