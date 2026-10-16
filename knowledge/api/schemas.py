"""Pydantic schemas for knowledge HTTP contracts."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator
import hashlib
import json


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
    inline_text: str | None = Field(default=None, min_length=1, max_length=131072)
    content_type: str | None = None
    content_hash: str | None = None
    metadata: KnowledgeMetadataSchema = Field(default_factory=KnowledgeMetadataSchema)
    options: KnowledgeIndexOptionsSchema = Field(default_factory=KnowledgeIndexOptionsSchema)


    @model_validator(mode="after")
    def validate_inline_snapshot(self):
        if self.inline_text is not None:
            from knowledge.api.cous_schemas import ServiceOrderScopeSchema
            scope = ServiceOrderScopeSchema.model_validate({
                key: self.metadata.extra.get(key)
                for key in ("source_system", "organization_id", "service_order_id")
            })
            try:
                snapshot = json.loads(self.inline_text)
            except (ValueError, TypeError) as exc:
                raise ValueError("Operational snapshot must be JSON") from exc
            if (not isinstance(snapshot, dict) or snapshot.get("schemaVersion") != 1
                or snapshot.get("scope") != scope.model_dump(mode="json")
                or str(snapshot.get("numeroOS", "")) != self.metadata.extra.get("service_order_number")
                or not isinstance(snapshot.get("equipamento"), dict)
                or snapshot["equipamento"].get("numeroSerie") != self.metadata.extra.get("equipment_serial")
                or not self.metadata.extra.get("equipment_serial")
                or not isinstance(snapshot.get("evidencias"), list)
                or not isinstance(snapshot.get("ensaios"), list)):
                raise ValueError("Snapshot body does not match declared service order identity")
            digest = hashlib.sha256(self.inline_text.encode("utf-8")).hexdigest()
            expected_uri = f"systemos://{scope.organization_id}/{scope.service_order_id}/{digest}"
            if self.source_uri != expected_uri or self.content_hash != digest:
                raise ValueError("Snapshot URI/hash does not match content and scope")
            if self.metadata.document_type != "service_order" or len(self.inline_text.encode("utf-8")) > 131072:
                raise ValueError("Inline content is reserved for scoped service order snapshots up to 128 KiB")
        return self


class KnowledgeIndexResponseSchema(BaseModel):
    duplicate_of: UUID | None = None
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
