"""Read-only MCP server exposing canonical COUS operational facts."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import asyncpg
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from runtime.diagnosis.electromechanical import CORRELATION_TIMELINE_QUERY, summarize_persisted_relations

server: Server = Server("cous-facts")

TOOLS = [
    Tool(
        name="count_service_orders",
        description=(
            "Count indexed service-order documents and distinct OS numbers, with an "
            "optional text filter such as manufacturer, model, client, or symptom. "
            "Use this for exact totals instead of listing and counting manually."
        ),
        inputSchema={
            "type": "object",
            "properties": {"query": {"type": "string", "default": ""}},
            "additionalProperties": False,
        },
    ),
    Tool(
        name="list_service_orders",
        description="List indexed service orders with stable pagination and optional text filter.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "default": ""},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
            },
            "additionalProperties": False,
        },
    ),
    Tool(
        name="get_service_order",
        description=(
            "Read one indexed service order by its exact OS number, including metadata "
            "and the full text assembled from its ordered chunks."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "service_order_number": {"type": "string", "minLength": 1},
            },
            "required": ["service_order_number"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="get_knowledge_document",
        description=(
            "Read an indexed knowledge document by exact UUID, title, source URI, "
            "or canonical path, including its ordered text chunks."
        ),
        inputSchema={
            "type": "object",
            "properties": {"identifier": {"type": "string", "minLength": 1}},
            "required": ["identifier"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="search_database",
        description=(
            "Search canonical OpenTracy data across indexed knowledge, measurements, "
            "diagnoses, and knowledge units. Use this before concluding that an "
            "identifier or fact is absent. This is bounded read-only search, not SQL."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1},
                "scopes": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "knowledge",
                            "measurements",
                            "diagnoses",
                            "knowledge_units",
                        ],
                    },
                    "uniqueItems": True,
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 25, "default": 10},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="database_inventory",
        description=(
            "Return authoritative counts for the canonical database: indexed documents "
            "and chunks, measurements, captures, diagnoses, and knowledge units."
        ),
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    Tool(
        name="get_measurement_session",
        description=(
            "Get a measurement by UUID, equipment serial number, or service-order number, "
            "including ingestion and projection status."
        ),
        inputSchema={
            "type": "object",
            "properties": {"identifier": {"type": "string", "minLength": 1}},
            "required": ["identifier"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="get_diagnosis",
        description=(
            "Get the latest formal deterministic diagnosis by correlation UUID "
            "or capture-session UUID."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "correlation_id": {"type": "string"},
                "capture_session_id": {"type": "string"},
            },
            "anyOf": [
                {"required": ["correlation_id"]},
                {"required": ["capture_session_id"]},
            ],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="get_capture_evidence",
        description=(
            "Get normalized electromechanical signatures, firmware-produced deviations, "
            "causal relations, and temporally summarized failure modes for one capture UUID."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "capture_session_id": {"type": "string", "minLength": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
            },
            "required": ["capture_session_id"],
            "additionalProperties": False,
        },
    ),
]


def _database_url() -> str:
    value = (
        os.environ.get("OPENTRACY_COUS_V3_DATABASE_URL")
        or os.environ.get("OPENTRACY_KNOWLEDGE_DATABASE_URL")
        or os.environ.get("OPENTRACY_MEASUREMENTS_DATABASE_URL")
    )
    if not value:
        raise RuntimeError("OpenTracy database URL is not configured")
    return value


async def _fetchrow(query: str, *args: Any) -> dict[str, Any] | None:
    conn = await asyncpg.connect(_database_url(), timeout=3.0)
    try:
        row = await conn.fetchrow(query, *args)
        return _normalize_row(dict(row)) if row else None
    finally:
        await conn.close()


async def _fetch(query: str, *args: Any) -> list[dict[str, Any]]:
    conn = await asyncpg.connect(_database_url(), timeout=3.0)
    try:
        return [_normalize_row(dict(row)) for row in await conn.fetch(query, *args)]
    finally:
        await conn.close()


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    for key, value in row.items():
        if not isinstance(value, str) or key not in {
            "context",
            "data",
            "diagnostic",
            "evidence_set",
            "metadata",
            "result_payload",
        }:
            continue
        try:
            row[key] = json.loads(value)
        except json.JSONDecodeError:
            pass
    return row


async def count_service_orders(query: str = "") -> dict[str, Any]:
    value = query.strip()
    row = await _fetchrow(
        """
        WITH documents AS (
            SELECT kd.id, kd.title, kd.source_uri, kd.manufacturer,
                   kd.model, kd.category, kd.metadata,
                   string_agg(kc.text, E'\n' ORDER BY kc.chunk_index) AS indexed_text
            FROM knowledge_documents kd
            LEFT JOIN knowledge_chunks kc ON kc.document_id = kd.id
            WHERE kd.document_type = 'service_order'
              AND kd.status <> 'deleted'
            GROUP BY kd.id
        ),
        orders AS (
            SELECT COALESCE(
                substring(metadata #>> '{extra,service_order_number}' from '([0-9]{3,})'),
                substring(metadata ->> 'service_order_number' from '([0-9]{3,})'),
                substring(title from '([0-9]{3,})'),
                substring(
                    upper(COALESCE(indexed_text, ''))
                    from 'ORDEM DE SERVI[^0-9]{0,20}([0-9]{3,})'
                )
            ) AS number
            FROM documents
            WHERE
              (
                  $1 = ''
                  OR concat_ws(' ', title, source_uri, manufacturer,
                               model, category, metadata::text, indexed_text)
                     ILIKE '%' || $1 || '%'
              )
        )
        SELECT $1::text AS query,
               COUNT(*)::int AS document_count,
               COUNT(DISTINCT number)::int AS distinct_order_count,
               COUNT(*) FILTER (WHERE number IS NULL)::int AS missing_number_count,
               COUNT(number) - COUNT(DISTINCT number) AS duplicate_number_count
        FROM orders
        """,
        value,
    )
    return row or {}


async def list_service_orders(
    query: str = "",
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    rows = await _fetch(
        """
        SELECT id,
               COALESCE(
                   NULLIF(metadata #>> '{extra,service_order_number}', ''),
                   NULLIF(metadata ->> 'service_order_number', ''),
                   NULLIF(split_part(COALESCE(title, ''), '_', 1), ''),
                   NULLIF(split_part(COALESCE(title, ''), '-', 1), '')
               ) AS service_order_number,
               title,
               COALESCE(
                   NULLIF(metadata #>> '{extra,serial_number}', ''),
                   NULLIF(metadata ->> 'serial_number', ''),
                   NULLIF(metadata #>> '{extra,equipment_serial_number}', '')
               ) AS equipment_serial_number,
               updated_at
        FROM knowledge_documents
        WHERE document_type = 'service_order'
          AND ($1 = '' OR title ILIKE '%' || $1 || '%'
               OR metadata::text ILIKE '%' || $1 || '%')
        ORDER BY updated_at DESC, id
        LIMIT $2 OFFSET $3
        """,
        query.strip(),
        max(1, min(int(limit), 100)),
        max(0, int(offset)),
    )
    return {"items": rows, "count": len(rows), "offset": max(0, int(offset))}


def _bounded_document(row: dict[str, Any] | None) -> dict[str, Any]:
    if row is None:
        return {"found": False, "document": {}}
    text = str(row.pop("indexed_text", "") or "")
    maximum = 40_000
    row["indexed_text"] = text[:maximum]
    row["text_length"] = len(text)
    row["text_truncated"] = len(text) > maximum
    return {"found": True, "document": row}


async def get_service_order(service_order_number: str) -> dict[str, Any]:
    number = service_order_number.strip()
    row = await _fetchrow(
        """
        SELECT kd.id,
               COALESCE(
                   NULLIF(kd.metadata #>> '{extra,service_order_number}', ''),
                   NULLIF(kd.metadata ->> 'service_order_number', ''),
                   NULLIF(split_part(COALESCE(kd.title, ''), '_', 1), ''),
                   NULLIF(split_part(COALESCE(kd.title, ''), '-', 1), '')
               ) AS service_order_number,
               kd.title, kd.source_uri, kd.canonical_path, kd.status,
               kd.manufacturer, kd.model, kd.metadata, kd.updated_at,
               COUNT(kc.id)::int AS chunk_count,
               string_agg(kc.text, E'\n' ORDER BY kc.chunk_index) AS indexed_text
        FROM knowledge_documents kd
        LEFT JOIN knowledge_chunks kc ON kc.document_id = kd.id
        WHERE kd.document_type = 'service_order'
          AND kd.status <> 'deleted'
          AND (
              kd.metadata #>> '{extra,service_order_number}' = $1
              OR kd.metadata ->> 'service_order_number' = $1
              OR split_part(COALESCE(kd.title, ''), '_', 1) = $1
              OR split_part(COALESCE(kd.title, ''), '-', 1) = $1
              OR regexp_replace(COALESCE(kd.title, ''), '\\D', '', 'g') = $1
          )
        GROUP BY kd.id
        ORDER BY kd.updated_at DESC
        LIMIT 1
        """,
        number,
    )
    result = _bounded_document(row)
    if not result["found"]:
        result["service_order_number"] = number
    return result


async def get_knowledge_document(identifier: str) -> dict[str, Any]:
    value = identifier.strip()
    row = await _fetchrow(
        """
        SELECT kd.id, kd.title, kd.source_uri, kd.canonical_path, kd.status,
               kd.manufacturer, kd.model, kd.category, kd.document_type,
               kd.metadata, kd.updated_at,
               COUNT(kc.id)::int AS chunk_count,
               string_agg(kc.text, E'\n' ORDER BY kc.chunk_index) AS indexed_text
        FROM knowledge_documents kd
        LEFT JOIN knowledge_chunks kc ON kc.document_id = kd.id
        WHERE kd.status <> 'deleted'
          AND (
              kd.id::text = $1
              OR lower(COALESCE(kd.title, '')) = lower($1)
              OR kd.source_uri = $1
              OR kd.canonical_path = $1
          )
        GROUP BY kd.id
        ORDER BY kd.updated_at DESC
        LIMIT 1
        """,
        value,
    )
    result = _bounded_document(row)
    if not result["found"]:
        result["identifier"] = value
    return result


_SEARCH_SCOPES = {
    "knowledge",
    "measurements",
    "diagnoses",
    "knowledge_units",
}


async def _search_knowledge(query: str, limit: int) -> list[dict[str, Any]]:
    return await _fetch(
        """
        SELECT 'knowledge' AS scope, kd.id, kd.document_type AS kind,
               kd.title AS label, kd.source_uri,
               left(COALESCE(kc.text, kd.metadata::text), 1200) AS excerpt,
               kc.chunk_index, kd.updated_at
        FROM knowledge_documents kd
        LEFT JOIN knowledge_chunks kc ON kc.document_id = kd.id
        WHERE kd.status <> 'deleted'
          AND concat_ws(' ', kd.id::text, kd.title, kd.source_uri,
                        kd.canonical_path, kd.manufacturer, kd.model,
                        kd.category, kd.document_type, kd.metadata::text,
                        kc.text) ILIKE '%' || $1 || '%'
        ORDER BY CASE
                     WHEN lower(COALESCE(kd.title, '')) = lower($1) THEN 0
                     WHEN kd.metadata::text ILIKE '%' || $1 || '%' THEN 1
                     ELSE 2
                 END,
                 kd.updated_at DESC, kc.chunk_index
        LIMIT $2
        """,
        query,
        limit,
    )


async def _search_measurements(query: str, limit: int) -> list[dict[str, Any]]:
    return await _fetch(
        """
        SELECT 'measurements' AS scope, id, 'measurement_session' AS kind,
               COALESCE(NULLIF(source_session_id, ''), id::text) AS label,
               left(concat_ws(' ', fabricante, modelo, numero_serie,
                              tipo_coleta, observacoes, diagnostic::text), 1200) AS excerpt,
               status, updated_at
        FROM measurement_sessions
        WHERE concat_ws(' ', id::text, source_session_id, capture_session_id::text,
                        fabricante, modelo, numero_serie, tipo_coleta,
                        observacoes, diagnostic::text) ILIKE '%' || $1 || '%'
        ORDER BY updated_at DESC
        LIMIT $2
        """,
        query,
        limit,
    )


async def _search_diagnoses(query: str, limit: int) -> list[dict[str, Any]]:
    return await _fetch(
        """
        SELECT 'diagnoses' AS scope, id, 'diagnosis' AS kind,
               id::text AS label,
               left(concat_ws(' ', context::text, evidence_set::text,
                              result_payload::text, error_message), 1200) AS excerpt,
               status, last_attempt_at AS updated_at
        FROM diagnosis_queue
        WHERE concat_ws(' ', id::text, capture_session_id::text, instance_id::text,
                        context::text, evidence_set::text, result_payload::text,
                        error_message) ILIKE '%' || $1 || '%'
        ORDER BY queued_at DESC
        LIMIT $2
        """,
        query,
        limit,
    )


async def _search_knowledge_units(query: str, limit: int) -> list[dict[str, Any]]:
    return await _fetch(
        """
        SELECT 'knowledge_units' AS scope, id, knowledge_level AS kind,
               title AS label, left(statement, 1200) AS excerpt,
               confidence, created_at AS updated_at
        FROM knowledge_units
        WHERE concat_ws(' ', id::text, title, statement,
                        knowledge_level) ILIKE '%' || $1 || '%'
        ORDER BY confidence DESC, created_at DESC
        LIMIT $2
        """,
        query,
        limit,
    )


async def search_database(
    query: str,
    scopes: list[str] | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    value = query.strip()
    if not value:
        raise ValueError("query is required")
    selected = set(scopes or _SEARCH_SCOPES)
    invalid = selected - _SEARCH_SCOPES
    if invalid:
        raise ValueError(f"invalid search scopes: {', '.join(sorted(invalid))}")
    bounded_limit = max(1, min(int(limit), 25))
    handlers = {
        "knowledge": _search_knowledge,
        "measurements": _search_measurements,
        "diagnoses": _search_diagnoses,
        "knowledge_units": _search_knowledge_units,
    }
    ordered_scopes = [scope for scope in handlers if scope in selected]
    per_scope_limit = max(1, (bounded_limit + len(ordered_scopes) - 1) // len(ordered_scopes))
    batches = await asyncio.gather(
        *(handlers[scope](value, per_scope_limit) for scope in ordered_scopes)
    )
    items: list[dict[str, Any]] = []
    for index in range(per_scope_limit):
        for batch in batches:
            if index < len(batch):
                items.append(batch[index])
    items = items[:bounded_limit]
    return {
        "query": value,
        "searched_scopes": ordered_scopes,
        "items": items,
        "count": len(items),
    }


async def database_inventory() -> dict[str, Any]:
    row = await _fetchrow(
        """
        SELECT
            (SELECT COUNT(*)::int FROM knowledge_documents
             WHERE status <> 'deleted') AS knowledge_documents,
            (SELECT COUNT(*)::int FROM knowledge_chunks kc
             JOIN knowledge_documents kd ON kd.id = kc.document_id
             WHERE kd.status <> 'deleted') AS knowledge_chunks,
            (SELECT COUNT(*)::int FROM measurement_sessions) AS measurement_sessions,
            (SELECT COUNT(*)::int FROM capture_sessions) AS capture_sessions,
            (SELECT COUNT(*)::int FROM diagnosis_queue) AS diagnoses,
            (SELECT COUNT(*)::int FROM knowledge_units
             WHERE superseded_by IS NULL) AS active_knowledge_units
        """
    )
    document_types = await _fetch(
        """
        SELECT COALESCE(document_type, 'unknown') AS document_type,
               COUNT(*)::int AS count
        FROM knowledge_documents
        WHERE status <> 'deleted'
        GROUP BY document_type
        ORDER BY count DESC, document_type
        """
    )
    diagnosis_statuses = await _fetch(
        """
        SELECT status, COUNT(*)::int AS count
        FROM diagnosis_queue
        GROUP BY status
        ORDER BY status
        """
    )
    return {
        "counts": row or {},
        "document_types": document_types,
        "diagnosis_statuses": diagnosis_statuses,
    }


async def get_measurement_session(identifier: str) -> dict[str, Any]:
    row = await _fetchrow(
        """
        SELECT id, source_session_id, capture_session_id, status,
               fabricante, modelo, numero_serie,
               tipo_coleta, observacoes, total_snapshots, valid_snapshots,
               invalid_snapshots, diagnostic, created_at, updated_at
        FROM measurement_sessions
        WHERE id::text = $1 OR source_session_id = $1
           OR numero_serie = $1 OR observacoes ILIKE '%' || $1 || '%'
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        identifier.strip(),
    )
    if row is None:
        return {"found": False, "identifier": identifier}
    projection = None
    if row.get("capture_session_id"):
        projection = await _fetchrow(
            """
            SELECT COUNT(*)::int AS projected_snapshots,
                   MAX(projected_at) AS last_projected_at
            FROM measurement_snapshot_projections
            WHERE capture_session_id = $1
            """,
            row["capture_session_id"],
        )
    return {"found": True, "session": row, "projection": projection or {}}


async def get_diagnosis(
    correlation_id: str = "",
    capture_session_id: str = "",
) -> dict[str, Any]:
    if not correlation_id.strip() and not capture_session_id.strip():
        raise ValueError("correlation_id or capture_session_id is required")
    row = await _fetchrow(
        """
        SELECT id AS correlation_id, capture_session_id, instance_id, domain_id,
               status, attempts, queued_at, last_attempt_at,
               CASE WHEN status = 'completed' THEN last_attempt_at END AS completed_at,
               error_message,
               callback_status, callback_attempts, result_payload, context
        FROM diagnosis_queue
        WHERE ($1 <> '' AND id::text = $1)
           OR ($2 <> '' AND capture_session_id::text = $2)
        ORDER BY queued_at DESC
        LIMIT 1
        """,
        correlation_id.strip(),
        capture_session_id.strip(),
    )
    return {"found": row is not None, "diagnosis": row or {}}


async def get_capture_evidence(
    capture_session_id: str,
    limit: int = 50,
) -> dict[str, Any]:
    rows = await _fetch(
        """
        SELECT es.id, es.timestamp_us, es.profile_label, es.valid, es.rpm,
               es.motor_current_ma, es.voltage_mv, es.bemf_v,
               es.winding_resistance_mohm,
               sd.bemf_error_permille, sd.winding_resistance_error_permille,
               sd.rpm_error_permille, sd.electrical_power_error_permille
        FROM electromechanical_signatures_default es
        LEFT JOIN signature_deviations sd ON sd.signature_id = es.id
        WHERE es.capture_session_id::text = $1
        ORDER BY es.timestamp_us DESC
        LIMIT $2
        """,
        capture_session_id.strip(),
        max(1, min(int(limit), 200)),
    )
    relation_rows = await _fetch(
        CORRELATION_TIMELINE_QUERY, capture_session_id.strip(),
        max(1, min(int(limit) * 20, 5000)),
    )
    modes = summarize_persisted_relations(relation_rows)
    return {
        "capture_session_id": capture_session_id,
        "items": rows,
        "count": len(rows),
        "relations": relation_rows,
        "relation_count": len(relation_rows),
        "diagnostic_modes": modes,
    }


HANDLERS = {
    "count_service_orders": count_service_orders,
    "list_service_orders": list_service_orders,
    "get_service_order": get_service_order,
    "get_knowledge_document": get_knowledge_document,
    "search_database": search_database,
    "database_inventory": database_inventory,
    "get_measurement_session": get_measurement_session,
    "get_diagnosis": get_diagnosis,
    "get_capture_evidence": get_capture_evidence,
}


async def invoke_tool(name: str, arguments: dict[str, Any] | None = None) -> str:
    handler = HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"unknown tool: {name}")
    async with asyncio.timeout(5.0):
        result = await handler(**(arguments or {}))
    return json.dumps(result, ensure_ascii=False, default=str)


@server.list_tools()
async def _list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def _call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        text = await invoke_tool(name, arguments)
    except Exception as exc:
        text = json.dumps(
            {"error": type(exc).__name__, "detail": str(exc)},
            ensure_ascii=False,
        )
    return [TextContent(type="text", text=text)]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
