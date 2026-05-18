"""Reader Protocol — structural interface for all ingestion readers."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agno_plus.core.models import Document


@runtime_checkable
class Reader(Protocol):
    def read(self, source: bytes | str, **kwargs: object) -> list[Document]: ...
