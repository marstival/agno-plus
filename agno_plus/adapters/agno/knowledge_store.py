"""KnowledgeStore — pgvector-backed semantic store for domain/user-scoped RAG.

Usage (application layer wires engine + embedder):

    from agno_plus.adapters.agno.knowledge_store import KnowledgeStore
    from agno.vectordb.distance import Distance

    store = KnowledgeStore(
        engine=my_engine,
        embedder=my_embedder,
        db_url="postgresql://...",  # for Agno's Knowledge registry
    )
    store.insert_document(text="...", name="report.pdf", metadata={...})
    results = store.search("revenue", user_id="u1", domain_id="d1")
"""

from __future__ import annotations

import logging
import uuid
from hashlib import md5
from typing import Any

from agno.knowledge.document.base import Document as AgnoDocument
from agno.vectordb.distance import Distance
from agno.vectordb.pgvector import PgVector
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

_TABLE_NAME = "agno_knowledge_chunks"
_SCHEMA = "ai"
_KNOWLEDGE_NAME = "agno-plus Knowledge Base"


class KnowledgeStore:
    """Domain/user-scoped semantic store backed by Agno PgVector.

    Stores chunks in <schema>.agno_knowledge_chunks with domain_id and user_id
    embedded in meta_data for JSONB containment filtering.

    Satisfies the SearchableStore protocol used by DomainKnowledge.

    Args:
        engine: SQLAlchemy engine pointing at the pgvector database.
        embedder: Agno embedder instance (OpenAIEmbedder, OllamaEmbedder, etc.).
        db_url: PostgreSQL DSN for Agno's Knowledge registry (agno_knowledge table).
            Pass None to skip registry writes.
        schema: PostgreSQL schema for the chunks table (default: "ai").
        table_name: Chunks table name (default: "agno_knowledge_chunks").
        knowledge_name: Name shown in Agno's knowledge registry.
        distance: pgvector distance metric (default: cosine).
    """

    def __init__(
        self,
        engine: Engine,
        embedder: Any,
        *,
        db_url: str | None = None,
        schema: str = _SCHEMA,
        table_name: str = _TABLE_NAME,
        knowledge_name: str = _KNOWLEDGE_NAME,
        distance: Distance = Distance.cosine,
    ) -> None:
        from agno.knowledge.knowledge import Knowledge

        self._vdb = PgVector(
            table_name=table_name,
            schema=schema,
            db_engine=engine,
            embedder=embedder,
            distance=distance,
        )
        self._vdb.create()

        self._knowledge: Knowledge | None = None
        if db_url:
            from agno.db.postgres.postgres import PostgresDb
            self._knowledge = Knowledge(
                name=knowledge_name,
                vector_db=self._vdb,
                contents_db=PostgresDb(db_url=db_url),
            )

    # ------------------------------------------------------------------
    # SearchableStore protocol (used by DomainKnowledge)
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        user_id: str,
        domain_id: str = "",
        top_k: int = 5,
        **_: Any,
    ) -> list[Any]:
        """Vector search with domain/user isolation.

        Returns a list of MemoryRecord-compatible objects (.id, .content, .metadata).
        """
        from agno_plus.core.models import MemoryRecord

        filters: dict[str, Any] = {"user_id": user_id}
        if domain_id:
            filters["domain_id"] = domain_id

        docs = self._vdb.search(query=query, limit=top_k, filters=filters)
        return [
            MemoryRecord(
                id=doc.id,
                content=doc.content,
                metadata={
                    **doc.meta_data,
                    "score": doc.meta_data.get("similarity_score", 0.0),
                    "domain_id": doc.meta_data.get("domain_id", ""),
                },
            )
            for doc in docs
        ]

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def upsert(self, content: str, metadata: dict[str, Any]) -> Any:
        """Insert or update a single chunk.

        metadata must include user_id and domain_id.
        """
        from agno_plus.core.models import MemoryRecord

        domain_id = metadata.get("domain_id", "")
        user_id = metadata.get("user_id") or ""
        if not user_id:
            raise ValueError("upsert requires user_id in metadata")
        record_id = metadata.get("id") or f"kc_{uuid.uuid4().hex[:12]}"

        doc = AgnoDocument(
            id=record_id,
            name=metadata.get("filename", "chunk"),
            content=content,
            meta_data=metadata,
            content_id=metadata.get("file_id") or None,
        )
        content_hash = md5(f"{domain_id}:{content}".encode()).hexdigest()
        self._vdb.upsert(
            content_hash=content_hash,
            documents=[doc],
            filters={"domain_id": domain_id, "user_id": user_id},
        )
        return MemoryRecord(id=record_id, content=content, metadata=metadata)

    def insert_document(
        self,
        text: str,
        name: str,
        metadata: dict[str, Any],
        content_id: str = "",
    ) -> int:
        """Chunk, embed, and store a document. Returns the number of chunks inserted."""
        from agno_plus.adapters.agno.chunking_strategy import TemporalMergeChunking

        domain_id = metadata.get("domain_id", "")
        user_id = metadata.get("user_id") or ""
        if not user_id:
            raise ValueError("insert_document requires user_id in metadata")

        doc_id = content_id or f"doc_{uuid.uuid4().hex[:12]}"
        source_doc = AgnoDocument(
            id=doc_id,
            name=name,
            content=text,
            meta_data={**metadata, "filename": name},
            content_id=content_id or None,
        )

        chunker = TemporalMergeChunking()
        chunks = chunker.chunk(source_doc)

        for chunk in chunks:
            chunk.meta_data.update(
                {
                    "domain_id": domain_id,
                    "user_id": user_id,
                    "filename": name,
                    "file_id": content_id,
                }
            )
            content_hash = md5(f"{domain_id}:{chunk.content}".encode()).hexdigest()
            self._vdb.upsert(
                content_hash=content_hash,
                documents=[chunk],
                filters={"domain_id": domain_id, "user_id": user_id},
            )

        return len(chunks)

    def ingest_documents(
        self,
        docs: list[Any],
        *,
        domain_id: str,
        user_id: str,
        filename: str,
    ) -> int:
        """Bulk-insert a list of reader document objects (each has .content and .metadata).

        Designed for dual-write: pass the output of PdfReader.read() directly.
        Returns total chunks stored across all documents.
        """
        total = 0
        for doc in docs:
            try:
                n = self.insert_document(
                    text=doc.content,
                    name=filename,
                    metadata={
                        "domain_id": domain_id,
                        "user_id": user_id,
                        "filename": filename,
                        **{k: v for k, v in (doc.metadata or {}).items()
                           if k not in ("domain_id", "user_id", "filename")},
                    },
                )
                total += n
            except Exception as exc:
                logger.warning("ingest_documents: block failed (%s): %s", filename, exc)
        return total

    # ------------------------------------------------------------------
    # Delete operations
    # ------------------------------------------------------------------

    def delete(self, record_id: str) -> None:
        self._vdb.delete_by_id(record_id)

    def delete_by_domain(self, domain_id: str) -> None:
        self._vdb.delete_by_metadata({"domain_id": domain_id})

    def delete_by_file(self, domain_id: str, filename: str) -> None:
        self._vdb.delete_by_metadata({"domain_id": domain_id, "filename": filename})

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------

    def register_file(
        self,
        file_id: str,
        filename: str,
        domain_id: str,
        user_id: str,
        source_type: str,
        chunks_count: int,
    ) -> None:
        """Write a KnowledgeRow to the Agno registry (agno_knowledge table)."""
        if self._knowledge is None:
            return
        from agno.db.schemas.knowledge import KnowledgeRow
        try:
            row = KnowledgeRow(
                id=file_id,
                name=filename,
                description=f"domain:{domain_id}  user:{user_id}",
                type=source_type,
                size=chunks_count,
                status="completed",
                metadata={"domain_id": domain_id, "user_id": user_id},
                linked_to=self._knowledge.name,
            )
            self._knowledge.contents_db.upsert_knowledge_content(row)
        except Exception as exc:
            logger.warning("register_file failed for %s: %s", filename, exc)
