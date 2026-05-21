"""PgTracer — TracingPort implementation writing DB lineage to PostgreSQL.

Creates four tables on first use (if they don't exist):
  trace_runs, trace_tool_calls, trace_retrievals, trace_answers

Schema is intentionally simple (TEXT/JSONB/TIMESTAMPTZ) so it can live in the
same database as Agno's tables without migration tooling at this stage.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from agno_plus.core.models import DataRef, EpisodicRef, KnowledgeRef, SourceRef, WebRef


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _source_ref_to_dict(ref: SourceRef) -> dict[str, Any]:
    return asdict(ref)  # type: ignore[arg-type]


class PgTracer:
    """Writes structured trace records to PostgreSQL via psycopg2."""

    def __init__(self, db_url: str) -> None:
        import psycopg2  # optional dep — installed alongside pgvector
        import psycopg2.extras

        self._conn = psycopg2.connect(db_url)
        self._conn.autocommit = True
        self._ensure_schema()

    def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        with self._conn.cursor() as cur:
            cur.execute(sql, params)

    def _ensure_schema(self) -> None:
        self._execute("""
            CREATE TABLE IF NOT EXISTS trace_runs (
                id           TEXT PRIMARY KEY,
                user_id      TEXT NOT NULL,
                input_text   TEXT NOT NULL,
                intents      TEXT[],
                grounded_text TEXT,
                status       TEXT NOT NULL DEFAULT 'running',
                created_at   TIMESTAMPTZ DEFAULT now(),
                completed_at TIMESTAMPTZ
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS trace_tool_calls (
                id          TEXT PRIMARY KEY,
                run_id      TEXT NOT NULL REFERENCES trace_runs(id),
                step        INT NOT NULL,
                tool_name   TEXT NOT NULL,
                tool_args   JSONB,
                tool_result TEXT,
                error       TEXT,
                created_at  TIMESTAMPTZ DEFAULT now()
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS trace_retrievals (
                id          TEXT PRIMARY KEY,
                run_id      TEXT NOT NULL REFERENCES trace_runs(id),
                source_type TEXT NOT NULL,
                source_ref  JSONB NOT NULL,
                score       FLOAT,
                created_at  TIMESTAMPTZ DEFAULT now()
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS trace_answers (
                id           TEXT PRIMARY KEY,
                run_id       TEXT NOT NULL REFERENCES trace_runs(id),
                answer_text  TEXT,
                sources_json JSONB,
                created_at   TIMESTAMPTZ DEFAULT now()
            )
        """)

    # --- TracingPort interface ---

    def start_run(self, user_id: str, input_text: str) -> str:
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        self._execute(
            "INSERT INTO trace_runs (id, user_id, input_text) VALUES (%s, %s, %s)",
            (run_id, user_id, input_text),
        )
        return run_id

    def log_tool_call(
        self,
        run_id: str,
        step: int,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: str | None = None,
        error: str | None = None,
    ) -> None:
        self._execute(
            """INSERT INTO trace_tool_calls
               (id, run_id, step, tool_name, tool_args, tool_result, error)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (
                f"tc_{uuid.uuid4().hex[:12]}",
                run_id, step, tool_name,
                json.dumps(tool_args), tool_result, error,
            ),
        )

    def log_retrieval(self, run_id: str, source_ref: SourceRef, score: float = 0.0) -> None:
        d = _source_ref_to_dict(source_ref)
        self._execute(
            """INSERT INTO trace_retrievals (id, run_id, source_type, source_ref, score)
               VALUES (%s, %s, %s, %s, %s)""",
            (
                f"ret_{uuid.uuid4().hex[:12]}",
                run_id, d.get("source_type", "unknown"),
                json.dumps(d), score,
            ),
        )

    def log_answer(self, run_id: str, answer_text: str, sources: list[SourceRef]) -> None:
        self._execute(
            """INSERT INTO trace_answers (id, run_id, answer_text, sources_json)
               VALUES (%s, %s, %s, %s)""",
            (
                f"ans_{uuid.uuid4().hex[:12]}",
                run_id, answer_text,
                json.dumps([_source_ref_to_dict(s) for s in sources]),
            ),
        )

    def complete_run(self, run_id: str, intents: list[str], status: str = "completed") -> None:
        self._execute(
            """UPDATE trace_runs
               SET status=%s, intents=%s, completed_at=%s
               WHERE id=%s""",
            (status, intents, _utcnow(), run_id),
        )
