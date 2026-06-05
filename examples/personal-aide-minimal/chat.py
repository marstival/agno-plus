"""Chat handler using Agno Agent + agno-plus DomainKnowledge.

Replaces the previous hand-rolled `call_llm` + raw RAG flow with a real
Agno agent:

  - knowledge=DomainKnowledge(store)  → search_knowledge tool bound to USER_ID
                                         (ADR-0009; in this demo USER_ID is a
                                         constant, in a real app it comes from
                                         the request)
  - db=TemporalGrounderDb(PostgresDb)  → defence-in-depth grounding hook on
                                         memory upserts (ADR-0005)
  - pre-grounding of the user message  → deterministic calendar grounding
                                         before Agno's MemoryManager paraphrase
                                         can drop or hallucinate the date
                                         (see ADR-0005 "Consequences")
  - add_history_to_context             → native session history, no custom
                                         table

Langfuse tracing is optional; when configured, a single trace is opened per
chat turn and the agent's run is attached as a generation span.
"""

from __future__ import annotations

from datetime import datetime, timezone

from agno_plus.core.time_grounding.models import GroundingMode

from bootstrap import USER_ID, agent, grounder, langfuse


def _pre_ground(message: str) -> str:
    """Replace relative time expressions with explicit calendar dates so
    Agno's MemoryManager paraphrase cannot drop or hallucinate the date.

    Format produced by TemporalGrounder is `YYYY-MM-DD [original token]`,
    e.g. "I went yesterday" → "I went 2026-06-04 [yesterday]".
    """
    text, _ = grounder().ground(
        message,
        mode=GroundingMode.PERSONAL,
        reference_date=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    return text


def reply(message: str) -> str:
    grounded = _pre_ground(message)
    lf = langfuse()
    trace = lf.trace(name="chat", input=message) if lf else None
    gen = trace.generation(name="agent", input=grounded) if trace else None
    try:
        response = agent().run(grounded, user_id=USER_ID)
        output = getattr(response, "content", str(response))
    except Exception as exc:
        output = f"Sorry, the agent failed: {exc}"
    finally:
        if gen:
            gen.end(output=output)
        if trace:
            trace.update(output=output)
        if lf:
            lf.flush()
    return output
