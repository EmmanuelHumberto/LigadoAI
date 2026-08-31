"""PostgreSQL semantic + lexical search adapter for the knowledge vertical.

Uses pgvector for semantic search (cosine similarity via embedding_vec <=> query_embedding).
Falls back to lexical ILIKE search when embeddings are not yet populated or pgvector
is unavailable.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import asyncpg

from knowledge.domain import KnowledgeSearchResult

logger = logging.getLogger("knowledge.search")

_FILTER_COLUMNS = {
    "manufacturer": "d.manufacturer",
    "model": "d.model",
    "category": "d.category",
    "document_type": "d.document_type",
    "source_uri": "d.source_uri",
    "title": "d.title",
}

# ── Embedder (loaded once) ──────────────────────────────────────────────

_EMBEDDER: Any = None
_EMBEDDER_DIM: int = 384


def _get_embedder():
    global _EMBEDDER, _EMBEDDER_DIM
    if _EMBEDDER is not None:
        return _EMBEDDER, _EMBEDDER_DIM
    try:
        from sentence_transformers import SentenceTransformer

        model_name = "intfloat/multilingual-e5-base"
        _EMBEDDER = SentenceTransformer(model_name)
        get_dimension = getattr(_EMBEDDER, "get_embedding_dimension", None)
        if get_dimension is None:
            get_dimension = _EMBEDDER.get_sentence_embedding_dimension
        _EMBEDDER_DIM = get_dimension() or 384
        logger.info("Embedder loaded: %s (dim=%d)", model_name, _EMBEDDER_DIM)
        return _EMBEDDER, _EMBEDDER_DIM
    except Exception as e:
        logger.warning("Failed to load embedder (%s) — falling back to lexical search", e)
        return None, 0


def _embed_query(query: str) -> list[float] | None:
    model, _ = _get_embedder()
    if model is None:
        return None
    try:
        # E5 prefix: "query: " for asymmetric retrieval
        embedding = model.encode(f"query: {query}", normalize_embeddings=True)
        return embedding.tolist()
    except Exception as e:
        logger.warning("Embedding generation failed: %s", e)
        return None


# ── Public search interface ─────────────────────────────────────────────


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
        if not query or not _terms(query):
            return []

        # Try semantic search first (pgvector)
        embedding = _embed_query(query)
        if embedding is not None:
            results = await self._semantic_search(embedding, query, top_k, filters)
            if results:
                return results
            logger.info("Semantic search returned 0 results — falling back to lexical")

        # Fallback: lexical search
        return await self._lexical_search(query, top_k, filters)

    async def _semantic_search(
        self,
        embedding: list[float],
        query: str,
        top_k: int,
        filters: dict[str, str] | None,
    ) -> list[KnowledgeSearchResult]:
        where_parts = ["d.status <> 'deleted'", "ke.embedding_vec IS NOT NULL"]
        vec_str = "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"
        params: list[Any] = [vec_str, max(1, min(top_k, 50))]

        if filters:
            for key, value in filters.items():
                column = _FILTER_COLUMNS.get(key)
                if column is None:
                    continue
                params.append(value)
                where_parts.append(f"lower({column}) = lower(${len(params)})")

        where_sql = " AND ".join(where_parts)
        sql = f"""
            SELECT
                c.id AS chunk_id,
                d.id AS document_id,
                c.text,
                d.source_uri,
                c.metadata AS chunk_metadata,
                d.manufacturer,
                d.model,
                d.category,
                d.document_type,
                (1.0 - (ke.embedding_vec <=> $1::vector))::float8 AS score
            FROM knowledge_chunks c
            JOIN knowledge_documents d ON d.id = c.document_id
            JOIN knowledge_embeddings ke ON ke.chunk_id = c.id
            WHERE {where_sql}
            ORDER BY ke.embedding_vec <=> $1::vector ASC
            LIMIT ${len(params)}
        """

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [_result_from_row(row) for row in rows]

    async def _lexical_search(
        self,
        query: str,
        top_k: int,
        filters: dict[str, str] | None,
    ) -> list[KnowledgeSearchResult]:
        terms = _terms(query)
        if not terms:
            return []

        sql, params = _build_lexical_query(terms, top_k=top_k, filters=filters or {})
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [_result_from_row(row) for row in rows]


# ── Lexical fallback ───────────────────────────────────────────────────


def _build_lexical_query(
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
