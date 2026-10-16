"""Canonical identity and enqueue SQL, using only connection-local temporary tables.

Opt in with OPENTRACY_RUN_DB_TESTS=1 and OPENTRACY_KNOWLEDGE_DATABASE_URL.
No persistent schema or customer record is modified.
"""
import os
from types import SimpleNamespace
from uuid import uuid4

import asyncpg
import httpx
import pytest
from fastapi import FastAPI
from knowledge.infrastructure.postgres.cous_repository import (
    CousKnowledgeRepository, ServiceOrderNotFoundError, ServiceOrderSerialMismatchError,
)
from runtime.diagnosis.routes import create_diagnosis_router


@pytest.fixture
def anyio_backend():
    return "asyncio"


class BorrowConnection:
    def __init__(self, connection): self.connection = connection
    async def __aenter__(self): return self.connection
    async def __aexit__(self, *_): return False


@pytest.mark.anyio
@pytest.mark.skipif(os.getenv("OPENTRACY_RUN_DB_TESTS") != "1", reason="opt-in temporary PostgreSQL tables")
async def test_scoped_resolution_and_idempotent_enqueue_in_postgres():
    conn = await asyncpg.connect(os.environ["OPENTRACY_KNOWLEDGE_DATABASE_URL"])
    try:
        # Fail closed: unqualified names can only resolve in this session's temp schema.
        await conn.execute("SET search_path TO pg_temp")
        await conn.execute("""
            CREATE TEMP TABLE domains (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text UNIQUE, version text, status text);
            CREATE TEMP TABLE knowledge_documents (id uuid PRIMARY KEY, domain_id uuid, metadata jsonb, document_type text,
                source_uri text, manufacturer text, model text, category text, title text, updated_at timestamptz DEFAULT now(), status text DEFAULT 'indexed');
            CREATE TEMP TABLE knowledge_chunks (id uuid DEFAULT gen_random_uuid(), document_id uuid, text text, chunk_index int, metadata jsonb DEFAULT '{}');
            CREATE TEMP TABLE entities (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), domain_id uuid, entity_type text,
                manufacturer text, model text, description text, created_at timestamptz DEFAULT now());
            CREATE TEMP TABLE instances (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), entity_id uuid, serial_number text,
                created_at timestamptz DEFAULT now());
            CREATE TEMP TABLE operational_sessions (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), session_type text, operator_name text, status text);
            CREATE TEMP TABLE capture_sessions (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), operational_session_id uuid,
                instance_id uuid, diagnosis_status text, service_order_document_id uuid, header_observations text);
            CREATE TEMP TABLE diagnosis_queue (id uuid PRIMARY KEY, capture_session_id uuid, instance_id uuid, domain_id uuid,
                callback_endpoint text, priority text, evidence_set jsonb, context jsonb, request_payload jsonb,
                queued_at timestamptz, status text, result_payload jsonb, error_message text, last_attempt_at timestamptz,
                callback_status text, callback_next_attempt_at timestamptz, callback_error text);
        """)
        import json
        org_a, org_b, order_a, order_b, doc_a, doc_b = [uuid4() for _ in range(6)]
        scope_a = {"source_system": "systemos", "organization_id": str(org_a), "service_order_id": str(order_a)}
        scope_b = {"source_system": "systemos", "organization_id": str(org_b), "service_order_id": str(order_b)}
        for doc, scope, serial in [(doc_a, scope_a, "SN-A"), (doc_b, scope_b, "SN-B")]:
            await conn.execute("INSERT INTO knowledge_documents(id, metadata, document_type, title) VALUES($1,$2::jsonb,'service_order','1141_maintenance')",
                doc, json.dumps({"extra": {**scope, "service_order_number": "1141", "equipment_serial": serial}}))
        await conn.execute("UPDATE knowledge_documents SET metadata = metadata || '{\"retrieval_eligible\":false}'::jsonb WHERE id=$1", doc_b)
        for doc in [doc_a, doc_b]:
            await conn.execute("INSERT INTO knowledge_chunks(document_id,text,chunk_index) VALUES($1,'PRIVATE_SEARCH_FIXTURE',0)", doc)
        from knowledge.infrastructure.postgres.search import PostgresKnowledgeSearch
        search = PostgresKnowledgeSearch(SimpleNamespace(acquire=lambda: BorrowConnection(conn)))
        hits = await search._lexical_search("PRIVATE_SEARCH_FIXTURE", 10, None)
        assert {hit.document_id for hit in hits} == {doc_a}
        repo = CousKnowledgeRepository(SimpleNamespace(acquire=lambda: BorrowConnection(conn)))
        base = dict(domain_name="tattoo_machines", manufacturer="TEST", model="TEST", service_order_number="1141")
        ids = await repo.resolve_capture_identity(**base, serial_number="SN-A", service_order_scope=scope_a)
        assert ids["service_order_document_id"] == doc_a
        capture_request = uuid4()
        repeated = await repo.resolve_capture_identity(**base, serial_number="SN-A", service_order_scope=scope_a,
            service_order_document_id=doc_a, capture_request_id=capture_request)
        again = await repo.resolve_capture_identity(**base, serial_number="SN-A", service_order_scope=scope_a,
            service_order_document_id=doc_a, capture_request_id=capture_request)
        assert repeated == again
        with pytest.raises(ServiceOrderNotFoundError):
            await repo.resolve_capture_identity(**base, serial_number="SN-A", service_order_scope=scope_a,
                service_order_document_id=doc_b)

        other = await repo.resolve_capture_identity(**base, serial_number="SN-B", service_order_scope=scope_b)
        assert other["service_order_document_id"] == doc_b
        with pytest.raises(ServiceOrderNotFoundError):
            await repo.resolve_capture_identity(**base, serial_number="SN-A", service_order_scope={**scope_a, "organization_id": str(uuid4())})
        with pytest.raises(ServiceOrderNotFoundError):
            await repo.resolve_capture_identity(**base, serial_number="SN-A", service_order_scope={**scope_a, "service_order_id": str(uuid4())})
        with pytest.raises(ServiceOrderSerialMismatchError):
            await repo.resolve_capture_identity(**base, serial_number="SN-B", service_order_scope=scope_a)
        assert await conn.fetchval("SELECT count(*) FROM capture_sessions") == 3
        app = FastAPI()
        app.include_router(create_diagnosis_router(repository=repo, auth_token="test-only"))
        payload = {
            "correlation_id": str(uuid4()), "capture_session_id": str(ids["capture_session_id"]),
            "instance_id": str(ids["instance_id"]), "domain_id": str(ids["domain_id"]),
            "delivery_mode": "polling", "service_order_scope": scope_a,
        }
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                headers={"Authorization": "Bearer test-only"}) as client:
            for invalid in [
                {"service_order_scope": scope_b}, {"instance_id": str(other["instance_id"])},
                {"domain_id": str(uuid4())}, {"capture_session_id": str(uuid4())},
            ]:
                assert (await client.post("/v3/diagnosis", json={**payload, **invalid})).status_code == 409
            assert await conn.fetchval("SELECT count(*) FROM diagnosis_queue") == 0
            first = await client.post("/v3/diagnosis", json=payload)
            assert first.status_code == 202, first.text
            from runtime.diagnosis.worker import DiagnosisWorker
            worker = DiagnosisWorker(repository=repo, http_client=client)
            await worker._mark_completed(__import__("uuid").UUID(payload["correlation_id"]), {"hypotheses": []})
            assert await conn.fetchval("SELECT callback_status FROM diagnosis_queue") == "not_required"
            second = await client.post("/v3/diagnosis", json=payload)
            assert second.status_code == 202, second.text
            assert second.json()["status"] == "completed"
            assert second.json()["queued_at"] == first.json()["queued_at"]
            assert await conn.fetchval("SELECT count(*) FROM diagnosis_queue") == 1
            conflict = await client.post("/v3/diagnosis", json={**payload, "context": {"changed": True}})
            assert conflict.status_code == 409
            # Identity resolver must also ignore deleted matching documents.
            await conn.execute("UPDATE knowledge_documents SET status='deleted' WHERE id=$1", doc_a)
            with pytest.raises(ServiceOrderNotFoundError):
                await repo.resolve_capture_identity(**base, serial_number="SN-A", service_order_scope=scope_a)
    finally:
        await conn.close()
