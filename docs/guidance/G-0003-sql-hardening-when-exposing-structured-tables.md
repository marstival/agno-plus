# G-0003 — Harden SQL access when exposing structured tables to an LLM agent

**Status:** Recommended for consumer applications

## Guidance

When an Agno agent is given Agno's `SQLTools` against tables created by `agno_plus.core.structured.create_dynamic_table`, three layers should be in place before the route is exposed to real users:

### 1. Database role boundary

Create a minimal-privilege role (`aide_readonly` in agentic-aide) that has `LOGIN`, `CONNECT`, `USAGE on public`, and `SELECT` only on the dynamic tables. Application tables (`agno_memories`, `ingested_files`, trace tables, auth tables) are never visible to the agent's SQL engine.

`create_dynamic_table(engine, table, headers, types, grant_to="aide_readonly")` issues the GRANT inline so new tables are reachable by the role on creation. The role is created once via an init script run as superuser.

### 2. Statement timeout at the connection level

`connect_args={"options": "-c statement_timeout=5000"}` on the read-only engine sets a server-side 5-second cap. Long-running or accidentally-malicious queries are killed at the database before they exhaust the pool.

### 3. User-scoping at the instruction layer

Provide a `list_my_sql_tables` tool that returns only the calling user's tables (joined to the application's `domains` table, filtered by `user_id`). The agent is instructed in its system prompt to only reference tables from that result. Combined with the role boundary, the agent has no SQL path to discover or read another user's tables.

`SQLTools(list_tables=False)` disables Agno's built-in introspection so the only enumeration path is the user-scoped tool.

## Why

LLM-generated SQL has two failure modes the application is responsible for closing:

- **Application-table escape.** Without role limits, an agent that drifts off-task can read `agno_memories` or `ingested_files`. The role boundary makes this a NOOP at the database layer.
- **Cross-user discovery.** Without instruction-layer scoping, the agent can issue `SELECT * FROM information_schema.tables` and discover every `sd_*` table. The user-scoping tool returns only the caller's; the role boundary catches drift on the instruction.

A third defence (AST allowlist via `sqlglot`) was evaluated in the agentic-aide codebase and rejected as redundant once both layers above are in place. Apps that need stricter audit may still add it.

## Apply when

- Exposing structured-domain SQL to an Agno agent in any production-shaped deployment.
- Multi-tenant assistant applications.

## Apply if not

- A single-user local example with one human in front of it (the role can be omitted; the instruction layer alone is sufficient for the cost/benefit).

## Related ADRs

- agno-plus ADR-0012 (dynamic structured tables; `grant_to` parameter).
- agentic-aide ADR-0013 (SQL hardening: aide_readonly role, statement timeout).
- agentic-aide ADR-0016 (unified KnowledgeAgent with SQLTools; instruction layer).
