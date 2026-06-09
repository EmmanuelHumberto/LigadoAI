import asyncio

from knowledge.domain import (
    CorpusVersion,
    DocumentStatus,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeEmbedding,
)
from knowledge.infrastructure.memory import InMemoryKnowledgeRepository


def test_memory_repository_status_counts_live_documents_and_chunks():
    asyncio.run(_test_memory_repository_status_counts_live_documents_and_chunks())


async def _test_memory_repository_status_counts_live_documents_and_chunks():
    repo = InMemoryKnowledgeRepository()
    document = await repo.upsert_document(
        KnowledgeDocument(
            source_uri="/docs/faulhaber-2616.pdf",
            content_hash="abc",
            status=DocumentStatus.INDEXED,
        )
    )
    chunk = KnowledgeChunk(
        document_id=document.id,
        chunk_index=0,
        text="Faulhaber 2616 brushless motor",
        text_hash="chunk-a",
    )
    await repo.replace_chunks(
        document.id,
        [chunk],
        [
            KnowledgeEmbedding(
                chunk_id=chunk.id,
                embedding_model="sentence-transformers/all-MiniLM-L6-v2",
                dimension=3,
                vector_raw=(0.1, 0.2, 0.3),
            )
        ],
    )
    await repo.create_corpus_version(
        CorpusVersion(
            version=1,
            status="ready",
            embedding_model="sentence-transformers/all-MiniLM-L6-v2",
            vector_dimension=384,
            chunking_strategy="technical_v1",
            ranking_strategy="hybrid_v1",
            schema_version="001",
            document_count=1,
            chunk_count=1,
        )
    )

    status = await repo.get_status()

    assert status.index_status == "ready"
    assert status.document_count == 1
    assert status.chunk_count == 1
    assert status.corpus_version == 1


def test_memory_repository_soft_delete_hides_document_from_status():
    asyncio.run(_test_memory_repository_soft_delete_hides_document_from_status())


async def _test_memory_repository_soft_delete_hides_document_from_status():
    repo = InMemoryKnowledgeRepository()
    document = await repo.upsert_document(
        KnowledgeDocument(
            source_uri="/docs/faulhaber-2616.pdf",
            content_hash="abc",
            status=DocumentStatus.INDEXED,
        )
    )
    chunk = KnowledgeChunk(
        document_id=document.id,
        chunk_index=0,
        text="Faulhaber 2616 brushless motor",
        text_hash="chunk-a",
    )
    await repo.replace_chunks(document.id, [chunk], [])

    deleted = await repo.soft_delete_document(document.id)
    status = await repo.get_status()
    stored = await repo.get_document(document.id)

    assert deleted is True
    assert stored is not None
    assert stored.status == DocumentStatus.DELETED
    assert status.document_count == 0
    assert status.chunk_count == 0
