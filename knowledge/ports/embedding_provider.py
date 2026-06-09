"""Embedding provider contract."""

from __future__ import annotations

from typing import Protocol


class EmbeddingProvider(Protocol):
    @property
    def model_name(self) -> str:
        ...

    @property
    def dimension(self) -> int:
        ...

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...
