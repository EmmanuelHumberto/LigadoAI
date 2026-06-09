"""Small in-memory adapters used by tests and local prototypes."""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from knowledge.domain import (
    CorpusVersion,
    DocumentStatus,
    JobStatus,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeEmbedding,
    KnowledgeJob,
    KnowledgeStoreStatus,
    utcnow,
)

_ACTIVE_STATUSES = {
    JobStatus.QUEUED,
    JobStatus.RUNNING,
    JobStatus.PROCESSING,
}


class InMemoryKnowledgeJobRepository:
    def __init__(self) -> None:
        self.jobs: dict[UUID, KnowledgeJob] = {}

    async def find_active_by_idempotency_key(self, key: str) -> KnowledgeJob | None:
        for job in self.jobs.values():
            if job.idempotency_key == key and job.status in _ACTIVE_STATUSES:
                return job
        return None

    async def save_job(self, job: KnowledgeJob) -> KnowledgeJob:
        self.jobs[job.id] = job
        return job

    async def get_job(self, job_id: UUID) -> KnowledgeJob | None:
        return self.jobs.get(job_id)

    async def update_job_status(
        self,
        job_id: UUID,
        status: JobStatus,
        *,
        stage: str | None = None,
        error_details: dict | None = None,
    ) -> KnowledgeJob | None:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        updated = replace(
            job,
            status=status,
            stage=stage,
            error_details=error_details,
            updated_at=utcnow(),
        )
        self.jobs[job_id] = updated
        return updated


class InMemoryKnowledgeQueue:
    def __init__(self) -> None:
        self.enqueued: list[KnowledgeJob] = []
        self.cancel_requested: set[UUID] = set()

    async def enqueue(self, job: KnowledgeJob) -> None:
        self.enqueued.append(job)

    async def request_cancel(self, job_id: UUID) -> None:
        self.cancel_requested.add(job_id)


class InMemoryKnowledgeRepository:
    def __init__(self) -> None:
        self.documents: dict[UUID, KnowledgeDocument] = {}
        self.chunks: dict[UUID, list[KnowledgeChunk]] = {}
        self.embeddings: dict[UUID, KnowledgeEmbedding] = {}
        self.corpus_versions: list[CorpusVersion] = []

    async def upsert_document(self, document: KnowledgeDocument) -> KnowledgeDocument:
        self.documents[document.id] = document
        return document

    async def replace_chunks(
        self,
        document_id: UUID,
        chunks: list[KnowledgeChunk],
        embeddings: list[KnowledgeEmbedding],
    ) -> None:
        previous_chunk_ids = {chunk.id for chunk in self.chunks.get(document_id, [])}
        self.chunks[document_id] = list(chunks)
        for chunk_id in previous_chunk_ids:
            if chunk_id in self.embeddings:
                del self.embeddings[chunk_id]
        for embedding in embeddings:
            self.embeddings[embedding.chunk_id] = embedding

    async def get_document(self, document_id: UUID) -> KnowledgeDocument | None:
        return self.documents.get(document_id)

    async def list_documents(
        self,
        *,
        include_deleted: bool = False,
    ) -> list[KnowledgeDocument]:
        documents = list(self.documents.values())
        if not include_deleted:
            documents = [doc for doc in documents if doc.status != DocumentStatus.DELETED]
        return sorted(documents, key=lambda doc: doc.updated_at, reverse=True)

    async def soft_delete_document(self, document_id: UUID) -> bool:
        document = self.documents.get(document_id)
        if document is None:
            return False
        self.documents[document_id] = replace(
            document,
            status=DocumentStatus.DELETED,
            updated_at=utcnow(),
        )
        return True

    async def create_corpus_version(self, version: CorpusVersion) -> CorpusVersion:
        self.corpus_versions.append(version)
        return version

    async def latest_corpus_version(self) -> CorpusVersion | None:
        if not self.corpus_versions:
            return None
        return max(self.corpus_versions, key=lambda version: version.version)

    async def get_status(self) -> KnowledgeStoreStatus:
        live_documents = [
            doc for doc in self.documents.values() if doc.status != DocumentStatus.DELETED
        ]
        live_document_ids = {doc.id for doc in live_documents}
        chunk_count = sum(
            len(chunks)
            for document_id, chunks in self.chunks.items()
            if document_id in live_document_ids
        )
        latest = await self.latest_corpus_version()
        return KnowledgeStoreStatus(
            index_status="ready" if latest else "unavailable",
            document_count=len(live_documents),
            chunk_count=chunk_count,
            corpus_version=latest.version if latest else None,
        )
