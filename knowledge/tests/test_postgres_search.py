import asyncio
from uuid import uuid4

from knowledge.infrastructure.postgres.search import PostgresKnowledgeSearch


class _AcquireContext:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def __init__(self, rows):
        self.conn = _FakeConnection(rows)

    def acquire(self):
        return _AcquireContext(self.conn)


class _FakeConnection:
    def __init__(self, rows):
        self.rows = rows
        self.sql = ""
        self.params = ()

    async def fetch(self, sql, *params):
        self.sql = sql
        self.params = params
        return self.rows


def test_postgres_search_builds_lexical_query_with_filters():
    asyncio.run(_test_postgres_search_builds_lexical_query_with_filters())


async def _test_postgres_search_builds_lexical_query_with_filters():
    chunk_id = uuid4()
    document_id = uuid4()
    pool = _FakePool(
        [
            {
                "chunk_id": chunk_id,
                "document_id": document_id,
                "score": 3.5,
                "text": "Motor brushless Faulhaber 2616",
                "source_uri": "/docs/faulhaber-2616.md",
                "chunk_metadata": {"page": 1},
                "manufacturer": "Faulhaber",
                "model": "2616",
                "category": "motor",
                "document_type": "datasheet",
            }
        ]
    )

    results = await PostgresKnowledgeSearch(pool).search(
        "Faulhaber 2616 brushless Faulhaber",
        top_k=5,
        filters={"manufacturer": "Faulhaber", "ignored": "value"},
    )

    assert len(results) == 1
    assert results[0].chunk_id == chunk_id
    assert results[0].document_id == document_id
    assert results[0].metadata["page"] == 1
    assert results[0].metadata["manufacturer"] == "Faulhaber"
    assert "d.status <> 'deleted'" in pool.conn.sql
    assert "lower(d.manufacturer)" in pool.conn.sql
    assert "ignored" not in pool.conn.sql
    assert pool.conn.params[-2:] == ("Faulhaber", 5)
    assert pool.conn.params.count("%faulhaber%") == 1


def test_postgres_search_ignores_empty_query():
    asyncio.run(_test_postgres_search_ignores_empty_query())


async def _test_postgres_search_ignores_empty_query():
    pool = _FakePool([])

    results = await PostgresKnowledgeSearch(pool).search("de 26")

    assert results == []
    assert pool.conn.sql == ""
