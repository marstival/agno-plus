"""LangfuseTracer — TracingPort implementation using the Langfuse SDK v4+.

Requires: pip install langfuse>=4
Env vars consumed by Langfuse SDK automatically:
  LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_BASE_URL (optional)

Traces are structured as:
  Root span (= one chat turn, anchored to a Langfuse trace)
    └─ Tool span per sub-agent invocation (ended immediately)
    └─ Retriever span per retrieval (ended immediately)
    └─ Generation span for the final answer (ended immediately)
"""

from __future__ import annotations

import dataclasses
from typing import Any

from agno_plus.core.models import SourceRef


def _source_ref_to_dict(ref: SourceRef) -> dict[str, Any]:
    return dataclasses.asdict(ref)  # type: ignore[arg-type]


class LangfuseTracer:
    """Wraps the Langfuse SDK v4 to implement TracingPort."""

    def __init__(
        self,
        public_key: str | None = None,
        secret_key: str | None = None,
        host: str | None = None,
    ) -> None:
        from langfuse import Langfuse  # optional dep

        kwargs: dict[str, Any] = {}
        if public_key:
            kwargs["public_key"] = public_key
        if secret_key:
            kwargs["secret_key"] = secret_key
        if host:
            kwargs["base_url"] = host  # v4 uses base_url

        self._client = Langfuse(**kwargs)
        self._root_spans: dict[str, Any] = {}  # run_id → root LangfuseSpan

    # --- TracingPort interface ---

    def start_run(self, run_id: str, user_id: str, input_text: str) -> None:
        from langfuse import Langfuse
        from langfuse.types import TraceContext

        trace_id = Langfuse.create_trace_id()
        root = self._client.start_observation(
            trace_context=TraceContext(trace_id=trace_id),
            name="chat_turn",
            as_type="span",
            input=input_text,
        )
        self._root_spans[run_id] = root

    def log_tool_call(
        self,
        run_id: str,
        step: int,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: str | None = None,
        error: str | None = None,
    ) -> None:
        root = self._root_spans.get(run_id)
        if root is None:
            return
        child = root.start_observation(
            name=tool_name,
            as_type="tool",
            input=tool_args,
            output=tool_result,
            level="ERROR" if error else "DEFAULT",
            status_message=error,
        )
        child.end()

    def log_retrieval(self, run_id: str, source_ref: SourceRef, score: float = 0.0) -> None:
        root = self._root_spans.get(run_id)
        if root is None:
            return
        child = root.start_observation(
            name="retrieval",
            as_type="retriever",
            input={"score": score},
            output=_source_ref_to_dict(source_ref),
        )
        child.end()

    def log_answer(self, run_id: str, answer_text: str, sources: list[SourceRef]) -> None:
        root = self._root_spans.get(run_id)
        if root is None:
            return
        child = root.start_observation(
            name="final_answer",
            as_type="generation",
            output=answer_text,
            metadata={"sources": [_source_ref_to_dict(s) for s in sources]},
        )
        child.end()

    def complete_run(self, run_id: str, intents: list[str], status: str = "completed") -> None:
        root = self._root_spans.get(run_id)
        if root is None:
            return
        root.update(metadata={"intents": intents, "status": status})
        root.end()
        self._client.flush()
        self._root_spans.pop(run_id, None)
