"""LangChain adapter: ImageReader → LangChain Document loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from agno_plus.core.readers.image import ImageReader


class LangChainImageLoader:
    """OCR an image into a single LangChain Document.

    Usage:
        loader = LangChainImageLoader("receipt.jpg", backend="openai")
        docs = loader.load()

    Requires: pip install agno-plus[langchain,image]
    """

    def __init__(
        self,
        file_path: str,
        backend: str = "openai",
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._path = file_path
        self._core = ImageReader(backend=backend, model=model, api_key=api_key)

    def load(self) -> list[Any]:
        return list(self.lazy_load())

    def lazy_load(self) -> Iterator[Any]:
        try:
            from langchain_core.documents import Document as LCDocument
        except ImportError:
            raise ImportError(
                "langchain-core is required for LangChainImageLoader. "
                "Install with: pip install agno-plus[langchain]"
            )

        filename = Path(self._path).name
        with open(self._path, "rb") as f:
            file_bytes = f.read()

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
