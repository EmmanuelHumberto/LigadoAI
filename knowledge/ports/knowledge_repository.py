"""Repository contracts for knowledge documents and jobs."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from knowledge.domain import (
    CorpusVersion,
    JobStatus,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeEmbedding,
    KnowledgeJob,
    KnowledgeStoreStatus,
)


class KnowledgeJobRepository(Protocol):
    async def find_active_by_idempotency_key(self, key: str) -> KnowledgeJob | None:
        ...

    async def save_job(self, job: KnowledgeJob) -> KnowledgeJob:
        ...

    async def get_job(self, job_id: UUID) -> KnowledgeJob | None:
        ...

    async def update_job_status(
        self,
        job_id: UUID,
        status: JobStatus,
        *,
        stage: str | None = None,
        error_details: dict | None = None,
    ) -> KnowledgeJob | None:
        ...


class KnowledgeRepository(Protocol):
    async def upsert_document(self, document: KnowledgeDocument) -> KnowledgeDocument:
        ...

    async def replace_chunks(
        self,
        document_id: UUID,
        chunks: list[KnowledgeChunk],
        embeddings: list[KnowledgeEmbedding],
    ) -> None:
        ...

    async def get_document(self, document_id: UUID) -> KnowledgeDocument | None:
        ...

    async def list_documents(
        self,
        *,
        include_deleted: bool = False,
    ) -> list[KnowledgeDocument]:
        ...

    async def soft_delete_document(self, document_id: UUID) -> bool:
        ...

    async def create_corpus_version(self, version: CorpusVersion) -> CorpusVersion:
        ...

    async def latest_corpus_version(self) -> CorpusVersion | None:
        ...

    async def get_status(self) -> KnowledgeStoreStatus:
        ...
