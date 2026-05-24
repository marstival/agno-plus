"""Agno ChunkingStrategy adapter — delegates to agno-plus semantic merge chunker.

Usage:
    from agno_plus.adapters.agno import TemporalMergeChunking

    knowledge = Knowledge(
        ...,
        chunking_strategy=TemporalMergeChunking(max_tokens=400, overlap_tokens=40),
    )
"""

from __future__ import annotations

from typing import List

from agno.knowledge.chunking.strategy import ChunkingStrategy
from agno.knowledge.document.base import Document as AgnoDocument

from agno_plus.core.pipeline.chunking import chunk_text_structured


class TemporalMergeChunking(ChunkingStrategy):
    """Wraps agno-plus chunk_text_structured as an Agno ChunkingStrategy.

    Produces semantically coherent chunks with configurable token budget.
    Preserves the source document's content_id on every chunk so callers
    can deduplicate by content hash across re-ingests.

    Args:
        max_tokens: Target maximum tokens per chunk.
        overlap_tokens: Token overlap between adjacent chunks.
    """

    def __init__(self, max_tokens: int = 400, overlap_tokens: int = 40) -> None:
        self._max_tokens = max_tokens
        self._overlap_tokens = overlap_tokens

    def chunk(self, document: AgnoDocument) -> List[AgnoDocument]:
        text = document.content or ""
        chunk_strings = chunk_text_structured(
            text, self._max_tokens, self._overlap_tokens
        ) or [text]

        results: List[AgnoDocument] = []
        for i, chunk_str in enumerate(chunk_strings):
            results.append(
                AgnoDocument(
                    id=self._generate_chunk_id(document, i),
                    name=document.name,
                    content=chunk_str,
                    meta_data=dict(document.meta_data or {}),
                    content_id=document.content_id,
                )
            )
        return results
