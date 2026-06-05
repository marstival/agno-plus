# G-0001 — User identity is required, never defaulted, at every agno-plus boundary

**Status:** Recommended for consumer applications

## Guidance

Applications built on agno-plus should treat `user_id` as a required, validated field on every ingestion call, every memory write, and every knowledge search. agno-plus enforces this where it can — `KnowledgeStore.upsert()` and `insert_document()` raise `ValueError` when `user_id` is missing — but most enforcement is at the application boundary.

Concretely:

1. **Authenticate before reaching agno-plus.** A FastAPI dependency, a session middleware, or an explicit `Authorization` header check resolves identity once per request. The resolved `user_id` is the only identity that touches the library.
2. **Never accept caller-provided `user_id` from end users.** Form fields and query parameters named `user_id` are not authenticated. Bot integrations (Discord, Slack) may pass `user_id` because the bot has its own service authentication and is trusted to resolve identity.
3. **Do not implement a fallback `user_id` for "anonymous" requests.** A missing identity is a programming error, not a recoverable condition. Raising `401` (or `400` for backend-bug cases) is the correct response.
4. **Pin the closure at run time, not construction time.** `DomainKnowledge.get_tools(run_context=...)` reads `run_context.user_id` per agent run (ADR-0009). Construction-time `user_id` is a multi-tenant bug.

## Why

A library that defaults `user_id` cannot guarantee tenant isolation — once a default exists, every caller that forgets to pass an explicit id silently shares one bucket. The agentic-aide team adopted this stance in their ADR-0009 after considering an "anonymous user" fallback; the audit cost of one wrong default outweighs the convenience.

The `os.agno.com` admin plane is an explicit exception in agentic-aide (the email-keyed admin user is unscoped) and is handled by separate Agent instances. Apps that don't have an admin plane should not adopt the exception.

## Apply when

- Wiring `KnowledgeStore` into ingestion routes.
- Building `DomainKnowledge` for an `Agent`.
- Using `EpisodicMemoryGrounder` or `TemporalGrounderDb` from a chat surface.

## Apply if not

- Building a single-user local example (e.g. `personal-aide-minimal`) — set `USER_ID = "local_user"` as a constant and document it. The single value still flows through every call; it just doesn't come from a JWT.

## Related ADRs

- agno-plus ADR-0009 (DomainKnowledge runtime closure).
- agno-plus ADR-0010 (KnowledgeStore raises on missing user_id).
- agentic-aide ADR-0009 (two-plane identity model).
