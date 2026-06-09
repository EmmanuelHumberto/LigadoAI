"""PostgreSQL adapters for the knowledge vertical."""

from knowledge.infrastructure.postgres.lazy import LazyPostgresKnowledgeRepository
from knowledge.infrastructure.postgres.repository import PostgresKnowledgeRepository
from knowledge.infrastructure.postgres.search import PostgresKnowledgeSearch

__all__ = [
    "LazyPostgresKnowledgeRepository",
    "PostgresKnowledgeRepository",
    "PostgresKnowledgeSearch",
]
