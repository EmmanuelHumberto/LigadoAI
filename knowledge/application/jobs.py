"""Use cases for creating knowledge jobs."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from knowledge.domain import JobKind, KnowledgeJob, KnowledgeMetadata
from knowledge.ports import KnowledgeJobRepository, KnowledgeQueue


@dataclass(frozen=True)
class CreateKnowledgeJobCommand:
    source_uri: str
    content_hash: str | None = None
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    chunking_strategy: str = "technical_v1"
    metadata: KnowledgeMetadata = field(default_factory=KnowledgeMetadata)
    force: bool = False


class CreateKnowledgeJob:
    """Create an idempotent indexing job and enqueue it.

    This use case deliberately does not perform conversion, embedding, or
    database writes for the document content. Long-running work belongs to a
    worker behind the KnowledgeQueue port.
    """

    def __init__(self, jobs: KnowledgeJobRepository, queue: KnowledgeQueue) -> None:
        self._jobs = jobs
        self._queue = queue

    async def execute(self, command: CreateKnowledgeJobCommand) -> KnowledgeJob:
        key = _idempotency_key(command)
        if not command.force:
            existing = await self._jobs.find_active_by_idempotency_key(key)
            if existing is not None:
                duplicate = KnowledgeJob(
                    kind=JobKind.INDEX_DOCUMENT,
                    source_uri=command.source_uri,
                    idempotency_key=key,
                    metadata=command.metadata.normalized().as_dict(),
                ).mark_duplicate(existing.id)
                return await self._jobs.save_job(duplicate)

        job = KnowledgeJob(
            kind=JobKind.INDEX_DOCUMENT,
            source_uri=command.source_uri,
            idempotency_key=key,
            metadata=command.metadata.normalized().as_dict(),
        )
        saved = await self._jobs.save_job(job)
        await self._queue.enqueue(saved)
        return saved


def _idempotency_key(command: CreateKnowledgeJobCommand) -> str:
    parts: list[str] = [
        command.source_uri.strip(),
        command.content_hash or "",
        command.embedding_model,
        command.chunking_strategy,
    ]
    metadata: dict[str, Any] = command.metadata.normalized().as_dict()
    for key in sorted(metadata):
        parts.append(f"{key}={metadata[key]}")
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
