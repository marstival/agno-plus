# Unified call_llm() lives in adapters/llm.py, not in core

**Status:** Accepted

## Decision

`adapters/llm.call_llm(prompt, *, backend, model, ...)` is the single place that branches between OpenAI-compatible and Ollama HTTP endpoints. It accepts `json_response`, `max_tokens`, `temperature`, `api_key`, `base_url`. It is **not** part of `agno_plus/core/`.

Use cases inside agno-plus:

- `ImageReader` calls it for OCR via vision LLM (the documented exception to deterministic ingestion — see ADR-0003).
- Application services may call it for LLM-driven enrichment (column descriptions, entity extraction).

The reference agent loop in consumer apps uses Agno's `Agent` / `Team`, **not** `call_llm()`. The helper is for one-shot completions, not chat orchestration.

## Rationale

OpenAI/Ollama backend switching is exactly the boilerplate that grows across every service in a small app — schema annotation, entity extraction, summarization. Centralizing it removes the per-service `if backend == "openai" / elif backend == "ollama"` ladder.

It belongs in `adapters/`, not `core/`, because:

1. It depends on `openai` and `httpx` packages, which violates the core-no-framework-deps rule (ADR-0001).
2. It is an integration concern — what specific LLM provider — rather than a domain concern. The same call could be replaced by a different helper that calls Anthropic or vLLM without changing core.

The function intentionally returns plain `str` (not a structured `Completion`) so JSON parsing is the caller's responsibility — keeping the helper provider-agnostic at the response shape.

## Alternatives considered

**Use Agno's `OpenAIChat` / `OllamaChat` directly.** Works for agent loops but adds ceremony for one-shot completions. The agno-plus helper is ~30 lines and saves consumers from importing two model classes just for a JSON extraction.

**Wrap LiteLLM.** LiteLLM unifies dozens of providers. Heavy dependency for a two-provider switch; we have not yet hit a use case that demands the third.

**Stream by default.** Streaming completions add buffering complexity for callers who only want the final string. Streaming variants can be added later as `call_llm_streaming()` without breaking the existing API.

## Consequences

- `call_llm()` is the only network-calling function in agno-plus that is not gated behind an explicit reader/store class. Documented as "side-effecting" so test suites know to mock it.
- `OPENAI_API_KEY` / `OLLAMA_URL` are env-driven at the application layer; the helper accepts them as keyword arguments and does not read environment variables itself.
- A streaming variant, a third backend (Anthropic, vLLM), or a structured-completion variant (Pydantic schema) can be added as new functions; the existing `call_llm()` signature stays stable.
- Apps that want full agentic behavior (tools, memory, history) use Agno's `Agent` / `Team`. `call_llm()` is the right tool only for narrow extraction/annotation prompts.
