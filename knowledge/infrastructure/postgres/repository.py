"""PostgreSQL repository for the knowledge vertical."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import asyncpg

from knowledge.domain import (
    CorpusVersion,
    DocumentStatus,
    JobKind,
    JobStatus,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeEmbedding,
    KnowledgeJob,
    KnowledgeStoreStatus,
)


class PostgresKnowledgeRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str, **kwargs: Any) -> PostgresKnowledgeRepository:
        pool = await asyncpg.create_pool(dsn=dsn, **kwargs)
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

    async def find_active_by_idempotency_key(self, key: str) -> KnowledgeJob | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM knowledge_jobs
                WHERE idempotency_key = $1
                  AND status IN ('queued', 'running', 'processing')
                ORDER BY created_at ASC
                LIMIT 1
                """,
                key,
            )
        return _job_from_row(row) if row else None

    async def save_job(self, job: KnowledgeJob) -> KnowledgeJob:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO knowledge_jobs (
                    id, kind, source_uri, document_id, status, stage,
                    progress_current, progress_total, idempotency_key,
                    metadata, error_details, created_at, updated_at
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6,
                    $7, $8, $9, $10::jsonb, $11::jsonb, $12, $13
                )
                ON CONFLICT (id) DO UPDATE SET
                    kind = EXCLUDED.kind,
                    source_uri = EXCLUDED.source_uri,
                    document_id = EXCLUDED.document_id,
                    status = EXCLUDED.status,
                    stage = EXCLUDED.stage,
                    progress_current = EXCLUDED.progress_current,
                    progress_total = EXCLUDED.progress_total,
                    idempotency_key = EXCLUDED.idempotency_key,
                    metadata = EXCLUDED.metadata,
                    error_details = EXCLUDED.error_details,
                    updated_at = EXCLUDED.updated_at
                RETURNING *
                """,
                job.id,
                job.kind.value,
                job.source_uri,
                job.document_id,
                job.status.value,
                job.stage,
                job.progress_current,
                job.progress_total,
                job.idempotency_key,
                _json(job.metadata),
                _json(job.error_details),
                job.created_at,
                job.updated_at,
            )
        return _job_from_row(row)

    async def get_job(self, job_id: UUID) -> KnowledgeJob | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM knowledge_jobs WHERE id = $1", job_id)
        return _job_from_row(row) if row else None

    async def update_job_status(
        self,
        job_id: UUID,
        status: JobStatus,
        *,
        stage: str | None = None,
        error_details: dict | None = None,
    ) -> KnowledgeJob | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE knowledge_jobs
                SET status = $2,
                    stage = COALESCE($3, stage),
                    error_details = COALESCE($4::jsonb, error_details),
                    updated_at = NOW()
                WHERE id = $1
                RETURNING *
                """,
                job_id,
                status.value,
                stage,
                _json(error_details) if error_details is not None else None,
            )
        return _job_from_row(row) if row else None

    async def upsert_document(self, document: KnowledgeDocument) -> KnowledgeDocument:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO knowledge_documents (
                    id, source_uri, canonical_path, title, manufacturer, model,
                    category, document_type, content_hash, status, metadata,
                    error_details, created_at, updated_at
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6,
                    $7, $8, $9, $10, $11::jsonb,
                    $12::jsonb, $13, $14
                )
                ON CONFLICT (id) DO UPDATE SET
                    source_uri = EXCLUDED.source_uri,
                    canonical_path = EXCLUDED.canonical_path,
                    title = EXCLUDED.title,
                    manufacturer = EXCLUDED.manufacturer,
                    model = EXCLUDED.model,
                    category = EXCLUDED.category,
                    document_type = EXCLUDED.document_type,
                    content_hash = EXCLUDED.content_hash,
                    status = EXCLUDED.status,
                    metadata = EXCLUDED.metadata,
                    error_details = EXCLUDED.error_details,
                    updated_at = EXCLUDED.updated_at
                RETURNING *
                """,
                document.id,
                document.source_uri,
                document.canonical_path,
                document.title,
                document.manufacturer,
                document.model,
                document.category,
                document.document_type,
                document.content_hash,
                document.status.value,
                _json(document.metadata),
                _json(document.error_details),
                document.created_at,
                document.updated_at,
            )
        return _document_from_row(row)

    async def replace_chunks(
        self,
        document_id: UUID,
        chunks: list[KnowledgeChunk],
        embeddings: list[KnowledgeEmbedding],
    ) -> None:
        embeddings_by_chunk = {embedding.chunk_id: embedding for embedding in embeddings}
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM knowledge_chunks WHERE document_id = $1",
                    document_id,
                )
                for chunk in chunks:
                    await conn.execute(
                        """
                        INSERT INTO knowledge_chunks (
                            id, document_id, chunk_index, text, text_hash,
                            metadata, created_at
                        )
                        VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
                        """,
                        chunk.id,
                        chunk.document_id,
                        chunk.chunk_index,
                        chunk.text,
                        chunk.text_hash,
                        _json(chunk.metadata),
                        chunk.created_at,
                    )
                    embedding = embeddings_by_chunk.get(chunk.id)
                    if embedding is None:
                        continue
                    await conn.execute(
                        """
                        INSERT INTO knowledge_embeddings (
                            chunk_id, embedding_model, dimension, vector_raw, created_at
                        )
                        VALUES ($1, $2, $3, $4::float4[], $5)
                        """,
                        embedding.chunk_id,
                        embedding.embedding_model,
                        embedding.dimension,
                        list(embedding.vector_raw),
                        embedding.created_at,
                    )

    async def get_document(self, document_id: UUID) -> KnowledgeDocument | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM knowledge_documents WHERE id = $1",
                document_id,
            )
        return _document_from_row(row) if row else None

    async def list_documents(
        self,
        *,
        include_deleted: bool = False,
    ) -> list[KnowledgeDocument]:
        where = "" if include_deleted else "WHERE status <> 'deleted'"
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT * FROM knowledge_documents
                {where}
                ORDER BY updated_at DESC
                """
            )
        return [_document_from_row(row) for row in rows]

    async def soft_delete_document(self, document_id: UUID) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE knowledge_documents
                SET status = $2, updated_at = NOW()
                WHERE id = $1 AND status <> $2
                """,
                document_id,
                DocumentStatus.DELETED.value,
            )
        return result != "UPDATE 0"

    async def create_corpus_version(self, version: CorpusVersion) -> CorpusVersion:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO knowledge_corpus_versions (
                    id, version, status, document_count, chunk_count,
                    embedding_model, vector_dimension, chunking_strategy,
                    ranking_strategy, prompt_version, converter_version,
                    ocr_profile, schema_version, created_at
                )
                VALUES (
                    $1, $2, $3, $4, $5,
                    $6, $7, $8,
                    $9, $10, $11,
                    $12, $13, $14
                )
                RETURNING *
                """,
                version.id,
                version.version,
                version.status,
                version.document_count,
                version.chunk_count,
                version.embedding_model,
                version.vector_dimension,
                version.chunking_strategy,
                version.ranking_strategy,
                version.prompt_version,
                version.converter_version,
                version.ocr_profile,
                version.schema_version,
                version.created_at,
            )
        return _corpus_version_from_row(row)

    async def latest_corpus_version(self) -> CorpusVersion | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM knowledge_corpus_versions ORDER BY version DESC LIMIT 1"
            )
        return _corpus_version_from_row(row) if row else None

    async def get_status(self) -> KnowledgeStoreStatus:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                  (SELECT COUNT(*) FROM knowledge_documents WHERE status <> 'deleted')
                    AS document_count,
                  (
                    SELECT COUNT(*)
                    FROM knowledge_chunks c
                    JOIN knowledge_documents d ON d.id = c.document_id
                    WHERE d.status <> 'deleted'
                  ) AS chunk_count,
                  (
                    SELECT version
                    FROM knowledge_corpus_versions
                    ORDER BY version DESC
                    LIMIT 1
                  ) AS corpus_version
                """
            )
        corpus_version = row["corpus_version"] if row else None
        return KnowledgeStoreStatus(
            index_status="ready" if corpus_version is not None else "unavailable",
            document_count=int(row["document_count"] or 0) if row else 0,
            chunk_count=int(row["chunk_count"] or 0) if row else 0,
            corpus_version=int(corpus_version) if corpus_version is not None else None,
        )


def _job_from_row(row: asyncpg.Record) -> KnowledgeJob:
    return KnowledgeJob(
        id=row["id"],
        kind=JobKind(row["kind"]),
        source_uri=row["source_uri"],
        document_id=row["document_id"],
        status=JobStatus(row["status"]),
        stage=row["stage"],
        progress_current=row["progress_current"],
        progress_total=row["progress_total"],
        idempotency_key=row["idempotency_key"],
        metadata=_json_dict(row["metadata"]),
        error_details=_json_dict(row["error_details"]) if row["error_details"] else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _document_from_row(row: asyncpg.Record) -> KnowledgeDocument:
    return KnowledgeDocument(
        id=row["id"],
        source_uri=row["source_uri"],
        canonical_path=row["canonical_path"],
        title=row["title"],
        manufacturer=row["manufacturer"],
        model=row["model"],
        category=row["category"],
        document_type=row["document_type"],
        content_hash=row["content_hash"],
        status=DocumentStatus(row["status"]),
        metadata=_json_dict(row["metadata"]),
        error_details=_json_dict(row["error_details"]) if row["error_details"] else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _corpus_version_from_row(row: asyncpg.Record) -> CorpusVersion:
    return CorpusVersion(
        id=row["id"],
        version=row["version"],
        status=row["status"],
        document_count=row["document_count"],
        chunk_count=row["chunk_count"],
        embedding_model=row["embedding_model"],
        vector_dimension=row["vector_dimension"],
        chunking_strategy=row["chunking_strategy"],
        ranking_strategy=row["ranking_strategy"],
        prompt_version=row["prompt_version"],
        converter_version=row["converter_version"],
        ocr_profile=row["ocr_profile"],
        schema_version=row["schema_version"],
        created_at=row["created_at"],
    )


def _json(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, default=str)


def _json_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        decoded = json.loads(value)
        return decoded if isinstance(decoded, dict) else {}
    return dict(value)
