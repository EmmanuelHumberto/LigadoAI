import asyncio

import httpx
from fastapi import FastAPI

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


def _client() -> tuple[
    FastAPI,
    InMemoryKnowledgeJobRepository,
    InMemoryKnowledgeQueue,
    InMemoryKnowledgeRepository,
]:
    repo = InMemoryKnowledgeJobRepository()
    queue = InMemoryKnowledgeQueue()
    knowledge = InMemoryKnowledgeRepository()
    app = FastAPI()
    app.include_router(
        create_knowledge_router(
            create_job=CreateKnowledgeJob(repo, queue),
            jobs=repo,
            queue=queue,
            repository=knowledge,
            search=InMemoryKnowledgeSearch(knowledge),
        )
    )
    return app, repo, queue, knowledge


def _client_with_worker() -> tuple[
    FastAPI,
    InMemoryKnowledgeJobRepository,
    InMemoryKnowledgeQueue,
    InMemoryKnowledgeRepository,
]:
    repo = InMemoryKnowledgeJobRepository()
    queue = InMemoryKnowledgeQueue()
    knowledge = InMemoryKnowledgeRepository()
    worker = IndexKnowledgeJob(
        jobs=repo,
        repository=knowledge,
        converter=LocalTextDocumentConverter(),
        validator=BasicContentValidator(min_chars=10),
        chunker=TechnicalTextChunker(min_chunk_chars=10),
        embedder=DeterministicFakeEmbeddingProvider(),
    )
    app = FastAPI()
    app.include_router(
        create_knowledge_router(
            create_job=CreateKnowledgeJob(repo, queue),
            jobs=repo,
            queue=queue,
            repository=knowledge,
            index_worker=worker,
            search=InMemoryKnowledgeSearch(knowledge),
            converter=worker._converter,  # noqa: SLF001 - test composition helper
            validator=worker._validator,  # noqa: SLF001 - test composition helper
        )
    )
    return app, repo, queue, knowledge


def _client_with_auth() -> FastAPI:
    repo = InMemoryKnowledgeJobRepository()
    queue = InMemoryKnowledgeQueue()
    knowledge = InMemoryKnowledgeRepository()
    app = FastAPI()
    app.include_router(
        create_knowledge_router(
            create_job=CreateKnowledgeJob(repo, queue),
            jobs=repo,
            queue=queue,
            repository=knowledge,
            search=InMemoryKnowledgeSearch(knowledge),
            auth_token="secret-token",
        )
    )
    return app


