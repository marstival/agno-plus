"""DomainKnowledge — KnowledgeProtocol implementation for domain/user-scoped RAG.

Usage:
    from agno_plus.adapters.agno import DomainKnowledge

    knowledge_agent = Agent(
        knowledge=DomainKnowledge(store=my_store, top_k=5),
        ...
    )

The store must satisfy the SearchableStore Protocol: a `search` method that
accepts (query, *, user_id, domain_id, top_k) and returns a list of objects
with `.id`, `.content`, and `.metadata` attributes (compatible with MemoryRecord).
"""

from __future__ import annotations

import json
from typing import Any, Callable, List, Protocol, runtime_checkable

from agno.knowledge.document.base import Document as AgnoDocument


@runtime_checkable
class SearchableStore(Protocol):
    """Structural interface required by DomainKnowledge.

    Any store with a matching search() signature satisfies this protocol —
    no inheritance required.
    """

    def search(
        self,
        query: str,
        *,
        user_id: str,
        domain_id: str,
        top_k: int,
    ) -> list[Any]:
        ...


class DomainKnowledge:
    """KnowledgeProtocol implementation with domain/user-scoped search for Agno agents.

    Args:
        store: Any object satisfying SearchableStore (search returns records
               with .id, .content, .metadata attributes).
        top_k: Maximum number of chunks returned per search call.
    """

    def __init__(self, store: SearchableStore, top_k: int = 5) -> None:
        self._store = store
        self._top_k = top_k

    def build_context(self, **kwargs: Any) -> str:
        return (
            "You have access to a domain-scoped knowledge base via the search_knowledge tool. "
            "Pass the domain UUID (e.g. '34e741ce-2350-40a1-b637-125f79115a8e') as domain_id "
            "to restrict results to a single domain. Pass an empty string to search across all "
            "domains. Never pass a domain name — only the UUID. "
            "Use this tool whenever the user's question may be answered by ingested documents."
        )

    def get_tools(self, **kwargs: Any) -> List[Callable]:
        run_context = kwargs.get("run_context")
        user_id: str = getattr(run_context, "user_id", None) or ""
        return [self._make_search_fn(user_id)]

    async def aget_tools(self, **kwargs: Any) -> List[Callable]:
        return self.get_tools(**kwargs)

    def get_valid_filters(self) -> set[str]:
        """Return metadata keys available for agentic filtering.

        These keys are stored in chunk metadata during ingestion.
        Enables enable_agentic_knowledge_filters=True on the agent when
        domain_name is also stored in chunk metadata.
        """
        return {"domain_id", "filename"}

    async def aget_valid_filters(self) -> set[str]:
        return self.get_valid_filters()

    def retrieve(self, query: str, **kwargs: Any) -> List[AgnoDocument]:
        _filters = kwargs.get("filters") or {}
        user_id: str = kwargs.get("user_id") or (
            _filters.get("user_id", "") if isinstance(_filters, dict) else ""
        )
        domain_id: str = kwargs.get("domain_id") or (
            _filters.get("domain_id", "") if isinstance(_filters, dict) else ""
        )
        records = self._store.search(
            query, user_id=user_id, domain_id=domain_id, top_k=self._top_k
        )
        return [
            AgnoDocument(
                id=r.id,
                name=r.metadata.get("filename", "chunk"),
                content=r.content,
                meta_data=r.metadata,
            )
            for r in records
        ]

    def _make_search_fn(self, user_id: str) -> Callable:
        store = self._store
        top_k = self._top_k

        def search_knowledge(query: str, domain_id: str = "") -> str:
            """Search the knowledge base for relevant information.

            Args:
                query: The search query text.
                domain_id: UUID of the domain to restrict search
                    (e.g. '34e741ce-2350-40a1-b637-125f79115a8e').
                    Pass empty string to search across ALL domains.
                    Never pass a domain name — only the UUID.
            """
            results = store.search(query, user_id=user_id, domain_id=domain_id, top_k=top_k)
            if not results:
                return json.dumps({"chunks": []})
            chunks = [
                {
                    "id": r.id,
                    "domain_id": r.metadata.get("domain_id", ""),
                    "excerpt": r.content[:400],
                    "score": r.metadata.get("score", 0.0),
                    "filename": r.metadata.get("filename", ""),
                }
                for r in results
            ]
            return json.dumps({"chunks": chunks})

        return search_knowledge
