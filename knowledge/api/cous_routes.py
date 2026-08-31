"""Rotas FastAPI para KnowledgeUnits e Knowledge Graph — COUS v3.0.

Factory function que recebe dependências injetadas (repositório, promoção).
Segue o padrão de knowledge/api/routes.py e measurements/api/routes.py.
"""

from __future__ import annotations

from collections.abc import Callable
from secrets import compare_digest
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from knowledge.api.cous_schemas import (
    CaptureIdentityResolveRequestSchema,
    CaptureIdentityResolveResponseSchema,
    ConfidenceBreakdownSchema,
    DemotionRequestSchema,
    GraphEdgeSchema,
    GraphNodeSchema,
    GraphPathSchema,
    GraphPathsResponseSchema,
    GraphValidationSchema,
    KnowledgeContradictionCreateSchema,
    KnowledgeContradictionResponseSchema,
    KnowledgeGraphResponseSchema,
    KnowledgeUnitCreateSchema,
    KnowledgeUnitListSchema,
    KnowledgeUnitRelationCreateSchema,
    KnowledgeUnitRelationResponseSchema,
    KnowledgeUnitResponseSchema,
    KnowledgeUnitUpdateSchema,
    PromotionRequestSchema,
    PromotionResponseSchema,
)
from knowledge.domain.cous_models import (
    ConfidenceBreakdown,
    KnowledgeContradiction,
    KnowledgeLevel,
    KnowledgeUnit,
    KnowledgeUnitRelation,
    RelationType,
)
from knowledge.domain.promotion import check_demotion, check_promotion
from knowledge.infrastructure.postgres.cous_repository import (
    CousKnowledgeRepository,
    ServiceOrderNotFoundError,
    ServiceOrderSerialMismatchError,
    ServiceOrderSerialMissingError,
)


def _bearer_auth_dependency(expected: str) -> Callable:
    async def verify(authorization: str = Header(...)) -> None:
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing Bearer token")
        token = authorization.removeprefix("Bearer ")
        if not compare_digest(token, expected):
            raise HTTPException(status_code=401, detail="Invalid token")
    return verify


def _ku_to_response(ku: KnowledgeUnit) -> KnowledgeUnitResponseSchema:
    bd = None
    if ku.confidence_breakdown:
        bd = ConfidenceBreakdownSchema(
            evidence_score=ku.confidence_breakdown.evidence_score,
            document_score=ku.confidence_breakdown.document_score,
            history_score=ku.confidence_breakdown.history_score,
            consistency_score=ku.confidence_breakdown.consistency_score,
        )
    return KnowledgeUnitResponseSchema(
        id=ku.id,
        domain_id=ku.domain_id,
        title=ku.title,
        statement=ku.statement,
        knowledge_level=ku.knowledge_level,
        confidence=ku.confidence,
        confidence_breakdown=bd,
        version=ku.version,
        superseded_by=ku.superseded_by,
        last_validated_at=ku.last_validated_at,
        created_at=ku.created_at,
    )


