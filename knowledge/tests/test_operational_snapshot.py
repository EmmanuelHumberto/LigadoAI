"""Scoped inline operational records are traceable, idempotent and excluded from RAG."""
import asyncio
import hashlib
import json
from uuid import uuid4
from types import SimpleNamespace
import pytest
from pydantic import ValidationError
from knowledge.api.schemas import KnowledgeIndexRequestSchema
from knowledge.application import CreateKnowledgeJob, CreateKnowledgeJobCommand, IndexKnowledgeJob
from knowledge.domain import JobStatus, KnowledgeMetadata
from knowledge.infrastructure.chunking import TechnicalTextChunker
from knowledge.infrastructure.conversion import LocalTextDocumentConverter
from knowledge.infrastructure.embeddings import DeterministicFakeEmbeddingProvider
from knowledge.infrastructure.memory import InMemoryKnowledgeJobRepository, InMemoryKnowledgeQueue, InMemoryKnowledgeRepository
from knowledge.infrastructure.search.memory import InMemoryKnowledgeSearch
from knowledge.infrastructure.postgres.search import _build_lexical_query, PostgresKnowledgeSearch
from knowledge.infrastructure.validation import BasicContentValidator
from techniques.rag.impl import _catalog_document


def snapshot_request():
    org, order = uuid4(), uuid4()
    scope = dict(source_system="systemos", organization_id=str(org), service_order_id=str(order))
    text = json.dumps({"schemaVersion":1, "scope":scope, "numeroOS":"1141",
        "equipamento":{"numeroSerie":"SN-TEST"}, "ensaios":[], "evidencias":[
            {"conteudo":"Teste de bancada e inspeção: equipamento sem ruptura; serviços apenas propostos."}]}, ensure_ascii=False)
    digest = hashlib.sha256(text.encode()).hexdigest()
    return dict(source_uri=f"systemos://{org}/{order}/{digest}", inline_text=text, content_hash=digest,
        metadata=dict(document_type="service_order", extra={**scope, "service_order_number":"1141", "equipment_serial":"SN-TEST"}))


@pytest.mark.parametrize("change", [{"content_hash": "bad"}, {"source_uri": "file:///etc/passwd"},
    {"metadata": {"document_type": "datasheet", "extra": {}}}])
def test_inline_snapshot_rejects_invalid_scope_hash_or_uri(change):
    with pytest.raises(ValidationError): KnowledgeIndexRequestSchema(**{**snapshot_request(), **change})


def test_inline_snapshot_does_not_fetch_uri_embed_or_leak_to_rag():
    asyncio.run(_verify_snapshot())


async def _verify_snapshot():
    payload = KnowledgeIndexRequestSchema(**snapshot_request())
    jobs, queue, repository = InMemoryKnowledgeJobRepository(), InMemoryKnowledgeQueue(), InMemoryKnowledgeRepository()
    class ForbiddenConverter:
        async def convert(self, *_): raise AssertionError("Inline snapshots must not fetch files or URLs")
    class ForbiddenEmbedder:
        async def embed_texts(self, *_): raise AssertionError("Operational snapshots must not enter vector index")
    create = CreateKnowledgeJob(jobs, queue)
    worker = IndexKnowledgeJob(jobs=jobs, repository=repository, converter=ForbiddenConverter(),
        validator=BasicContentValidator(min_chars=40), chunker=TechnicalTextChunker(min_chunk_chars=20), embedder=ForbiddenEmbedder())
    document_ids = []
    for _ in range(2):
        job = await create.execute(CreateKnowledgeJobCommand(source_uri=payload.source_uri, content_hash=payload.content_hash,
            metadata=KnowledgeMetadata(document_type="service_order", extra={**payload.metadata.extra,
                "_inline_text": payload.inline_text, "retrieval_eligible": False})))
        done = await worker.process(job.id)
        assert done.status == JobStatus.INDEXED, done.error_details
        document_ids.append(done.document_id)
    assert document_ids[0] == document_ids[1]
    doc = await repository.get_document(document_ids[0])
    assert "_inline_text" not in doc.metadata
    assert doc.metadata["retrieval_eligible"] is False
    assert repository.chunks[doc.id]
    assert not await InMemoryKnowledgeSearch(repository).search("equipamento serviços")
    assert "systemos://" not in _catalog_document([doc]).content


def test_postgres_search_excludes_operational_records_in_both_paths():
    query, _ = _build_lexical_query(["equipamento"], top_k=3, filters={})
    assert "retrieval_eligible" in query
    class Connection:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def fetch(self, query, *params):
            assert "retrieval_eligible" in query
            return []
    search = PostgresKnowledgeSearch(SimpleNamespace(acquire=lambda: Connection()))
    asyncio.run(search._semantic_search([0.1], "equipamento", 3, None))


@pytest.mark.parametrize("reserved", [True, False])
def test_operational_snapshot_cannot_bypass_body_validation_via_metadata(reserved):
    request = snapshot_request()
    request.pop("inline_text")
    if reserved:
        request["metadata"]["extra"]["_inline_text"] = "Unvalidated body"
    with pytest.raises(ValidationError): KnowledgeIndexRequestSchema(**request)
