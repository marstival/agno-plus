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
      - DomainKnowledge → search_knowledge tool, user_id closure at run time (ADR-0009)
      - TemporalGrounderDb → episodic memory grounded automatically (ADR-0005)
      - native session history (Agno's add_history_to_context)
    """
    from agno.agent import Agent
    from agno.db.postgres.postgres import PostgresDb

    from agno_plus.adapters.agno import DomainKnowledge

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
        instructions=[
            "You are a helpful personal aide with access to the user's uploaded "
            "documents and structured tables.",
            "Use search_knowledge to retrieve relevant document chunks before answering. "
            f"Pass an empty string as domain_id to search all of '{DOMAIN_ID}'.",
            "When the user asks about dates, prefer the grounded event_at metadata "
            "over raw text — relative dates are already normalized.",
        ],
    )


def _build_langfuse() -> Any | None:
    if not (settings.langfuse_host and settings.langfuse_public_key and settings.langfuse_secret_key):
        return None
    try:
        from langfuse import Langfuse
    except ImportError:
        print("[warn] langfuse package not installed; tracing disabled")
        return None
    client = Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
    )
    if not callable(getattr(client, "trace", None)):
        print("[warn] langfuse SDK >=3 detected; pin langfuse<3 — tracing disabled")
        return None
    print(f"[langfuse] tracing to {settings.langfuse_host}")
    return client


# ---------------------------------------------------------------------------
# Singletons (built lazily on first access to avoid import-time DB connects)
# ---------------------------------------------------------------------------


_engine: Any = None
_storage: LocalStorageBackend | None = None
_grounder: TemporalGrounder | None = None
_store: KnowledgeStore | None = None
_pipeline: IngestionPipeline | None = None
_agent: Any = None
_langfuse: Any = None


def engine() -> Any:
    global _engine
    if _engine is None:
        _engine = sa.create_engine(settings.database_url)
    return _engine


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


def langfuse() -> Any | None:
    global _langfuse
    if _langfuse is None:
        _langfuse = _build_langfuse()
    return _langfuse


__all__ = [
    "DOMAIN_ID",
    "USER_ID",
    "agent",
    "engine",
    "grounder",
    "knowledge_store",
    "langfuse",
    "pipeline",
    "storage",
]
