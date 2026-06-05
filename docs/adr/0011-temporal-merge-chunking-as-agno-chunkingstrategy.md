# TemporalMergeChunking implements Agno ChunkingStrategy, not a Knowledge.insert override

**Status:** Accepted

## Decision

`adapters/agno/chunking_strategy.TemporalMergeChunking` implements Agno's `ChunkingStrategy` ABC (`chunk(document) → List[Document]`). It delegates to `core/pipeline/chunking.chunk_text_structured`, then re-wraps each chunk string as an Agno `Document` preserving `content_id`, `name`, and `meta_data` from the source.

This strategy is the canonical plug-in for Agno's `Knowledge` and `KnowledgeStore.insert_document()`. It does not subclass or override Agno's `Knowledge.insert()`.

## Rationale

`Knowledge.insert()` owns its own chunking pipeline internally, with no hook between READ/GROUND and CHUNK. Two constraints make the public override of `insert()` unattractive:

1. **One registry row per `insert()` call.** A multi-block reader output (Excel with three sheets) ends up as three registry rows for one logical file when `insert()` is called per document.
2. **Temporal grounding must run before chunking.** Grounding rewrites relative dates in the raw text. Delegating chunking to `insert()` bypasses grounding entirely.

`ChunkingStrategy` is Agno's published extension point. By implementing it instead of overriding `insert()`, agno-plus stays compatible across Agno minor versions and the chunker becomes usable anywhere Agno accepts a `ChunkingStrategy` (e.g. `Knowledge.insert(chunking_strategy=...)`).

`content_id` propagation matters: it lets the agentic-knowledge-filters feature (Agno) deduplicate by source document and lets the chat UI roll up citations back to a single source file.

## Alternatives considered

**Subclass `Knowledge` and override `insert()`.** Ties application logic to private internals; breaks on Agno upgrade. The `ChunkingStrategy` ABC is the stable surface.

**Inline chunk/embed/upsert via raw SQL.** Bypasses Agno's registry semantics. Any schema change to `ai.agno_knowledge` silently breaks the integration.

**Re-implement chunking in adapter only.** Couples chunking to Agno; LangChain adapter would duplicate it. Keeping the chunker in `core/` with adapter wrappers honours ADR-0001.

## Consequences

- The CHUNK step of `IngestionPipeline` is logically the same algorithm as `TemporalMergeChunking.chunk()` — both call `chunk_text_structured`. Apps that delegate CHUNK/EMBED/UPSERT to `KnowledgeStore.insert_document()` (which uses the strategy internally) still get identical chunk boundaries.
- `_generate_chunk_id` is provided by the Agno base class; we don't override it. If Agno changes the id format, our chunks change format automatically.
- The strategy is configurable per instance (`max_tokens`, `overlap_tokens`) so applications can tune chunk size without forking the class.
- Semantic-similarity-driven merging (the `similarity_fn` in `chunk_text_structured`) is reachable from the core but not yet exposed on this Agno strategy. Adding it is one constructor argument when an adapter needs it.