def create_cous_v3_router(
    *,
    repository: CousKnowledgeRepository,
    auth_token: str | None = None,
) -> APIRouter:
    dependencies = []
    if auth_token:
        dependencies.append(Depends(_bearer_auth_dependency(auth_token)))

    router = APIRouter(prefix="/v3", tags=["cous-v3"], dependencies=dependencies)

    # ── Operational Identity ────────────────────────────────────────

    @router.post(
        "/operational/resolve-capture",
        response_model=CaptureIdentityResolveResponseSchema,
        status_code=status.HTTP_201_CREATED,
    )
    async def resolve_capture_identity(
        payload: CaptureIdentityResolveRequestSchema,
    ) -> CaptureIdentityResolveResponseSchema:
        try:
            ids = await repository.resolve_capture_identity(
                domain_name=payload.domain_name,
                domain_version=payload.domain_version,
                entity_type=payload.entity_type,
                manufacturer=payload.manufacturer,
                model=payload.model,
                serial_number=payload.serial_number,
                service_order_number=payload.service_order_number,
                measurement_observations=payload.measurement_observations,
                operator_name=payload.operator_name,
            )
        except ServiceOrderNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ServiceOrderSerialMissingError, ServiceOrderSerialMismatchError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return CaptureIdentityResolveResponseSchema(**ids)

    # ── KnowledgeUnits CRUD ──────────────────────────────────────────

    @router.post("/knowledge-units", response_model=KnowledgeUnitResponseSchema,
                 status_code=status.HTTP_201_CREATED)
    async def create_ku(payload: KnowledgeUnitCreateSchema) -> KnowledgeUnitResponseSchema:
        breakdown = None
        if payload.confidence_breakdown:
            bd = payload.confidence_breakdown
            breakdown = ConfidenceBreakdown(
                evidence_score=bd.evidence_score,
                document_score=bd.document_score,
                history_score=bd.history_score,
                consistency_score=bd.consistency_score,
            )

        ku = KnowledgeUnit(
            domain_id=payload.domain_id,
            title=payload.title,
            statement=payload.statement,
            knowledge_level=payload.knowledge_level,
            confidence=payload.confidence,
            confidence_breakdown=breakdown,
            version=payload.version,
        )
        created = await repository.create_ku(ku)
        return _ku_to_response(created)

    @router.get("/knowledge-units", response_model=KnowledgeUnitListSchema)
    async def list_kus(
        domain_id: UUID | None = Query(default=None),
        knowledge_level: KnowledgeLevel | None = Query(default=None),
        confidence_min: float | None = Query(default=None, ge=0.0, le=1.0),
        confidence_max: float | None = Query(default=None, ge=0.0, le=1.0),
        search: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> KnowledgeUnitListSchema:
        items = await repository.list_kus(
            domain_id=domain_id,
            level=knowledge_level,
            confidence_min=confidence_min,
            confidence_max=confidence_max,
            search=search,
            limit=limit,
            offset=offset,
        )
        total = await repository.count_kus(
            domain_id=domain_id,
            level=knowledge_level,
        )
        return KnowledgeUnitListSchema(
            items=[_ku_to_response(ku) for ku in items],
            total=total,
        )

    @router.get("/knowledge-units/{ku_id}", response_model=KnowledgeUnitResponseSchema)
    async def get_ku(ku_id: UUID) -> KnowledgeUnitResponseSchema:
        ku = await repository.get_ku(ku_id)
        if ku is None:
            raise HTTPException(status_code=404, detail="KnowledgeUnit not found")
        return _ku_to_response(ku)

    @router.patch("/knowledge-units/{ku_id}", response_model=KnowledgeUnitResponseSchema)
    async def update_ku(
        ku_id: UUID,
        payload: KnowledgeUnitUpdateSchema,
    ) -> KnowledgeUnitResponseSchema:
        updates = payload.model_dump(exclude_none=True)
        if "confidence_breakdown" in updates and updates["confidence_breakdown"]:
            bd = updates["confidence_breakdown"]
            updates["confidence_breakdown"] = ConfidenceBreakdown(
                evidence_score=bd.evidence_score,
                document_score=bd.document_score,
                history_score=bd.history_score,
                consistency_score=bd.consistency_score,
            )
        ku = await repository.update_ku(ku_id, **updates)
        if ku is None:
            raise HTTPException(status_code=404, detail="KnowledgeUnit not found")
        return _ku_to_response(ku)

    # ── Promotion / Demotion ─────────────────────────────────────────

    @router.post("/knowledge-units/{ku_id}/promote",
                 response_model=PromotionResponseSchema)
    async def promote_ku(ku_id: UUID, payload: PromotionRequestSchema) -> PromotionResponseSchema:
        ku = await repository.get_ku(ku_id)
        if ku is None:
            raise HTTPException(status_code=404, detail="KnowledgeUnit not found")

        result = check_promotion(
            ku,
            target=payload.target_level,
            confirmed_source_count=payload.confirmed_source_count,
            has_human_validation=payload.has_human_validation,
            has_open_contradictions=payload.has_open_contradictions,
            has_specialist_review=payload.has_specialist_review,
        )

        if result.allowed and result.target_level:
            await repository.update_ku(ku_id, knowledge_level=result.target_level,
                                       last_validated_at=ku.created_at)

        return PromotionResponseSchema(
            allowed=result.allowed,
            current_level=result.current_level,
            target_level=result.target_level,
            reason=result.reason,
        )

    @router.post("/knowledge-units/{ku_id}/demote",
                 response_model=PromotionResponseSchema)
    async def demote_ku(ku_id: UUID, payload: DemotionRequestSchema) -> PromotionResponseSchema:
        ku = await repository.get_ku(ku_id)
        if ku is None:
            raise HTTPException(status_code=404, detail="KnowledgeUnit not found")

        result = check_demotion(
            ku,
            has_open_contradictions=payload.has_open_contradictions,
            has_new_refutation=payload.has_new_refutation,
        )

        if result.allowed and result.target_level:
            await repository.update_ku(ku_id, knowledge_level=result.target_level)

        return PromotionResponseSchema(
            allowed=result.allowed,
            current_level=result.current_level,
            target_level=result.target_level,
            reason=result.reason,
        )

    # ── Relations ────────────────────────────────────────────────────

    @router.get("/knowledge-units/{ku_id}/relations",
                response_model=list[KnowledgeUnitRelationResponseSchema])
    async def list_relations(ku_id: UUID) -> list[KnowledgeUnitRelationResponseSchema]:
        ku = await repository.get_ku(ku_id)
        if ku is None:
            raise HTTPException(status_code=404, detail="KnowledgeUnit not found")
        relations = await repository.list_relations(ku_id)
        return [
            KnowledgeUnitRelationResponseSchema(
                id=r.id, source_ku_id=r.source_ku_id, target_ku_id=r.target_ku_id,
                relation_type=r.relation_type, confidence=r.confidence,
                source=r.source, created_at=r.created_at,
            )
            for r in relations
        ]

    @router.post("/knowledge-units/{ku_id}/relations",
                 response_model=KnowledgeUnitRelationResponseSchema,
                 status_code=status.HTTP_201_CREATED)
    async def create_relation(
        ku_id: UUID, payload: KnowledgeUnitRelationCreateSchema
    ) -> KnowledgeUnitRelationResponseSchema:
        ku = await repository.get_ku(ku_id)
        if ku is None:
            raise HTTPException(status_code=404, detail="KnowledgeUnit not found")

        target = await repository.get_ku(payload.target_ku_id)
        if target is None:
            raise HTTPException(status_code=404, detail="Target KnowledgeUnit not found")

        rel = KnowledgeUnitRelation(
            source_ku_id=ku_id,
            target_ku_id=payload.target_ku_id,
            relation_type=payload.relation_type,
            confidence=payload.confidence,
            source=payload.source,
        )
        created = await repository.create_relation(rel)
        return KnowledgeUnitRelationResponseSchema(
            id=created.id, source_ku_id=created.source_ku_id,
            target_ku_id=created.target_ku_id, relation_type=created.relation_type,
            confidence=created.confidence, source=created.source,
            created_at=created.created_at,
        )

    @router.delete("/knowledge-units/{ku_id}/relations/{rel_id}",
                   status_code=status.HTTP_204_NO_CONTENT)
    async def delete_relation(ku_id: UUID, rel_id: UUID) -> None:
        deleted = await repository.delete_relation(rel_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Relation not found")

    # ── Contradictions ───────────────────────────────────────────────

    @router.get("/knowledge-units/{ku_id}/contradictions",
                response_model=list[KnowledgeContradictionResponseSchema])
    async def list_contradictions(ku_id: UUID) -> list[KnowledgeContradictionResponseSchema]:
        ku = await repository.get_ku(ku_id)
        if ku is None:
            raise HTTPException(status_code=404, detail="KnowledgeUnit not found")
        contradictions = await repository.list_contradictions(ku_id)
        return [
            KnowledgeContradictionResponseSchema(
                id=c.id, knowledge_unit_id=c.knowledge_unit_id,
                contradicting_case_id=c.contradicting_case_id,
                contradicting_evidence_id=c.contradicting_evidence_id,
                description=c.description, resolution_status=c.resolution_status,
                created_at=c.created_at,
            )
            for c in contradictions
        ]

    @router.post("/knowledge-units/{ku_id}/contradictions",
                 response_model=KnowledgeContradictionResponseSchema,
                 status_code=status.HTTP_201_CREATED)
    async def create_contradiction(
        ku_id: UUID, payload: KnowledgeContradictionCreateSchema
    ) -> KnowledgeContradictionResponseSchema:
        ku = await repository.get_ku(ku_id)
        if ku is None:
            raise HTTPException(status_code=404, detail="KnowledgeUnit not found")

        contradiction = KnowledgeContradiction(
            knowledge_unit_id=ku_id,
            contradicting_case_id=payload.contradicting_case_id,
            contradicting_evidence_id=payload.contradicting_evidence_id,
            description=payload.description,
        )
        created = await repository.create_contradiction(contradiction)
        return KnowledgeContradictionResponseSchema(
            id=created.id, knowledge_unit_id=created.knowledge_unit_id,
            contradicting_case_id=created.contradicting_case_id,
            contradicting_evidence_id=created.contradicting_evidence_id,
            description=created.description,
            resolution_status=created.resolution_status,
            created_at=created.created_at,
        )

    # ── Knowledge Graph ──────────────────────────────────────────────

    @router.get("/knowledge-graph/{domain_id}",
                response_model=KnowledgeGraphResponseSchema)
    async def get_knowledge_graph(domain_id: UUID) -> KnowledgeGraphResponseSchema:
        nodes = await repository.get_graph_nodes(domain_id)
        edges = await repository.get_graph_edges(domain_id)

        return KnowledgeGraphResponseSchema(
            domain_id=domain_id,
            nodes=[
                GraphNodeSchema(
                    id=n["id"], title=n["title"],
                    level=KnowledgeLevel(n["knowledge_level"]),
                    confidence=float(n["confidence"]),
                )
                for n in nodes
            ],
            edges=[
                GraphEdgeSchema(
                    source_id=e["source_ku_id"], target_id=e["target_ku_id"],
                    relation_type=RelationType(e["relation_type"]),
                    confidence=float(e["confidence"]),
                )
                for e in edges
            ],
        )

    @router.get("/knowledge-graph/{domain_id}/paths",
                response_model=GraphPathsResponseSchema)
    async def find_paths(
        domain_id: UUID,
        source_id: UUID = Query(...),
        target_id: UUID = Query(...),
        max_depth: int = Query(default=5, ge=1, le=10),
    ) -> GraphPathsResponseSchema:
        paths = await repository.find_paths(source_id, target_id, max_depth)
        return GraphPathsResponseSchema(
            paths=[
                GraphPathSchema(
                    path=[UUID(str(p)) if isinstance(p, str) else p for p in row["path"]]
                        + [row["target_ku_id"]],
                    relations=[RelationType(r) for r in row["rels"]],
                    total_confidence=float(row["confidence"]),
                )
                for row in paths
            ]
        )

    @router.get("/knowledge-graph/{domain_id}/validate",
                response_model=GraphValidationSchema)
    async def validate_graph(domain_id: UUID) -> GraphValidationSchema:
        from knowledge.domain.graph_validator import validate_graph as validate

        nodes = await repository.get_graph_nodes(domain_id)
        edges = await repository.get_graph_edges(domain_id)

        result = validate(nodes, edges)

        return GraphValidationSchema(
            valid=result.valid,
            cycles_detected=result.cycles_detected,
            self_relations_detected=result.self_relations_detected,
            domain_mismatches=result.domain_mismatches,
            details=result.details,
        )

    @router.get("/knowledge-graph/{domain_id}/metrics")
    async def graph_metrics(domain_id: UUID) -> dict:
        from knowledge.domain.graph_validator import compute_graph_metrics

        nodes = await repository.get_graph_nodes(domain_id)
        edges = await repository.get_graph_edges(domain_id)

        return compute_graph_metrics(nodes, edges)

    return router
