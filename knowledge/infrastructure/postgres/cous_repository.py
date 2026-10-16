"""Repositório PostgreSQL para KnowledgeUnits e Knowledge Graph — COUS v3.0.

Padrão: asyncpg, dataclasses imutáveis, transações explícitas.
"""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

import asyncpg

from knowledge.domain.cous_models import (
    ConfidenceBreakdown,
    ContradictionStatus,
    KnowledgeContradiction,
    KnowledgeLevel,
    KnowledgeUnit,
    KnowledgeUnitRelation,
    RelationType,
)


def _json_list(uuids: list[UUID]) -> str:
    return json.dumps([str(u) for u in uuids])


def _json_dict(data: dict[str, Any] | None) -> str | None:
    if data is None:
        return None
    return json.dumps(data)


def _optional_uuid(value: str | None) -> UUID | None:
    return UUID(value) if value else None


class ServiceOrderNotFoundError(ValueError):
    pass


class ServiceOrderSerialMissingError(ValueError):
    pass


class ServiceOrderSerialMismatchError(ValueError):
    pass


_SERIAL_COR_SUFFIX = re.compile(r"\s+COR\b.*$", re.IGNORECASE)


def _normalized_serial(value: object) -> str:
    """Normaliza serial para comparação: remove coluna COR e espaços em excesso.

    Documentos indexados antes da limpeza de extração podem guardar o serial
    com a coluna ``COR`` e espaços de coluna (ex.: ``W1NP2403464   COR: DOURADA``).
    Esta normalização torna a comparação tolerante a essa poluição sem alterar
    espaços simples legítimos do serial (ex.: ``EP10757 040523``).
    """
    raw = str(value or "").strip()
    raw = _SERIAL_COR_SUFFIX.sub("", raw)
    return re.sub(r"\s+", " ", raw).casefold()


