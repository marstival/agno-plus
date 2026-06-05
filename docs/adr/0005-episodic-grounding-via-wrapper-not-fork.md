# Episodic temporal grounding via transparent wrapper, not a forked memory implementation

**Status:** Accepted

## Decision

Episodic memory grounding is implemented as two wrapper types — `EpisodicMemoryGrounder` (wraps any `MemoryStore`) and `TemporalGrounderDb` (wraps any Agno `BaseDb`). Neither forks Agno's memory module.

`EpisodicMemoryGrounder` intercepts `store(text, user_id, **meta)` calls, runs `TemporalGrounder` in `PERSONAL` mode with `reference_date=now()`, writes the normalized text and an `event_at` datetime into metadata, then delegates to the wrapped `MemoryStore`.

`TemporalGrounderDb` intercepts Agno's `upsert_user_memory` and `upsert_memories` directly, rewrites the `memory` attribute on the `UserMemory` object, and adds an `event_at:YYYY-MM-DD` topic tag. Every other db method is forwarded transparently via `__getattr__`. The class is virtually registered as a subclass of `agno.db.base.BaseDb` so that Agno's `isinstance(db, BaseDb)` guards accept it.

## Rationale

Two integration shapes exist in the wild — apps that use `agno-plus` as a thin core layer and wire memory themselves (`EpisodicMemoryGrounder`), and apps that use Agno's native `enable_agentic_memory=True` and need grounding applied at the moment Agno itself decides to persist a memory (`TemporalGrounderDb`). Both shapes are served by wrappers; neither needs a custom memory table or a fork of Agno's `MemoryManager`.

Forking the memory implementation was the alternative the agentic-aide team initially considered (ADR-0001 in that repo) and explicitly walked back from in their ADR-0003. We carry that lesson into agno-plus: Agno's native memory pipeline is rich (deduplication, summarization, agentic memory decisions). Recreating it loses every future Agno improvement and adds maintenance surface for no differentiation.

## Alternatives considered

**Subclass Agno `MemoryManager`.** Direct hook, but the subclass binds to internal method names that change across Agno releases. The wrapper at the `BaseDb` level only depends on `upsert_user_memory` / `upsert_memories`, which are part of the public storage contract.

**Application-side grounding before calling memory APIs.** Move the grounding into application code that calls `Agent.add_memory(...)`. Works for explicit calls but misses Agno's *automatic* agentic-memory writes (the ones triggered inside the agent loop by `enable_agentic_memory=True`). Wrapping at the db level catches every write, automatic or explicit.

**Post-write update of `event_at`.** Read memories after the agent run and patch `event_at` into the metadata. Two writes per memory, race-prone with concurrent reads, and adds a second consistent-state requirement.

## Consequences

- Applications that already build their own `MemoryStore` use `EpisodicMemoryGrounder(store, grounder)` with no further wiring.
- Applications that use Agno native memory replace `PostgresDb(...)` with `TemporalGrounderDb(db=PostgresDb(...), grounder=TemporalGrounder())` and keep `enable_agentic_memory=True` as-is.
- Frozen-dataclass `UserMemory` objects are handled defensively — `_ground_memory` swallows `AttributeError` so a future memory model change does not crash the wrapper.
- `event_at:YYYY-MM-DD` topic format is the contract used downstream by recall queries. Changes to the format are breaking for any app that filters on that topic prefix.

### `TemporalGrounderDb` runs *after* Agno's MemoryManager paraphrase

`enable_agentic_memory=True` routes memory writes through Agno's `MemoryManager`, which asks the LLM to summarize the user's message into a memory text **before** the db's `upsert_user_memory` is called. The wrapper hooks the upsert, so by the time grounding runs the text has already been rewritten — including any relative time expressions like "yesterday" or "next Tuesday".

In practice the LLM does one of three things to relative dates during paraphrase:

1. **Drops them** ("I bought groceries yesterday" → "User bought groceries"). No `event_at` is derivable. The grounder finds nothing to ground; the memory is stored without a date.
2. **Substitutes a nearby absolute date from the context window.** If the conversation just retrieved chunks with dates like `2024-01-16`, the LLM may write the memory as "User bought groceries on 2024-01-16" — a wrong calendar grounding the grounder cannot correct because the word "yesterday" is gone.
3. **Preserves the relative expression.** In this case the wrapper grounds it correctly and tags the memory with `event_at:YYYY-MM-DD`.

(1) and (2) are common; the wrapper alone cannot guarantee deterministic grounding because the paraphrasing step happens upstream. **Apps that need deterministic calendar grounding of chat-originated memories should ground the user input *before* it reaches the agent.** Pattern:

```python
from agno_plus.core.time_grounding.grounder import TemporalGrounder
from agno_plus.core.time_grounding.models import GroundingMode
from datetime import datetime, timezone

def ground_user_input(text: str, grounder: TemporalGrounder) -> str:
    grounded, _ = grounder.ground(
        text,
        mode=GroundingMode.PERSONAL,
        reference_date=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    return grounded

# Then:
agent.run(ground_user_input(user_message, grounder), user_id=...)
```

The agent (and the downstream MemoryManager) sees `"I bought groceries 2026-06-04 [yesterday] and spent 45 euros"`. Paraphrase becomes `"User bought groceries on 2026-06-04 for 45 euros"` — already correct. `TemporalGrounderDb` then runs and detects the inline `2026-06-04`, so the `event_at:2026-06-04` topic is populated even though the paraphrase stripped the bracketed annotation.

`TemporalGrounderDb` remains useful as a defence in depth — it catches memories that bypass the pre-grounding path (for instance, memories Agno writes automatically from agent-side intermediate thoughts).

#### Inline ISO date fallback

When the grounder finds no relative expression, the hook scans the (post-paraphrase) memory text for the first valid `YYYY-MM-DD` token and uses it as `event_at`. Validation uses the `datetime` constructor, so regex matches like `2024-13-45` are rejected.

Precedence: relative-expression groundings win over inline ISO dates in the same text. A memory like `"Old note dated 2020-01-01: I met Bob yesterday"` produces `event_at:<today minus 1>`, not `event_at:2020-01-01`. The relative grounding is treated as the more authoritative signal because it carries the user's reference frame; the inline date is a fallback for paraphrased text where the relative expression has already been normalized.
