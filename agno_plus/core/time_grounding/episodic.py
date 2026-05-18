"""EpisodicMemoryGrounder — wraps any MemoryStore and auto-grounds chat memories."""

from __future__ import annotations

from datetime import datetime, timezone

from agno_plus.core.models import MemoryRecord, MemoryStore
from agno_plus.core.time_grounding.grounder import TemporalGrounder
from agno_plus.core.time_grounding.models import GroundingMode


class EpisodicMemoryGrounder:
    """Wraps a MemoryStore and applies PERSONAL temporal grounding before every upsert.

    All chat-channel memories are grounded with reference_date=now(). Callers
    do not need to think about grounding — it is automatic and invisible.
    """

    def __init__(self, store: MemoryStore, grounder: TemporalGrounder) -> None:
        self._store = store
        self._grounder = grounder

    def store(self, text: str, user_id: str, **meta: object) -> MemoryRecord:
        reference_date = datetime.now(timezone.utc).replace(tzinfo=None)
        grounded_text, groundings = self._grounder.ground(
            text,
            mode=GroundingMode.PERSONAL,
            reference_date=reference_date,
        )
        event_at = groundings[0].resolved_date if groundings else None
        return self._store.upsert(
            content=grounded_text,
            metadata={"event_at": event_at, "user_id": user_id, **meta},
        )

    def search(self, query: str, user_id: str, **kwargs: object) -> list[MemoryRecord]:
        return self._store.search(query, user_id, **kwargs)

    def delete(self, record_id: str) -> None:
        self._store.delete(record_id)
