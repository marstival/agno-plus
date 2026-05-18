"""Agno adapter: ImageReader → agno Document list."""

from __future__ import annotations

from typing import Any

from agno_plus.core.time_grounding.models import GroundingMode


class AgnoImageReader:
    """Wraps core ImageReader for use inside an Agno KnowledgeBase.

    Requires: pip install agno-plus[image]
    """

    def __init__(self, grounding_mode: str | GroundingMode = GroundingMode.PERSONAL) -> None:
        self.grounding_mode = GroundingMode(grounding_mode)

    def read(self, source: bytes | str, filename: str = "image.jpg", **kwargs: Any) -> list[Any]:
        try:
            from agno.document import Document as AgnoDocument
        except ImportError:
            raise ImportError("agno is required. Install with: pip install agno-plus[agno]")

        from agno_plus.core.readers.image import ImageReader

        core_docs = ImageReader().read(source, filename=filename, **kwargs)
        return [
            AgnoDocument(
                id=doc.id,
                content=doc.content,
                meta_data={**doc.metadata, "grounding_mode": self.grounding_mode.value},
                name=doc.source_name,
            )
            for doc in core_docs
        ]
