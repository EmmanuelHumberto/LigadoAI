"""Tests for diagnosis runtime composition."""

from __future__ import annotations

import asyncio

import httpx
from fastapi import FastAPI

from runtime.diagnosis import runtime as diagnosis_runtime_module
from runtime.diagnosis.runtime import DiagnosisRuntime, DiagnosisRuntimeConfig


def test_diagnosis_runtime_status_unavailable_without_database():
    asyncio.run(_test_diagnosis_runtime_status_unavailable_without_database())


async def _test_diagnosis_runtime_status_unavailable_without_database():
    runtime = DiagnosisRuntime(
        DiagnosisRuntimeConfig(enabled=True, database_url=None),
    )
    app = FastAPI()
    app.include_router(runtime.router())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/v3/diagnosis/status")

    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"
    assert response.json()["database_configured"] is False


def test_diagnosis_runtime_status_available_with_database_and_worker_disabled():
    asyncio.run(
        _test_diagnosis_runtime_status_available_with_database_and_worker_disabled()
    )


async def _test_diagnosis_runtime_status_available_with_database_and_worker_disabled():
    runtime = DiagnosisRuntime(
        DiagnosisRuntimeConfig(
            enabled=True,
            database_url="postgresql://example/test",
            worker_enabled=False,
        ),
    )
    app = FastAPI()
    app.include_router(runtime.router())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/v3/diagnosis/status")

    assert response.status_code == 200
    assert response.json()["status"] == "available"
    assert response.json()["database_configured"] is True
    assert response.json()["worker_enabled"] is False


def test_diagnosis_runtime_starts_and_stops_worker(monkeypatch):
    asyncio.run(_test_diagnosis_runtime_starts_and_stops_worker(monkeypatch))


async def _test_diagnosis_runtime_starts_and_stops_worker(monkeypatch):
    events: list[str] = []

    class FakeHttpClient:
        async def aclose(self):
            events.append("http_closed")

    class FakeWorker:
        def __init__(self, **kwargs):
            events.append("worker_created")

        async def start(self):
            events.append("worker_started")

        async def stop(self):
            events.append("worker_stopped")

    monkeypatch.setattr(diagnosis_runtime_module.httpx, "AsyncClient", FakeHttpClient)
    monkeypatch.setattr(diagnosis_runtime_module, "DiagnosisWorker", FakeWorker)

    runtime = DiagnosisRuntime(
        DiagnosisRuntimeConfig(
            enabled=True,
            database_url="postgresql://example/test",
            worker_enabled=True,
        ),
    )

    await runtime.start()
    await runtime.stop()

    assert events == [
        "worker_created",
        "worker_started",
        "worker_stopped",
        "http_closed",
    ]
