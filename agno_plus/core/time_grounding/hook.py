"""TemporalGrounderDb — wraps any Agno-compatible db and applies temporal
grounding before every memory upsert.

Usage (in agent setup):
    from agno.db.postgres import PostgresDb
    from agno_plus.core.time_grounding.hook import TemporalGrounderDb
    from agno_plus.core.time_grounding.grounder import TemporalGrounder

    base_db = PostgresDb(db_url=settings.db_url)
    grounded_db = TemporalGrounderDb(db=base_db, grounder=TemporalGrounder())

    agent = Agent(db=grounded_db, enable_agentic_memory=True, ...)

The wrapper intercepts upsert_user_memory and upsert_memories, normalises
relative time expressions in the memory text, and adds an "event_at:YYYY-MM-DD"
topic so temporal queries can filter by when the event happened (not when it was
stored). All other db methods are transparently delegated.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agno_plus.core.time_grounding.grounder import TemporalGrounder
from agno_plus.core.time_grounding.models import GroundingMode


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _ground_memory(memory: Any, grounder: TemporalGrounder) -> Any:
    """Apply temporal grounding to a UserMemory-duck-typed object in place."""
    raw_text: str = getattr(memory, "memory", "") or ""
    if not raw_text:
        return memory

    reference_date = _utcnow()
    grounded_text, groundings = grounder.ground(
        raw_text,
        mode=GroundingMode.PERSONAL,
        reference_date=reference_date,
    )

    # Write normalised text back
    try:
        memory.memory = grounded_text
    except AttributeError:
        pass  # frozen dataclass — leave as-is

    if groundings:
        event_date = groundings[0].resolved_date
        topic_tag = f"event_at:{event_date.strftime('%Y-%m-%d')}"
        existing: list[str] = list(getattr(memory, "topics", None) or [])
        # Remove any stale event_at tag before adding the new one
        existing = [t for t in existing if not t.startswith("event_at:")]
        existing.append(topic_tag)
        try:
            memory.topics = existing
        except AttributeError:
            pass

    return memory


class TemporalGrounderDb:
    """Transparent proxy around any Agno BaseDb that grounds memories on write.

    Registered as a virtual subclass of agno.db.base.BaseDb so that Agno's
    isinstance(db, BaseDb) guards treat it as a sync db (not async).
    """

    def __init__(self, db: Any, grounder: TemporalGrounder | None = None) -> None:
        self._db = db
        self._grounder = grounder or TemporalGrounder()


try:
    from agno.db.base import BaseDb as _BaseDb
    _BaseDb.register(TemporalGrounderDb)
except Exception:
    pass

    # Transparent delegation for all non-overridden attributes
    def __getattr__(self, name: str) -> Any:
        return getattr(self._db, name)

    # --- Intercepted write methods ---

    def upsert_user_memory(self, memory: Any, deserialize: Any = True) -> Any:
        _ground_memory(memory, self._grounder)
        return self._db.upsert_user_memory(memory, deserialize)

    def upsert_memories(self, memories: list[Any], **kwargs: Any) -> list[Any]:
        for m in memories:
            _ground_memory(m, self._grounder)
        return self._db.upsert_memories(memories, **kwargs)
