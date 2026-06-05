# IngestionPipeline as the reusable job contract — extraction_payload and chunks_count

**Status:** Accepted

## Decision

`IngestionPipeline` (in `core/pipeline/worker.py`) implements the `IngestionWorker` Protocol with two methods: `submit(source, filename, meta) → job_id` and `status(job_id) → JobStatus`.

`JobStatus` fields exposed to consumers:

| Field                 | Set after step | Type                  |
|-----------------------|----------------|-----------------------|
| `state`               | end            | `JobState` enum       |
| `current_step`        | each step      | `JobStep` enum / None |
| `completed_steps`     | each step      | `list[JobStep]`       |
| `extraction_payload`  | READ           | `list[dict]` or None  |
| `chunks_count`        | CHUNK          | `int`                 |
| `error`               | failed only    | `str` or None         |

`extraction_payload` is serialized `Document` data: `{id, source_type, source_name, content, metadata}` per emitted document. It is plain JSON-safe `list[dict]` (not the dataclass) so application code can persist it directly to a JSONB column without re-importing `core/models.py`.

The reference `IngestionPipeline` runs steps synchronously inside `submit()`. Production deployments are expected to wrap it in a thread pool, async worker, or queue (Celery, RQ) — the protocol's `submit` returns immediately by contract but the reference implementation chooses synchrony for simplicity and testability.

## Rationale

Two needs drive the `JobStatus` shape:

1. **Extraction preview.** Apps want to show users what was parsed from the file (block list, table headers, row counts) without re-running the reader. Storing the serialized document list immediately after READ makes that data available to the app layer.
2. **Observability.** A pipeline that does not surface intermediate progress turns "still running after 5 minutes" into a black box. `current_step` plus `completed_steps` lets the UI render a step bar (read → ground → chunk → embed → upsert) without polling-time guesswork.

Picking *which* fields to expose was a deliberate scope cut. `chunks_count` is recorded; chunk *content* is not — chunks are upserted into the store and live there. Re-shipping every chunk on the status object would bloat the response and duplicate truth.

## Alternatives considered

**One callback per step.** Pass `on_step(step, payload)` callbacks. Works for in-process apps but doesn't survive serialization to a queue worker — the worker would need to re-establish the callback after deserializing the job. Status fields on a serializable object compose better with FastAPI's `GET /jobs/{id}` pattern.

**Store full chunks on `JobStatus`.** Apps already need vector store search; chunk text lives there. Two truths to keep in sync.

**Status as plain dict.** Faster to define, harder to evolve. Adding a field is a silent breaking change for consumers reading by key.

## Consequences

- Apps persist `extraction_payload` and `chunks_count` into their own `ingested_files` table after the job completes (see agentic-aide ADR-0005 for the consumer pattern).
- The reference pipeline is synchronous. The async/queue concern is documented as a consumer responsibility (see consumer guidance ADR G-0002).
- `JobStep.EMBED` is a marker step — embedding actually happens inside the vector store's upsert. The marker is kept so the step bar renders the same five steps the user sees in docs.
- Adding a new step (e.g. `EXTRACT_ENTITIES`) means extending the `JobStep` enum, which is a versioned event for downstream consumers that pattern-match on it.
