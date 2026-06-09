"""Indexing worker use case."""

from __future__ import annotations

import hashlib
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
    utcnow,
)
from knowledge.ports import (
    ContentValidator,
    DocumentConverter,
    EmbeddingProvider,
    KnowledgeJobRepository,
    KnowledgeRepository,
    TextChunker,
)


class IndexKnowledgeJob:
    """Process a queued knowledge indexing job."""

    def __init__(
        self,
        *,
        jobs: KnowledgeJobRepository,
        repository: KnowledgeRepository,
        converter: DocumentConverter,
        validator: ContentValidator,
        chunker: TextChunker,
        embedder: EmbeddingProvider,
        chunking_strategy: str = "technical_v1",
        ranking_strategy: str = "hybrid_v1",
        schema_version: str = "001",
    ) -> None:
        self._jobs = jobs
        self._repository = repository
        self._converter = converter
        self._validator = validator
        self._chunker = chunker
        self._embedder = embedder
        self._chunking_strategy = chunking_strategy
        self._ranking_strategy = ranking_strategy
        self._schema_version = schema_version

    async def process(self, job_id: UUID) -> KnowledgeJob:
        job = await self._jobs.get_job(job_id)
        if job is None:
            raise ValueError(f"knowledge job not found: {job_id}")
        if not job.source_uri:
            return await self._fail(job, "missing_source_uri", "job has no source_uri")

        await self._jobs.update_job_status(job.id, JobStatus.RUNNING, stage="convert")

        try:
            converted = await self._converter.convert(job.source_uri)
            validation = await self._validator.validate(converted)
            if not validation.approved:
                return await self._fail(
                    job,
                    "validation_failed",
                    "converted document did not pass validation",
                    {"errors": validation.errors},
                )

            content_hash = hashlib.sha256(converted.text.encode("utf-8")).hexdigest()
            document = KnowledgeDocument(
                source_uri=converted.source_uri,
                content_hash=content_hash,
                title=_metadata_value(job, "title") or converted.title,
                manufacturer=_metadata_value(job, "manufacturer"),
                model=_metadata_value(job, "model"),
                category=_metadata_value(job, "category"),
                document_type=_metadata_value(job, "document_type"),
                status=DocumentStatus.INDEXED,
                metadata={**converted.metadata, **job.metadata},
            )
            document = await self._repository.upsert_document(document)

            texts = self._chunker.chunk(converted.text)
            if not texts:
                return await self._fail(job, "no_chunks", "document produced no indexable chunks")

            await self._jobs.update_job_status(
                job.id,
                JobStatus.PROCESSING,
                stage="embedding",
            )
            vectors = await self._embedder.embed_texts(texts)
            chunks = [
                KnowledgeChunk(
                    document_id=document.id,
                    chunk_index=index,
                    text=text,
                    text_hash=hashlib.sha1(text.encode("utf-8")).hexdigest(),
                    metadata={
                        "source_uri": document.source_uri,
                        "title": document.title,
                        "manufacturer": document.manufacturer,
                        "model": document.model,
                        "category": document.category,
                        "document_type": document.document_type,
                    },
                )
                for index, text in enumerate(texts)
            ]
            embeddings = [
                KnowledgeEmbedding(
                    chunk_id=chunk.id,
                    embedding_model=self._embedder.model_name,
                    dimension=self._embedder.dimension,
                    vector_raw=tuple(float(value) for value in vector),
                )
                for chunk, vector in zip(chunks, vectors, strict=True)
            ]
            await self._repository.replace_chunks(document.id, chunks, embeddings)

            latest = await self._repository.latest_corpus_version()
            next_version = 1 if latest is None else latest.version + 1
            store_status = await self._repository.get_status()
            await self._repository.create_corpus_version(
                CorpusVersion(
                    version=next_version,
                    status="ready",
                    document_count=store_status.document_count,
                    chunk_count=store_status.chunk_count,
                    embedding_model=self._embedder.model_name,
                    vector_dimension=self._embedder.dimension,
                    chunking_strategy=self._chunking_strategy,
                    ranking_strategy=self._ranking_strategy,
                    schema_version=self._schema_version,
                )
            )

            completed = replace(
                job,
                document_id=document.id,
                status=JobStatus.INDEXED,
                stage="done",
                progress_current=len(chunks),
                progress_total=len(chunks),
                updated_at=utcnow(),
            )
            return await self._jobs.save_job(completed)
        except Exception as exc:
            return await self._fail(job, "indexing_failed", str(exc))

    async def _fail(
        self,
        job: KnowledgeJob,
        code: str,
        message: str,
        extra: dict | None = None,
    ) -> KnowledgeJob:
        details = {"code": code, "message": message}
        if extra:
            details.update(extra)
        failed = replace(
            job,
            status=JobStatus.FAILED,
            stage="failed",
            error_details=details,
            updated_at=utcnow(),
        )
        return await self._jobs.save_job(failed)


def _metadata_value(job: KnowledgeJob, key: str) -> str | None:
    value = job.metadata.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None
