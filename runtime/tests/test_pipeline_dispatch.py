"""Availability, scope propagation and real running-work capacity tests."""
import asyncio
from contextvars import ContextVar
from threading import Event, Lock
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import httpx
import pytest
from fastapi import FastAPI
from runtime.executor.dispatch import PipelineDispatcher, PipelineBusyError


def test_run_keeps_health_and_authenticated_knowledge_responsive(monkeypatch):
    from runtime import server
    from runtime.tenants import quota
    from runtime.executor import dispatch
    from knowledge.runtime import KnowledgeRuntimeConfig, create_default_knowledge_router
    from runtime.security import RuntimeSecurityMiddleware
    entered, release = Event(), Event()
    worker = PipelineDispatcher()
    record = SimpleNamespace(response='synthetic result', duration_ms=1.0, success=True,
                             error=None, agent_version='test', stages=[])
    class Executor:
        def run(self, *args, **kwargs):
            entered.set()
            assert release.wait(5), 'test did not release blocked inference'
            return None, record
    monkeypatch.setattr(dispatch, 'pipeline_dispatcher', worker)
    monkeypatch.setitem(server._state, 'executor', Executor())
    monkeypatch.setattr(server, 'write_trace', lambda *a, **k: 'synthetic-trace')
    for method in ('check_rate_limit', 'check_trace_quota', 'consume_trace'):
        monkeypatch.setattr(quota, method, lambda: None)
    monkeypatch.setenv('OPENTRACY_RUNTIME_SECURITY', 'required')
    monkeypatch.setenv('OPENTRACY_RUNTIME_INTERNAL_TOKEN', 't' * 32)
    app = FastAPI()
    app.add_middleware(RuntimeSecurityMiddleware)
    app.add_api_route('/run', server.run, methods=['POST'])
    @app.get('/health')
    async def health(): return {'status': 'ok'}
    app.include_router(create_default_knowledge_router(KnowledgeRuntimeConfig(backend='memory', auth_token='synthetic-knowledge')))
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            task = asyncio.create_task(client.post('/run', json={'request': 'synthetic'}, headers={'x-opentracy-runtime-key': 't' * 32}))
            try:
                assert await asyncio.to_thread(entered.wait, 2)
                assert not task.done()
                assert (await asyncio.wait_for(client.get('/health'), .5)).status_code == 200
                response = await asyncio.wait_for(client.get('/knowledge/status', headers={'authorization': 'Bearer synthetic-knowledge'}), .5)
                assert response.status_code == 200
                assert (await client.get('/knowledge/status')).status_code == 401
            finally:
                release.set()
                response = await task
            assert response.status_code == 200
            assert response.json()['response'] == 'synthetic result'
            assert response.json()['trace_id'] == 'synthetic-trace'
    try: asyncio.run(exercise())
    finally: release.set(); worker.close()


def test_context_isolation_capacity_and_running_cancellation():
    worker = PipelineDispatcher()
    scope = ContextVar('synthetic_identity', default='no-identity')
    entered, release = Event(), Event()
    observed = []
    def held():
        observed.append(scope.get())
        entered.set()
        assert release.wait(5)
        return scope.get()
    async def exercise():
        scope.set('tenant-a/agent-a')
        first = asyncio.create_task(worker.execute(held))
        assert await asyncio.to_thread(entered.wait, 2)
        scope.set('tenant-b/agent-b')
        second = asyncio.create_task(worker.execute(lambda: scope.get()))
        await asyncio.sleep(0)
        with pytest.raises(PipelineBusyError): await worker.execute(lambda: None)
        first.cancel()
        with pytest.raises(asyncio.CancelledError): await first
        # The cancelled HTTP task does not free its still-running worker slot.
        with pytest.raises(PipelineBusyError): await worker.execute(lambda: None)
        release.set()
        assert await second == 'tenant-b/agent-b'
        assert observed == ['tenant-a/agent-a']
        assert await worker.execute(lambda: scope.get()) == 'tenant-b/agent-b'
    try: asyncio.run(exercise())
    finally: release.set(); worker.close()


def test_queued_cancellation_and_failure_release_capacity():
    worker = PipelineDispatcher()
    entered, release = Event(), Event()
    executed_cancelled = []
    def held():
        entered.set()
        assert release.wait(5)
    def failure(): raise ValueError('synthetic failure')
    async def exercise():
        first = asyncio.create_task(worker.execute(held))
        assert await asyncio.to_thread(entered.wait, 2)
        queued = asyncio.create_task(worker.execute(lambda: executed_cancelled.append(True)))
        await asyncio.sleep(0)
        queued.cancel()
        with pytest.raises(asyncio.CancelledError): await queued
        replacement = asyncio.create_task(worker.execute(failure))
        await asyncio.sleep(0)
        with pytest.raises(PipelineBusyError): await worker.execute(lambda: None)
        release.set()
        await first
        with pytest.raises(ValueError, match='synthetic failure'): await replacement
        assert executed_cancelled == []
        assert await worker.execute(lambda: 'recovered') == 'recovered'
    try: asyncio.run(exercise())
    finally: release.set(); worker.close()


def test_shared_executor_serializes_sync_and_dispatched_callers():
    from runtime.executor.pipeline import PipelineExecutor
    executor = PipelineExecutor(SimpleNamespace())
    entered, release, attempted = Event(), Event(), Event()
    active = 0
    maximum = 0
    lock = Lock()
    def implementation(request, **kwargs):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(active, maximum)
        try:
            if request == 'first':
                entered.set()
                assert release.wait(5)
            return request
        finally:
            with lock: active -= 1
    executor._run_unlocked = implementation
    def second():
        attempted.set()
        return executor.run('second')
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(executor.run, 'first')
        try:
            assert entered.wait(2)
            following = pool.submit(second)
            assert attempted.wait(2)
            assert not following.done()
        finally: release.set()
        assert first.result() == 'first'
        assert following.result() == 'second'
    assert maximum == 1
