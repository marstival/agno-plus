# agno-plus — docs

Architecture decision records and consumer guidance for `agno-plus`.

## Library ADRs (`adr/`)

Library-scope decisions that govern how `agno-plus` is built. Each ADR explains a single decision: the choice, why, what was rejected, and the consequences. Numbering is monotonic; the index is below.

| # | Title |
|---|---|
| 0001 | [Framework-agnostic core and adapters](adr/0001-framework-agnostic-core-and-adapters.md) |
| 0002 | [Own Document and MemoryRecord model](adr/0002-own-document-and-memory-model.md) |
| 0003 | [Deterministic ingestion — no LLM calls in pipeline](adr/0003-deterministic-ingestion-no-llm-in-pipeline.md) |
| 0004 | [Three temporal-grounding modes; bootstrap-time choice](adr/0004-temporal-grounding-modes-and-app-bootstrap.md) |
| 0005 | [Episodic grounding via wrapper, not memory fork](adr/0005-episodic-grounding-via-wrapper-not-fork.md) |
| 0006 | [Spreadsheet block detection vs Agno ExcelReader](adr/0006-spreadsheet-block-detection-vs-agno-excelreader.md) |
| 0007 | [IngestionPipeline job contract — extraction_payload + chunks_count](adr/0007-ingestion-pipeline-job-contract.md) |
| 0008 | [Typed SourceRef union for citations](adr/0008-source-ref-typed-citations.md) |
| 0009 | [DomainKnowledge KnowledgeProtocol with run-context user closure](adr/0009-domain-knowledge-knowledgeprotocol-runtime-user-closure.md) |
| 0010 | [KnowledgeStore — PgVector with domain/user scoping](adr/0010-knowledge-store-pgvector-domain-user-scoping.md) |
| 0011 | [TemporalMergeChunking as Agno ChunkingStrategy](adr/0011-temporal-merge-chunking-as-agno-chunkingstrategy.md) |
| 0012 | [Dynamic structured tables with conservative type inference](adr/0012-dynamic-structured-tables-conservative-type-inference.md) |
| 0013 | [TracingPort with Pg and Langfuse adapters](adr/0013-tracing-port-pluggable-adapters.md) |
| 0014 | [StorageBackend port; LocalStorageBackend default](adr/0014-storage-backend-port-local-default.md) |
| 0015 | [call_llm() lives in adapters, not core](adr/0015-llm-helper-as-adapter-not-core.md) |

## Consumer guidance (`guidance/`)

Recommended patterns for applications **built on** `agno-plus`. These are not library code — they document recurring decisions that consumer apps repeatedly get right or wrong. Each one points back to the library ADRs and the agentic-aide ADRs it draws from.

| # | Title |
|---|---|
| G-0001 | [Identity required — never default user_id](guidance/G-0001-identity-required-no-default-user.md) |
| G-0002 | [Async ingest with 202 + poll](guidance/G-0002-async-ingest-202-and-poll.md) |
| G-0003 | [Harden SQL access when exposing structured tables](guidance/G-0003-sql-hardening-when-exposing-structured-tables.md) |
| G-0004 | [Grounding mode per source — set at bootstrap](guidance/G-0004-grounding-mode-per-source-policy.md) |

## Other documents

- [`boundary-analysis.md`](boundary-analysis.md) — what goes in `agno-plus` vs the application layer, with the rationale and concrete examples from `agentic-aide` and `personal-aide-minimal`.
