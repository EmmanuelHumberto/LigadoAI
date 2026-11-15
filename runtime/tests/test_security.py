import asyncio
import pytest
from runtime.security import RuntimeSecurityMiddleware, validate_security_config

@pytest.fixture(autouse=True)
def security(monkeypatch):
    monkeypatch.setenv("OPENTRACY_RUNTIME_SECURITY", "required")
    monkeypatch.setenv("OPENTRACY_RUNTIME_INTERNAL_TOKEN", "t" * 32)
    monkeypatch.setenv("BACKEND_API_KEYS", "operator-test")
    monkeypatch.setenv("OPENTRACY_KNOWLEDGE_AUTH_TOKEN", "cous-test")

async def invoke(app, path, method="GET", headers=()):
    messages = []
    async def send(value): messages.append(value)
    async def receive(): return {"type": "http.request", "body": b"", "more_body": False}
    await app({"type": "http", "path": path, "method": method, "headers": headers}, receive, send)
    return messages[0]["status"]

async def ok(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})

@pytest.mark.parametrize("path", ["/agent/config", "/policy", "/agents", "/run", "/traces", "/docs", "/admin/tenants", "/api/cous/internal-run"])
def test_anonymous_admin_denied(path):
    assert asyncio.run(invoke(RuntimeSecurityMiddleware(ok), path)) == 401

@pytest.mark.parametrize("path", ["/health", "/measurements/status", "/v3/diagnosis/status", "/knowledge/status", "/api/cous/chat"])
def test_protocol_routes_reach_their_existing_auth(path):
    assert asyncio.run(invoke(RuntimeSecurityMiddleware(ok), path)) == 200


def test_internal_operator_and_cous_scopes():
    async def check():
        app=RuntimeSecurityMiddleware(ok)
        assert await invoke(app,"/policy",headers=[(b"x-opentracy-runtime-key",b"t"*32)])==200
        assert await invoke(app,"/policy",headers=[(b"authorization",b"Bearer operator-test")])==200
        assert await invoke(app,"/agent/config",headers=[(b"authorization",b"Bearer cous-test")])==200
        assert await invoke(app,"/policy",headers=[(b"authorization",b"Bearer cous-test")])==401
        assert await invoke(app,"/agent/config",method="PUT",headers=[(b"authorization",b"Bearer cous-test")])==401
    asyncio.run(check())


def test_absent_internal_token_fails_closed(monkeypatch):
    monkeypatch.delenv("OPENTRACY_RUNTIME_INTERNAL_TOKEN")
    with pytest.raises(RuntimeError):validate_security_config()
    assert asyncio.run(invoke(RuntimeSecurityMiddleware(ok),"/policy"))==503


def test_concurrency_and_health_and_release():
    async def check():
        entered=asyncio.Event();release=asyncio.Event()
        async def held(scope,receive,send):
            if scope["path"]=="/run":entered.set();await release.wait()
            await ok(scope,receive,send)
        app=RuntimeSecurityMiddleware(held,max_concurrent=1)
        auth=[(b"x-opentracy-runtime-key",b"t"*32)]
        first=asyncio.create_task(invoke(app,"/run","POST",auth));await entered.wait()
        assert await invoke(app,"/run","POST",auth)==429
        assert await invoke(app,"/health")==200
        release.set();assert await first==200
        assert app.active==0
        assert await invoke(app,"/run","POST",auth)==200
    asyncio.run(check())


def test_cancelled_analysis_releases_slot():
    async def check():
        entered=asyncio.Event()
        async def held(scope,receive,send):entered.set();await asyncio.Event().wait()
        app=RuntimeSecurityMiddleware(held,1)
        task=asyncio.create_task(invoke(app,"/run","POST",[(b"x-opentracy-runtime-key",b"t"*32)]))
        await entered.wait();task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert app.active==0
    asyncio.run(check())


def test_unknown_security_mode_is_not_silently_accepted(monkeypatch):
    monkeypatch.setenv("OPENTRACY_RUNTIME_SECURITY", "requried")
    with pytest.raises(RuntimeError):validate_security_config()


def test_failing_analysis_releases_slot():
    async def check():
        async def fail(scope, receive, send):raise RuntimeError("synthetic failure")
        app=RuntimeSecurityMiddleware(fail,1)
        with pytest.raises(RuntimeError):
            await invoke(app,"/run","POST",[(b"x-opentracy-runtime-key",b"t"*32)])
        assert app.active==0
    asyncio.run(check())
