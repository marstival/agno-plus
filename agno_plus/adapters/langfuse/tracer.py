"""LangfuseTracer — TracingPort implementation using the Langfuse SDK.

Requires: pip install langfuse
Env vars consumed by Langfuse SDK automatically:
  LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST (optional)

Traces are structured as:
  Trace (= one chat turn)
    └─ Span per sub-agent invocation (tool_call)
         └─ Event per retrieval
    └─ Generation for the final answer
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from agno_plus.core.models import SourceRef


def _source_ref_to_dict(ref: SourceRef) -> dict[str, Any]:
    return dataclasses.asdict(ref)  # type: ignore[arg-type]


class LangfuseTracer:
    """Wraps the Langfuse SDK to implement TracingPort."""

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
            kwargs["host"] = host

        self._client = Langfuse(**kwargs)
        self._traces: dict[str, Any] = {}   # run_id → trace
        self._spans: dict[str, Any] = {}    # run_id → {step: span}

    # --- TracingPort interface ---

    def start_run(self, user_id: str, input_text: str) -> str:
        trace = self._client.trace(
            name="chat_turn",
            input=input_text,
            user_id=user_id,
        )
        run_id = trace.id
        self._traces[run_id] = trace
        self._spans[run_id] = {}
        return run_id

    def log_tool_call(
        self,
        run_id: str,
        step: int,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: str | None = None,
        error: str | None = None,
    ) -> None:
        trace = self._traces.get(run_id)
        if trace is None:
            return
        span = trace.span(
            name=tool_name,
            input=tool_args,
            output=tool_result,
            level="ERROR" if error else "DEFAULT",
            status_message=error,
        )
        self._spans[run_id][step] = span

    def log_retrieval(self, run_id: str, source_ref: SourceRef, score: float = 0.0) -> None:
        trace = self._traces.get(run_id)
        if trace is None:
            return
        trace.event(
            name="retrieval",
            input={"score": score},
            output=_source_ref_to_dict(source_ref),
        )

    def log_answer(self, run_id: str, answer_text: str, sources: list[SourceRef]) -> None:
        trace = self._traces.get(run_id)
        if trace is None:
            return
        trace.generation(
            name="final_answer",
            output=answer_text,
            metadata={"sources": [_source_ref_to_dict(s) for s in sources]},
        )

    def complete_run(self, run_id: str, intents: list[str], status: str = "completed") -> None:
        trace = self._traces.get(run_id)
        if trace is None:
            return
        trace.update(
            metadata={"intents": intents, "status": status},
        )
        self._client.flush()
        self._traces.pop(run_id, None)
        self._spans.pop(run_id, None)
