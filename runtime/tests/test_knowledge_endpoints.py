import asyncio

import httpx
from fastapi import FastAPI

from knowledge.runtime import KnowledgeRuntimeConfig, create_default_knowledge_router


def _transport_client(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _knowledge_app() -> FastAPI:
    app = FastAPI()
    app.include_router(
        create_default_knowledge_router(
            KnowledgeRuntimeConfig(backend="memory", auth_token=None)
        )
    )
    return app


def test_runtime_exposes_knowledge_status():
    asyncio.run(_test_runtime_exposes_knowledge_status())


async def _test_runtime_exposes_knowledge_status():
    app = _knowledge_app()
    async with _transport_client(app) as client:
        response = await client.get("/knowledge/status")

    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"


def test_runtime_exposes_knowledge_index_job_contract(tmp_path):
    asyncio.run(_test_runtime_exposes_knowledge_index_job_contract(tmp_path))


async def _test_runtime_exposes_knowledge_index_job_contract(tmp_path):
    app = _knowledge_app()

    source = tmp_path / "doc.md"
    source.write_text(
        "# Test\n\n"
        "Documento tecnico para indexacao com conteudo suficiente. "
        "Este arquivo descreve parametros de motor, tensao nominal, corrente, "
        "torque, velocidade sem carga, eficiencia e observacoes de uso em bancada. "
        "O texto precisa passar pelo chunker tecnico default do runtime local.",
        encoding="utf-8",
    )
    async with _transport_client(app) as client:
        response = await client.post(
            "/knowledge/index",
            json={"source_uri": str(source), "content_hash": "abc"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["job_id"]
        assert body["status"] == "queued"

        job = (await client.get(f"/knowledge/jobs/{body['job_id']}")).json()
        status = (await client.get("/knowledge/status")).json()
        assert job["status"] == "indexed"
        assert status["status"] == "ready"

        search = await client.post(
            "/knowledge/search",
            json={"query": "motor tensao torque", "top_k": 3},
        )
        assert search.status_code == 200
        assert search.json()["results"]

        documents = await client.get("/knowledge/documents")
        assert documents.status_code == 200
        assert documents.json()["documents"]
