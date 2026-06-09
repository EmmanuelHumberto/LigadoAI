"""Text chunker contract."""

from __future__ import annotations

from typing import Protocol


class TextChunker(Protocol):
    def chunk(self, text: str) -> list[str]:
        ...
