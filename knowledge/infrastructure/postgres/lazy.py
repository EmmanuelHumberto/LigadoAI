"""Lazy PostgreSQL adapter for runtime composition."""

from __future__ import annotations

import asyncio
from pathlib import Path
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
    """Open the PostgreSQL pool and apply migrations on first use."""

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
            await _apply_migrations(repo)
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


async def _apply_migrations(repo: PostgresKnowledgeRepository) -> None:
    migration_dir = Path(__file__).resolve().parent / "migrations"
    migration_files = sorted(migration_dir.glob("*.sql"))
    async with repo._pool.acquire() as conn:  # noqa: SLF001 - infrastructure-local migration
        for migration in migration_files:
            await conn.execute(migration.read_text(encoding="utf-8"))
