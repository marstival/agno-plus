"""Tests for DomainKnowledge Agno adapter."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

pytest.importorskip("agno", reason="agno not installed")

from agno_plus.adapters.agno.domain_knowledge import DomainKnowledge, SearchableStore  # noqa: E402
from agno_plus.core.models import MemoryRecord  # noqa: E402


def _make_record(id: str, content: str, **meta: Any) -> MemoryRecord:
    return MemoryRecord(id=id, content=content, metadata=meta)


def _make_store(records: list[MemoryRecord]) -> Any:
    store = MagicMock()
    store.search.return_value = records
    return store


def test_searchable_store_protocol():
    """A class with a matching search() signature satisfies SearchableStore structurally."""

    class ConcreteStore:
        def search(self, query: str, *, user_id: str, domain_id: str, top_k: int) -> list:
            return []

    assert isinstance(ConcreteStore(), SearchableStore)


def test_build_context_returns_string():
    dk = DomainKnowledge(store=_make_store([]))
    ctx = dk.build_context()
    assert isinstance(ctx, str)
    assert "search_knowledge" in ctx


def test_get_tools_returns_callable():
    dk = DomainKnowledge(store=_make_store([]))
    run_context = MagicMock()
    run_context.user_id = "user-1"
    tools = dk.get_tools(run_context=run_context)
    assert len(tools) == 1
    assert callable(tools[0])


def test_search_fn_passes_user_id():
    store = _make_store([])
    dk = DomainKnowledge(store=store, top_k=3)
    run_context = MagicMock()
    run_context.user_id = "user-abc"
    search_fn = dk.get_tools(run_context=run_context)[0]
    search_fn("my query", domain_id="d1")
    store.search.assert_called_once_with("my query", user_id="user-abc", domain_id="d1", top_k=3)


def test_search_fn_returns_json_chunks():
    records = [
        _make_record("r1", "chunk text", domain_id="d1", filename="file.pdf", score=0.9),
    ]
    dk = DomainKnowledge(store=_make_store(records))
    run_context = MagicMock()
    run_context.user_id = "u1"
    search_fn = dk.get_tools(run_context=run_context)[0]
    result = json.loads(search_fn("query"))
    assert "chunks" in result
    assert result["chunks"][0]["id"] == "r1"
    assert result["chunks"][0]["filename"] == "file.pdf"


def test_search_fn_empty_result():
    dk = DomainKnowledge(store=_make_store([]))
    run_context = MagicMock()
    run_context.user_id = "u1"
    search_fn = dk.get_tools(run_context=run_context)[0]
    result = json.loads(search_fn("query"))
    assert result == {"chunks": []}


def test_retrieve_returns_agno_documents():
    from agno.knowledge.document.base import Document as AgnoDocument
    records = [_make_record("r1", "content", filename="doc.pdf")]
    dk = DomainKnowledge(store=_make_store(records))
    docs = dk.retrieve("query", user_id="u1", domain_id="d1")
    assert len(docs) == 1
    assert isinstance(docs[0], AgnoDocument)
    assert docs[0].content == "content"


def test_no_user_id_falls_back_to_empty_string():
    store = _make_store([])
    dk = DomainKnowledge(store=store)
    run_context = MagicMock()
    run_context.user_id = None
    search_fn = dk.get_tools(run_context=run_context)[0]
    search_fn("q")
    store.search.assert_called_once_with("q", user_id="", domain_id="", top_k=5)
