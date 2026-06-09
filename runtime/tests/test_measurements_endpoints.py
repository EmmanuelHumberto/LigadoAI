import asyncio
import os

import httpx

from measurements.runtime import MeasurementsRuntimeConfig, create_default_measurements_router


def _transport_client(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def test_runtime_exposes_measurements_contract():
    asyncio.run(_test_runtime_exposes_measurements_contract())


async def _test_runtime_exposes_measurements_contract():
    from runtime.dotenv import load_env
    from runtime.server import _include_feature_routers, app

    os.environ["OPENTRACY_MEASUREMENTS_BACKEND"] = "memory"
    os.environ["OPENTRACY_MEASUREMENTS_AUTH_TOKEN"] = ""
    os.environ["OPENTRACY_MEASUREMENTS_DATABASE_URL"] = ""
    os.environ["OPENTRACY_KNOWLEDGE_AUTH_TOKEN"] = ""
    load_env()
    _include_feature_routers()

    async with _transport_client(app) as client:
        status = (await client.get("/measurements/status")).json()
        created = (
            await client.post(
                "/measurements/sessions",
                json={
                    "header": {
                        "fabricante": "FK Irons",
                        "modelo": "Flux",
                        "tipo_coleta": "desempenho",
                        "verticais": ["hall"],
                    }
                },
            )
        ).json()
        listed = (await client.get("/measurements/sessions")).json()

    assert status["enabled"] is True
    assert status["backend"] in {"memory", "postgres"}
    assert created["id"]
    assert listed["sessions"]


def test_measurements_postgres_runtime_uses_knowledge_database_url(monkeypatch):
    monkeypatch.setenv("OPENTRACY_MEASUREMENTS_BACKEND", "postgres")
    monkeypatch.delenv("OPENTRACY_MEASUREMENTS_DATABASE_URL", raising=False)
    monkeypatch.setenv("OPENTRACY_KNOWLEDGE_DATABASE_URL", "postgres://local/test")
    monkeypatch.setenv("OPENTRACY_KNOWLEDGE_AUTH_TOKEN", "secret")

    config = MeasurementsRuntimeConfig.from_env()
    router = create_default_measurements_router(config)

    assert config.database_url == "postgres://local/test"
    assert config.auth_token == "secret"
    assert router.routes
