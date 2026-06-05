"""Singleton wiring for agno-plus components.

Bootstraps every shared object the FastAPI routes need:

  engine           SQLAlchemy engine for the demo Postgres
  storage          agno-plus LocalStorageBackend (ADR-0014)
  grounder         agno-plus TemporalGrounder (ADR-0004)
  knowledge_store  agno-plus KnowledgeStore wrapping PgVector (ADR-0010)
  pipeline         agno-plus IngestionPipeline registered per extension (ADR-0007)
  agent            Agno Agent with DomainKnowledge + TemporalGrounderDb (ADRs 0005, 0009)
  langfuse         Optional Langfuse v2 client

The pipeline writes chunks straight into the knowledge_store via the
MemoryStore protocol — same store the agent reads from at chat time.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from agno_plus.adapters.agno import KnowledgeStore
from agno_plus.core.pipeline.worker import IngestionPipeline
from agno_plus.core.readers.image import ImageReader
from agno_plus.core.readers.pdf import IntelligentPdfReader
from agno_plus.core.readers.spreadsheet import SpreadsheetReader
from agno_plus.core.readers.text import TextReader
from agno_plus.core.storage import LocalStorageBackend
from agno_plus.core.time_grounding.grounder import TemporalGrounder
from agno_plus.core.time_grounding.hook import TemporalGrounderDb

from config import DOMAIN_ID, USER_ID, settings


def _build_embedder() -> Any:
    if settings.llm_backend == "openai":
        from agno.knowledge.embedder.openai import OpenAIEmbedder
        return OpenAIEmbedder(id=settings.embed_model, api_key=settings.openai_api_key)
    from agno.knowledge.embedder.ollama import OllamaEmbedder
    return OllamaEmbedder(id="nomic-embed-text", host=settings.ollama_url)


def _build_chat_model() -> Any:
    if settings.llm_backend == "openai":
        from agno.models.openai import OpenAIChat
        return OpenAIChat(id=settings.llm_model, api_key=settings.openai_api_key)
    from agno.models.ollama import Ollama
    return Ollama(id=settings.llm_model, host=settings.ollama_url)


def _build_pipeline(store: KnowledgeStore, grounder: TemporalGrounder) -> IngestionPipeline:
    """Register one reader per supported extension. Grounding mode is per source
    (G-0004): receipts and chats are PERSONAL, generic uploads are AUTO."""
    spreadsheet = SpreadsheetReader()
    readers = {
        ".xlsx": spreadsheet,
        ".xls":  spreadsheet,
        ".csv":  spreadsheet,
        ".tsv":  spreadsheet,
        ".pdf":  IntelligentPdfReader(),
        ".txt":  TextReader(),
        ".md":   TextReader(),
    }
    if settings.openai_api_key or settings.llm_backend == "ollama":
        image_reader = ImageReader(
            backend=settings.llm_backend,
            model=settings.vision_model,
            api_key=settings.openai_api_key or None,
            ollama_base_url=settings.ollama_url,
        )
        for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            readers[ext] = image_reader

    return IngestionPipeline(readers=readers, memory_store=store, grounder=grounder)


def _build_agent(store: KnowledgeStore, grounder: TemporalGrounder) -> Any:
    """Agno Agent wired with:
      - DomainKnowledge       → search_knowledge tool, user_id closure at run time (ADR-0009)
      - SQLTools + custom     → run_sql_query over the user's structured tables,
                                with annotation-aware list/describe (ADR-0016)
      - TemporalGrounderDb    → episodic memory grounded automatically (ADR-0005)
      - native session history (Agno's add_history_to_context)
    """
    from agno.agent import Agent
    from agno.db.postgres.postgres import PostgresDb
    from agno.tools.sql import SQLTools

    from agno_plus.adapters.agno import DomainKnowledge

    # Imported here so sql.py can import bootstrap.engine without a cycle.
    from sql import describe_table, list_my_sql_tables

    base_db = PostgresDb(db_url=settings.database_url)
    grounded_db = TemporalGrounderDb(db=base_db, grounder=grounder)

    return Agent(
        name="Personal Aide",
        model=_build_chat_model(),
        knowledge=DomainKnowledge(store=store, top_k=5),
        db=grounded_db,
        enable_agentic_memory=True,
        add_history_to_context=True,
        num_history_runs=5,
        search_knowledge=True,
        # Single-user demo: scope every auto-retrieval to this user/domain.
        # In a multi-tenant app, replace with run_context-driven filters
        # (see ADR-0009 and agentic-aide ADR-0009).
        knowledge_filters={"user_id": USER_ID, "domain_id": DOMAIN_ID},
        tools=[
            # Agno's built-in run_sql_query against a separate engine with a
            # 5-second statement timeout. Built-in list_tables / describe_table
            # are disabled so the agent has to go through our annotation-aware
            # variants (G-0003, ADR-0016).
            SQLTools(
                db_engine=sql_engine(),
                enable_list_tables=False,
                enable_describe_table=False,
            ),
            list_my_sql_tables,
            describe_table,
        ],
        instructions=[
            "You are a helpful personal aide with access to the user's uploaded "
            "documents and structured tables.",
            "Use search_knowledge to retrieve relevant document chunks before answering. "
            f"Pass an empty string as domain_id to search all of '{DOMAIN_ID}'.",
            "For questions that look numeric, tabular, or quantitative (totals, counts, "
            "filters, comparisons across rows), use the SQL flow: "
            "(1) call list_my_sql_tables, (2) call describe_table on the relevant one, "
            "(3) call run_sql_query with the table name from step 1. Never invent table "
            "or column names — always derive them from list_my_sql_tables and describe_table.",
            "It is fine to combine search_knowledge and run_sql_query in the same turn "
            "when a question spans documents and tables.",
            "When the user asks about dates, prefer the grounded event_at metadata "
            "over raw text — relative dates are already normalized.",
        ],
    )


# ---------------------------------------------------------------------------
# Singletons (built lazily on first access to avoid import-time DB connects)
# ---------------------------------------------------------------------------


_engine: Any = None
_sql_engine: Any = None
_storage: LocalStorageBackend | None = None
_grounder: TemporalGrounder | None = None
_store: KnowledgeStore | None = None
_pipeline: IngestionPipeline | None = None
_agent: Any = None


def engine() -> Any:
    global _engine
    if _engine is None:
        _engine = sa.create_engine(settings.database_url)
    return _engine


def sql_engine() -> Any:
    """Separate engine for SQLTools with a 5-second statement timeout (G-0003).

    Skipped in this demo: a dedicated read-only Postgres role with SELECT-only
    grants on `sd_*` tables. The `create_dynamic_table` helper accepts
    `grant_to=` for that, but creating the role itself is operator-level setup
    we intentionally leave out of the minimal example.
    """
    global _sql_engine
    if _sql_engine is None:
        _sql_engine = sa.create_engine(
            settings.database_url,
            connect_args={"options": "-c statement_timeout=5000"},
        )
    return _sql_engine


def storage() -> LocalStorageBackend:
    global _storage
    if _storage is None:
        _storage = LocalStorageBackend(root=settings.uploads_dir)
    return _storage


def grounder() -> TemporalGrounder:
    global _grounder
    if _grounder is None:
        _grounder = TemporalGrounder()
    return _grounder


def knowledge_store() -> KnowledgeStore:
    global _store
    if _store is None:
        _store = KnowledgeStore(
            engine=engine(),
            embedder=_build_embedder(),
            db_url=settings.database_url,
        )
    return _store


def pipeline() -> IngestionPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = _build_pipeline(knowledge_store(), grounder())
    return _pipeline


def agent() -> Any:
    global _agent
    if _agent is None:
        _agent = _build_agent(knowledge_store(), grounder())
    return _agent


__all__ = [
    "DOMAIN_ID",
    "USER_ID",
    "agent",
    "engine",
    "grounder",
    "knowledge_store",
    "pipeline",
    "sql_engine",
    "storage",
]
