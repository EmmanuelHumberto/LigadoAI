"""Tests for the rag/dense retriever."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import uuid4

from knowledge.domain import KnowledgeSearchResult
from runtime.protocols import Context
from techniques.rag.impl import RagTechnique, _DenseRetriever


class _FakeKnowledgeSearch:
    async def search(self, query: str, *, top_k: int = 8, filters=None):
        return [
            KnowledgeSearchResult(
                chunk_id=uuid4(),
                document_id=uuid4(),
                score=3.5,
                text="Faulhaber 2224 SR DFF coreless motor technical data.",
                source_uri="/docs/faulhaber-2224.md",
                metadata={"manufacturer": "Faulhaber", "model": "2224"},
            )
        ][:top_k]


class _FailingKnowledgeSearch:
    async def search(self, query: str, *, top_k: int = 8, filters=None):
        raise RuntimeError("database down")


@dataclass
class _FakeDocument:
    title: str
    source_uri: str
    status: str = "indexed"
    manufacturer: str | None = None
    model: str | None = None
    document_type: str | None = None


class _FakeInventorySearch(_FakeKnowledgeSearch):
    async def list_documents(self, include_deleted: bool = False):
        return [
            _FakeDocument(
                title="Motor 1",
                source_uri="/docs/motor-1.md",
                manufacturer="Faulhaber",
                model="2224",
                document_type="datasheet",
            ),
            _FakeDocument(
                title="Motor 2",
                source_uri="/docs/motor-2.md",
                manufacturer="Faulhaber",
                model="2610",
                document_type="datasheet",
            ),
        ]


def test_dense_returns_docs_from_knowledge_search():
    retriever = _DenseRetriever(knobs={"k": 3})
    retriever._search = _FakeKnowledgeSearch()
    ctx = Context(request="Faulhaber 2224", documents=[])
    retriever.execute(ctx)
    assert len(ctx.documents) == 1
    top = ctx.documents[0]
    assert "2224" in top.content
    assert top.metadata["variant"] == "dense"
    assert top.metadata["source"].endswith("faulhaber-2224.md")
    assert top.metadata["manufacturer"] == "Faulhaber"
    assert "stub" not in top.metadata


def test_dense_can_run_inside_existing_event_loop():
    retriever = _DenseRetriever(knobs={"k": 3})
    retriever._search = _FakeKnowledgeSearch()
    ctx = Context(request="Faulhaber 2224", documents=[])

    async def execute_from_runtime_loop():
        retriever.execute(ctx)

    asyncio.run(execute_from_runtime_loop())

    assert len(ctx.documents) == 1
    assert "2224" in ctx.documents[0].content


def test_dense_adds_catalog_for_inventory_request():
    retriever = _DenseRetriever(knobs={"k": 3})
    retriever._search = _FakeInventorySearch()
    ctx = Context(request="liste todos os motores", documents=[])
    retriever.execute(ctx)

    assert len(ctx.documents) == 2
    catalog = ctx.documents[0]
    assert catalog.metadata["variant"] == "catalog"
    assert "Motor 1" in catalog.content
    assert "Motor 2" in catalog.content


def test_dense_without_configured_knowledge_returns_no_docs(monkeypatch):
    monkeypatch.delenv("OPENTRACY_KNOWLEDGE_BACKEND", raising=False)
    monkeypatch.delenv("OPENTRACY_KNOWLEDGE_DATABASE_URL", raising=False)
    retriever = _DenseRetriever(knobs={"k": 8})
    ctx = Context(request="anything at all", documents=[])
    retriever.execute(ctx)
    assert ctx.documents == []


def test_dense_search_failure_returns_no_docs():
    retriever = _DenseRetriever(knobs={"k": 3})
    retriever._search = _FailingKnowledgeSearch()
    ctx = Context(request="x", documents=[])
    retriever.execute(ctx)
    assert ctx.documents == []


def test_sparse_and_hybrid_still_stub():
    """Non-dense variants stay stubs for now."""
    for variant in ("sparse", "hybrid"):
        stage = RagTechnique().compile(variant, knobs={"k": 4})
        ctx = Context(request="anything", documents=[])
        stage.execute(ctx)
        assert len(ctx.documents) == 4
        assert all(d.metadata.get("stub") for d in ctx.documents)


def test_dense_respects_k_knob():
    """k=1 returns at most 1 doc."""
    retriever = _DenseRetriever(knobs={"k": 1})
    retriever._search = _FakeKnowledgeSearch()
    ctx = Context(request="shipping brazil", documents=[])
    retriever.execute(ctx)
    assert len(ctx.documents) == 1


def test_retrieval_status_distinguishes_failure_from_empty_knowledge(monkeypatch):
    retriever = _DenseRetriever(knobs={})
    assert retriever.timeout_seconds == 45
    retriever._search = _FailingKnowledgeSearch()
    ctx = Context(request="motor")
    retriever.execute(ctx)
    assert ctx.state["retrieval"] == {"status": "unavailable", "reason": "search_error", "documents": 0}
    monkeypatch.setattr("techniques.rag.impl._run_async", lambda awaitable, **kwargs: (awaitable.close(), (_ for _ in ()).throw(TimeoutError()))[1])
    retriever.execute(ctx)
    assert ctx.state["retrieval"]["reason"] == "timeout"


def test_successful_retrieval_reports_available_documents():
    retriever = _DenseRetriever(knobs={"timeout_seconds": 45})
    retriever._search = _FakeKnowledgeSearch()
    ctx = Context(request="motor")
    retriever.execute(ctx)
    assert ctx.state["retrieval"] == {"status": "ok", "documents": 1}
