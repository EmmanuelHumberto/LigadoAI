"""Schemas Pydantic para API COUS v3.0 — KnowledgeUnits e Knowledge Graph."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID
from typing import Literal

from pydantic import BaseModel, Field

from knowledge.domain.cous_models import (
    ContradictionStatus,
    KnowledgeLevel,
    RelationType,
)

# ── Confidence Breakdown ─────────────────────────────────────────────────

class ConfidenceBreakdownSchema(BaseModel):
    evidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    document_score: float = Field(default=0.0, ge=0.0, le=1.0)
    history_score: float = Field(default=0.0, ge=0.0, le=1.0)
    consistency_score: float = Field(default=0.0, ge=0.0, le=1.0)


# ── KnowledgeUnit ────────────────────────────────────────────────────────

class KnowledgeUnitCreateSchema(BaseModel):
    domain_id: UUID
    title: str = Field(min_length=1, max_length=255)
    statement: str = Field(min_length=1)
    knowledge_level: KnowledgeLevel = KnowledgeLevel.EXPERIMENTAL
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence_breakdown: ConfidenceBreakdownSchema | None = None
    version: int = Field(default=1, ge=1)


class KnowledgeUnitUpdateSchema(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    statement: str | None = Field(default=None, min_length=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence_breakdown: ConfidenceBreakdownSchema | None = None


class KnowledgeUnitResponseSchema(BaseModel):
    id: UUID
    domain_id: UUID
    title: str
    statement: str
    knowledge_level: KnowledgeLevel
    confidence: float
    confidence_breakdown: ConfidenceBreakdownSchema | None = None
    version: int
    superseded_by: UUID | None = None
    last_validated_at: datetime | None = None
    created_at: datetime


class KnowledgeUnitListSchema(BaseModel):
    items: list[KnowledgeUnitResponseSchema]
    total: int


# ── KnowledgeUnit Relations ──────────────────────────────────────────────

class KnowledgeUnitRelationCreateSchema(BaseModel):
    target_ku_id: UUID
    relation_type: RelationType
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source: str = "inference"


class KnowledgeUnitRelationResponseSchema(BaseModel):
    id: UUID
    source_ku_id: UUID
    target_ku_id: UUID
    relation_type: RelationType
    confidence: float
    source: str
    created_at: datetime


# ── Contradictions ───────────────────────────────────────────────────────

class KnowledgeContradictionCreateSchema(BaseModel):
    contradicting_case_id: UUID | None = None
    contradicting_evidence_id: UUID | None = None
    description: str = Field(min_length=1)


class KnowledgeContradictionResponseSchema(BaseModel):
    id: UUID
    knowledge_unit_id: UUID
    contradicting_case_id: UUID | None = None
    contradicting_evidence_id: UUID | None = None
    description: str
    resolution_status: ContradictionStatus
    created_at: datetime


# ── Promotion / Demotion ─────────────────────────────────────────────────

class PromotionRequestSchema(BaseModel):
    target_level: KnowledgeLevel
    confirmed_source_count: int = Field(default=0, ge=0)
    has_human_validation: bool = False
    has_open_contradictions: bool = False
    has_specialist_review: bool = False


class PromotionResponseSchema(BaseModel):
    allowed: bool
    current_level: KnowledgeLevel
    target_level: KnowledgeLevel | None = None
    reason: str = ""


class DemotionRequestSchema(BaseModel):
    has_open_contradictions: bool = False
    has_new_refutation: bool = False


# ── Knowledge Graph ──────────────────────────────────────────────────────

class GraphNodeSchema(BaseModel):
    id: UUID
    title: str
    level: KnowledgeLevel
    confidence: float


class GraphEdgeSchema(BaseModel):
    source_id: UUID
    target_id: UUID
    relation_type: RelationType
    confidence: float


class KnowledgeGraphResponseSchema(BaseModel):
    domain_id: UUID
    nodes: list[GraphNodeSchema]
    edges: list[GraphEdgeSchema]


class GraphPathSchema(BaseModel):
    path: list[UUID]
    relations: list[RelationType]
    total_confidence: float


class GraphPathsResponseSchema(BaseModel):
    paths: list[GraphPathSchema]


class GraphValidationSchema(BaseModel):
    valid: bool
    cycles_detected: int = 0
    self_relations_detected: int = 0
    domain_mismatches: int = 0
    details: list[str] = Field(default_factory=list)


# ── Filters ──────────────────────────────────────────────────────────────

class KnowledgeUnitFilterSchema(BaseModel):
    domain_id: UUID | None = None
    knowledge_level: KnowledgeLevel | None = None
    confidence_min: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence_max: float | None = Field(default=None, ge=0.0, le=1.0)
    search: str | None = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


# ── Operational Identity ─────────────────────────────────────────────────

class ServiceOrderScopeSchema(BaseModel):
    """External OS identity. Missing scope never falls back to a numbered OS."""
    model_config = {"extra": "forbid"}
    source_system: Literal["systemos"]
    organization_id: UUID
    service_order_id: UUID


class CaptureIdentityResolveRequestSchema(BaseModel):
    service_order_scope: ServiceOrderScopeSchema | None = None
    domain_name: str = Field(default="tattoo_machines", min_length=1, max_length=255)
    domain_version: str = Field(default="v1", max_length=50)
    entity_type: str = Field(default="tattoo_machine", min_length=1, max_length=100)
    manufacturer: str = Field(default="", max_length=255)
    model: str = Field(default="", max_length=255)
    serial_number: str = Field(min_length=1, max_length=255)
    service_order_number: str = Field(min_length=1, max_length=255)
    measurement_observations: str = Field(default="", max_length=10000)
    operator_name: str = Field(default="", max_length=255)


class CaptureIdentityResolveResponseSchema(BaseModel):
    domain_id: UUID
    entity_id: UUID
    instance_id: UUID
    operational_session_id: UUID
    capture_session_id: UUID
    service_order_document_id: UUID
