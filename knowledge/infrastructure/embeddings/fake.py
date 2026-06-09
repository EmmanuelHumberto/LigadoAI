"""Deterministic fake embeddings for tests and local wiring."""

from __future__ import annotations

import hashlib


class DeterministicFakeEmbeddingProvider:
    model_name = "fake-deterministic"
    dimension = 8

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [_embed(text, self.dimension) for text in texts]


def _embed(text: str, dimension: int) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values: list[float] = []
    for i in range(dimension):
        value = digest[i] / 255.0
        values.append(value)
    return values
