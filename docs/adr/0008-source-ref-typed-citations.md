# Typed SourceRef union for agent citations

**Status:** Accepted

## Decision

`core/models.py` defines four citation dataclasses and one union alias:

- `EpisodicRef(memory_id, event_at, excerpt, source_type="episodic")`
- `KnowledgeRef(domain_id, domain_name, document_name, excerpt, score, source_type="knowledge")`
- `DataRef(domain_id, domain_name, table_name, sql_query, row_count, source_type="data")`
- `WebRef(url, title, snippet, source_type="web")`
- `SourceRef = EpisodicRef | KnowledgeRef | DataRef | WebRef`

Sub-agents and tools produce these; the chat UI consumes them. The `source_type` discriminant is a fixed string per class so a JSON consumer can branch without dynamic isinstance checks.

## Rationale

Agent answers in a multi-source assistant come from very different surfaces: a recalled memory carries an `event_at`; a vector retrieval carries a chunk excerpt and a score; a SQL answer carries the table and the query that produced it; a web search carries a URL. A single citation type forces every surface into the lowest common shape (`{title, snippet}`) and the UI loses context. Four discriminated types let each surface render with the right affordance — a date pill for memories, a table-name chip for SQL, a domain breadcrumb for RAG.

Defining the types in agno-plus (not in the application) means every consumer of the library uses the same shape. The `agentic-aide` chat UI and the `personal-aide-minimal` example can share citation components.

## Alternatives considered

**Plain dict with a `type` key.** Loses static type checking, makes refactors brittle, and forces every UI consumer to learn the unwritten schema. Discriminated dataclasses give the same JSON shape with type safety.

**A single `SourceRef` with optional fields.** Every consumer must check which optional fields are populated. The type system can't help. The cross-product of which fields are present for each source surface is exactly the discriminator we want.

**Pydantic `BaseModel` with `Literal[...]` discriminators.** Cleaner JSON schema, but pulls Pydantic into `core/` which violates ADR-0002 (core stays dependency-free). Validation at the API boundary is the application's job.

## Consequences

- Sub-agent return shape is `tuple[answer_text: str, sources: list[SourceRef]]` (or equivalent), not free-form text.
- `TracingPort.log_retrieval(run_id, source_ref, score)` accepts the union — adapters serialize per source type.
- Adding a new source surface (e.g. `CalendarRef`) means adding one dataclass and one union member; existing UI code keeps working until it learns to render the new type.
- JSON serialization is by `dataclasses.asdict()` — the `source_type` field is preserved automatically.
