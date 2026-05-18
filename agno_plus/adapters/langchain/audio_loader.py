"""LangChain adapter: AudioReader → LangChain Document loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from agno_plus.core.readers.audio import AudioReader


class LangChainAudioLoader:
    """Transcribe an audio file into a single LangChain Document.

    Usage:
        loader = LangChainAudioLoader("interview.mp3", backend="local")
        docs = loader.load()

    Requires: pip install agno-plus[langchain,audio]
    """

    def __init__(
        self,
        file_path: str,
        backend: str = "local",
        model_size: str = "base",
        api_key: str | None = None,
    ) -> None:
        self._path = file_path
        self._core = AudioReader(backend=backend, model_size=model_size, api_key=api_key)

    def load(self) -> list[Any]:
        return list(self.lazy_load())

    def lazy_load(self) -> Iterator[Any]:
        try:
            from langchain_core.documents import Document as LCDocument
        except ImportError:
            raise ImportError(
                "langchain-core is required for LangChainAudioLoader. "
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
