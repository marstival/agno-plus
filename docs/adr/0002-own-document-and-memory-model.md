# Own Document, Chunk, and MemoryRecord types in core

**Status:** Accepted

## Decision

`agno_plus/core/models.py` defines `Document`, `Chunk`, `IngestionResult`, `MemoryRecord`, `JobStatus`, and the `SourceRef` union as plain `dataclasses`. Adapters convert to and from framework-native types (`agno.knowledge.document.base.Document`, `langchain_core.documents.Document`) at the adapter boundary.

Dataclasses are used (not Pydantic) so core remains dependency-free. Field naming follows agno-plus conventions (`metadata`, `source_type`, `source_name`) regardless of what the framework calls them.

## Rationale

The core pipeline (`read → ground → chunk → embed → upsert`) must run without importing any framework. The pipeline therefore needs a `Document` type that core owns. Re-using Agno's `Document` would make `core/` import `agno`, violating ADR-0001. Re-using LangChain's would force the same on a LangChain consumer who never installs Agno.

Owning the type also lets us evolve fields (e.g. add `source_type`, `source_name` for the SpreadsheetReader block model) without negotiating with upstream frameworks.

## Alternatives considered

**Pydantic models.** Adds a heavyweight runtime dependency on core and gives little extra value since most fields are plain types. Validation at the framework boundary is sufficient. Dataclasses + `@runtime_checkable` Protocol give equivalent guarantees with the standard library.

**Re-export Agno's `Document`.** Adopting Agno's type as canonical creates an import dependency on Agno from `core/`, blocking the LangChain adapter. Adapters then end up converting Agno→Agno when chaining, which is wasted work.

**Generic `dict` payloads everywhere.** Loses static type checking, makes refactoring painful, and forces every consumer to know the unwritten schema by reading code.

## Consequences

- Every adapter has a tiny `_to_X_doc` / `_from_X_doc` conversion shim. The shim is the only place where framework type coupling exists.
- Core types are intentionally minimal — they do not carry embedding vectors. Embedding stays inside the vector store adapter.
- `JobStatus.extraction_payload` is serialized to `list[dict]` so application code can persist it without re-importing core. This is the only field where we exchange the dataclass for plain JSON-friendly types.
- `SourceRef` (ADR-0008) lives next to `Document` in the same module because the chat UI consumes both.
