"""TracingPort — cross-cutting observability protocol.

Implementations: PgTracer (DB lineage), LangfuseTracer (visual UI).
Passed to sub-agents at construction; silent when not provided (None check).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from agno_plus.core.models import SourceRef


@runtime_checkable
class TracingPort(Protocol):
    def start_run(
        self,
        user_id: str,
        input_text: str,
    ) -> str:
        """Create a new trace run. Returns run_id."""
        ...

    def log_tool_call(
        self,
        run_id: str,
        step: int,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: str | None = None,
        error: str | None = None,
    ) -> None: ...

    def log_retrieval(
        self,
        run_id: str,
        source_ref: SourceRef,
        score: float = 0.0,
    ) -> None: ...

    def log_answer(
        self,
        run_id: str,
        answer_text: str,
        sources: list[SourceRef],
    ) -> None: ...

    def complete_run(
        self,
        run_id: str,
        intents: list[str],
        status: str = "completed",
    ) -> None: ...
