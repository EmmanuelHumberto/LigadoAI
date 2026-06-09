"""Content validator contract."""

from __future__ import annotations

from typing import Protocol

from knowledge.domain import ConvertedDocument, ValidationResult


class ContentValidator(Protocol):
    async def validate(self, document: ConvertedDocument) -> ValidationResult:
        ...
