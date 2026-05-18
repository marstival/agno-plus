"""Agno adapter: MemoryStore Protocol → Agno KnowledgeBase storage."""

from __future__ import annotations

import uuid
from typing import Any

from agno_plus.core.models import MemoryRecord


class AgnoMemoryStore:
    """Wraps an Agno KnowledgeBase to satisfy the agno_plus MemoryStore Protocol.

    The KB handles embedding + vector storage. This adapter translates between
    the agno_plus MemoryRecord domain type and Agno's Document type.

    Usage:
        kb = AgnoKnowledgeBase(...)
        store = AgnoMemoryStore(kb)
        episodic = EpisodicMemoryGrounder(store=store, grounder=grounder)
    """

    def __init__(self, knowledge_base: Any) -> None:
        self._kb = knowledge_base

    def upsert(self, content: str, metadata: dict[str, Any]) -> MemoryRecord:
        try:
            from agno.document import Document as AgnoDocument
        except ImportError:
            raise ImportError("agno is required. Install with: pip install agno-plus[agno]")

        record_id = metadata.get("id") or f"mem_{uuid.uuid4().hex[:8]}"
        doc = AgnoDocument(id=record_id, content=content, meta_data=metadata)
        self._kb.load_documents([doc], upsert=True)
        return MemoryRecord(id=record_id, content=content, metadata=metadata)

    def search(self, query: str, user_id: str, **kwargs: Any) -> list[MemoryRecord]:
        try:
            results = self._kb.search(query, **kwargs)
        except Exception:
            return []
        return [
            MemoryRecord(
                id=getattr(doc, "id", ""),
                content=getattr(doc, "content", ""),
                metadata=getattr(doc, "meta_data", {}),
            )
            for doc in (results or [])
        ]

    def delete(self, record_id: str) -> None:
        # Agno KnowledgeBase doesn't expose a delete-by-id API universally;
        # implementations that need delete should override this adapter.
        raise NotImplementedError(
            "AgnoMemoryStore.delete requires a KB implementation that supports it. "
            "Override or use PgvectorMemoryStore for delete support."
        )
