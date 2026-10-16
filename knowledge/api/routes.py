"""FastAPI route factory for the knowledge vertical.

The router is built from application ports/use cases. It does not create a
database pool, queue backend, or embedding model on import.
"""

from __future__ import annotations

from collections.abc import Callable
from secrets import compare_digest
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, status

from knowledge.api.schemas import (
    KnowledgeDocumentSchema,
    KnowledgeDocumentsResponseSchema,
    KnowledgeIndexRequestSchema,
    KnowledgeIndexResponseSchema,
    KnowledgeJobProgressSchema,
    KnowledgeJobResponseSchema,
    KnowledgeSearchRequestSchema,
    KnowledgeSearchResponseSchema,
    KnowledgeSearchResultSchema,
    KnowledgeStatusSchema,
    KnowledgeValidateRequestSchema,
    KnowledgeValidateResponseSchema,
)
from knowledge.application import CreateKnowledgeJob, CreateKnowledgeJobCommand, IndexKnowledgeJob
from knowledge.domain import JobStatus, KnowledgeDocument, KnowledgeJob, KnowledgeMetadata
from knowledge.ports import (
    ContentValidator,
    DocumentConverter,
    KnowledgeJobRepository,
    KnowledgeQueue,
    KnowledgeRepository,
    KnowledgeSearchPort,
)


