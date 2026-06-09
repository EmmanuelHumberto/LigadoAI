"""Core domain objects for OpenTracy knowledge ingestion.

These types intentionally do not import FastAPI, PostgreSQL, FAISS, or any
client-specific code. Infrastructure adapts them to storage, queues, and APIs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


def utcnow() -> datetime:
    return datetime.now(UTC)


class DocumentStatus(StrEnum):
    PROCESSING = "processing"
    INDEXED = "indexed"
    FAILED = "failed"
    DELETED = "deleted"
    SUPERSEDED = "superseded"


class JobKind(StrEnum):
    INDEX_DOCUMENT = "index-document"
    REBUILD_INDEX = "rebuild-index"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PROCESSING = "processing"
    INDEXED = "indexed"
    SKIPPED = "skipped"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    DUPLICATE = "duplicate"


@dataclass(frozen=True)
class KnowledgeMetadata:
    manufacturer: str | None = None
    model: str | None = None
    category: str | None = None
    document_type: str | None = None
    title: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def normalized(self) -> KnowledgeMetadata:
        return KnowledgeMetadata(
            manufacturer=_clean_optional(self.manufacturer),
            model=_clean_optional(self.model),
            category=_clean_optional(self.category),
            document_type=_clean_optional(self.document_type),
            title=_clean_optional(self.title),
            extra=dict(self.extra),
        )

    def as_dict(self) -> dict[str, Any]:
        data = dict(self.extra)
        for key in ("manufacturer", "model", "category", "document_type", "title"):
            value = getattr(self, key)
            if value:
                data[key] = value
        return data


@dataclass(frozen=True)
class KnowledgeDocument:
    source_uri: str
    content_hash: str
    id: UUID = field(default_factory=uuid4)
    canonical_path: str | None = None
    title: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    category: str | None = None
    document_type: str | None = None
    status: DocumentStatus = DocumentStatus.PROCESSING
    metadata: dict[str, Any] = field(default_factory=dict)
    error_details: dict[str, Any] | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class KnowledgeChunk:
    document_id: UUID
    chunk_index: int
    text: str
    text_hash: str
    id: UUID = field(default_factory=uuid4)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class KnowledgeEmbedding:
    chunk_id: UUID
    embedding_model: str
    dimension: int
    vector_raw: tuple[float, ...]
    created_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class CorpusVersion:
    version: int
    status: str
    embedding_model: str
    vector_dimension: int
    chunking_strategy: str
    ranking_strategy: str
    schema_version: str
    id: UUID = field(default_factory=uuid4)
    document_count: int = 0
    chunk_count: int = 0
    prompt_version: str | None = None
    converter_version: str | None = None
    ocr_profile: str | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class KnowledgeJob:
    kind: JobKind
    source_uri: str | None = None
    id: UUID = field(default_factory=uuid4)
    document_id: UUID | None = None
    status: JobStatus = JobStatus.QUEUED
    stage: str | None = None
    progress_current: int = 0
    progress_total: int = 0
    idempotency_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    error_details: dict[str, Any] | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    def mark_duplicate(self, duplicate_of: UUID) -> KnowledgeJob:
        metadata = dict(self.metadata)
        metadata["duplicate_of"] = str(duplicate_of)
        return KnowledgeJob(
            kind=self.kind,
            source_uri=self.source_uri,
            id=self.id,
            document_id=self.document_id,
            status=JobStatus.DUPLICATE,
            stage=self.stage,
            progress_current=self.progress_current,
            progress_total=self.progress_total,
            idempotency_key=self.idempotency_key,
            metadata=metadata,
            error_details=self.error_details,
            created_at=self.created_at,
            updated_at=utcnow(),
        )


@dataclass(frozen=True)
class KnowledgeStoreStatus:
    index_status: str
    document_count: int = 0
    chunk_count: int = 0
    corpus_version: int | None = None


@dataclass(frozen=True)
class ConvertedDocument:
    source_uri: str
    text: str
    content_type: str | None = None
    title: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ValidationResult:
    approved: bool
    status: str = "approved"
    errors: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class KnowledgeSearchResult:
    chunk_id: UUID
    document_id: UUID
    score: float
    text: str
    source_uri: str
    metadata: dict[str, Any] = field(default_factory=dict)


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None
