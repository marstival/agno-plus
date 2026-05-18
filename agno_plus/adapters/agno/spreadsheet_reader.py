"""Agno adapter: SpreadsheetReader → agno.document.reader.base.Reader."""

from __future__ import annotations

from typing import Any

from agno_plus.core.readers.spreadsheet import SpreadsheetReader as CoreReader
from agno_plus.core.time_grounding.models import GroundingMode


class AgnoSpreadsheetReader:
    """Wraps core SpreadsheetReader for use inside an Agno KnowledgeBase.

    Agno's native ExcelReader silently drops merged cells (read_only=True).
    This reader expands merged ranges and returns one Document per block.

    Usage:
        kb = AgnoKnowledgeBase(
            reader=AgnoSpreadsheetReader(grounding_mode="personal"),
            ...
        )
    """

    def __init__(self, grounding_mode: str | GroundingMode = GroundingMode.AUTO) -> None:
        self._core = CoreReader()
        self.grounding_mode = GroundingMode(grounding_mode)

    def read(self, source: bytes | str, **kwargs: Any) -> list[Any]:
        """Read and return Agno-compatible Document objects."""
        try:
            from agno.document import Document as AgnoDocument
        except ImportError:
            raise ImportError(
                "agno is required for AgnoSpreadsheetReader. "
                "Install it with: pip install agno-plus[agno]"
            )

        core_docs = self._core.read(source, **kwargs)
        return [
            AgnoDocument(
                id=doc.id,
                content=doc.content,
                meta_data={**doc.metadata, "grounding_mode": self.grounding_mode.value},
                name=doc.source_name,
            )
            for doc in core_docs
        ]
