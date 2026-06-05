# DomainKnowledge implements Agno KnowledgeProtocol with a runtime user_id closure

**Status:** Accepted

## Decision

`adapters/agno/domain_knowledge.DomainKnowledge` implements Agno's `KnowledgeProtocol` (`build_context`, `get_tools`, `aget_tools`, `retrieve`, `get_valid_filters`).

- `get_tools(run_context=...)` reads `run_context.user_id` and returns a fresh `search_knowledge(query, domain_id)` closure bound to that `user_id`. Called on every agent run by Agno.
- `retrieve(query, user_id=..., domain_id=...)` is a direct programmatic retrieval path.
- `build_context()` returns a string injected into the agent system prompt explaining the `search_knowledge` tool and the UUID-only contract for `domain_id`.
- `get_valid_filters()` returns `{"domain_id", "filename"}` enabling Agno's `enable_agentic_knowledge_filters=True`.

The store is required to satisfy a structural `SearchableStore` protocol: `search(query, *, user_id, domain_id, top_k) -> list[record]` where each record has `.id`, `.content`, and `.metadata`.

## Rationale

Two requirements rule out the simpler `@tool` decorator:

1. **`user_id` must be bound at run time, not construction time.** A module-level closure captures whatever `user_id` was present when the agent was built — fine for a single-user demo, wrong for any real assistant. Agno's `run_context` injects the current run's `user_id`, and `get_tools()` is the published hook for using it.
2. **System prompt integration.** `Agent(knowledge=DomainKnowledge(...))` wires `build_context()` into the prompt automatically and registers the returned tools as first-class knowledge tools. Hand-rolled tools require the developer to remember to add an instructions block to the system prompt and stay consistent across agents. The KnowledgeProtocol hook removes the chance for drift.

Implementing the protocol structurally (not by inheritance) keeps the adapter type free of `agno.Knowledge` base-class coupling — only the protocol methods are needed.

## Alternatives considered

**Plain `@tool` with module-level user_id.** Works only for a fixed-user environment. Breaks multi-tenant agents and on-the-fly run context changes.

**Subclass Agno `KnowledgeTools`.** Inherits unwanted behaviour, especially a default `search_knowledge()` with no `domain_id` parameter. Replacing methods means fighting the parent class signature.

**Pass `user_id` via tool argument.** Lets the LLM populate `user_id` from prompt text. Trust-boundary violation: the LLM can be coerced (prompt injection, copy-paste) to pass another user's id. The closure pattern makes the binding non-negotiable from the agent's perspective.

## Consequences

- The `domain_id` argument on the tool is a UUID string. Passing a name silently returns no results — documented in `build_context()`. UUID validation is not enforced here because the cost of a bad UUID is an empty result, not a security issue (the `user_id` closure already gates).
- Adapters that want to expose more filter dimensions (e.g. `tag`, `language`) extend `get_valid_filters()` and read the filters from `**kwargs` in `retrieve()`.
- The async pair `aget_tools` delegates to `get_tools` for now; if a future store needs async I/O, override both.
- Apps that combine semantic search with SQL execution (see agentic-aide ADR-0016) wire `DomainKnowledge` *and* Agno `SQLTools` onto the same agent — the protocol does not preclude additional tools.