def _service_order_serial(metadata: object, indexed_text: object) -> str:
    parsed_metadata = metadata
    if isinstance(parsed_metadata, str):
        parsed_metadata = json.loads(parsed_metadata)
    if not isinstance(parsed_metadata, dict):
        parsed_metadata = {}
    extra = parsed_metadata.get("extra")
    if not isinstance(extra, dict):
        extra = {}
    registered = extra.get("equipment_serial") or parsed_metadata.get(
        "equipment_serial"
    )
    if registered:
        return str(registered).strip()
    match = re.search(
        r"(?:n[º°o]\s*(?:de|do)?\s*(?:s[ée]rie|serial)|"
        r"s[ée]rie)\s*:\s*([\w.-]+)",
        str(indexed_text or ""),
        re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""


class CousKnowledgeRepository:
    """Repositório PostgreSQL para KnowledgeUnits e Knowledge Graph."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str, **kwargs: Any) -> CousKnowledgeRepository:
        pool = await asyncpg.create_pool(dsn=dsn, **kwargs)
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

    # ── KnowledgeUnits ───────────────────────────────────────────────

    async def create_ku(self, ku: KnowledgeUnit) -> KnowledgeUnit:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO knowledge_units (
                    id, domain_id, title, statement, knowledge_level,
                    confidence, confidence_breakdown, version, superseded_by,
                    last_validated_at, created_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $10, $11)
                RETURNING *
                """,
                ku.id,
                ku.domain_id,
                ku.title,
                ku.statement,
                ku.knowledge_level.value,
                ku.confidence,
                _json_dict(ku.confidence_breakdown.as_dict() if ku.confidence_breakdown else None),
                ku.version,
                ku.superseded_by,
                ku.last_validated_at,
                ku.created_at,
            )
            return _ku_from_row(row)

    async def get_ku(self, ku_id: UUID) -> KnowledgeUnit | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM knowledge_units WHERE id = $1", ku_id
            )
            return _ku_from_row(row) if row else None

    async def list_kus(
        self,
        domain_id: UUID | None = None,
        level: KnowledgeLevel | None = None,
        confidence_min: float | None = None,
        confidence_max: float | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[KnowledgeUnit]:
        query = "SELECT * FROM knowledge_units WHERE 1=1"
        params: list[Any] = []
        idx = 1

        if domain_id is not None:
            query += f" AND domain_id = ${idx}"
            params.append(domain_id)
            idx += 1
        if level is not None:
            query += f" AND knowledge_level = ${idx}"
            params.append(level.value)
            idx += 1
        if confidence_min is not None:
            query += f" AND confidence >= ${idx}"
            params.append(confidence_min)
            idx += 1
        if confidence_max is not None:
            query += f" AND confidence <= ${idx}"
            params.append(confidence_max)
            idx += 1
        if search:
            query += f" AND (title ILIKE ${idx} OR statement ILIKE ${idx})"
            params.append(f"%{search}%")
            idx += 1

        query += f" ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx + 1}"
        params.extend([limit, offset])

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [_ku_from_row(r) for r in rows]

    async def count_kus(
        self,
        domain_id: UUID | None = None,
        level: KnowledgeLevel | None = None,
    ) -> int:
        query = "SELECT COUNT(*) FROM knowledge_units WHERE 1=1"
        params: list[Any] = []
        idx = 1

        if domain_id is not None:
            query += f" AND domain_id = ${idx}"
            params.append(domain_id)
            idx += 1
        if level is not None:
            query += f" AND knowledge_level = ${idx}"
            params.append(level.value)
            idx += 1

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, *params)
            return row["count"] if row else 0

    async def update_ku(self, ku_id: UUID, **fields: Any) -> KnowledgeUnit | None:
        valid = {"title", "statement", "confidence", "confidence_breakdown",
                  "knowledge_level", "version", "superseded_by", "last_validated_at"}
        updates = {k: v for k, v in fields.items() if k in valid and v is not None}
        if not updates:
            return await self.get_ku(ku_id)

        set_clauses = []
        params: list[Any] = []
        idx = 1

        for key, value in updates.items():
            if key == "confidence_breakdown" and isinstance(value, ConfidenceBreakdown):
                value = json.dumps(value.as_dict())
            if isinstance(value, KnowledgeLevel):
                value = value.value
            set_clauses.append(f"{key} = ${idx}")
            params.append(value)
            idx += 1

        params.append(ku_id)
        query = f"UPDATE knowledge_units SET {', '.join(set_clauses)} WHERE id = ${idx} RETURNING *"

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, *params)
            return _ku_from_row(row) if row else None

    # ── KnowledgeUnit Relations ──────────────────────────────────────

    async def create_relation(self, rel: KnowledgeUnitRelation) -> KnowledgeUnitRelation:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO knowledge_unit_relations (
                    id, source_ku_id, target_ku_id, relation_type,
                    confidence, source, created_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING *
                """,
                rel.id, rel.source_ku_id, rel.target_ku_id,
                rel.relation_type.value, rel.confidence, rel.source, rel.created_at,
            )
            return _relation_from_row(row)

    async def list_relations(self, ku_id: UUID) -> list[KnowledgeUnitRelation]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM knowledge_unit_relations
                WHERE source_ku_id = $1 OR target_ku_id = $1
                ORDER BY created_at DESC
                """,
                ku_id,
            )
            return [_relation_from_row(r) for r in rows]

    async def delete_relation(self, rel_id: UUID) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM knowledge_unit_relations WHERE id = $1", rel_id
            )
            return result != "DELETE 0"

    # ── Source Cases ─────────────────────────────────────────────────

    async def add_ku_source(self, ku_id: UUID, case_id: UUID) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO knowledge_unit_sources (knowledge_unit_id, case_id)
                VALUES ($1, $2)
                ON CONFLICT DO NOTHING
                """,
                ku_id, case_id,
            )

    async def increment_chunk_usage(self, document_ids: list[UUID]) -> None:
        """Incrementa usage_count_confirmed para chunks dos documentos usados em caso confirmado."""
        if not document_ids:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE knowledge_chunks
                SET usage_count_confirmed = usage_count_confirmed + 1
                WHERE document_id = ANY($1::uuid[])
                """,
                document_ids,
            )

    async def count_sources(self, ku_id: UUID) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) FROM knowledge_unit_sources WHERE knowledge_unit_id = $1",
                ku_id,
            )
            return row["count"] if row else 0

    # ── Contradictions ───────────────────────────────────────────────

    async def create_contradiction(
        self, contradiction: KnowledgeContradiction
    ) -> KnowledgeContradiction:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO knowledge_contradictions (
                    id, knowledge_unit_id, contradicting_case_id,
                    contradicting_evidence_id, description,
                    resolution_status, created_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING *
                """,
                contradiction.id,
                contradiction.knowledge_unit_id,
                contradiction.contradicting_case_id,
                contradiction.contradicting_evidence_id,
                contradiction.description,
                contradiction.resolution_status.value,
                contradiction.created_at,
            )
            return _contradiction_from_row(row)

    async def list_contradictions(
        self, ku_id: UUID, status: str | None = None
    ) -> list[KnowledgeContradiction]:
        query = "SELECT * FROM knowledge_contradictions WHERE knowledge_unit_id = $1"
        params: list[Any] = [ku_id]
        if status:
            query += " AND resolution_status = $2"
            params.append(status)
        query += " ORDER BY created_at DESC"

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [_contradiction_from_row(r) for r in rows]

    async def count_open_contradictions(self, ku_id: UUID) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT COUNT(*) FROM knowledge_contradictions
                WHERE knowledge_unit_id = $1 AND resolution_status = 'open'
                """,
                ku_id,
            )
            return row["count"] if row else 0

    # ── Knowledge Graph ──────────────────────────────────────────────

    async def get_graph_nodes(self, domain_id: UUID) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, title, knowledge_level, confidence
                FROM knowledge_units
                WHERE domain_id = $1
                ORDER BY confidence DESC
                """,
                domain_id,
            )
            return [dict(r) for r in rows]

    async def get_graph_edges(self, domain_id: UUID) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT kur.id, kur.source_ku_id, kur.target_ku_id,
                       kur.relation_type, kur.confidence
                FROM knowledge_unit_relations kur
                JOIN knowledge_units ku ON ku.id = kur.source_ku_id
                WHERE ku.domain_id = $1
                ORDER BY kur.confidence DESC
                """,
                domain_id,
            )
            return [dict(r) for r in rows]

    async def find_paths(
        self, source_id: UUID, target_id: UUID, max_depth: int = 5
    ) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH RECURSIVE kg_path AS (
                    SELECT kur.source_ku_id, kur.target_ku_id,
                           kur.relation_type, kur.confidence,
                           1 AS depth,
                           ARRAY[kur.source_ku_id] AS path,
                           ARRAY[kur.relation_type] AS rels
                    FROM knowledge_unit_relations kur
                    WHERE kur.source_ku_id = $1

                    UNION ALL

                    SELECT kur.source_ku_id, kur.target_ku_id,
                           kur.relation_type, kur.confidence,
                           kg.depth + 1,
                           kg.path || kur.source_ku_id,
                           kg.rels || kur.relation_type
                    FROM knowledge_unit_relations kur
                    JOIN kg_path kg ON kur.source_ku_id = kg.target_ku_id
                    WHERE NOT kur.target_ku_id = ANY(kg.path)
                      AND kg.depth < $3
                )
                SELECT * FROM kg_path
                WHERE target_ku_id = $2
                ORDER BY depth ASC
                """,
                source_id, target_id, max_depth,
            )
            return [dict(r) for r in rows]

    # ── Operational Identity ─────────────────────────────────────────

    async def resolve_capture_identity(
        self,
        *,
        domain_name: str,
        domain_version: str = "v1",
        entity_type: str = "tattoo_machine",
        manufacturer: str = "",
        model: str = "",
        serial_number: str,
        service_order_number: str,
        measurement_observations: str = "",
        operator_name: str = "",
        service_order_scope: dict[str, str] | None = None,
    ) -> dict[str, UUID]:
        """Resolve/cria a identidade física e abre uma sessão de captura.

        Domínio, entidade e instância são reutilizados quando já existem.
        A sessão operacional/captura representa um evento novo de medição.
        """
        if service_order_scope is not None:
            if set(service_order_scope) != {"source_system", "organization_id", "service_order_id"}:
                raise ValueError("Incomplete service order scope")
            if service_order_scope["source_system"] != "systemos":
                raise ValueError("Unsupported source system")
            # Validate at the repository boundary too (not only the HTTP schema).
            UUID(service_order_scope["organization_id"])
            UUID(service_order_scope["service_order_id"])
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                domain = await conn.fetchrow(
                    """
                    INSERT INTO domains (name, version, status)
                    VALUES ($1, $2, 'active')
                    ON CONFLICT (name) DO UPDATE
                    SET version = COALESCE(domains.version, EXCLUDED.version)
                    RETURNING id
                    """,
                    domain_name,
                    domain_version,
                )
                domain_id = domain["id"]

                service_order = await conn.fetchrow(
                    """
                    SELECT kd.id, kd.metadata,
                           string_agg(kc.text, E'\n' ORDER BY kc.chunk_index)
                               AS indexed_text
                    FROM knowledge_documents kd
                    LEFT JOIN knowledge_chunks kc ON kc.document_id = kd.id
                    WHERE kd.document_type = 'service_order'
                      AND (kd.domain_id = $1 OR kd.domain_id IS NULL)
                      AND kd.status <> 'deleted'
                      AND ($3::jsonb IS NULL OR kd.metadata -> 'extra' @> $3::jsonb)
                      AND (
                          kd.metadata #>> '{extra,service_order_number}' = $2
                          OR kd.metadata ->> 'service_order_number' = $2
                          OR split_part(COALESCE(kd.title, ''), '_', 1) = $2
                          OR split_part(COALESCE(kd.title, ''), '-', 1) = $2
                      )
                    GROUP BY kd.id
                    ORDER BY (kd.domain_id = $1) DESC, kd.updated_at DESC
                    LIMIT 1
                    """,
                    domain_id,
                    service_order_number,
                    json.dumps(service_order_scope) if service_order_scope is not None else None,
                )
                if service_order is None:
                    raise ServiceOrderNotFoundError(
                        f"ordem de servico nao indexada: {service_order_number}"
                    )
                registered_serial = _service_order_serial(
                    service_order["metadata"],
                    service_order["indexed_text"],
                )
                if not _normalized_serial(registered_serial):
                    raise ServiceOrderSerialMissingError(
                        f"OS {service_order_number} nao possui numero de serie indexado"
                    )
                if _normalized_serial(registered_serial) != _normalized_serial(serial_number):
                    raise ServiceOrderSerialMismatchError(
                        f"numero de serie da medicao diverge da OS {service_order_number}"
                    )

                entity = await conn.fetchrow(
                    """
                    SELECT id FROM entities
                    WHERE domain_id = $1
                      AND entity_type = $2
                      AND COALESCE(manufacturer, '') = $3
                      AND COALESCE(model, '') = $4
                    ORDER BY created_at ASC
                    LIMIT 1
                    """,
                    domain_id,
                    entity_type,
                    manufacturer,
                    model,
                )
                if entity is None:
                    entity = await conn.fetchrow(
                        """
                        INSERT INTO entities (
                            domain_id, entity_type, manufacturer, model, description
                        )
                        VALUES ($1, $2, $3, $4, $5)
                        RETURNING id
                        """,
                        domain_id,
                        entity_type,
                        manufacturer,
                        model,
                        "Created by COUS operational identity resolver",
                    )
                entity_id = entity["id"]

                instance = await conn.fetchrow(
                    """
                    SELECT id FROM instances
                    WHERE entity_id = $1 AND serial_number = $2
                    ORDER BY created_at ASC
                    LIMIT 1
                    """,
                    entity_id,
                    serial_number,
                )
                if instance is None:
                    instance = await conn.fetchrow(
                        """
                        INSERT INTO instances (entity_id, serial_number)
                        VALUES ($1, $2)
                        RETURNING id
                        """,
                        entity_id,
                        serial_number,
                    )
                instance_id = instance["id"]

                operational_session = await conn.fetchrow(
                    """
                    INSERT INTO operational_sessions (
                        session_type, operator_name, status
                    )
                    VALUES ('capture', $1, 'open')
                    RETURNING id
                    """,
                    operator_name,
                )
                operational_session_id = operational_session["id"]

                capture_session = await conn.fetchrow(
                    """
                    INSERT INTO capture_sessions (
                        operational_session_id, instance_id, diagnosis_status,
                        service_order_document_id, header_observations
                    )
                    VALUES ($1, $2, 'pending', $3, $4)
                    RETURNING id
                    """,
                    operational_session_id,
                    instance_id,
                    service_order["id"],
                    measurement_observations,
                )

        return {
            "domain_id": domain_id,
            "entity_id": entity_id,
            "instance_id": instance_id,
            "operational_session_id": operational_session_id,
            "capture_session_id": capture_session["id"],
            "service_order_document_id": service_order["id"],
        }


# ── Row parsers ──────────────────────────────────────────────────────────

def _ku_from_row(row: asyncpg.Record) -> KnowledgeUnit:
    breakdown_raw = row.get("confidence_breakdown")
    if breakdown_raw:
        breakdown_raw = (
            json.loads(breakdown_raw)
            if isinstance(breakdown_raw, str)
            else breakdown_raw
        )
        breakdown = ConfidenceBreakdown.from_dict(breakdown_raw)
    else:
        breakdown = None

    return KnowledgeUnit(
        id=row["id"],
        domain_id=row["domain_id"],
        title=row["title"],
        statement=row["statement"],
        knowledge_level=KnowledgeLevel(row["knowledge_level"]),
        confidence=float(row["confidence"]),
        confidence_breakdown=breakdown,
        version=int(row["version"]),
        superseded_by=row.get("superseded_by"),
        last_validated_at=row.get("last_validated_at"),
        created_at=row["created_at"],
    )


def _relation_from_row(row: asyncpg.Record) -> KnowledgeUnitRelation:
    return KnowledgeUnitRelation(
        id=row["id"],
        source_ku_id=row["source_ku_id"],
        target_ku_id=row["target_ku_id"],
        relation_type=RelationType(row["relation_type"]),
        confidence=float(row["confidence"]),
        source=row["source"],
        created_at=row["created_at"],
    )


def _contradiction_from_row(row: asyncpg.Record) -> KnowledgeContradiction:
    return KnowledgeContradiction(
        id=row["id"],
        knowledge_unit_id=row["knowledge_unit_id"],
        contradicting_case_id=row.get("contradicting_case_id"),
        contradicting_evidence_id=row.get("contradicting_evidence_id"),
        description=row["description"],
        resolution_status=ContradictionStatus(row["resolution_status"]),
        created_at=row["created_at"],
    )
