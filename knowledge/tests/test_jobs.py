import asyncio

from knowledge.application import CreateKnowledgeJob, CreateKnowledgeJobCommand
from knowledge.domain import JobStatus, KnowledgeMetadata
from knowledge.infrastructure.memory import (
    InMemoryKnowledgeJobRepository,
    InMemoryKnowledgeQueue,
)


def test_create_job_enqueues_new_job():
    asyncio.run(_test_create_job_enqueues_new_job())


async def _test_create_job_enqueues_new_job():
    repo = InMemoryKnowledgeJobRepository()
    queue = InMemoryKnowledgeQueue()
    use_case = CreateKnowledgeJob(repo, queue)

    job = await use_case.execute(
        CreateKnowledgeJobCommand(
            source_uri="/docs/faulhaber-2616.pdf",
            content_hash="abc",
            metadata=KnowledgeMetadata(
                manufacturer="Faulhaber",
                model="2616",
                category="brushless",
                document_type="datasheet",
            ),
        )
    )

    assert job.status == JobStatus.QUEUED
    assert job.metadata["manufacturer"] == "Faulhaber"
    assert queue.enqueued == [job]


def test_create_job_returns_duplicate_for_active_same_idempotency_key():
    asyncio.run(_test_create_job_returns_duplicate_for_active_same_idempotency_key())


async def _test_create_job_returns_duplicate_for_active_same_idempotency_key():
    repo = InMemoryKnowledgeJobRepository()
    queue = InMemoryKnowledgeQueue()
    use_case = CreateKnowledgeJob(repo, queue)
    command = CreateKnowledgeJobCommand(
        source_uri="/docs/faulhaber-2616.pdf",
        content_hash="abc",
    )

    first = await use_case.execute(command)
    second = await use_case.execute(command)

    assert first.status == JobStatus.QUEUED
    assert second.status == JobStatus.DUPLICATE
    assert second.metadata["duplicate_of"] == str(first.id)
    assert queue.enqueued == [first]
