"""Deterministic lexical search over the in-memory knowledge repository."""

from __future__ import annotations

import re

from knowledge.domain import DocumentStatus, KnowledgeDocument, KnowledgeSearchResult
from knowledge.infrastructure.memory import InMemoryKnowledgeRepository


class InMemoryKnowledgeSearch:
    def __init__(self, repository: InMemoryKnowledgeRepository) -> None:
        self._repository = repository

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

        results: list[KnowledgeSearchResult] = []
        filters = filters or {}
        for document_id, chunks in self._repository.chunks.items():
            document = self._repository.documents.get(document_id)
            if document is None or document.status == DocumentStatus.DELETED:
                continue
            if document.metadata.get("retrieval_eligible") is False or document.metadata.get("extra", {}).get("retrieval_eligible") is False:
                continue
            if not _matches_filters(document, filters):
                continue
            for chunk in chunks:
                score = _score(document, chunk.text, terms)
                if score <= 0:
                    continue
                results.append(
                    KnowledgeSearchResult(
                        chunk_id=chunk.id,
                        document_id=document.id,
                        score=score,
                        text=chunk.text,
                        source_uri=document.source_uri,
                        metadata={
                            **chunk.metadata,
                            "manufacturer": document.manufacturer,
                            "model": document.model,
                            "category": document.category,
                            "document_type": document.document_type,
                        },
                    )
                )

        results.sort(key=lambda result: result.score, reverse=True)
        return results[:top_k]


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


def _matches_filters(document: KnowledgeDocument, filters: dict[str, str]) -> bool:
    for key, expected in filters.items():
        value = getattr(document, key, None)
        if value is None:
            return False
        if str(value).lower() != expected.lower():
            return False
    return True


def _score(document: KnowledgeDocument, text: str, terms: list[str]) -> float:
    haystack_parts = [
        text,
        document.source_uri,
        document.title or "",
        document.manufacturer or "",
        document.model or "",
        document.category or "",
        document.document_type or "",
    ]
    haystack = " ".join(haystack_parts).lower()
    score = 0.0
    for term in terms:
        if term in haystack:
            score += 1.0
        if re.search(rf"\b{re.escape(term)}\b", haystack):
            score += 0.5
        if _metadata_exact(document, term):
            score += 1.0
    return score


def _metadata_exact(document: KnowledgeDocument, term: str) -> bool:
    values: tuple[str | None, ...] = (
        document.manufacturer,
        document.model,
        document.category,
        document.document_type,
    )
    return any(value is not None and value.lower() == term for value in values)
