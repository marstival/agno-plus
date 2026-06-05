# TracingPort with pluggable Pg and Langfuse adapters

**Status:** Accepted

## Decision

`core/tracing.TracingPort` is a `Protocol` with five methods:

- `start_run(user_id, input_text) → run_id`
- `log_tool_call(run_id, step, tool_name, tool_args, tool_result=None, error=None)`
- `log_retrieval(run_id, source_ref: SourceRef, score=0.0)`
- `log_answer(run_id, answer_text, sources: list[SourceRef])`
- `complete_run(run_id, intents: list[str], status="completed")`

Two adapters are provided:

- `adapters/pgvector/tracer.PgTracer` — writes lineage rows into `trace_runs`, `trace_tool_calls`, `trace_retrievals`, `trace_answers`. Queryable in SQL for ad-hoc analytics.
- `adapters/langfuse/tracer.LangfuseTracer` — emits OTLP spans for Langfuse's visual trace UI.

Sub-agents and tools accept an optional `TracingPort`. When `None`, every method is a no-op via short-circuit at the call site. Two tracers can run side-by-side by wrapping them in a fan-out adapter; we don't ship one because applications differ on which signals to fork where.

## Rationale

Two tracing surfaces serve different audiences:

- **DB lineage** is for engineers writing SQL against runs: "show me retrieval scores for queries containing the word X in the last 24 hours." Cheap, persistent, joinable to `ingested_files`.
- **Langfuse** is for operators looking at the run graph visually: prompt → tool → retrieval → answer with span timings.

Forcing one or the other into a single sink would lose one audience. A Protocol with two adapters is the smallest abstraction that supports both.

Putting the port in `core/` (not in `adapters/`) is intentional because the `SourceRef` argument lives in core. The protocol can be implemented from outside without importing any adapter.

## Alternatives considered

**OpenTelemetry-only.** Langfuse implements OTLP, so an OTel-only design covers Langfuse. It does not cover the DB-lineage use case cleanly (would need a custom OTel exporter that writes to PostgreSQL). The Protocol with two named methods (`log_retrieval`, `log_answer`) is more directly aligned with the application's domain language than generic OTel spans.

**Adapter as decorator wrapping the agent.** Trace by wrapping `Agent.run()`. Misses the granular events the explicit `log_*` methods give (per-tool-call args, per-retrieval scores).

**Hardcode Langfuse in the app and skip the abstraction.** Works until a second sink is needed. We have two sinks already, so the abstraction has paid back.

## Consequences

- Sub-agents accept `tracer: TracingPort | None = None` in `__init__` and gate every `log_*` call with `if self._tracer:`. The boilerplate is acceptable; an inert `NullTracer` could remove it.
- A fan-out tracer is a 20-line wrapper class in the application; we don't ship one in agno-plus because the fan-out policy (e.g. log retrievals to Pg but answers to both) is consumer-specific.
- `complete_run(status="failed")` is the failure surface. Mid-run failures should land here, not raise out of the tracer.
- Adding a new tracer (Honeycomb, DataDog) is one file in `adapters/<vendor>/tracer.py` implementing the five methods.