def _transport_client(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def test_index_endpoint_returns_processing_job():
    asyncio.run(_test_index_endpoint_returns_processing_job())


async def _test_index_endpoint_returns_processing_job():
    app, _, queue, _ = _client()

    async with _transport_client(app) as client:
        response = await client.post(
            "/knowledge/index",
            json={
                "source_uri": "/docs/faulhaber-2616.pdf",
                "content_hash": "abc",
                "metadata": {"manufacturer": "Faulhaber", "model": "2616"},
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["job_id"]
    assert len(queue.enqueued) == 1


def test_knowledge_auth_rejects_missing_token():
    asyncio.run(_test_knowledge_auth_rejects_missing_token())


async def _test_knowledge_auth_rejects_missing_token():
    app = _client_with_auth()

    async with _transport_client(app) as client:
        response = await client.get("/knowledge/status")

    assert response.status_code == 401
    assert response.json()["detail"] == "missing_authorization"


def test_knowledge_auth_rejects_invalid_token():
    asyncio.run(_test_knowledge_auth_rejects_invalid_token())


async def _test_knowledge_auth_rejects_invalid_token():
    app = _client_with_auth()

    async with _transport_client(app) as client:
        response = await client.get(
            "/knowledge/status",
            headers={"Authorization": "Bearer wrong-token"},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_token"


def test_knowledge_auth_accepts_valid_bearer_token():
    asyncio.run(_test_knowledge_auth_accepts_valid_bearer_token())


async def _test_knowledge_auth_accepts_valid_bearer_token():
    app = _client_with_auth()

    async with _transport_client(app) as client:
        response = await client.get(
            "/knowledge/status",
            headers={"Authorization": "Bearer secret-token"},
        )

    assert response.status_code == 200


def test_get_job_endpoint_returns_job_state():
    asyncio.run(_test_get_job_endpoint_returns_job_state())


async def _test_get_job_endpoint_returns_job_state():
    app, _, _, _ = _client()
    async with _transport_client(app) as client:
        created = (
            await client.post(
                "/knowledge/index",
                json={"source_uri": "/docs/faulhaber-2616.pdf", "content_hash": "abc"},
            )
        ).json()

        response = await client.get(f"/knowledge/jobs/{created['job_id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == created["job_id"]
    assert body["status"] == "queued"


def test_cancel_job_endpoint_marks_cancel_requested():
    asyncio.run(_test_cancel_job_endpoint_marks_cancel_requested())


async def _test_cancel_job_endpoint_marks_cancel_requested():
    app, _, queue, _ = _client()
    async with _transport_client(app) as client:
        created = (
            await client.post(
                "/knowledge/index",
                json={"source_uri": "/docs/faulhaber-2616.pdf", "content_hash": "abc"},
            )
        ).json()

        response = await client.post(f"/knowledge/jobs/{created['job_id']}/cancel")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancel_requested"
    assert queue.cancel_requested


def test_status_endpoint_uses_repository_status():
    asyncio.run(_test_status_endpoint_uses_repository_status())


async def _test_status_endpoint_uses_repository_status():
    app, _, _, _ = _client()
    async with _transport_client(app) as client:
        response = await client.get("/knowledge/status")

    assert response.status_code == 200
    assert response.json() == {
        "status": "unavailable",
        "document_count": 0,
        "chunk_count": 0,
        "corpus_version": None,
    }


def test_index_endpoint_can_schedule_worker_for_text_document(tmp_path):
    asyncio.run(_test_index_endpoint_can_schedule_worker_for_text_document(tmp_path))


async def _test_index_endpoint_can_schedule_worker_for_text_document(tmp_path):
    app, _, _, _ = _client_with_worker()
    source = tmp_path / "doc.md"
    source.write_text(
        "# Faulhaber 2616\n\n"
        "Documento tecnico com conteudo suficiente para validacao. "
        "O motor brushless possui dados de tensao nominal, corrente, "
        "torque, velocidade e observacoes de manutencao preventiva.",
        encoding="utf-8",
    )

    async with _transport_client(app) as client:
        created = (
            await client.post(
                "/knowledge/index",
                json={"source_uri": str(source), "content_hash": "abc"},
            )
        ).json()
        job = (await client.get(f"/knowledge/jobs/{created['job_id']}")).json()
        status = (await client.get("/knowledge/status")).json()

    assert job["status"] == "indexed"
    assert status["status"] == "ready"
    assert status["document_count"] == 1
    assert status["chunk_count"] == 1


def test_search_endpoint_returns_indexed_text_document(tmp_path):
    asyncio.run(_test_search_endpoint_returns_indexed_text_document(tmp_path))


async def _test_search_endpoint_returns_indexed_text_document(tmp_path):
    app, _, _, _ = _client_with_worker()
    source = tmp_path / "faulhaber-2616.md"
    source.write_text(
        "# Faulhaber 2616\n\n"
        "Documento tecnico sobre motor brushless Faulhaber modelo 2616.",
        encoding="utf-8",
    )
    async with _transport_client(app) as client:
        await client.post(
            "/knowledge/index",
            json={
                "source_uri": str(source),
                "content_hash": "abc",
                "metadata": {"manufacturer": "Faulhaber", "model": "2616"},
            },
        )

        response = await client.post(
            "/knowledge/search",
            json={"query": "Faulhaber 2616 brushless", "top_k": 3},
        )

    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 1
    assert results[0]["metadata"]["manufacturer"] == "Faulhaber"
    assert "brushless" in results[0]["text"].lower()


def test_documents_endpoints_list_get_and_soft_delete(tmp_path):
    asyncio.run(_test_documents_endpoints_list_get_and_soft_delete(tmp_path))


async def _test_documents_endpoints_list_get_and_soft_delete(tmp_path):
    app, _, _, _ = _client_with_worker()
    source = tmp_path / "faulhaber-2616.md"
    source.write_text(
        "# Faulhaber 2616\n\n"
        "Documento tecnico sobre motor brushless Faulhaber modelo 2616.",
        encoding="utf-8",
    )
    async with _transport_client(app) as client:
        created = (
            await client.post(
                "/knowledge/index",
                json={
                    "source_uri": str(source),
                    "content_hash": "abc",
                    "metadata": {"manufacturer": "Faulhaber", "model": "2616"},
                },
            )
        ).json()
        job = (await client.get(f"/knowledge/jobs/{created['job_id']}")).json()
        document_id = job["document_id"]

        listed = (await client.get("/knowledge/documents")).json()["documents"]
        fetched = (await client.get(f"/knowledge/documents/{document_id}")).json()

        assert len(listed) == 1
        assert listed[0]["id"] == document_id
        assert fetched["manufacturer"] == "Faulhaber"

        deleted = await client.delete(f"/knowledge/documents/{document_id}")
        listed_after_delete = (await client.get("/knowledge/documents")).json()["documents"]
        listed_with_deleted = (
            await client.get(
                "/knowledge/documents",
                params={"include_deleted": True},
            )
        ).json()["documents"]
        search_after_delete = (
            await client.post(
                "/knowledge/search",
                json={"query": "Faulhaber 2616"},
            )
        ).json()["results"]

    assert deleted.status_code == 204
    assert listed_after_delete == []
    assert listed_with_deleted[0]["status"] == "deleted"
    assert search_after_delete == []


def test_validate_endpoint_approves_supported_document(tmp_path):
    asyncio.run(_test_validate_endpoint_approves_supported_document(tmp_path))


async def _test_validate_endpoint_approves_supported_document(tmp_path):
    app, _, _, _ = _client_with_worker()
    source = tmp_path / "doc.md"
    source.write_text(
        "# Documento valido\n\n"
        "Conteudo tecnico suficiente para validacao com diversas palavras uteis.",
        encoding="utf-8",
    )

    async with _transport_client(app) as client:
        response = await client.post("/knowledge/validate", json={"source_uri": str(source)})

    assert response.status_code == 200
    body = response.json()
    assert body["approved"] is True
    assert body["char_count"] > 40
    assert body["title"] == "Documento valido"


def test_validate_endpoint_rejects_bad_document(tmp_path):
    asyncio.run(_test_validate_endpoint_rejects_bad_document(tmp_path))


async def _test_validate_endpoint_rejects_bad_document(tmp_path):
    app, _, _, _ = _client_with_worker()
    source = tmp_path / "bad.md"
    source.write_text("erro " * 80, encoding="utf-8")

    async with _transport_client(app) as client:
        response = await client.post("/knowledge/validate", json={"source_uri": str(source)})

    assert response.status_code == 200
    body = response.json()
    assert body["approved"] is False
    assert {error["code"] for error in body["errors"]}


def test_validate_endpoint_reports_conversion_failure():
    asyncio.run(_test_validate_endpoint_reports_conversion_failure())


async def _test_validate_endpoint_reports_conversion_failure():
    app, _, _, _ = _client_with_worker()

    async with _transport_client(app) as client:
        response = await client.post(
            "/knowledge/validate",
            json={"source_uri": "/tmp/arquivo-inexistente.md"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["approved"] is False
    assert body["errors"][0]["code"] == "conversion_failed"
