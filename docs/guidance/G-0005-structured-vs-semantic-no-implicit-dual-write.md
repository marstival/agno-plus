# G-0005 — Structured ingestion goes to SQL; semantic ingestion goes to vectors. No implicit dual-write.

**Status:** Recommended for consumer applications

## Guidance

When a consumer app supports both structured ingestion (CSV / XLSX → dynamic SQL tables via `agno_plus.core.structured`) and semantic ingestion (PDF / text / image → `KnowledgeStore`), keep the paths separate:

- **Structured ingestion writes to SQL only.** No `KnowledgeStore.insert_document()` or `ingest_documents()` call for the same rows.
- **Semantic ingestion writes to the vector store only.** Don't shadow-copy chunks into SQL tables either.
- If the same file genuinely needs both surfaces, expose that as an explicit consumer action (e.g. an `ingest_mode=both` form field or two separate upload calls), not as a silent dual-write.

The agent reaches structured data through Agno's `SQLTools` plus annotation-aware helpers (`list_my_sql_tables`, `describe_table`, `run_sql_query`). It reaches unstructured documents through `DomainKnowledge` / `search_knowledge`. The two paths do not need to overlap.

## Why

The dual-write pattern (writing a flattened text representation of every CSV row into the vector store alongside the SQL upsert) has three concrete failure modes that we hit in `personal-aide-minimal` before removing it:

1. **Silent leakage into the agent's context.** With `search_knowledge=True` on the Agent, every turn does an automatic retrieval. The flattened CSV chunk contains every row including every distinct value of every column. The model picks up category lists, IDs, and prices from the retrieval and can use them in generated SQL without ever issuing a `SELECT DISTINCT`. That looks like deduction in the trace; it is actually leakage. (Observed: model enumerated 9 of 10 categories in a `WHERE category IN (...)` clause without querying for them.)

2. **Source-of-truth drift.** The SQL table is authoritative for tabular data. The chunk is a frozen snapshot at ingest time. Re-uploads, row deletes, and column-type changes (DATE → TEXT, etc.) update the table but not the chunk. Queries that reach the chunk return stale answers; queries that reach the table return current answers; the agent cannot tell the difference.

3. **Token cost without a clear win.** The flattened chunk consumes embedding cost at ingest, vector-store cost at storage, and prompt cost on every retrieval, in exchange for letting the model answer a question the SQL path already answers more accurately. The shape of "average / count / filter / compare" questions is exactly what `SQLTools` is for.

The dual-write was originally motivated by "the agent should be able to answer questions about CSV contents through RAG too." With `SQLTools` in the agent's tool list (see agentic-aide ADR-0016, agno-plus G-0003) that motivation goes away.

## Apply when

- Building any consumer app that has both a structured ingest path and a semantic ingest path.
- Specifically: ingesting CSV / XLSX into dynamic SQL tables while also running an agent with `DomainKnowledge` over `KnowledgeStore`.

## Apply if not

- You need the same content searchable by semantic similarity *and* queryable by SQL, and the app's UX makes it acceptable that the vector copy may go stale. In that case, do the dual-write explicitly in a documented `ingest_mode=both` path so the trade-off is visible — don't make it the default.
- The structured ingest produces text that has narrative value beyond the rows (e.g. a CSV of notes/comments). Then the prose belongs in vectors; the metadata can go to SQL.

## Related decisions

- agno-plus ADR-0010 (KnowledgeStore is still appropriate for semantic ingestion; `ingest_documents` is still useful for multi-block readers like PDFs).
- agno-plus ADR-0012 (structured DDL helpers stay framework-agnostic; this guidance covers *how* a consumer uses them alongside the semantic store).
- agno-plus G-0003 (SQL hardening when exposing structured tables to an LLM agent).
- agentic-aide ADR-0015 documents the dual-write pattern in the reference app. agentic-aide ships the dual-write and accepts its trade-offs; `personal-aide-minimal` chooses not to. Both are valid consumer-side decisions.
