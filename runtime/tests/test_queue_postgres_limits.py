"""Real concurrent admission/claim tests; refuses any non-disposable database."""
import asyncio
import os
import re
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import uuid4
import httpx
import pytest
from fastapi import FastAPI
from runtime.diagnosis.routes import create_diagnosis_router
from runtime.diagnosis.worker import DiagnosisWorker

DSN = os.getenv('OPENTRACY_SECURITY_TEST_DSN')
pytestmark = pytest.mark.skipif(not DSN, reason='Explicit disposable PostgreSQL test database required')


def test_real_postgres_admission_and_worker_limits(monkeypatch):
    monkeypatch.setenv('OPENTRACY_DIAGNOSIS_QUEUE_CAPACITY', '3')
    asyncio.run(exercise())


async def exercise():
    import asyncpg
    assert re.fullmatch(r'opentracy_security_test_[a-f0-9]{16}',urlsplit(DSN).path.lstrip('/'))
    pool=await asyncpg.create_pool(DSN,min_size=1,max_size=8)
    try:
        async with pool.acquire() as conn:
            assert not await conn.fetchval("SELECT to_regclass('public.diagnosis_queue') IS NOT NULL")
            await conn.execute("""
                CREATE TABLE entities(id uuid PRIMARY KEY,domain_id uuid);
                CREATE TABLE instances(id uuid PRIMARY KEY,entity_id uuid);
                CREATE TABLE knowledge_documents(id uuid PRIMARY KEY,document_type text,status text,metadata jsonb);
                CREATE TABLE capture_sessions(id uuid PRIMARY KEY,instance_id uuid,service_order_document_id uuid);
                CREATE TABLE diagnosis_queue(id uuid PRIMARY KEY,capture_session_id uuid,instance_id uuid,domain_id uuid,
                  callback_endpoint text,priority text,evidence_set jsonb,context jsonb,request_payload jsonb,
                  queued_at timestamptz,status text,attempts integer DEFAULT 0,last_attempt_at timestamptz,
                  error_message text,result_payload jsonb,callback_status text DEFAULT 'pending',callback_attempts integer DEFAULT 0,
                  callback_last_attempt_at timestamptz,callback_next_attempt_at timestamptz,callback_error text);
            """)
            entity,instance,capture,domain=[uuid4() for _ in range(4)]
            await conn.execute('INSERT INTO entities VALUES($1,$2)',entity,domain)
            await conn.execute('INSERT INTO instances VALUES($1,$2)',instance,entity)
            await conn.execute('INSERT INTO capture_sessions(id,instance_id) VALUES($1,$2)',capture,instance)
        repo=SimpleNamespace(_pool=pool)
        app=FastAPI();app.include_router(create_diagnosis_router(repository=repo))
        payloads=[dict(correlation_id=str(uuid4()),capture_session_id=str(capture),instance_id=str(instance),
                       domain_id=str(domain),delivery_mode='polling') for _ in range(12)]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            responses=await asyncio.gather(*(client.post('/v3/diagnosis',json=p) for p in payloads))
            assert [r.status_code for r in responses].count(202)==3
            assert [r.status_code for r in responses].count(429)==9
            winner=next(p for p,r in zip(payloads,responses) if r.status_code==202)
            repeated=await client.post('/v3/diagnosis',json=winner)
            assert repeated.status_code==202
            async with pool.acquire() as conn:
                assert await conn.fetchval('SELECT count(*) FROM diagnosis_queue')==3
                failed=uuid4()
                await conn.execute("INSERT INTO diagnosis_queue(id,status) VALUES($1,'failed')",failed)
            response=await client.post('/v3/diagnosis/'+str(failed)+'/retry')
            assert response.status_code==429
        workers=[DiagnosisWorker(repo,None,max_concurrent=2) for _ in range(2)]
        async def blocked(row):await asyncio.Event().wait()
        for worker in workers:worker._process_one=blocked
        await asyncio.gather(*(w._process_pending() for w in workers))
        assert sum(len(w._jobs) for w in workers)==2
        async with pool.acquire() as conn:
            assert await conn.fetchval("SELECT count(*) FROM diagnosis_queue WHERE status='processing'")==2
            assert await conn.fetchval("SELECT count(*) FROM diagnosis_queue WHERE status='pending'")==1
        await asyncio.gather(*(w.stop() for w in workers))
        async with pool.acquire() as conn:
            assert await conn.fetchval("SELECT count(*) FROM diagnosis_queue WHERE status='processing'")==0
            assert await conn.fetchval("SELECT count(*) FROM diagnosis_queue WHERE status='pending'")==3
            ids=await conn.fetch("SELECT id FROM diagnosis_queue WHERE status='pending' ORDER BY id LIMIT 2")
            for attempts,row in zip((8,7),ids):
                await conn.execute("UPDATE diagnosis_queue SET status='completed',result_payload='{}',callback_status='failed',callback_attempts=$2 WHERE id=$1",row['id'],attempts)
        delivered=[]
        async def send(item_id,result):delivered.append(item_id)
        workers[0]._send_callback=send
        await workers[0]._process_callback_outbox()
        assert delivered==[ids[1]['id']]
        async with pool.acquire() as conn:
            assert await conn.fetchval('SELECT callback_status FROM diagnosis_queue WHERE id=$1',ids[0]['id'])=='failed'
            assert await conn.fetchval('SELECT callback_attempts FROM diagnosis_queue WHERE id=$1',ids[0]['id'])==8
            assert await conn.fetchval('SELECT callback_status FROM diagnosis_queue WHERE id=$1',ids[1]['id'])=='delivered'

    finally:
        await pool.close()
