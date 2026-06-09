"""PostgreSQL lexical search adapter for the knowledge vertical."""

from __future__ import annotations

import json
import re
from typing import Any

import asyncpg

from knowledge.domain import KnowledgeSearchResult

_FILTER_COLUMNS = {
    "manufacturer": "d.manufacturer",
    "model": "d.model",
    "category": "d.category",
    "document_type": "d.document_type",
    "source_uri": "d.source_uri",
    "title": "d.title",
}


class PostgresKnowledgeSearch:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def search(
        self,
        query: str,
        *,
        top_k: int = 8,
        filters: dict[str, str] | None = None,
    ) -> list[KnowledgeSearchResult]:
        terms = _terms(query)
        if not terms:
            return []

        sql, params = _build_search_query(terms, top_k=top_k, filters=filters or {})
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [_result_from_row(row) for row in rows]


def _build_search_query(
    terms: list[str],
    *,
    top_k: int,
    filters: dict[str, str],
) -> tuple[str, list[Any]]:
    params: list[Any] = []
    score_parts: list[str] = []
    where_parts = ["d.status <> 'deleted'"]

    for term in terms:
        params.append(f"%{term}%")
        like_param = f"${len(params)}"
        params.append(term)
        exact_param = f"${len(params)}"
        score_parts.append(
            f"""
            CASE WHEN base.search_text ILIKE {like_param} THEN 1.0 ELSE 0 END
            + CASE WHEN lower(base.manufacturer) = lower({exact_param}) THEN 1.0 ELSE 0 END
            + CASE WHEN lower(base.model) = lower({exact_param}) THEN 1.0 ELSE 0 END
            + CASE WHEN lower(base.category) = lower({exact_param}) THEN 0.5 ELSE 0 END
            + CASE WHEN lower(base.document_type) = lower({exact_param}) THEN 0.5 ELSE 0 END
            """
        )

    for key, value in filters.items():
        column = _FILTER_COLUMNS.get(key)
        if column is None:
            continue
        params.append(value)
        where_parts.append(f"lower({column}) = lower(${len(params)})")

    params.append(max(1, min(top_k, 50)))
    limit_param = f"${len(params)}"
    score_sql = " + ".join(score_parts)
    where_sql = " AND ".join(where_parts)

    sql = f"""
        WITH base AS (
            SELECT
                c.id AS chunk_id,
                d.id AS document_id,
                c.text,
                c.metadata AS chunk_metadata,
                d.source_uri,
                d.manufacturer,
                d.model,
                d.category,
                d.document_type,
                concat_ws(
                    ' ',
                    c.text,
                    d.source_uri,
                    d.title,
                    d.manufacturer,
                    d.model,
                    d.category,
                    d.document_type
                ) AS search_text
            FROM knowledge_chunks c
            JOIN knowledge_documents d ON d.id = c.document_id
            WHERE {where_sql}
        )
        SELECT
            chunk_id,
            document_id,
            text,
            source_uri,
            chunk_metadata,
            manufacturer,
            model,
            category,
            document_type,
            ({score_sql})::float8 AS score
        FROM base
        WHERE ({score_sql}) > 0
        ORDER BY score DESC, chunk_id ASC
        LIMIT {limit_param}
    """
    return sql, params


def _terms(query: str) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for term in re.findall(r"[\w.-]+", query.lower()):
        if len(term) < 3:
            continue
        if term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms


def _result_from_row(row: asyncpg.Record) -> KnowledgeSearchResult:
    metadata = _json_dict(row["chunk_metadata"])
    metadata.update(
        {
            "manufacturer": row["manufacturer"],
            "model": row["model"],
            "category": row["category"],
            "document_type": row["document_type"],
        }
    )
    return KnowledgeSearchResult(
        chunk_id=row["chunk_id"],
        document_id=row["document_id"],
        score=float(row["score"]),
        text=row["text"],
        source_uri=row["source_uri"],
        metadata=metadata,
    )


def _json_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        decoded = json.loads(value)
        return decoded if isinstance(decoded, dict) else {}
    return dict(value)
