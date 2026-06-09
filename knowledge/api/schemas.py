"""Pydantic schemas for knowledge HTTP contracts."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class KnowledgeMetadataSchema(BaseModel):
    manufacturer: str | None = None
    model: str | None = None
    category: str | None = None
    document_type: str | None = None
    title: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class KnowledgeIndexOptionsSchema(BaseModel):
    force: bool = False


class KnowledgeIndexRequestSchema(BaseModel):
    source_uri: str
    content_type: str | None = None
    content_hash: str | None = None
    metadata: KnowledgeMetadataSchema = Field(default_factory=KnowledgeMetadataSchema)
    options: KnowledgeIndexOptionsSchema = Field(default_factory=KnowledgeIndexOptionsSchema)


class KnowledgeIndexResponseSchema(BaseModel):
    job_id: UUID
    document_id: UUID | None = None
    status: str
    message: str


class KnowledgeValidateRequestSchema(BaseModel):
    source_uri: str


class KnowledgeValidateResponseSchema(BaseModel):
    approved: bool
    status: str
    source_uri: str
    title: str | None = None
    content_type: str | None = None
    char_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
    errors: list[dict[str, Any]] = Field(default_factory=list)


class KnowledgeJobProgressSchema(BaseModel):
    current: int = 0
    total: int = 0


class KnowledgeJobResponseSchema(BaseModel):
    job_id: UUID
    document_id: UUID | None = None
    status: str
    kind: str
    stage: str | None = None
    progress: KnowledgeJobProgressSchema = Field(default_factory=KnowledgeJobProgressSchema)
    error: dict[str, Any] | None = None


class KnowledgeDocumentSchema(BaseModel):
    id: UUID
    source_uri: str
    canonical_path: str | None = None
    title: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    category: str | None = None
    document_type: str | None = None
    content_hash: str
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeDocumentsResponseSchema(BaseModel):
    documents: list[KnowledgeDocumentSchema] = Field(default_factory=list)


class KnowledgeSearchRequestSchema(BaseModel):
    query: str
    top_k: int = Field(default=8, ge=1, le=50)
    filters: dict[str, str] = Field(default_factory=dict)


class KnowledgeSearchResultSchema(BaseModel):
    chunk_id: UUID
    document_id: UUID
    score: float
    text: str
    source_uri: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeSearchResponseSchema(BaseModel):
    results: list[KnowledgeSearchResultSchema] = Field(default_factory=list)


class KnowledgeStatusSchema(BaseModel):
    status: Literal["ready", "loading", "rebuilding", "stale", "unavailable"]
    document_count: int = 0
    chunk_count: int = 0
    corpus_version: int | None = None
