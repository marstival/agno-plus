"""LangChain adapter: SpreadsheetReader → LangChain Document loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from agno_plus.core.readers.spreadsheet import SpreadsheetReader


class LangChainSpreadsheetLoader:
    """Load an Excel/CSV file into LangChain Documents.

    One LangChain Document per detected block (table, key-value, note).
    Merged cells are expanded correctly — unlike LangChain's default CSV loader.

    Usage:
        loader = LangChainSpreadsheetLoader("expenses.xlsx")
        docs = loader.load()

    Requires: pip install agno-plus[langchain]
    """

    def __init__(self, file_path: str, **kwargs: Any) -> None:
        self._path = file_path
        self._core = SpreadsheetReader(**kwargs)

    def load(self) -> list[Any]:
        """Load and return a list of LangChain Document objects."""
        return list(self.lazy_load())

    def lazy_load(self) -> Iterator[Any]:
        """Yield LangChain Document objects one at a time."""
        try:
            from langchain_core.documents import Document as LCDocument
        except ImportError:
            raise ImportError(
                "langchain-core is required for LangChainSpreadsheetLoader. "
                "Install with: pip install agno-plus[langchain]"
            )

        with open(self._path, "rb") as f:
            file_bytes = f.read()

        filename = Path(self._path).name
        core_docs = self._core.read(file_bytes, filename=filename)

        for doc in core_docs:
            yield LCDocument(
                page_content=doc.content,
                metadata={
                    **doc.metadata,
                    "source": self._path,
                    "source_type": doc.source_type,
                    "source_name": doc.source_name,
                },
            )
