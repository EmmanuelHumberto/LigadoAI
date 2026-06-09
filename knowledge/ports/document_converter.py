"""Document converter contract."""

from __future__ import annotations

from typing import Protocol

from knowledge.domain import ConvertedDocument


class DocumentConverter(Protocol):
    async def convert(self, source_uri: str) -> ConvertedDocument:
        ...
