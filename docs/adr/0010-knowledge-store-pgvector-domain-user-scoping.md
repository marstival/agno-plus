# KnowledgeStore: PgVector with domain/user scoping and content-hash dedupe

**Status:** Accepted

## Decision

`adapters/agno/knowledge_store.KnowledgeStore` wraps Agno's `PgVector` with three responsibilities:

1. **Domain/user scoping.** Every upsert writes `domain_id` and `user_id` into `meta_data`; every `search()` passes those as PgVector filters. A missing `user_id` raises `ValueError` immediately at the boundary (see consumer guidance G-0001).
2. **Content-hash dedupe.** Each upsert computes `md5(f"{domain_id}:{content}")` as `content_hash`. Re-ingesting the same chunk to the same domain is a no-op at the vector layer.
3. **Optional Agno registry write.** If `db_url` is provided, a `Knowledge` instance is constructed with a `PostgresDb` `contents_db`. `register_file()` writes a `KnowledgeRow` so the file shows up in Agno cloud's `/knowledge` UI with `linked_to=knowledge_name`. If `db_url` is omitted, the registry write is silently skipped.

Chunks are stored in `<schema>.<table_name>` with defaults `ai.agno_knowledge_chunks`. Both can be overridden per instance.

`KnowledgeStore.search()` returns `MemoryRecord`-compatible objects (`.id`, `.content`, `.metadata`) so the same store satisfies both the `SearchableStore` protocol used by `DomainKnowledge` (ADR-0009) and the `MemoryStore` protocol used by `IngestionPipeline` (ADR-0007).

## Rationale

A multi-tenant semantic store needs filter pushdown to the vector layer — re-filtering in application code after retrieval pulls every domain's chunks into memory before discarding them, scaling badly. PgVector accepts a JSONB filter, so user/domain become metadata fields, not separate columns.

The content-hash is *domain-prefixed* (not just `md5(content)`) so two domains can hold the same chunk text independently. Without the prefix, ingesting the same boilerplate paragraph into two domains becomes one chunk visible to both, breaking isolation.

The optional registry write decouples this adapter from the Agno cloud registry concern. Apps that don't use os.agno.com still get a working semantic store. Apps that do get the file visible in the cloud UI by passing `db_url`.

## Alternatives considered

**Separate physical tables per user.** Strongest isolation, awful operational story for backups and migrations. Filter-based isolation with a role boundary on the SQL side (when `SQLTools` is in play) is sufficient for the assistant use case.

**Don't dedupe.** Lets re-ingestion bloat the table linearly. The MD5 is cheap and removes the support burden.

**Hash content without domain prefix.** Cross-domain bleed. Rejected.

**Always require `db_url`.** Forces a registry write even when the app doesn't use Agno cloud. The optional pattern keeps the store useful in pure-pgvector deployments.

## Consequences

- `KnowledgeStore.upsert(content, metadata)` requires `user_id` in metadata; throws on absence. This is the consumer-side enforcement of G-0001.
- `delete_by_file(domain_id, filename)` and `delete_by_domain(domain_id)` exist for cleanup. They use `PgVector.delete_by_metadata()` so they are filter-driven, not id-driven.
- `register_file()` is silent when `db_url` is None — apps that need the registry but forget to wire it get no error. This is intentional: surfacing it would force every test to mock a PostgresDb.
- Chunking happens inside `insert_document()` via `TemporalMergeChunking` (ADR-0011) so dedupe runs on the chunked text, not the original document.
