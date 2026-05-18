"""Agno adapter: AudioReader → agno Document list."""

from __future__ import annotations

from typing import Any


class AgnoAudioReader:
    """Wraps core AudioReader for use inside an Agno KnowledgeBase.

    Requires: pip install agno-plus[audio]
    """

    def read(self, source: bytes | str, filename: str = "audio.mp3", **kwargs: Any) -> list[Any]:
        try:
            from agno.document import Document as AgnoDocument
        except ImportError:
            raise ImportError("agno is required. Install with: pip install agno-plus[agno]")

        from agno_plus.core.readers.audio import AudioReader

        core_docs = AudioReader().read(source, filename=filename, **kwargs)
        return [
            AgnoDocument(
                id=doc.id,
                content=doc.content,
                meta_data=doc.metadata,
                name=doc.source_name,
            )
            for doc in core_docs
        ]
