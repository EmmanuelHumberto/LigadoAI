"""Runtime composition helpers for the knowledge vertical."""

from __future__ import annotations

import os
from dataclasses import dataclass

from fastapi import APIRouter

from knowledge.api.routes import create_knowledge_router
from knowledge.application import CreateKnowledgeJob, IndexKnowledgeJob
from knowledge.infrastructure.chunking import TechnicalTextChunker
from knowledge.infrastructure.conversion import LocalTextDocumentConverter
from knowledge.infrastructure.embeddings import DeterministicFakeEmbeddingProvider
from knowledge.infrastructure.memory import (
    InMemoryKnowledgeJobRepository,
    InMemoryKnowledgeQueue,
    InMemoryKnowledgeRepository,
)
from knowledge.infrastructure.search import InMemoryKnowledgeSearch
from knowledge.infrastructure.validation import BasicContentValidator


@dataclass(frozen=True)
class KnowledgeRuntimeConfig:
    enabled: bool = True
    backend: str = "memory"
    database_url: str | None = None
    auth_token: str | None = None

    @classmethod
    def from_env(cls) -> KnowledgeRuntimeConfig:
        enabled_raw = os.environ.get("OPENTRACY_KNOWLEDGE_ENABLED", "1").strip().lower()
        backend = os.environ.get("OPENTRACY_KNOWLEDGE_BACKEND", "memory").strip().lower()
        database_url = os.environ.get("OPENTRACY_KNOWLEDGE_DATABASE_URL")
        auth_token = os.environ.get("OPENTRACY_KNOWLEDGE_AUTH_TOKEN")
        return cls(
            enabled=enabled_raw not in {"0", "false", "no", "off"},
            backend=backend or "memory",
            database_url=database_url.strip() if database_url else None,
            auth_token=auth_token.strip() if auth_token else None,
        )


def create_default_knowledge_router(
    config: KnowledgeRuntimeConfig | None = None,
) -> APIRouter:
    """Create the runtime knowledge router.

    The default backend is in-memory so the endpoint contract is available
    before PostgreSQL and a durable queue are wired in. Production wiring should
    replace this composition with PostgresKnowledgeRepository plus a durable
    KnowledgeQueue adapter.
    """
    config = config or KnowledgeRuntimeConfig.from_env()
    if not config.enabled:
        return APIRouter()
    if config.backend == "memory":
        return _memory_router(config)
    if config.backend == "postgres":
        return _postgres_router(config)
    raise RuntimeError(
        "unsupported knowledge backend "
        f"{config.backend!r}; expected 'memory' or 'postgres'"
    )


def _memory_router(config: KnowledgeRuntimeConfig) -> APIRouter:
    jobs = InMemoryKnowledgeJobRepository()
    queue = InMemoryKnowledgeQueue()
    repository = InMemoryKnowledgeRepository()
    search = InMemoryKnowledgeSearch(repository)
    converter = LocalTextDocumentConverter()
    validator = BasicContentValidator(min_alpha_ratio=0.05)
    index_worker = _index_worker(
        jobs=jobs,
        repository=repository,
        converter=converter,
        validator=validator,
    )
    return create_knowledge_router(
        create_job=CreateKnowledgeJob(jobs, queue),
        jobs=jobs,
        queue=queue,
        repository=repository,
        index_worker=index_worker,
        search=search,
        converter=converter,
        validator=validator,
        auth_token=config.auth_token,
    )


def _postgres_router(config: KnowledgeRuntimeConfig) -> APIRouter:
    if not config.database_url:
        raise RuntimeError(
            "OPENTRACY_KNOWLEDGE_DATABASE_URL is required when "
            "OPENTRACY_KNOWLEDGE_BACKEND=postgres"
        )
    from knowledge.infrastructure.postgres import LazyPostgresKnowledgeRepository

    repository = LazyPostgresKnowledgeRepository(config.database_url)
    queue = InMemoryKnowledgeQueue()
    converter = LocalTextDocumentConverter()
    validator = BasicContentValidator(min_alpha_ratio=0.05)
    index_worker = _index_worker(
        jobs=repository,
        repository=repository,
        converter=converter,
        validator=validator,
    )
    return create_knowledge_router(
        create_job=CreateKnowledgeJob(repository, queue),
        jobs=repository,
        queue=queue,
        repository=repository,
        index_worker=index_worker,
        search=repository,
        converter=converter,
        validator=validator,
        auth_token=config.auth_token,
    )


def _index_worker(*, jobs, repository, converter, validator) -> IndexKnowledgeJob:
    return IndexKnowledgeJob(
        converter=converter,
        validator=validator,
        chunker=TechnicalTextChunker(),
        embedder=DeterministicFakeEmbeddingProvider(),
        jobs=jobs,
        repository=repository,
    )
