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
      - DomainKnowledge       → build_context text in the system prompt (ADR-0009)
      - explicit search_knowledge tool registered in `tools=[...]` — gives the
        agent an auditable, agency-driven retrieval call (no silent auto path)
      - SQLTools + custom     → run_sql_query over the user's structured tables,
                                with annotation-aware list/describe (ADR-0016)
      - TemporalGrounderDb    → episodic memory grounded automatically (ADR-0005)
      - native session history (Agno's add_history_to_context)
    """
    import json

    from agno.agent import Agent
    from agno.db.postgres.postgres import PostgresDb
    from agno.tools import tool
    from agno.tools.sql import SQLTools

    from agno_plus.adapters.agno import DomainKnowledge

    # Imported here so sql.py can import bootstrap.engine without a cycle.
    from sql import describe_table, list_my_sql_tables

    @tool
    def search_knowledge(query: str, domain_id: str = "") -> str:
        """Search the user's ingested documents (PDFs, text, markdown, image OCR)
        for content relevant to the question.

        Always call this for any question that might be answered from the user's
        documents — facts, definitions, descriptions, named entities, explanations,
        or relationships. Call it before considering the SQL flow.

        Args:
            query: Search query text. Use a focused paraphrase of the user's
                question for better matches.
            domain_id: Optional domain filter. Pass empty string to search
                across all of the user's documents (recommended default).

        Returns:
            JSON {"chunks": [{id, excerpt, filename, block_type, page_number,
            table_label, score}, ...]}. Empty chunks list means nothing relevant
            was found — try a different query before falling back to SQL.
        """
        results = store.search(query, user_id=USER_ID, domain_id=domain_id, top_k=5)
        if not results:
            return json.dumps({"chunks": []})
        chunks = [
            {
                "id": r.id,
                "excerpt": r.content[:400],
                "filename": r.metadata.get("filename", ""),
                "block_type": r.metadata.get("block_type", ""),
                "page_number": r.metadata.get("page_number", ""),
                "table_label": r.metadata.get("table_label", ""),
                "score": r.metadata.get("score", 0.0),
            }
            for r in results
        ]
        return json.dumps({"chunks": chunks})

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
        # Auto knowledge retrieval is OFF — search_knowledge is exposed as an
        # explicit tool the agent must call. This makes the retrieval visible
        # in the trace, gives the agent agency to refine its query, and
        # prevents fixation on SQL by surfacing document chunks as a tool
        # result rather than silent system-prompt context.
        search_knowledge=False,
        # Defence in depth: if any future Agno change re-enables an auto path,
        # scope it to this user/domain. The live user_id binding is via the
        # DomainKnowledge.get_tools closure (ADR-0009).
        knowledge_filters={"user_id": USER_ID, "domain_id": DOMAIN_ID},
        tools=[
            # Explicit semantic retrieval. Registered here (rather than via
            # search_knowledge=True on the Agent) so the call shows up as a
            # tool invocation in the trace and the agent has explicit agency
            # over what it searches for.
            search_knowledge,
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
            "You are a helpful personal aide with two complementary stores of "
            "knowledge: (a) uploaded documents reached via the `search_knowledge` "
            "tool (semantic search over PDFs, text, markdown, image OCR) and "
            "(b) structured tables reached via `list_my_sql_tables`, "
            "`describe_table`, and `run_sql_query` (Postgres).",
            "",
            "WORKFLOW for every user question — follow these steps in order:",
            "1. ALWAYS call `search_knowledge` first with the user's question (or "
            f"a focused paraphrase). Use domain_id='' to search all of '{DOMAIN_ID}'. "
            "Read the returned chunks carefully — most non-trivial answers are at "
            "least partly there.",
            "2. If the question asks for aggregations (sum, count, average, min/max), "
            "exact-row lookups by attribute, or comparisons across rows, ALSO run "
            "the SQL flow: `list_my_sql_tables` → `describe_table` → "
            "`run_sql_query`. Derive table and column names only from those tool "
            "results — never invent them.",
            "3. Synthesize the answer using BOTH sources when both contributed. "
            "Briefly state the source: '(from your documents)' or '(from your "
            "<table> table)'.",
            "",
            "Anti-patterns to avoid:",
            "- Do not call `run_sql_query` before calling `search_knowledge`. The "
            "document chunks may explain what columns mean or contain the answer "
            "outright.",
            "- Do not retry the same SQL query with minor variations when it "
            "returned NULL or empty rows. Fall back to `search_knowledge` with a "
            "refined query instead.",
            "- Do not reply 'I don't have access to that' before actually calling "
            "`search_knowledge` and (if applicable) the SQL flow.",
            "",
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
