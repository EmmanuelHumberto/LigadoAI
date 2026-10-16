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


class EnqueueConnection(FakeConnection):
    def __init__(self):
        super().__init__()
        self.identity_valid = True
        self.saved = None
        self.inserts = 0

    async def fetchrow(self, query, *args):
        if "FROM capture_sessions" in query:
            return {"id": args[0]} if self.identity_valid else None
        if "INSERT INTO diagnosis_queue" in query:
            if self.saved is not None:
                return None
            self.inserts += 1
            import json
            self.saved = {"request_payload": json.loads(args[8]), "status": "completed", "queued_at": args[9]}
            return {"id": args[0]}
        if "SELECT * FROM diagnosis_queue" in query:
            return self.saved
        return await super().fetchrow(query, *args)


def enqueue_payload():
    return {
        "correlation_id": str(DIAGNOSIS_ID),
        "capture_session_id": "00000000-0000-0000-0000-0000000000c1",
        "instance_id": "00000000-0000-0000-0000-0000000000a1",
        "domain_id": "00000000-0000-0000-0000-0000000000b1",
        "callback_endpoint": "http://127.0.0.1:9999/callback",
    }


@pytest.mark.anyio
async def test_enqueue_rejects_unrelated_capture_before_any_write():
    repo = FakeRepository()
    repo.conn = EnqueueConnection()
    repo.conn.identity_valid = False
    repo._pool = FakePool(repo.conn)
    app = FastAPI()
    app.include_router(create_diagnosis_router(repository=repo))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v3/diagnosis", json=enqueue_payload())
    assert response.status_code == 409
    assert repo.conn.inserts == 0


@pytest.mark.anyio
async def test_equivalent_retry_returns_existing_completed_state_without_requeue():
    repo = FakeRepository()
    repo.conn = EnqueueConnection()
    repo._pool = FakePool(repo.conn)
    app = FastAPI()
    app.include_router(create_diagnosis_router(repository=repo))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/v3/diagnosis", json=enqueue_payload())
        repeated = await client.post("/v3/diagnosis", json=enqueue_payload())
    assert first.status_code == repeated.status_code == 202
    assert repeated.json()["status"] == "completed"
    assert first.json()["queued_at"] == repeated.json()["queued_at"]
    assert repeated.json()["position"] == 0
    assert repo.conn.inserts == 1


@pytest.mark.anyio
@pytest.mark.parametrize("change", [
    {"context": {"different": True}}, {"callback_endpoint": "http://127.0.0.1:9998/other"},
    {"capture_session_id": "00000000-0000-0000-0000-0000000000c2"},
    {"evidence_set": [{"evidence_type": "different"}]},
])
async def test_correlation_cannot_be_reused_for_changed_request(change):
    repo = FakeRepository()
    repo.conn = EnqueueConnection()
    repo._pool = FakePool(repo.conn)
    app = FastAPI()
    app.include_router(create_diagnosis_router(repository=repo))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/v3/diagnosis", json=enqueue_payload())
        response = await client.post("/v3/diagnosis", json={**enqueue_payload(), **change})
    assert response.status_code == 409
    assert repo.conn.inserts == 1


@pytest.mark.anyio
async def test_enqueue_remains_authenticated_when_token_configured():
    repo = FakeRepository()
    app = FastAPI()
    app.include_router(create_diagnosis_router(repository=repo, auth_token="test-only"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v3/diagnosis", json=enqueue_payload(), headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401


@pytest.mark.parametrize("payload", [
    {"delivery_mode": "callback", "callback_endpoint": ""},
    {"delivery_mode": "polling", "callback_endpoint": "http://127.0.0.1:9999/test"},
])
def test_delivery_modes_do_not_silently_fall_back_to_callback(payload):
    from pydantic import ValidationError
    from runtime.diagnosis.routes import DiagnosisRequestSchema
    with pytest.raises(ValidationError):
        DiagnosisRequestSchema(**{**enqueue_payload(), **payload})
