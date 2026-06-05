"""OpenTelemetry → Langfuse bridge for the agent.

Agno 2.x ships an OpenInference instrumentor that auto-emits OTel spans for
agent runs, model calls, *and tool executions*. Langfuse ingests standard
OTLP at `<LANGFUSE_HOST>/api/public/otel/v1/traces`, so wiring those two
together gets every tool call into the Langfuse UI with no manual spans.

Setup is idempotent — safe to call multiple times under uvicorn `--reload`.

Auth: Langfuse OTLP uses HTTP Basic with `public_key:secret_key`.
"""

from __future__ import annotations

import base64
import logging

from config import settings

logger = logging.getLogger(__name__)

_initialised = False


def setup() -> None:
    """Install Agno OpenInference instrumentation with OTLP export to Langfuse.

    No-op if any of LANGFUSE_HOST / LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY
    is missing.
    """
    global _initialised
    if _initialised:
        return
    if not (settings.langfuse_host and settings.langfuse_public_key and settings.langfuse_secret_key):
        return

    try:
        from openinference.instrumentation.agno import AgnoInstrumentor
        from opentelemetry import trace as trace_api
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    except ImportError as exc:
        logger.warning(
            "tracing: OpenTelemetry packages missing (%s); spans disabled. "
            "Install: opentelemetry-api opentelemetry-sdk "
            "opentelemetry-exporter-otlp-proto-http openinference-instrumentation-agno",
            exc,
        )
        return

    # Don't double-install if some other code already configured a provider.
    if isinstance(trace_api.get_tracer_provider(), TracerProvider):
        logger.info("tracing: provider already configured; skipping")
        _initialised = True
        return

    token = base64.b64encode(
        f"{settings.langfuse_public_key}:{settings.langfuse_secret_key}".encode()
    ).decode()
    exporter = OTLPSpanExporter(
        endpoint=f"{settings.langfuse_host.rstrip('/')}/api/public/otel/v1/traces",
        headers={"Authorization": f"Basic {token}"},
    )

    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace_api.set_tracer_provider(provider)

    AgnoInstrumentor().instrument(tracer_provider=provider)
    _initialised = True
    print(f"[tracing] OTel → {settings.langfuse_host} (Agno instrumentor active)")
