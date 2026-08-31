"""Tests for COUS diagnosis REST routes."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI

from runtime.diagnosis.routes import create_diagnosis_router

DIAGNOSIS_ID = UUID("00000000-0000-0000-0000-0000000000d1")


class FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return FakeAcquire(self._conn)


class FakeConnection:
    def __init__(self):
        self.row = {
            "id": DIAGNOSIS_ID,
            "status": "processing",
            "attempts": 2,
            "last_attempt_at": datetime(2026, 7, 7, 12, 0, tzinfo=UTC),
            "error_message": None,
            "callback_status": "failed",
            "callback_attempts": 3,
            "callback_error": "ConnectError",
            "result_payload": {
                "correlation_id": str(DIAGNOSIS_ID),
                "hypotheses": [{"description": "Atrito elevado"}],
            },
        }

    async def fetchrow(self, query, *args):
        if "COUNT" in query:
            return {"count": 0}
        return self.row if args and args[0] == DIAGNOSIS_ID else None

    async def fetch(self, query, *args):
        return [self.row]

    async def execute(self, query, *args):
        return "INSERT 0 1"


class FakeRepository:
    def __init__(self):
        self.conn = FakeConnection()
        self._pool = FakePool(self.conn)


@pytest.mark.anyio
async def test_diagnosis_queue_route_is_not_captured_by_uuid_route():
    repo = FakeRepository()
    app = FastAPI()
    app.include_router(create_diagnosis_router(repository=repo))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.get("/v3/diagnosis/queue")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["correlation_id"] == str(DIAGNOSIS_ID)


@pytest.mark.anyio
async def test_diagnosis_status_route_returns_queue_state():
    repo = FakeRepository()
    app = FastAPI()
    app.include_router(create_diagnosis_router(repository=repo))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.get(f"/v3/diagnosis/{DIAGNOSIS_ID}")

    assert response.status_code == 200
    body = response.json()
    assert body["correlation_id"] == str(DIAGNOSIS_ID)
    assert body["status"] == "processing"
    assert body["attempts"] == 2
    assert body["callback_status"] == "failed"
    assert body["callback_attempts"] == 3
    assert body["result"]["hypotheses"][0]["description"] == "Atrito elevado"


@pytest.mark.anyio
async def test_retry_route_requeues_only_failed_diagnosis():
    repo = FakeRepository()
    app = FastAPI()
    app.include_router(create_diagnosis_router(repository=repo))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.post(f"/v3/diagnosis/{DIAGNOSIS_ID}/retry")

    assert response.status_code == 200
    assert response.json() == {
        "correlation_id": str(DIAGNOSIS_ID),
        "status": "pending",
    }
