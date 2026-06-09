"""Knowledge search contract."""

from __future__ import annotations

from typing import Protocol

from knowledge.domain import KnowledgeSearchResult


class KnowledgeSearchPort(Protocol):
    async def search(
        self,
        query: str,
        *,
        top_k: int = 8,
        filters: dict[str, str] | None = None,
    ) -> list[KnowledgeSearchResult]:
        ...