def create_knowledge_router(
    *,
    create_job: CreateKnowledgeJob,
    jobs: KnowledgeJobRepository,
    queue: KnowledgeQueue | None = None,
    repository: KnowledgeRepository | None = None,
    index_worker: IndexKnowledgeJob | None = None,
    search: KnowledgeSearchPort | None = None,
    converter: DocumentConverter | None = None,
    validator: ContentValidator | None = None,
    auth_token: str | None = None,
) -> APIRouter:
    dependencies = []
    if auth_token:
        dependencies.append(Depends(_bearer_auth_dependency(auth_token)))
    router = APIRouter(prefix="/knowledge", tags=["knowledge"], dependencies=dependencies)

    @router.post("/index", response_model=KnowledgeIndexResponseSchema)
    async def index_document(
        payload: KnowledgeIndexRequestSchema,
        background_tasks: BackgroundTasks,
    ) -> KnowledgeIndexResponseSchema:
        job = await create_job.execute(
            CreateKnowledgeJobCommand(
                source_uri=payload.source_uri,
                content_hash=payload.content_hash,
                metadata=KnowledgeMetadata(
                    manufacturer=payload.metadata.manufacturer,
                    model=payload.metadata.model,
                    category=payload.metadata.category,
                    document_type=payload.metadata.document_type,
                    title=payload.metadata.title,
                    extra={**payload.metadata.extra, **({
                        "_inline_text": payload.inline_text,
                        "retrieval_eligible": False,
                    } if payload.inline_text is not None else {})},
                ),
                force=payload.options.force,
            )
        )
        if index_worker is not None and job.status == JobStatus.QUEUED:
            background_tasks.add_task(index_worker.process, job.id)
        message = "Documento recebido para indexacao."
        if job.status == JobStatus.DUPLICATE:
            message = "Job equivalente ja esta em processamento."
        return KnowledgeIndexResponseSchema(
            job_id=job.id,
            duplicate_of=job.metadata.get("duplicate_of"),
            document_id=job.document_id,
            status=job.status.value,
            message=message,
        )

    @router.post("/validate", response_model=KnowledgeValidateResponseSchema)
    async def validate_document(
        payload: KnowledgeValidateRequestSchema,
    ) -> KnowledgeValidateResponseSchema:
        if converter is None or validator is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="knowledge validation unavailable",
            )
        try:
            converted = await converter.convert(payload.source_uri)
            result = await validator.validate(converted)
        except Exception as exc:
            return KnowledgeValidateResponseSchema(
                approved=False,
                status="failed",
                source_uri=payload.source_uri,
                errors=[
                    {
                        "code": "conversion_failed",
                        "message": str(exc),
                    }
                ],
            )
        return KnowledgeValidateResponseSchema(
            approved=result.approved,
            status=result.status,
            source_uri=converted.source_uri,
            title=converted.title,
            content_type=converted.content_type,
            char_count=len(converted.text),
            metadata=converted.metadata,
            errors=result.errors,
        )

    @router.get("/jobs/{job_id}", response_model=KnowledgeJobResponseSchema)
    async def get_job(job_id: UUID) -> KnowledgeJobResponseSchema:
        job = await jobs.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
        return _job_response(job)

    @router.post("/jobs/{job_id}/cancel", response_model=KnowledgeJobResponseSchema)
    async def cancel_job(job_id: UUID) -> KnowledgeJobResponseSchema:
        if queue is not None:
            await queue.request_cancel(job_id)
        job = await jobs.update_job_status(job_id, JobStatus.CANCEL_REQUESTED)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
        return _job_response(job)

    @router.get("/status", response_model=KnowledgeStatusSchema)
    async def knowledge_status() -> KnowledgeStatusSchema:
        if repository is None:
            return KnowledgeStatusSchema(status="unavailable")
        store_status = await repository.get_status()
        return KnowledgeStatusSchema(
            status=store_status.index_status,
            document_count=store_status.document_count,
            chunk_count=store_status.chunk_count,
            corpus_version=store_status.corpus_version,
        )

    @router.get("/documents", response_model=KnowledgeDocumentsResponseSchema)
    async def list_documents(include_deleted: bool = False) -> KnowledgeDocumentsResponseSchema:
        if repository is None:
            return KnowledgeDocumentsResponseSchema()
        documents = await repository.list_documents(include_deleted=include_deleted)
        return KnowledgeDocumentsResponseSchema(
            documents=[_document_response(document) for document in documents]
        )

    @router.get("/documents/{document_id}", response_model=KnowledgeDocumentSchema)
    async def get_document(document_id: UUID) -> KnowledgeDocumentSchema:
        if repository is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
        document = await repository.get_document(document_id)
        if document is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
        return _document_response(document)

    @router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_document(document_id: UUID) -> None:
        if repository is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
        deleted = await repository.soft_delete_document(document_id)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
        return None

    @router.post("/search", response_model=KnowledgeSearchResponseSchema)
    async def search_knowledge(
        payload: KnowledgeSearchRequestSchema,
    ) -> KnowledgeSearchResponseSchema:
        if search is None:
            return KnowledgeSearchResponseSchema()
        results = await search.search(
            payload.query,
            top_k=payload.top_k,
            filters=payload.filters,
        )
        return KnowledgeSearchResponseSchema(
            results=[
                KnowledgeSearchResultSchema(
                    chunk_id=result.chunk_id,
                    document_id=result.document_id,
                    score=result.score,
                    text=result.text,
                    source_uri=result.source_uri,
                    metadata=result.metadata,
                )
                for result in results
            ]
        )

    return router


def _bearer_auth_dependency(expected_token: str) -> Callable[[str | None], None]:
    async def require_bearer(
        authorization: str | None = Header(default=None),
    ) -> None:
        if not authorization:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing_authorization",
            )
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="bad_authorization",
            )
        if not compare_digest(token.strip(), expected_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid_token",
            )

    return require_bearer


def _job_response(job: KnowledgeJob) -> KnowledgeJobResponseSchema:
    return KnowledgeJobResponseSchema(
        job_id=job.id,
        document_id=job.document_id,
        status=job.status.value,
        kind=job.kind.value,
        stage=job.stage,
        progress=KnowledgeJobProgressSchema(
            current=job.progress_current,
            total=job.progress_total,
        ),
        error=job.error_details,
    )


def _document_response(document: KnowledgeDocument) -> KnowledgeDocumentSchema:
    return KnowledgeDocumentSchema(
        id=document.id,
        source_uri=document.source_uri,
        canonical_path=document.canonical_path,
        title=document.title,
        manufacturer=document.manufacturer,
        model=document.model,
        category=document.category,
        document_type=document.document_type,
        content_hash=document.content_hash,
        status=document.status.value,
        metadata=document.metadata,
    )
