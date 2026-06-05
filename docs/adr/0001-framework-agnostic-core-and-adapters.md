# Framework-agnostic core with framework-specific adapters

**Status:** Accepted

## Decision

`agno_plus/core/` contains zero framework imports. Every module that touches Agno, LangChain, PgVector, Langfuse, OpenAI, or Ollama lives in `agno_plus/adapters/<framework>/`.

Core depends only on the Python standard library, `dataclasses`, `typing.Protocol`, and a narrow set of pure-Python parsers (`openpyxl`, `pypdf`). Embedding, vector storage, agent runtimes, and LLM calls are reached through adapter modules.

Interfaces are defined as `typing.Protocol` (structural, not nominal). Adapters do not inherit from a core base class; they satisfy a protocol by shape. `runtime_checkable` is applied where the protocol is used for `isinstance` defence.

## Rationale

Two consumers were anticipated: the in-tree Agno consumer (`agentic-aide`) and an out-of-tree LangChain consumer. Without a clean port boundary, every reader, store, and pipeline grows a framework dependency that forces consumers to install both frameworks even when they only use one. A protocol-based core also lets test code stub stores and tracers without import gymnastics.

Hexagonal architecture also matches the layering already used in the reference codebase. Keeping the same shape makes the boundary obvious during code review — anything in `core/` that imports `agno` or `langchain` is a bug.

## Alternatives considered

**Single-package design with conditional imports.** Use lazy `try`/`except ImportError` inside core modules. Rejected: the import graph becomes opaque, tests need to monkey-patch import machinery, and a missing optional dependency surfaces as a runtime error rather than at install time.

**ABCs instead of Protocols.** Forces inheritance, which couples adapter classes to library classes and prevents third parties from satisfying the contract from an unrelated package. Protocols are structural and accept any conformant type.

## Consequences

- New framework adapter = one new subdirectory under `adapters/<name>/` plus the import shim; core untouched.
- `pyproject.toml` declares framework integrations as extras (`[agno]`, `[langchain]`, `[langfuse]`); none are required by base install.
- Linting rule: imports of `agno`, `langchain`, `openai`, `ollama`, `httpx`, `langfuse`, or `pgvector` in `agno_plus/core/**` are violations.
- A protocol in core sometimes duplicates a near-identical type in Agno (e.g. `MemoryStore`). The duplication is intentional and is paid back the first time another framework adapter is added.
