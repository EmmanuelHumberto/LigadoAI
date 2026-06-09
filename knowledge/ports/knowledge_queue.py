"""Queue contract for knowledge jobs."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from knowledge.domain import KnowledgeJob


class KnowledgeQueue(Protocol):
    async def enqueue(self, job: KnowledgeJob) -> None:
        ...

    async def request_cancel(self, job_id: UUID) -> None:
        ...
