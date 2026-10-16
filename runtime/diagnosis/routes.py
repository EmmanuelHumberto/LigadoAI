"""Endpoints REST para diagnóstico — COUS v3.0.

POST   /v3/diagnosis          — enfileirar diagnóstico
GET    /v3/diagnosis/{id}     — consultar status
GET    /v3/diagnosis/queue    — listar fila
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from secrets import compare_digest
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from knowledge.infrastructure.postgres.cous_repository import CousKnowledgeRepository
from knowledge.api.cous_schemas import ServiceOrderScopeSchema


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    try:
        return row[key]
    except (KeyError, TypeError):
        return default


def _bearer_auth_dependency(expected: str) -> Callable:
    async def verify(authorization: str = Header(...)) -> None:
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing Bearer token")
        token = authorization.removeprefix("Bearer ")
        if not compare_digest(token, expected):
            raise HTTPException(status_code=401, detail="Invalid token")
    return verify


class DiagnosisRequestSchema(BaseModel):
    service_order_scope: ServiceOrderScopeSchema | None = None
    correlation_id: UUID
    capture_session_id: UUID
    instance_id: UUID
    domain_id: UUID
    callback_endpoint: str
    priority: str = "normal"
    evidence_set: list[dict] = Field(default_factory=list)
    context: dict = Field(default_factory=dict)


class DiagnosisResponseSchema(BaseModel):
    correlation_id: UUID
    status: str
    queued_at: str
    position: int = 0


class DiagnosisStatusSchema(BaseModel):
    correlation_id: UUID
    status: str
    attempts: int = 0
    last_attempt_at: str | None = None
    error_message: str | None = None
    result: dict[str, Any] | None = None
    callback_status: str | None = None
    callback_attempts: int = 0
    callback_error: str | None = None


class DiagnosisQueueSchema(BaseModel):
    items: list[DiagnosisStatusSchema]
    total: int


class DiagnosisRetrySchema(BaseModel):
    correlation_id: UUID
    status: str


def create_diagnosis_router(
    *,
    repository: CousKnowledgeRepository,
    auth_token: str | None = None,
) -> APIRouter:
    dependencies = []
    if auth_token:
        dependencies.append(Depends(_bearer_auth_dependency(auth_token)))

    router = APIRouter(prefix="/v3/diagnosis", tags=["diagnosis"], dependencies=dependencies)

    @router.post("", response_model=DiagnosisResponseSchema,
                 status_code=status.HTTP_202_ACCEPTED)
    async def request_diagnosis(
        payload: DiagnosisRequestSchema,
    ) -> DiagnosisResponseSchema:
        """Enfileira uma requisição de diagnóstico."""
        queued_at = datetime.now(UTC)
        async with repository._pool.acquire() as conn:
            # A caller must not combine a capture from one machine with another
            # instance/domain or an unrelated external service order.
            identity = await conn.fetchrow(
                """
                SELECT cs.id FROM capture_sessions cs
                JOIN instances i ON i.id = cs.instance_id
                JOIN entities e ON e.id = i.entity_id
                LEFT JOIN knowledge_documents kd ON kd.id = cs.service_order_document_id
                WHERE cs.id = $1 AND cs.instance_id = $2 AND e.domain_id = $3
                  AND ($4::jsonb IS NULL OR (
                    kd.document_type = 'service_order' AND kd.status <> 'deleted'
                    AND kd.metadata -> 'extra' @> $4::jsonb
                  ))
                """,
                payload.capture_session_id, payload.instance_id, payload.domain_id,
                payload.service_order_scope.model_dump_json() if payload.service_order_scope else None,
            )
            if identity is None:
                raise HTTPException(status_code=409, detail="Capture identity or service order scope mismatch")
            pos_row = await conn.fetchrow(
                "SELECT COUNT(*) FROM diagnosis_queue WHERE status = 'pending'"
            )
            position = pos_row["count"] if pos_row else 0
            inserted = await conn.fetchrow(
                """
                INSERT INTO diagnosis_queue (
                    id, capture_session_id, instance_id,
                    domain_id, callback_endpoint, priority,
                    evidence_set, context, request_payload,
                    queued_at, status
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9::jsonb, $10, 'pending')
                ON CONFLICT (id) DO NOTHING
                RETURNING id
                """,
                payload.correlation_id, payload.capture_session_id, payload.instance_id,
                payload.domain_id, payload.callback_endpoint, payload.priority,
                json.dumps(payload.evidence_set, default=str),
                json.dumps(payload.context, default=str), payload.model_dump_json(), queued_at,
            )
            if inserted is None:
                previous = await conn.fetchrow(
                    "SELECT * FROM diagnosis_queue WHERE id = $1", payload.correlation_id,
                )
                saved = _row_json_value(previous, "request_payload") if previous else None
                # Defaults absent from old persisted payloads retain their meaning.
                try:
                    equivalent = saved is not None and DiagnosisRequestSchema.model_validate(saved) == payload
                except ValueError:
                    equivalent = False
                if not equivalent:
                    raise HTTPException(status_code=409, detail="Correlation ID already used for a different request")
                return DiagnosisResponseSchema(
                    correlation_id=payload.correlation_id, status=previous["status"],
                    queued_at=previous["queued_at"].isoformat(), position=0,
                )
        return DiagnosisResponseSchema(
            correlation_id=payload.correlation_id, status="queued",
            queued_at=queued_at.isoformat(), position=position + 1,
        )

    @router.get("/queue", response_model=DiagnosisQueueSchema)
    async def list_queue() -> DiagnosisQueueSchema:
        async with repository._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM diagnosis_queue ORDER BY queued_at DESC LIMIT 100"
            )
        items = [
            DiagnosisStatusSchema(
                correlation_id=row["id"],
                status=row["status"],
                attempts=int(row["attempts"]),
                last_attempt_at=row["last_attempt_at"].isoformat()
                if row["last_attempt_at"]
                else None,
                error_message=_row_value(row, "error_message"),
                callback_status=_row_value(row, "callback_status"),
                callback_attempts=int(_row_value(row, "callback_attempts", 0) or 0),
                callback_error=_row_value(row, "callback_error"),
            )
            for row in rows
        ]
        return DiagnosisQueueSchema(items=items, total=len(items))

    @router.post("/{correlation_id}/retry", response_model=DiagnosisRetrySchema)
    async def retry_failed_diagnosis(
        correlation_id: UUID,
    ) -> DiagnosisRetrySchema:
        async with repository._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE diagnosis_queue
                SET status = 'pending',
                    attempts = 0,
                    queued_at = NOW(),
                    last_attempt_at = NULL,
                    error_message = NULL,
                    result_payload = NULL,
                    callback_status = 'pending',
                    callback_attempts = 0,
                    callback_last_attempt_at = NULL,
                    callback_next_attempt_at = NULL,
                    callback_error = NULL
                WHERE id = $1 AND status = 'failed'
                RETURNING id
                """,
                correlation_id,
            )
        if row is None:
            raise HTTPException(
                status_code=409,
                detail="Diagnosis is not failed or does not exist",
            )
        return DiagnosisRetrySchema(
            correlation_id=correlation_id,
            status="pending",
        )

    @router.get("/{correlation_id}", response_model=DiagnosisStatusSchema)
    async def diagnosis_status(correlation_id: UUID) -> DiagnosisStatusSchema:
        async with repository._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM diagnosis_queue WHERE id = $1",
                correlation_id,
            )
        if row is None:
            raise HTTPException(status_code=404, detail="Diagnosis not found")

        return DiagnosisStatusSchema(
            correlation_id=correlation_id,
            status=row["status"],
            attempts=int(row["attempts"]),
            last_attempt_at=row["last_attempt_at"].isoformat() if row["last_attempt_at"] else None,
            error_message=_row_value(row, "error_message"),
            result=_row_json_value(row, "result_payload"),
            callback_status=_row_value(row, "callback_status"),
            callback_attempts=int(_row_value(row, "callback_attempts", 0) or 0),
            callback_error=_row_value(row, "callback_error"),
        )

    return router


def _row_json_value(row: Any, key: str) -> dict[str, Any] | None:
    raw = _row_value(row, key)
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None
