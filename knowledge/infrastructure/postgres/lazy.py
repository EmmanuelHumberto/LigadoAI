"""Lazy PostgreSQL adapter for runtime composition."""

from __future__ import annotations

import asyncio
from uuid import UUID

from knowledge.domain import (
    CorpusVersion,
    JobStatus,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeEmbedding,
    KnowledgeJob,
    KnowledgeSearchResult,
    KnowledgeStoreStatus,
)
from knowledge.infrastructure.postgres.repository import PostgresKnowledgeRepository
from knowledge.infrastructure.postgres.search import PostgresKnowledgeSearch


class LazyPostgresKnowledgeRepository:
    """Open the PostgreSQL pool and validate its schema without changing it."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._repo: PostgresKnowledgeRepository | None = None
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        if self._repo is not None:
            await self._repo.close()
            self._repo = None

    async def _ensure_repo(self) -> PostgresKnowledgeRepository:
        if self._repo is not None:
            return self._repo
        async with self._lock:
            if self._repo is not None:
                return self._repo
            repo = await PostgresKnowledgeRepository.connect(self._dsn)
            try:
                await _validate_schema(repo)
            except BaseException:
                await repo.close()
                raise
            self._repo = repo
            return repo

    async def find_active_by_idempotency_key(self, key: str) -> KnowledgeJob | None:
        return await (await self._ensure_repo()).find_active_by_idempotency_key(key)

    async def save_job(self, job: KnowledgeJob) -> KnowledgeJob:
        return await (await self._ensure_repo()).save_job(job)

    async def get_job(self, job_id: UUID) -> KnowledgeJob | None:
        return await (await self._ensure_repo()).get_job(job_id)

    async def update_job_status(
        self,
        job_id: UUID,
        status: JobStatus,
        *,
        stage: str | None = None,
        error_details: dict | None = None,
    ) -> KnowledgeJob | None:
        return await (await self._ensure_repo()).update_job_status(
            job_id,
            status,
            stage=stage,
            error_details=error_details,
        )

    async def upsert_document(self, document: KnowledgeDocument) -> KnowledgeDocument:
        return await (await self._ensure_repo()).upsert_document(document)

    async def replace_chunks(
        self,
        document_id: UUID,
        chunks: list[KnowledgeChunk],
        embeddings: list[KnowledgeEmbedding],
    ) -> None:
        await (await self._ensure_repo()).replace_chunks(document_id, chunks, embeddings)

    async def get_document(self, document_id: UUID) -> KnowledgeDocument | None:
        return await (await self._ensure_repo()).get_document(document_id)

    async def list_documents(
        self,
        *,
        include_deleted: bool = False,
    ) -> list[KnowledgeDocument]:
        return await (await self._ensure_repo()).list_documents(include_deleted=include_deleted)

    async def soft_delete_document(self, document_id: UUID) -> bool:
        return await (await self._ensure_repo()).soft_delete_document(document_id)

    async def create_corpus_version(self, version: CorpusVersion) -> CorpusVersion:
        return await (await self._ensure_repo()).create_corpus_version(version)

    async def latest_corpus_version(self) -> CorpusVersion | None:
        return await (await self._ensure_repo()).latest_corpus_version()

    async def get_status(self) -> KnowledgeStoreStatus:
        return await (await self._ensure_repo()).get_status()

    async def search(
        self,
        query: str,
        *,
        top_k: int = 8,
        filters: dict[str, str] | None = None,
    ) -> list[KnowledgeSearchResult]:
        repo = await self._ensure_repo()
        return await PostgresKnowledgeSearch(repo._pool).search(  # noqa: SLF001
            query,
            top_k=top_k,
            filters=filters,
        )


async def _validate_schema(repo: PostgresKnowledgeRepository) -> None:
    """Fail before serving requests if the deployed schema is incomplete.

    Schema changes belong to scripts/migrate-postgres.py, run by the owner.
    LIMIT 0 checks relations/columns without reading customer records.
    """
    probes = (
        'SELECT * FROM public.knowledge_documents LIMIT 0',
        'SELECT * FROM public.knowledge_chunks LIMIT 0',
        'SELECT * FROM public.knowledge_embeddings LIMIT 0',
        'SELECT * FROM public.knowledge_corpus_versions LIMIT 0',
        'SELECT * FROM public.knowledge_jobs LIMIT 0',
        'SELECT service_order_document_id, header_observations FROM public.capture_sessions LIMIT 0',
        'SELECT callback_status, callback_attempts, callback_last_attempt_at, callback_next_attempt_at, callback_error FROM public.diagnosis_queue LIMIT 0',
        'SELECT winding_resistance_mohm FROM public.electromechanical_signatures LIMIT 0',
        'SELECT winding_resistance_error_permille, rpm_error_permille, electrical_power_error_permille FROM public.signature_deviations LIMIT 0',
    )
    async with repo._pool.acquire() as conn:  # noqa: SLF001
        async with conn.transaction(readonly=True):
            for query in probes:
                await conn.execute(query)
